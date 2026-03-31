"""Stage 4.7: Deterministic risk validator.

Pure Python rules that flag (not block) risk violations on each
Recommendation after GPT synthesis. Violations are informational —
the user makes the final call via the FeedbackTab.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from pipeline.schemas import ChartAnalysis, Recommendation, StrategyConfig

if TYPE_CHECKING:
    from services.fmp_service import FmpEnrichedStock

logger = logging.getLogger(__name__)


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
) -> list[Recommendation]:
    """Run deterministic risk checks on each recommendation.

    Attaches ``risk_violations`` and sets ``risk_approved`` on each
    recommendation. Violations are advisory — they flag concerns but
    do not remove or alter the recommendation.

    Args:
        recommendations: GPT-produced recommendations to validate.
        config: Strategy configuration with risk params.
        charts: Claude chart analyses (used for ATR extraction).
        fmp_context: FMP enriched stock data keyed by ticker.

    Returns:
        The same list with risk fields populated in-place.
    """
    rp = config.risk_params

    for rec in recommendations:
        violations: list[str] = []

        if rec.action == "HOLD":
            rec.risk_violations = violations
            rec.risk_approved = True
            continue

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
