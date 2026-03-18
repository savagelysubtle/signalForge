"""Perplexity Sonar integration for stock/crypto screening and research.

Uses the OpenAI-compatible API via the ``openai`` SDK. Supports two modes:
- **Discovery:** Screen the market for tickers matching strategy criteria.
- **Analysis:** Research user-provided tickers with fundamental data.
"""

from __future__ import annotations

import asyncio
import logging
import time

from openai import AsyncOpenAI

from pipeline.prompts.perplexity_analysis import (
    ANALYSIS_SYSTEM_PROMPT,
    build_analysis_prompt,
)
from pipeline.prompts.perplexity_analysis import get_prompt_hash as analysis_hash
from pipeline.prompts.perplexity_discovery import (
    DISCOVERY_SYSTEM_PROMPT,
    build_discovery_prompt,
    build_prompted_discovery_prompt,
)
from pipeline.prompts.perplexity_discovery import get_prompt_hash as discovery_hash
from pipeline.schemas import ScreeningResult, StrategyConfig
from pipeline.validation import with_validation_retry
from services.keyring_service import get_api_key

logger = logging.getLogger(__name__)

PERPLEXITY_BASE_URL = "https://api.perplexity.ai"
PERPLEXITY_MODEL = "sonar-pro"

_semaphore = asyncio.Semaphore(3)


def _get_client() -> AsyncOpenAI:
    """Build an AsyncOpenAI client pointed at the Perplexity API."""
    api_key = get_api_key("perplexity")
    if not api_key:
        raise RuntimeError(
            "Perplexity API key not configured. Set PERPLEXITY_API_KEY in .env (see .env.example)."
        )
    return AsyncOpenAI(api_key=api_key, base_url=PERPLEXITY_BASE_URL)


@with_validation_retry(schema=ScreeningResult, max_retries=2)
async def _call_perplexity(
    system_prompt: str,
    user_prompt: str,
    *,
    error_context: str = "",
) -> str:
    """Make a single call to Perplexity Sonar and return the raw response text.

    Args:
        system_prompt: The system prompt defining output format.
        user_prompt: The user prompt with screening/analysis instructions.
        error_context: Appended to user prompt on retries for self-correction.

    Returns:
        Raw response content string from the API.
    """
    client = _get_client()

    full_user_prompt = user_prompt
    if error_context:
        full_user_prompt = f"{user_prompt}\n\n---\nCORRECTION: {error_context}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": full_user_prompt},
    ]

    async with _semaphore:
        response = await client.chat.completions.create(
            model=PERPLEXITY_MODEL,
            messages=messages,
        )

    return response.choices[0].message.content or ""


async def run_discovery(
    config: StrategyConfig,
) -> tuple[ScreeningResult | None, dict]:
    """Run Perplexity in discovery mode to screen the market.

    Args:
        config: Strategy configuration driving the screening prompt.

    Returns:
        Tuple of (validated ScreeningResult or None, metadata dict with
        timing, prompt hash, model, raw response info).
    """
    user_prompt = build_discovery_prompt(config)
    metadata: dict = {
        "stage": "perplexity",
        "mode": "discovery",
        "model": PERPLEXITY_MODEL,
        "prompt_hash": discovery_hash(),
        "prompt_text": f"{DISCOVERY_SYSTEM_PROMPT}\n---\n{user_prompt}",
    }

    start = time.perf_counter()
    try:
        result = await _call_perplexity(DISCOVERY_SYSTEM_PROMPT, user_prompt)
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "success" if result else "validation_failed"
        if result is not None:
            metadata["raw_response"] = result.model_dump_json()
        return result, metadata
    except Exception as exc:
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "api_error"
        metadata["error"] = str(exc)
        logger.exception("Perplexity discovery failed")
        return None, metadata


async def run_prompted_discovery(
    user_prompt: str,
    config: StrategyConfig | None = None,
) -> tuple[ScreeningResult | None, dict]:
    """Run Perplexity in prompt-driven discovery mode.

    The user's free-form text drives the screening. If a strategy is
    selected its constraints and limits are layered on top.

    Args:
        user_prompt: The user's free-form screening request.
        config: Optional strategy configuration for additional context.

    Returns:
        Tuple of (validated ScreeningResult or None, metadata dict).
    """
    prompt = build_prompted_discovery_prompt(user_prompt, config)
    metadata: dict = {
        "stage": "perplexity",
        "mode": "prompt",
        "model": PERPLEXITY_MODEL,
        "prompt_hash": discovery_hash(),
        "prompt_text": f"{DISCOVERY_SYSTEM_PROMPT}\n---\n{prompt}",
    }

    start = time.perf_counter()
    try:
        result = await _call_perplexity(DISCOVERY_SYSTEM_PROMPT, prompt)
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "success" if result else "validation_failed"
        if result is not None:
            metadata["raw_response"] = result.model_dump_json()
        return result, metadata
    except Exception as exc:
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "api_error"
        metadata["error"] = str(exc)
        logger.exception("Perplexity prompted discovery failed")
        return None, metadata


async def run_analysis(
    tickers: list[str],
    config: StrategyConfig | None = None,
) -> tuple[ScreeningResult | None, dict]:
    """Run Perplexity in analysis mode to research given tickers.

    Args:
        tickers: List of ticker symbols to research.
        config: Optional strategy configuration for context.

    Returns:
        Tuple of (validated ScreeningResult or None, metadata dict).
    """
    user_prompt = build_analysis_prompt(tickers, config)
    metadata: dict = {
        "stage": "perplexity",
        "mode": "analysis",
        "model": PERPLEXITY_MODEL,
        "prompt_hash": analysis_hash(),
        "prompt_text": f"{ANALYSIS_SYSTEM_PROMPT}\n---\n{user_prompt}",
    }

    start = time.perf_counter()
    try:
        result = await _call_perplexity(ANALYSIS_SYSTEM_PROMPT, user_prompt)
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "success" if result else "validation_failed"
        if result is not None:
            metadata["raw_response"] = result.model_dump_json()
        return result, metadata
    except Exception as exc:
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "api_error"
        metadata["error"] = str(exc)
        logger.exception("Perplexity analysis failed")
        return None, metadata
