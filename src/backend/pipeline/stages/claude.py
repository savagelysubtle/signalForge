"""Claude Vision chart analysis stage.

Stage 3: For each ticker, fetches a TradingView chart screenshot via
Chart-Img, sends the image to Claude Vision along with news context
from Gemini (Stage 2) and strategy config, and returns a validated
``ChartAnalysis``.

Uses the ``anthropic`` SDK with ``AsyncAnthropic`` and base64 image
content blocks for vision analysis.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time

from anthropic import AsyncAnthropic

from pipeline.prompts.claude_chart import (
    CHART_SYSTEM_PROMPT,
    CHART_SYSTEM_PROMPT_V2,
    build_chart_prompt,
    build_chart_prompt_v2,
)
from pipeline.prompts.claude_chart import get_prompt_hash as chart_hash
from pipeline.prompts.claude_chart import get_prompt_hash_v2 as chart_hash_v2
from pipeline.schemas import (
    ChartAnalysis,
    MultiTimeframeTechnical,
    SentimentAnalysis,
    StrategyConfig,
    TechnicalAssessment,
)
from pipeline.stages.numerical_ta import format_ta_for_prompt
from pipeline.validation import with_validation_retry
from services.chart_image import fetch_chart_image
from services.keyring_service import get_api_key

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-opus-4-6"

_semaphore = asyncio.Semaphore(3)


def _format_quote_for_claude(live_quotes: dict | None, ticker: str) -> str | None:
    """Format a single ticker's live quote for the Claude prompt.

    Args:
        live_quotes: Mapping of ticker → FmpQuote (may be None).
        ticker: The ticker to format.

    Returns:
        Formatted string or None if no quote available.
    """
    if not live_quotes or ticker not in live_quotes:
        return None
    q = live_quotes[ticker]
    if q.price is None:
        return None
    parts = [f"Price: ${q.price:.2f}"]
    if q.changesPercentage is not None:
        parts.append(f"Change: {q.changesPercentage:+.2f}%")
    if q.open is not None:
        parts.append(f"Open: ${q.open:.2f}")
    if q.dayLow is not None and q.dayHigh is not None:
        parts.append(f"Day range: ${q.dayLow:.2f}-${q.dayHigh:.2f}")
    if q.volume is not None and q.avgVolume:
        rvol = q.volume / q.avgVolume
        parts.append(f"Volume: {q.volume:,} (RVOL: {rvol:.1f}x avg)")
    return "\n".join(parts)


def _get_client() -> AsyncAnthropic:
    """Build an async Anthropic client using the configured API key."""
    api_key = get_api_key("anthropic")
    if not api_key:
        raise RuntimeError(
            "Anthropic API key not configured. Set ANTHROPIC_API_KEY in .env (see .env.example)."
        )
    return AsyncAnthropic(api_key=api_key)


@with_validation_retry(schema=ChartAnalysis, max_retries=2)
async def _call_claude_vision(
    system_prompt: str,
    user_prompt: str,
    image_bytes: bytes,
    *,
    error_context: str = "",
) -> str:
    """Send a chart image to Claude Vision and get analysis text back.

    Args:
        system_prompt: System instruction defining output format.
        user_prompt: Per-ticker chart analysis request with news context.
        image_bytes: Raw PNG bytes of the chart screenshot.
        error_context: Appended to user prompt on retries for self-correction.

    Returns:
        Raw response text from the API.
    """
    client = _get_client()

    full_user_prompt = user_prompt
    if error_context:
        full_user_prompt = f"{user_prompt}\n\n---\nCORRECTION: {error_context}"

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    async with _semaphore:
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": full_user_prompt,
                        },
                    ],
                }
            ],
        )

    return response.content[0].text


async def _analyze_ticker(
    ticker: str,
    config: StrategyConfig,
    sentiment: SentimentAnalysis | None,
    run_id: str,
    user_id: str = "",
    timeframe_override: str | None = None,
    indicators_override: list[str] | None = None,
    fmp_context_str: str | None = None,
    regime_context: str = "",
    live_quote_context: str | None = None,
) -> tuple[ChartAnalysis | None, dict]:
    """Run chart analysis for a single ticker and timeframe.

    Fetches the chart image, sends it to Claude Vision with news context,
    FMP fundamental context, and real-time quote data, and returns a
    validated ChartAnalysis.

    Args:
        ticker: Stock/crypto ticker symbol.
        config: Strategy configuration with chart params.
        sentiment: Gemini's sentiment result for this ticker, or None.
        run_id: Pipeline run UUID for chart image filenames.
        user_id: User UUID for storage path isolation.
        timeframe_override: If set, use this timeframe instead of the
            strategy's ``chart_timeframe``.
        indicators_override: If set, use these indicators instead of
            the strategy's ``chart_indicators`` (for short-TF analysis).
        fmp_context_str: Pre-formatted FMP fundamental context, or None.
        regime_context: Pre-formatted market regime header, or empty.
        live_quote_context: Pre-formatted real-time quote string, or None.

    Returns:
        Tuple of (validated ChartAnalysis or None, metadata dict).
    """
    effective_timeframe = timeframe_override or config.chart_timeframe
    effective_indicators = indicators_override or config.chart_indicators
    user_prompt = build_chart_prompt(
        ticker,
        config,
        sentiment,
        timeframe_override=timeframe_override,
        indicators_override=effective_indicators,
        fmp_context=fmp_context_str,
        regime_context=regime_context,
        live_quote_context=live_quote_context,
    )
    metadata: dict = {
        "stage": "claude",
        "ticker": ticker,
        "model": CLAUDE_MODEL,
        "prompt_hash": chart_hash(),
        "prompt_text": f"{CHART_SYSTEM_PROMPT}\n---\n{user_prompt}",
    }

    start = time.perf_counter()

    last_fetch_error: Exception | None = None
    for attempt in range(2):
        try:
            image_bytes, image_path = await fetch_chart_image(
                ticker,
                effective_timeframe,
                effective_indicators,
                run_id,
                user_id,
            )
            last_fetch_error = None
            break
        except Exception as exc:
            last_fetch_error = exc
            if attempt == 0:
                logger.warning("Chart fetch attempt 1 failed for %s, retrying: %s", ticker, exc)
                await asyncio.sleep(2)

    if last_fetch_error is not None:
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "chart_fetch_error"
        metadata["error"] = str(last_fetch_error)
        logger.exception("Chart image fetch failed for %s after retry", ticker)
        return None, metadata

    try:
        result = await _call_claude_vision(CHART_SYSTEM_PROMPT, user_prompt, image_bytes)
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)

        if result is not None:
            result.ticker = ticker
            result.timeframe = effective_timeframe
            result.chart_image_path = image_path
            metadata["status"] = "success"
            metadata["raw_response"] = result.model_dump_json()
            metadata["retry_count"] = getattr(result, "_retry_count", 0)
        else:
            metadata["status"] = "validation_failed"

        return result, metadata
    except Exception as exc:
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "api_error"
        metadata["error"] = str(exc)
        logger.exception("Claude Vision failed for %s", ticker)
        return None, metadata


async def run_chart_analysis(
    tickers: list[str],
    config: StrategyConfig,
    sentiments: list[SentimentAnalysis],
    run_id: str,
    user_id: str = "",
    fmp_context: dict | None = None,
    regime_context: str = "",
    live_quotes: dict | None = None,
) -> tuple[list[ChartAnalysis], list[dict]]:
    """Run chart analysis for all tickers in parallel.

    Each ticker gets its own Claude Vision call with a chart screenshot,
    news context from Gemini, fundamental context from FMP, and real-time
    quote data. Calls are rate-limited by a semaphore (max 3 concurrent).

    Args:
        tickers: List of ticker symbols from screening.
        config: Strategy configuration with chart params.
        sentiments: List of SentimentAnalysis results from Gemini.
        run_id: Pipeline run UUID for chart image filenames.
        user_id: User UUID for storage path isolation.
        fmp_context: Mapping of ticker -> FmpEnrichedStock for
            fundamental context injection into chart prompts.
        regime_context: Pre-formatted market regime header, or empty.
        live_quotes: Mapping of ticker -> FmpQuote for real-time
            price injection into chart prompts (may be None).

    Returns:
        Tuple of (list of successful ChartAnalysis results,
        list of per-ticker metadata dicts).
    """
    from pipeline.fmp_context import format_fmp_for_claude

    sentiment_map: dict[str, SentimentAnalysis] = {s.ticker: s for s in sentiments}

    tasks = []
    task_tickers: list[str] = []
    for ticker in tickers:
        sentiment = sentiment_map.get(ticker)
        fmp_str: str | None = None
        if fmp_context and ticker in fmp_context:
            fmp_str = format_fmp_for_claude(fmp_context[ticker])
        quote_str = _format_quote_for_claude(live_quotes, ticker) if live_quotes else None
        tasks.append(
            _analyze_ticker(
                ticker,
                config,
                sentiment,
                run_id,
                user_id,
                fmp_context_str=fmp_str,
                regime_context=regime_context,
                live_quote_context=quote_str,
            )
        )
        task_tickers.append(ticker)
        for extra_tf in config.additional_timeframes:
            if extra_tf != config.chart_timeframe:
                tasks.append(
                    _analyze_ticker(
                        ticker,
                        config,
                        sentiment,
                        run_id,
                        user_id,
                        timeframe_override=extra_tf,
                        fmp_context_str=fmp_str,
                        regime_context=regime_context,
                        live_quote_context=quote_str,
                    )
                )
                task_tickers.append(ticker)
        for short_tf in config.short_timeframes:
            if short_tf != config.chart_timeframe:
                tasks.append(
                    _analyze_ticker(
                        ticker,
                        config,
                        sentiment,
                        run_id,
                        user_id,
                        timeframe_override=short_tf,
                        indicators_override=config.short_tf_indicators,
                        fmp_context_str=fmp_str,
                        regime_context=regime_context,
                        live_quote_context=quote_str,
                    )
                )
                task_tickers.append(ticker)
    results = await asyncio.gather(*tasks, return_exceptions=True)

    charts: list[ChartAnalysis] = []
    all_metadata: list[dict] = []

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("Claude task failed for %s: %s", task_tickers[i], result)
            all_metadata.append(
                {
                    "stage": "claude",
                    "ticker": task_tickers[i],
                    "model": CLAUDE_MODEL,
                    "status": "api_error",
                    "error": str(result),
                }
            )
            continue

        chart, metadata = result
        all_metadata.append(metadata)
        if chart is not None:
            charts.append(chart)

    logger.info(
        "Claude chart analysis: %d/%d tickers succeeded",
        len(charts),
        len(tickers),
    )
    return charts, all_metadata


# ---------------------------------------------------------------------------
# Pipeline v2: Independent technical analysis (no sentiment/FMP injection)
# ---------------------------------------------------------------------------


async def _analyze_ticker_v2(
    ticker: str,
    config: StrategyConfig,
    ta_context: str,
    run_id: str,
    user_id: str = "",
    timeframe_override: str | None = None,
    indicators_override: list[str] | None = None,
    regime_context: str = "",
    live_quote_context: str | None = None,
) -> tuple[TechnicalAssessment | None, dict]:
    """Run v2 chart analysis for a single ticker and timeframe.

    Pipeline v2: Claude acts as a technical analyst whose primary data is
    the numerical TA snapshot.  The chart image is a visual sanity check.
    Live quotes provide real-time price calibration.
    Returns a ``TechnicalAssessment`` (aliased as ``ChartAnalysis``).

    Args:
        ticker: Stock/crypto ticker symbol.
        config: Strategy configuration with chart params.
        ta_context: Pre-formatted numerical TA text.
        run_id: Pipeline run UUID for chart image filenames.
        user_id: User UUID for storage path isolation.
        timeframe_override: Override timeframe for additional/short TFs.
        indicators_override: Override indicators for short-TF analysis.
        regime_context: Pre-formatted market regime header, or empty.
        live_quote_context: Pre-formatted real-time quote string, or None.

    Returns:
        Tuple of (validated TechnicalAssessment or None, metadata dict).
    """
    effective_timeframe = timeframe_override or config.chart_timeframe
    effective_indicators = indicators_override or config.chart_indicators
    user_prompt = build_chart_prompt_v2(
        ticker,
        config,
        ta_context,
        timeframe_override=timeframe_override,
        indicators_override=effective_indicators,
        regime_context=regime_context,
        live_quote_context=live_quote_context,
    )
    metadata: dict = {
        "stage": "claude",
        "ticker": ticker,
        "model": CLAUDE_MODEL,
        "prompt_hash": chart_hash_v2(),
        "prompt_text": f"{CHART_SYSTEM_PROMPT_V2}\n---\n{user_prompt}",
        "pipeline_version": "v2",
    }

    start = time.perf_counter()

    last_fetch_error: Exception | None = None
    for attempt in range(2):
        try:
            image_bytes, image_path = await fetch_chart_image(
                ticker,
                effective_timeframe,
                effective_indicators,
                run_id,
                user_id,
            )
            last_fetch_error = None
            break
        except Exception as exc:
            last_fetch_error = exc
            if attempt == 0:
                logger.warning("Chart fetch attempt 1 failed for %s, retrying: %s", ticker, exc)
                await asyncio.sleep(2)

    if last_fetch_error is not None:
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "chart_fetch_error"
        metadata["error"] = str(last_fetch_error)
        logger.exception("Chart image fetch failed for %s after retry", ticker)
        return None, metadata

    try:
        result = await _call_claude_vision(CHART_SYSTEM_PROMPT_V2, user_prompt, image_bytes)
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)

        if result is not None:
            result.ticker = ticker
            result.timeframe = effective_timeframe
            result.chart_image_path = image_path
            metadata["status"] = "success"
            metadata["raw_response"] = result.model_dump_json()
            metadata["retry_count"] = getattr(result, "_retry_count", 0)
        else:
            metadata["status"] = "validation_failed"

        return result, metadata
    except Exception as exc:
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "api_error"
        metadata["error"] = str(exc)
        logger.exception("Claude Vision v2 failed for %s", ticker)
        return None, metadata


async def run_chart_analysis_v2(
    tickers: list[str],
    config: StrategyConfig,
    ta_snapshots: list[MultiTimeframeTechnical],
    run_id: str,
    user_id: str = "",
    regime_context: str = "",
    live_quotes: dict | None = None,
) -> tuple[list[TechnicalAssessment], list[dict]]:
    """Run v2 chart analysis for all tickers in parallel.

    Pipeline v2: Each ticker receives numerical TA data as its primary
    analytical input.  Claude interprets the numbers and uses the chart
    image as visual confirmation.  Live quotes provide real-time price
    calibration.  Returns ``TechnicalAssessment`` objects (aliased as
    ``ChartAnalysis`` for backward compatibility).

    Args:
        tickers: List of ticker symbols.
        config: Strategy configuration with chart params.
        ta_snapshots: MultiTimeframeTechnical results from Phase 1 stage.
        run_id: Pipeline run UUID.
        user_id: User UUID for storage path isolation.
        regime_context: Pre-formatted market regime header, or empty.
        live_quotes: Mapping of ticker -> FmpQuote for real-time
            price injection into chart prompts (may be None).

    Returns:
        Tuple of (list of successful ChartAnalysis results,
        list of per-ticker metadata dicts).
    """
    ta_map: dict[str, MultiTimeframeTechnical] = {s.ticker: s for s in ta_snapshots}

    tasks = []
    task_tickers: list[str] = []
    for ticker in tickers:
        ta = ta_map.get(ticker)
        ta_text = format_ta_for_prompt(ta) if ta else f"Ticker: {ticker}\n[No TA data available]"
        quote_str = _format_quote_for_claude(live_quotes, ticker) if live_quotes else None

        tasks.append(
            _analyze_ticker_v2(
                ticker,
                config,
                ta_text,
                run_id,
                user_id,
                regime_context=regime_context,
                live_quote_context=quote_str,
            )
        )
        task_tickers.append(ticker)

        for extra_tf in config.additional_timeframes:
            if extra_tf != config.chart_timeframe:
                tasks.append(
                    _analyze_ticker_v2(
                        ticker,
                        config,
                        ta_text,
                        run_id,
                        user_id,
                        timeframe_override=extra_tf,
                        regime_context=regime_context,
                        live_quote_context=quote_str,
                    )
                )
                task_tickers.append(ticker)

        for short_tf in config.short_timeframes:
            if short_tf != config.chart_timeframe:
                tasks.append(
                    _analyze_ticker_v2(
                        ticker,
                        config,
                        ta_text,
                        run_id,
                        user_id,
                        timeframe_override=short_tf,
                        indicators_override=config.short_tf_indicators,
                        regime_context=regime_context,
                        live_quote_context=quote_str,
                    )
                )
                task_tickers.append(ticker)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    charts: list[ChartAnalysis] = []
    all_metadata: list[dict] = []

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("Claude v2 task failed for %s: %s", task_tickers[i], result)
            all_metadata.append(
                {
                    "stage": "claude",
                    "ticker": task_tickers[i],
                    "model": CLAUDE_MODEL,
                    "status": "api_error",
                    "error": str(result),
                    "pipeline_version": "v2",
                }
            )
            continue

        chart, metadata = result
        all_metadata.append(metadata)
        if chart is not None:
            charts.append(chart)

    logger.info(
        "Claude v2 chart analysis: %d/%d tickers succeeded",
        len(charts),
        len(tickers),
    )
    return charts, all_metadata
