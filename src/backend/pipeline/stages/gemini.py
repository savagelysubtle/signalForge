"""Gemini news sentiment integration with Google Search grounding.

Stage 2: Gathers recent news for each ticker discovered by Perplexity,
scores sentiment, and extracts key catalysts. Runs before Claude so
that chart analysis is informed by real-time news context.

Uses the ``google-genai`` SDK with Google Search grounding for
real-time web access.
"""

from __future__ import annotations

import asyncio
import logging
import time

from google import genai
from google.genai import types

from pipeline.prompts.gemini_sentiment import (
    SENTIMENT_SYSTEM_PROMPT,
    build_sentiment_prompt,
)
from pipeline.prompts.gemini_sentiment import get_prompt_hash as sentiment_hash
from pipeline.schemas import SentimentAnalysis, StrategyConfig
from pipeline.validation import with_validation_retry
from services.keyring_service import get_api_key

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"

_semaphore = asyncio.Semaphore(5)


def _get_client() -> genai.Client:
    """Build a Gemini client using the configured API key."""
    api_key = get_api_key("google")
    if not api_key:
        raise RuntimeError(
            "Google API key not configured. Set GOOGLE_API_KEY in .env (see .env.example)."
        )
    return genai.Client(api_key=api_key)


@with_validation_retry(schema=SentimentAnalysis, max_retries=2)
async def _call_gemini(
    system_prompt: str,
    user_prompt: str,
    *,
    error_context: str = "",
) -> str:
    """Make a single Gemini call with Google Search grounding.

    Args:
        system_prompt: System instruction defining output format.
        user_prompt: Per-ticker sentiment analysis request.
        error_context: Appended to user prompt on retries for self-correction.

    Returns:
        Raw response text from the API.
    """
    client = _get_client()

    full_user_prompt = user_prompt
    if error_context:
        full_user_prompt = f"{user_prompt}\n\n---\nCORRECTION: {error_context}"

    async with _semaphore:
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=full_user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )

    return response.text or ""


async def _analyze_ticker(
    ticker: str,
    config: StrategyConfig,
    news_urls: list[str] | None = None,
) -> tuple[SentimentAnalysis | None, dict]:
    """Run sentiment analysis for a single ticker.

    Args:
        ticker: Stock/crypto ticker symbol.
        config: Strategy configuration with news_recency and news_scope.
        news_urls: Pre-researched article URLs from Perplexity.

    Returns:
        Tuple of (validated SentimentAnalysis or None, metadata dict).
    """
    user_prompt = build_sentiment_prompt(ticker, config, news_urls=news_urls)
    metadata: dict = {
        "stage": "gemini",
        "ticker": ticker,
        "model": GEMINI_MODEL,
        "prompt_hash": sentiment_hash(),
        "prompt_text": f"{SENTIMENT_SYSTEM_PROMPT}\n---\n{user_prompt}",
    }

    start = time.perf_counter()
    try:
        result = await _call_gemini(SENTIMENT_SYSTEM_PROMPT, user_prompt)
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "success" if result else "validation_failed"
        if result is not None:
            metadata["raw_response"] = result.model_dump_json()
        return result, metadata
    except Exception as exc:
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "api_error"
        metadata["error"] = str(exc)
        logger.exception("Gemini sentiment failed for %s", ticker)
        return None, metadata


async def run_sentiment(
    tickers: list[str],
    config: StrategyConfig,
    ticker_news: dict[str, list[str]] | None = None,
) -> tuple[list[SentimentAnalysis], list[dict]]:
    """Run news sentiment analysis for all tickers in parallel.

    Each ticker gets its own Gemini call with Google Search grounding.
    Calls are rate-limited by a semaphore (max 5 concurrent).

    Args:
        tickers: List of ticker symbols from Perplexity screening.
        config: Strategy configuration with news_recency and news_scope.
        ticker_news: Mapping of ticker -> pre-researched article URLs
            from Perplexity. If None or missing for a ticker, Gemini
            falls back to its own Google Search.

    Returns:
        Tuple of (list of successful SentimentAnalysis results,
        list of per-ticker metadata dicts).
    """
    news_map = ticker_news or {}
    tasks = [
        _analyze_ticker(ticker, config, news_urls=news_map.get(ticker))
        for ticker in tickers
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    sentiments: list[SentimentAnalysis] = []
    all_metadata: list[dict] = []

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("Gemini task failed for %s: %s", tickers[i], result)
            all_metadata.append(
                {
                    "stage": "gemini",
                    "ticker": tickers[i],
                    "model": GEMINI_MODEL,
                    "status": "api_error",
                    "error": str(result),
                }
            )
            continue

        sentiment, metadata = result
        all_metadata.append(metadata)
        if sentiment is not None:
            sentiments.append(sentiment)

    logger.info(
        "Gemini sentiment: %d/%d tickers succeeded",
        len(sentiments),
        len(tickers),
    )
    return sentiments, all_metadata
