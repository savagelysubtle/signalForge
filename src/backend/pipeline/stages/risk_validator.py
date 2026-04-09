"""Stage 4.7: Deterministic risk validator.

Pure Python rules that flag (not block) risk violations on each
Recommendation after GPT synthesis. Violations are informational —
the user makes the final call via the FeedbackTab.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from pipeline.schemas import ChartAnalysis, Recommendation, RiskAssessment, StrategyConfig

if TYPE_CHECKING:
    from services.fmp_service import FmpEnrichedStock, FmpQuote

logger = logging.getLogger(__name__)

# Maximum allowed deviation from live quote price (as a fraction)
_MAX_PRICE_DEVIATION = 0.10  # 10%


def _check_price_sanity(
    rec: Recommendation,
    live_quotes: dict[str, FmpQuote] | None,
) -> list[str]:
    """Validate that LLM-generated prices are sane relative to the live quote.

    Checks entry, stop loss, and take profit against the last traded price.
    Flags any price that deviates more than 10% from the live quote.

    Args:
        rec: Recommendation with price fields.
        live_quotes: Live quotes keyed by ticker.

    Returns:
        List of violation strings (empty if all prices are sane).
    """
    if not live_quotes:
        return []

    quote = live_quotes.get(rec.ticker)
    if not quote or not quote.price or quote.price <= 0:
        return []

    violations: list[str] = []
    last_price = quote.price

    for field_name, field_value in [
        ("entry_price", rec.entry_price),
        ("stop_loss", rec.stop_loss),
        ("take_profit", rec.take_profit),
    ]:
        if field_value is None or field_value <= 0:
            continue
        deviation = abs(field_value - last_price) / last_price
        if deviation > _MAX_PRICE_DEVIATION:
            violations.append(
                f"Possibly hallucinated {field_name}: ${field_value:.2f} is "
                f"{deviation:.0%} from live price ${last_price:.2f}"
            )

    return violations


def _parse_atr_from_charts(
    ticker: str,
    charts: list[ChartAnalysis],
) -> float | None:
    """Extract numeric ATR value from chart indicator readings."""
    for ca in charts:
        if ca.ticker != ticker:
            continue
        for ir in ca.indicator_readings:
            if ir.indicator.upper() == "ATR" and ir.value:
                match = re.search(r"[\d.]+", ir.value)
                if match:
                    try:
                        return float(match.group())
                    except ValueError:
                        continue
    return None


def validate_risks(
    recommendations: list[Recommendation],
    config: StrategyConfig,
    charts: list[ChartAnalysis],
    fmp_context: dict[str, FmpEnrichedStock] | None = None,
    live_quotes: dict[str, FmpQuote] | None = None,
    risk_assessments: list[RiskAssessment] | None = None,
) -> list[Recommendation]:
    """Run deterministic risk checks on each recommendation.

    Attaches ``risk_violations`` and sets ``risk_approved`` on each
    recommendation. Also scales ``position_size_pct`` inversely with
    risk_score from the risk post-filter, and hard-blocks extreme
    fundamental risk (distressed Altman Z-score or very low Piotroski).

    Args:
        recommendations: GPT-produced recommendations to validate.
        config: Strategy configuration with risk params.
        charts: Claude chart analyses (used for ATR extraction).
        fmp_context: FMP enriched stock data keyed by ticker.
        live_quotes: Live price quotes keyed by ticker for price sanity checks.
        risk_assessments: Per-ticker risk assessments from the risk post-filter.

    Returns:
        The same list with risk fields populated in-place.
    """
    rp = config.risk_params
    _risk_map = {ra.ticker: ra for ra in (risk_assessments or [])}

    for rec in recommendations:
        violations: list[str] = []

        if rec.action == "HOLD":
            rec.risk_violations = violations
            rec.risk_approved = True
            continue

        # Price sanity check against live quotes
        violations.extend(_check_price_sanity(rec, live_quotes))

        if rec.risk_reward_ratio is not None and rec.risk_reward_ratio < rp.min_risk_reward:
            violations.append(
                f"R:R ratio {rec.risk_reward_ratio:.1f} below minimum {rp.min_risk_reward:.1f}"
            )

        if rec.position_size_pct > rp.max_position_pct:
            violations.append(
                f"Position size {rec.position_size_pct:.1f}% exceeds max {rp.max_position_pct:.1f}%"
            )

        if rec.confidence < 0.45:
            violations.append(f"Low conviction: confidence {rec.confidence:.0%} on a {rec.action}")

        atr = _parse_atr_from_charts(rec.ticker, charts)
        if atr and atr > 0 and rec.entry_price and rec.stop_loss:
            sl_distance = abs(rec.entry_price - rec.stop_loss)
            ratio = sl_distance / atr
            if ratio < 0.8:
                violations.append(
                    f"Stop loss too tight: {sl_distance:.2f} is {ratio:.1f}x ATR "
                    f"(min 0.8x ATR = {atr * 0.8:.2f})"
                )
            elif ratio > 2.5:
                violations.append(
                    f"Stop loss too wide: {sl_distance:.2f} is {ratio:.1f}x ATR "
                    f"(max 2.5x ATR = {atr * 2.5:.2f})"
                )

        if fmp_context:
            fmp_data = fmp_context.get(rec.ticker)
            if fmp_data:
                earnings_days = getattr(fmp_data, "earnings_days_away", None)
                if earnings_days is not None and earnings_days <= 5:
                    violations.append(
                        f"Earnings in {earnings_days} day{'s' if earnings_days != 1 else ''} "
                        "— elevated volatility risk"
                    )
                if fmp_data.altman_z_score is not None and fmp_data.altman_z_score < 1.0:
                    violations.append(
                        f"Extreme distress: Altman Z-score {fmp_data.altman_z_score:.2f} "
                        f"(distress zone <1.0)"
                    )
                if fmp_data.piotroski_score is not None and fmp_data.piotroski_score < 2:
                    violations.append(
                        f"Very weak fundamentals: Piotroski F-Score "
                        f"{fmp_data.piotroski_score}/9 (<2)"
                    )

        # Scale position size inversely with risk_score from post-filter
        if risk_assessments and rec.action in ("BUY", "SHORT"):
            ra = _risk_map.get(rec.ticker)
            if ra and ra.risk_score < 1.0:
                risk_size_factor = max(0.25, ra.risk_score)
                original_size = rec.position_size_pct
                rec.position_size_pct = round(rec.position_size_pct * risk_size_factor, 2)
                if rec.position_size_pct < original_size:
                    violations.append(
                        f"Position scaled {original_size:.1f}% -> {rec.position_size_pct:.1f}% "
                        f"(risk_score={ra.risk_score:.2f})"
                    )

        rec.risk_violations = violations
        rec.risk_approved = len(violations) == 0

        if violations:
            logger.info(
                "Risk violations for %s: %s",
                rec.ticker,
                "; ".join(violations),
            )

    total_flagged = sum(1 for r in recommendations if not r.risk_approved)
    if total_flagged:
        logger.info(
            "Risk validation: %d/%d recommendations flagged",
            total_flagged,
            len(recommendations),
        )

    return recommendations
