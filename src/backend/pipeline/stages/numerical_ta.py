"""Numerical TA pipeline stage.

Stage 0.7: Fetches pre-computed technical indicators from FMP and builds
structured ``MultiTimeframeTechnical`` snapshots for each ticker.

Runs BEFORE the three parallel LLM tracks. Its output feeds into Claude
(Track C) as structured data and into GPT (synthesis) for verification.

Follows the same concurrency pattern as existing stages: all tickers run
in parallel, rate-limited by the FMP semaphore in the service layer.
"""

from __future__ import annotations

import asyncio
import logging
import time

from pipeline.schemas import MultiTimeframeTechnical, StrategyConfig
from services.technical_analysis import build_multi_timeframe

logger = logging.getLogger(__name__)


async def run_numerical_ta(
    tickers: list[str],
    config: StrategyConfig,
) -> tuple[list[MultiTimeframeTechnical], list[dict]]:
    """Run numerical TA for all tickers across strategy timeframes.

    Builds a ``MultiTimeframeTechnical`` snapshot per ticker using the
    strategy's configured primary, additional, and short timeframes.

    Args:
        tickers: List of ticker symbols from screening.
        config: Strategy configuration with timeframe settings.

    Returns:
        Tuple of (list of successful MultiTimeframeTechnical results,
        list of per-ticker metadata dicts for stage_outputs).
    """
    start = time.perf_counter()

    primary_tf = config.chart_timeframe
    additional_tfs = config.additional_timeframes
    short_tfs = config.short_timeframes

    tasks = [
        build_multi_timeframe(
            symbol=ticker,
            primary_tf=primary_tf,
            additional_tfs=additional_tfs,
            short_tfs=short_tfs,
        )
        for ticker in tickers
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    snapshots: list[MultiTimeframeTechnical] = []
    all_metadata: list[dict] = []

    for ticker, result in zip(tickers, results, strict=False):
        meta: dict = {
            "stage": "numerical_ta",
            "ticker": ticker,
            "primary_timeframe": primary_tf,
            "additional_timeframes": additional_tfs,
            "short_timeframes": short_tfs,
        }

        if isinstance(result, Exception):
            logger.error("Numerical TA failed for %s: %s", ticker, result)
            meta["status"] = "error"
            meta["error"] = str(result)
        elif result is None:
            logger.warning("Numerical TA returned no data for %s", ticker)
            meta["status"] = "no_data"
        else:
            snapshots.append(result)
            meta["status"] = "success"
            meta["timeframe_alignment"] = result.timeframe_alignment
            meta["primary_momentum_score"] = result.primary.momentum_score
            meta["primary_trend_alignment"] = result.primary.trend_alignment
            meta["ema_crosses_detected"] = len(result.primary.ema_crosses)

        all_metadata.append(meta)

    elapsed = time.perf_counter() - start
    logger.info(
        "Numerical TA stage: %d/%d tickers succeeded in %.1fs",
        len(snapshots),
        len(tickers),
        elapsed,
    )

    return snapshots, all_metadata


def format_ta_for_prompt(snapshot: MultiTimeframeTechnical) -> str:
    """Format a MultiTimeframeTechnical as structured text for LLM prompts.

    Produces the human-readable numerical data block that replaces Claude's
    pixel-guessing approach. Designed to be injected into the Claude prompt
    as the ``TECHNICAL DATA (PRIMARY)`` section.

    Args:
        snapshot: Complete multi-timeframe TA for one ticker.

    Returns:
        Formatted string ready for prompt injection.
    """
    p = snapshot.primary
    lines: list[str] = [
        f"Ticker: {p.ticker}",
        f"Timeframe: {p.timeframe}",
        f"Current Price: ${p.price_current:.2f}",
        f"Today's Range: ${p.price_low:.2f} - ${p.price_high:.2f}",
        "",
        "EMA Stack:",
    ]

    sorted_emas = sorted(p.emas, key=lambda e: e.period)
    for ema in sorted_emas:
        direction = "rising" if ema.slope > 0 else "falling" if ema.slope < 0 else "flat"
        lines.append(
            f"  {ema.period} EMA: ${ema.current_value:.2f} ({direction}, slope {ema.slope:+.2f})"
        )

    if sorted_emas:
        periods = [e.period for e in sorted_emas]
        values = [e.current_value for e in sorted_emas]
        is_bullish_stack = all(values[i] > values[i + 1] for i in range(len(values) - 1))
        is_bearish_stack = all(values[i] < values[i + 1] for i in range(len(values) - 1))
        if is_bullish_stack:
            order_str = " > ".join(str(p) for p in periods)
            lines.append(f"  Stack Order: {order_str} (BULLISH ALIGNMENT)")
        elif is_bearish_stack:
            order_str = " < ".join(str(p) for p in periods)
            lines.append(f"  Stack Order: {order_str} (BEARISH ALIGNMENT)")
        else:
            lines.append("  Stack Order: MIXED")

    if p.ema_crosses:
        lines.append("")
        lines.append("EMA Crosses:")
        for cross in p.ema_crosses:
            lines.append(
                f"  {cross.fast_period}/{cross.slow_period} EMA: "
                f"{cross.cross_type.title()} cross {cross.candles_ago} candles ago, "
                f"spread {cross.spread_pct:.2f}% and {cross.spread_direction.upper()}"
            )

    if p.rsi:
        lines.append("")
        lines.append(
            f"RSI (14): {p.rsi.current:.1f} ({p.rsi.zone} zone, "
            f"{p.rsi.trend} from {p.rsi.previous:.1f})"
        )
        lines.append(f"  Divergence: {p.rsi.divergence.replace('_', ' ').title()}")

    if p.macd:
        lines.append("")
        lines.append("MACD:")
        lines.append(
            f"  Line: {p.macd.macd_line:.4f}, Signal: {p.macd.signal_line:.4f}, "
            f"Histogram: {p.macd.histogram:+.4f} ({p.macd.histogram_slope.upper()})"
        )
        lines.append(f"  Signal: MACD {p.macd.signal_cross} signal line")

    lines.append("")
    lines.append(f"ADX: {p.adx:.1f} ({'trending' if p.adx >= 25 else 'no trend / weak trend'})")
    lines.append(f"ATR: ${p.atr:.2f} ({p.atr_pct:.2f}% of price)")

    if p.volume:
        lines.append(f"Volume: {p.volume.ratio:.1f}x 20-day average ({p.volume.trend})")

    lines.append("")
    lines.append(
        f"Composite Momentum Score: {p.momentum_score:+.2f} ",
    )

    if p.momentum_score > 0.4:
        lines.append("  Interpretation: Moderately to strongly bullish")
    elif p.momentum_score > 0.1:
        lines.append("  Interpretation: Mildly bullish")
    elif p.momentum_score > -0.1:
        lines.append("  Interpretation: Neutral / no clear edge")
    elif p.momentum_score > -0.4:
        lines.append("  Interpretation: Mildly bearish")
    else:
        lines.append("  Interpretation: Moderately to strongly bearish")

    if snapshot.additional or snapshot.short:
        lines.append("")
        lines.append("MULTI-TIMEFRAME SUMMARY:")
        lines.append(
            f"  Overall alignment: {snapshot.timeframe_alignment.replace('_', ' ').upper()}"
        )
        for s in snapshot.additional:
            lines.append(
                f"  {s.timeframe}: momentum {s.momentum_score:+.2f}, "
                f"trend {s.trend_alignment.replace('_', ' ')}"
            )
        for s in snapshot.short:
            lines.append(
                f"  {s.timeframe} (short): momentum {s.momentum_score:+.2f}, "
                f"trend {s.trend_alignment.replace('_', ' ')}"
            )

    return "\n".join(lines)
