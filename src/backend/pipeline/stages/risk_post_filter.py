"""Pipeline v2: Risk post-filter and lightweight pre-filter.

In the v2 parallel architecture, the risk screener can't run until all
three tracks complete. Instead of removing tickers before Claude:

1. **Pre-filter** (``pre_filter_tickers``): Fast, no-LLM check using FMP
   data. Drops tickers with obvious disqualifiers before parallel tracks.

2. **Post-filter** (``risk_post_filter``): Enriches GPT's input with
   ``RiskAssessment`` per ticker (risk_flags + risk_approved). GPT makes
   the final risk-adjusted call with full information.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pipeline.schemas import (
    FmpScreenerConfig,
    RiskAssessment,
    SentimentAnalysis,
    StrategyConfig,
)

if TYPE_CHECKING:
    from pipeline.schemas import ChartAnalysis, MultiTimeframeTechnical
    from services.fmp_service import FmpEnrichedStock

logger = logging.getLogger(__name__)


def pre_filter_tickers(
    tickers: list[str],
    fmp_map: dict[str, FmpEnrichedStock],
    config: StrategyConfig,
) -> list[str]:
    """Fast, cheap pre-filter using FMP fundamentals only (no LLM call).

    Drops tickers with obvious disqualifiers before the expensive parallel
    LLM tracks run. Only filters on data the FMP pre-screening stage
    already has: market cap, volume, price.

    Args:
        tickers: Ticker symbols to filter.
        fmp_map: Mapping of ticker -> FmpEnrichedStock from FMP screening.
        config: Strategy configuration with FMP screener config.

    Returns:
        Filtered ticker list (only tickers that pass basic checks).
    """
    if not fmp_map or not config.fmp_screener:
        return tickers

    screener: FmpScreenerConfig = config.fmp_screener
    passed: list[str] = []

    for ticker in tickers:
        stock = fmp_map.get(ticker)
        if not stock:
            logger.info(
                "Pre-filter: passing %s (not in FMP data — may be valid ticker without FMP coverage)",
                ticker,
            )
            passed.append(ticker)
            continue

        if (
            screener.market_cap_min
            and stock.market_cap
            and stock.market_cap < screener.market_cap_min
        ):
            logger.info(
                "Pre-filter: dropping %s (market cap %s < min %s)",
                ticker,
                stock.market_cap,
                screener.market_cap_min,
            )
            continue

        if screener.volume_min and stock.volume and stock.volume < screener.volume_min:
            logger.info(
                "Pre-filter: dropping %s (volume %s < min %s)",
                ticker,
                stock.volume,
                screener.volume_min,
            )
            continue

        if screener.price_min and stock.price and stock.price < screener.price_min:
            logger.info("Pre-filter: dropping %s (price below min)", ticker)
            continue

        if screener.price_max and stock.price and stock.price > screener.price_max:
            logger.info("Pre-filter: dropping %s (price above max)", ticker)
            continue

        passed.append(ticker)

    if len(passed) < len(tickers):
        logger.info(
            "Pre-filter: %d → %d tickers (%d dropped)",
            len(tickers),
            len(passed),
            len(tickers) - len(passed),
        )
    return passed


def risk_post_filter(
    tickers: list[str],
    sentiments: list[SentimentAnalysis],
    charts: list[ChartAnalysis],
    ta_snapshots: list[MultiTimeframeTechnical],
    config: StrategyConfig,
    fmp_map: dict[str, FmpEnrichedStock] | None = None,
) -> list[RiskAssessment]:
    """Enrich tickers with risk flags for GPT synthesis (no ticker removal).

    In v2 pipeline, this replaces the LLM-based risk screener. Instead of
    removing tickers, it adds structured risk flags that GPT can factor
    into its NO_TRADE/WATCH decision.

    Args:
        tickers: All ticker symbols in the pipeline run.
        sentiments: Gemini sentiment results.
        charts: Claude chart analysis results.
        ta_snapshots: Numerical TA snapshots from Phase 1.
        config: Strategy configuration with risk params.
        fmp_map: Optional FMP data for fundamental checks.

    Returns:
        List of RiskAssessment, one per ticker.
    """
    sentiment_map = {s.ticker: s for s in sentiments}
    chart_map = {c.ticker: c for c in charts}
    ta_map = {t.ticker: t for t in ta_snapshots}

    assessments: list[RiskAssessment] = []

    for ticker in tickers:
        flags: list[str] = []
        risk_approved = True
        risk_score = 1.0

        sa = sentiment_map.get(ticker)
        ca = chart_map.get(ticker)
        ta = ta_map.get(ticker)

        if sa:
            if sa.sentiment_score <= -0.6:
                flags.append(f"Strongly bearish sentiment ({sa.sentiment_score:+.2f})")
                risk_score -= 0.2
            if sa.confidence < 0.3:
                flags.append(f"Low sentiment confidence ({sa.confidence:.2f})")

        if ta and ta.primary:
            p = ta.primary
            if p.adx < 20 and config.strategy_type in ("momentum", "swing", "trend"):
                flags.append(f"No trend (ADX {p.adx:.1f} < 20) for trend-following strategy")
                risk_score -= 0.15
            if p.rsi and p.rsi.current > 80:
                flags.append(f"Extremely overbought RSI ({p.rsi.current:.1f})")
                risk_score -= 0.1
            if p.rsi and p.rsi.current < 20:
                flags.append(f"Extremely oversold RSI ({p.rsi.current:.1f})")
                risk_score -= 0.1
            if p.volume and p.volume.ratio < 0.5:
                flags.append(f"Very low volume ({p.volume.ratio:.1f}x avg)")
                risk_score -= 0.1

        if fmp_map and ticker in fmp_map:
            stock = fmp_map[ticker]
            if stock.altman_z_score is not None and stock.altman_z_score < 1.8:
                flags.append(f"Distress zone Altman Z-score ({stock.altman_z_score:.1f})")
                risk_score -= 0.15
            if stock.piotroski_score is not None and stock.piotroski_score < 3:
                flags.append(f"Weak Piotroski score ({stock.piotroski_score})")
                risk_score -= 0.1

        if not ca:
            flags.append("No chart analysis available")
            risk_score -= 0.1

        risk_score = max(0.0, min(1.0, risk_score))
        if risk_score < 0.4:
            risk_approved = False

        reason = "; ".join(flags) if flags else "Passed all risk checks"

        assessments.append(
            RiskAssessment(
                ticker=ticker,
                risk_flags=flags,
                risk_approved=risk_approved,
                risk_score=round(risk_score, 2),
                reason=reason,
            )
        )

    approved = sum(1 for a in assessments if a.risk_approved)
    flagged = sum(1 for a in assessments if a.risk_flags)
    logger.info(
        "Risk post-filter: %d/%d approved, %d flagged with warnings",
        approved,
        len(assessments),
        flagged,
    )
    return assessments
