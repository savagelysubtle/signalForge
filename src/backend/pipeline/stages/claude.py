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
    build_chart_prompt,
)
from pipeline.prompts.claude_chart import get_prompt_hash as chart_hash
from pipeline.schemas import ChartAnalysis, SentimentAnalysis, StrategyConfig
from pipeline.validation import with_validation_retry
from services.chart_image import fetch_chart_image
from services.keyring_service import get_api_key

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-20250514"

_semaphore = asyncio.Semaphore(3)


def _get_client() -> AsyncAnthropic:
    """Build an async Anthropic client using the configured API key."""
    api_key = get_api_key("anthropic")
    if not api_key:
        raise RuntimeError(
            "Anthropic API key not configured. "
            "Set ANTHROPIC_API_KEY in .env (see .env.example)."
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
) -> tuple[ChartAnalysis | None, dict]:
    """Run chart analysis for a single ticker.

    Fetches the chart image, sends it to Claude Vision with news context,
    and returns a validated ChartAnalysis.

    Args:
        ticker: Stock/crypto ticker symbol.
        config: Strategy configuration with chart params.
        sentiment: Gemini's sentiment result for this ticker, or None.
        run_id: Pipeline run UUID for chart image filenames.

    Returns:
        Tuple of (validated ChartAnalysis or None, metadata dict).
    """
    user_prompt = build_chart_prompt(ticker, config, sentiment)
    metadata: dict = {
        "stage": "claude",
        "ticker": ticker,
        "model": CLAUDE_MODEL,
        "prompt_hash": chart_hash(),
        "prompt_text": f"{CHART_SYSTEM_PROMPT}\n---\n{user_prompt}",
    }

    start = time.perf_counter()

    try:
        image_bytes, image_path = await fetch_chart_image(
            ticker, config.chart_timeframe, config.chart_indicators, run_id, user_id,
        )
    except Exception as exc:
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "chart_fetch_error"
        metadata["error"] = str(exc)
        logger.exception("Chart image fetch failed for %s", ticker)
        return None, metadata

    try:
        result = await _call_claude_vision(CHART_SYSTEM_PROMPT, user_prompt, image_bytes)
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)

        if result is not None:
            result.chart_image_path = image_path.name
            metadata["status"] = "success"
            metadata["raw_response"] = result.model_dump_json()
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
) -> tuple[list[ChartAnalysis], list[dict]]:
    """Run chart analysis for all tickers in parallel.

    Each ticker gets its own Claude Vision call with a chart screenshot
    and news context from Gemini. Calls are rate-limited by a semaphore
    (max 3 concurrent to respect Anthropic rate limits).

    Args:
        tickers: List of ticker symbols from screening.
        config: Strategy configuration with chart params.
        sentiments: List of SentimentAnalysis results from Gemini.
        run_id: Pipeline run UUID for chart image filenames.

    Returns:
        Tuple of (list of successful ChartAnalysis results,
        list of per-ticker metadata dicts).
    """
    sentiment_map: dict[str, SentimentAnalysis] = {s.ticker: s for s in sentiments}

    tasks = [
        _analyze_ticker(ticker, config, sentiment_map.get(ticker), run_id, user_id)
        for ticker in tickers
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    charts: list[ChartAnalysis] = []
    all_metadata: list[dict] = []

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("Claude task failed for %s: %s", tickers[i], result)
            all_metadata.append({
                "stage": "claude",
                "ticker": tickers[i],
                "model": CLAUDE_MODEL,
                "status": "api_error",
                "error": str(result),
            })
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
