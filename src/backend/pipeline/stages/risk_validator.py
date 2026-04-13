"""Stage 4.7: Deterministic risk validator.

Pure Python rules that flag (not block) risk violations on each
Recommendation after GPT synthesis. Includes hard overrides:
- R:R below strategy minimum → override to WATCH
- Missing entry prices on BUY/SHORT → override to WATCH
- ADX < 20 on trend-following strategies → override to WATCH
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from pipeline.schemas import (
    ChartAnalysis,
    MultiTimeframeTechnical,
    Recommendation,
    RecommendationAction,
    RiskAssessment,
    StrategyConfig,
)

if TYPE_CHECKING:
    from services.fmp_service import FmpEnrichedStock, FmpQuote

logger = logging.getLogger(__name__)

_MAX_PRICE_DEVIATION = 0.10  # 10%

_TREND_FOLLOWING_TYPES = frozenset({"swing", "momentum", "trend", "breakout", "position"})


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
    ta_snapshots: list[MultiTimeframeTechnical] | None = None,
) -> list[Recommendation]:
    """Run deterministic risk checks on each recommendation.

    Attaches ``risk_violations`` and sets ``risk_approved`` on each
    recommendation. Includes hard overrides that convert BUY/SHORT to
    WATCH when quantitative thresholds are violated (R:R < min, missing
    entry prices, ADX < 20 on trend strategies).

    Args:
        recommendations: GPT-produced recommendations to validate.
        config: Strategy configuration with risk params.
        charts: Claude chart analyses (used for ATR extraction).
        fmp_context: FMP enriched stock data keyed by ticker.
        live_quotes: Live price quotes keyed by ticker for price sanity checks.
        risk_assessments: Per-ticker risk assessments from the risk post-filter.
        ta_snapshots: Numerical TA data for ADX/momentum checks.

    Returns:
        The same list with risk fields populated in-place.
    """
    rp = config.risk_params
    _risk_map = {ra.ticker: ra for ra in (risk_assessments or [])}
    _ta_map: dict[str, MultiTimeframeTechnical] = {}
    if ta_snapshots:
        for snap in ta_snapshots:
            _ta_map[snap.ticker.upper()] = snap

    for rec in recommendations:
        violations: list[str] = []

        if rec.action in ("HOLD", "NO_TRADE"):
            rec.risk_violations = violations
            rec.risk_approved = True
            continue

        # Price sanity check against live quotes
        violations.extend(_check_price_sanity(rec, live_quotes))

        # --- Hard overrides: BUY/SHORT → WATCH ---

        # Override 1: Missing entry setup on BUY/SHORT
        if rec.action in ("BUY", "SHORT"):
            missing_prices = []
            if rec.entry_price is None:
                missing_prices.append("entry_price")
            if rec.stop_loss is None:
                missing_prices.append("stop_loss")
            if rec.take_profit is None:
                missing_prices.append("take_profit")
            if missing_prices:
                violations.append(f"Missing {', '.join(missing_prices)} — overriding to WATCH")
                logger.warning(
                    "Override %s→WATCH for %s: missing %s",
                    rec.action,
                    rec.ticker,
                    ", ".join(missing_prices),
                )
                rec.action = RecommendationAction.WATCH

        # Override 2: R:R below strategy minimum → WATCH
        if (
            rec.action in ("BUY", "SHORT")
            and rec.risk_reward_ratio is not None
            and rec.risk_reward_ratio < rp.min_risk_reward
        ):
            violations.append(
                f"R:R {rec.risk_reward_ratio:.1f} < {rp.min_risk_reward:.1f} minimum "
                f"— overriding to WATCH"
            )
            logger.info(
                "Override %s→WATCH for %s: R:R %.1f < %.1f",
                rec.action,
                rec.ticker,
                rec.risk_reward_ratio,
                rp.min_risk_reward,
            )
            rec.action = RecommendationAction.WATCH

        # Override 3: ADX < 20 on trend-following strategy → WATCH
        ta = _ta_map.get(rec.ticker.upper())
        if rec.action in ("BUY", "SHORT") and ta and ta.primary:
            adx = ta.primary.adx
            if adx < 20 and config.strategy_type in _TREND_FOLLOWING_TYPES:
                violations.append(
                    f"No trend detected (ADX {adx:.1f} < 20) for "
                    f"{config.strategy_type} strategy — overriding to WATCH"
                )
                logger.info(
                    "Override %s→WATCH for %s: ADX %.1f < 20",
                    rec.action,
                    rec.ticker,
                    adx,
                )
                rec.action = RecommendationAction.WATCH

        # Warning: Momentum near zero (informational, no override)
        if rec.action in ("BUY", "SHORT") and ta and ta.primary:
            mom = ta.primary.momentum_score
            if -0.2 <= mom <= 0.2:
                violations.append(f"Momentum near zero ({mom:+.2f})")

        # --- Standard violation checks ---

        if rec.position_size_pct > rp.max_position_pct:
            violations.append(
                f"Position size {rec.position_size_pct:.1f}% exceeds max {rp.max_position_pct:.1f}%"
            )

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

        # ATR-based position sizing (volatility-adjusted)
        if (
            atr
            and atr > 0
            and rec.action in ("BUY", "SHORT")
            and rec.entry_price
            and rec.entry_price > 0
        ):
            atr_mult = {"intraday_scalp": 1.0, "crypto_intraday_scalp": 1.0}.get(
                config.strategy_type, 1.5
            )
            dollar_risk_per_share = atr * atr_mult
            max_risk_pct = rp.max_portfolio_risk_pct / max(rp.max_position_pct / 2, 1.0)
            atr_based_pct = round(
                (max_risk_pct / (dollar_risk_per_share / rec.entry_price * 100)), 2
            )
            atr_capped = min(atr_based_pct, rp.max_position_pct)
            if atr_capped < rec.position_size_pct:
                violations.append(
                    f"ATR-based sizing: {rec.position_size_pct:.1f}% → "
                    f"{atr_capped:.1f}% (ATR={atr:.2f})"
                )
                rec.position_size_pct = atr_capped

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

        # --- WATCH completeness enforcement ---
        if rec.action == "WATCH":
            watch_issues: list[str] = []
            if not rec.entry_trigger:
                watch_issues.append("missing entry_trigger")
            if not rec.entry_price:
                watch_issues.append("missing entry_price (trigger level)")
            if not rec.invalidation_conditions:
                watch_issues.append("missing invalidation_conditions")
            if not rec.entry_valid_window:
                watch_issues.append("missing entry_valid_window")

            if watch_issues:
                violations.append(
                    f"Vague WATCH — overriding to NO_TRADE: {', '.join(watch_issues)}"
                )
                logger.info(
                    "Override WATCH→NO_TRADE for %s: %s",
                    rec.ticker,
                    ", ".join(watch_issues),
                )
                rec.action = RecommendationAction.NO_TRADE

        # --- Setup archetype enforcement ---
        archetypes = config.setup_archetypes
        if (
            archetypes
            and rec.setup_type
            and rec.action in ("BUY", "SHORT", "WATCH")
            and rec.setup_type not in archetypes
        ):
            violations.append(
                f"Setup type '{rec.setup_type}' not in strategy archetypes "
                f"({', '.join(archetypes[:3])}...) -- flagged"
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
    overridden = sum(
        1
        for r in recommendations
        if r.action in ("WATCH", "NO_TRADE") and r.raw_gpt_confidence is not None
    )
    if total_flagged:
        logger.info(
            "Risk validation: %d/%d flagged, %d overridden to WATCH/NO_TRADE",
            total_flagged,
            len(recommendations),
            overridden,
        )

    return recommendations
