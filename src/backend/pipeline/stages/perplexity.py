"""Perplexity Sonar Pro integration for stock/crypto screening and research.

Uses the official ``perplexityai`` SDK with targeted search parameters
(domain filters, recency, context size). Citations are parsed from the
API response — never from LM-generated JSON.

Supports two modes:
- **Discovery:** Screen the market for tickers matching strategy criteria.
- **Analysis:** Research user-provided tickers with fundamental data.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from perplexity import AsyncPerplexity
from pydantic import ValidationError

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
from pipeline.validation import validate_llm_json
from services.keyring_service import get_api_key

logger = logging.getLogger(__name__)

PERPLEXITY_MODEL = "sonar-pro"
MAX_RETRIES = 2

_semaphore = asyncio.Semaphore(3)


def _get_client() -> AsyncPerplexity:
    """Build an AsyncPerplexity client."""
    api_key = get_api_key("perplexity")
    if not api_key:
        raise RuntimeError(
            "Perplexity API key not configured. Set PERPLEXITY_API_KEY in .env (see .env.example)."
        )
    return AsyncPerplexity(api_key=api_key)


def _build_search_params(config: StrategyConfig | None) -> dict:
    """Build Sonar Pro search parameters from strategy config.

    Args:
        config: Strategy configuration (None for defaults).

    Returns:
        Dict of API parameters for search filtering.
    """
    params: dict = {
        "web_search_options": {"search_context_size": "high"},
    }

    recency_map = {"today": "day", "week": "week", "month": "month"}
    if config:
        params["search_recency_filter"] = recency_map.get(config.news_recency, "week")
    else:
        params["search_recency_filter"] = "week"

    stock_domains = [
        "finance.yahoo.com",
        "reuters.com",
        "bloomberg.com",
        "marketwatch.com",
        "theglobeandmail.com",
        "financialpost.com",
        "seekingalpha.com",
        "barrons.com",
    ]
    crypto_domains = [
        "coindesk.com",
        "cointelegraph.com",
        "theblock.co",
        "coingecko.com",
        "decrypt.co",
    ]

    is_crypto = config and "crypt" in (config.name or "").lower()
    params["search_domain_filter"] = crypto_domains if is_crypto else stock_domains

    return params


async def _call_perplexity_raw(
    system_prompt: str,
    user_prompt: str,
    *,
    search_params: dict | None = None,
) -> tuple[str, list[str]]:
    """Make a single call to Perplexity Sonar and return text + citations.

    Args:
        system_prompt: The system prompt defining output format.
        user_prompt: The user prompt (search-query-style).
        search_params: API search parameters (domain filter, recency, etc.).

    Returns:
        Tuple of (raw response text, list of citation URLs from the API).
    """
    client = _get_client()

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    api_kwargs: dict = {
        "model": PERPLEXITY_MODEL,
        "messages": messages,
    }

    if search_params:
        if "search_recency_filter" in search_params:
            api_kwargs["search_recency_filter"] = search_params["search_recency_filter"]
        if "search_domain_filter" in search_params:
            api_kwargs["search_domain_filter"] = search_params["search_domain_filter"]
        if "web_search_options" in search_params:
            api_kwargs["web_search_options"] = search_params["web_search_options"]

    async with _semaphore:
        response = await client.chat.completions.create(**api_kwargs)

    text = response.choices[0].message.content or "" if response.choices else ""

    citations: list[str] = []
    if hasattr(response, "citations") and response.citations:
        citations = list(response.citations)

    return text, citations


async def _call_with_retry(
    system_prompt: str,
    user_prompt: str,
    *,
    search_params: dict | None = None,
) -> tuple[ScreeningResult | None, list[str]]:
    """Call Perplexity with validation retry logic and return result + citations.

    Retries up to MAX_RETRIES times on validation failure, appending the
    error details so the LM can self-correct.

    Args:
        system_prompt: The system prompt defining output format.
        user_prompt: The user prompt.
        search_params: API search parameters.

    Returns:
        Tuple of (validated ScreeningResult or None, citation URLs).
    """
    last_error = ""
    all_citations: list[str] = []

    for attempt in range(1 + MAX_RETRIES):
        effective_prompt = user_prompt
        if attempt > 0 and last_error:
            effective_prompt = (
                f"{user_prompt}\n\n---\n"
                f"CORRECTION: Your previous response failed validation: {last_error}. "
                f"Please respond with valid JSON matching this schema: "
                f"{ScreeningResult.model_json_schema()}"
            )
            logger.warning(
                "Retry %d/%d for Perplexity: %s",
                attempt,
                MAX_RETRIES,
                last_error,
            )

        try:
            raw_text, citations = await _call_perplexity_raw(
                system_prompt,
                effective_prompt,
                search_params=search_params,
            )
            if citations:
                all_citations = citations

            result = validate_llm_json(raw_text, ScreeningResult)
            result.citations = all_citations
            return result, all_citations

        except (ValueError, json.JSONDecodeError) as exc:
            last_error = f"JSON parse error: {exc}"
        except ValidationError as exc:
            last_error = f"Schema validation error: {exc}"

    logger.error(
        "All %d attempts failed for Perplexity. Last error: %s",
        1 + MAX_RETRIES,
        last_error,
    )
    return None, all_citations


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
    search_params = _build_search_params(config)
    metadata: dict = {
        "stage": "perplexity",
        "mode": "discovery",
        "model": PERPLEXITY_MODEL,
        "prompt_hash": discovery_hash(),
        "prompt_text": f"{DISCOVERY_SYSTEM_PROMPT}\n---\n{user_prompt}",
    }

    start = time.perf_counter()
    try:
        result, citations = await _call_with_retry(
            DISCOVERY_SYSTEM_PROMPT, user_prompt, search_params=search_params
        )
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "success" if result else "validation_failed"
        if result is not None:
            metadata["raw_response"] = result.model_dump_json()
        if citations:
            metadata["citations"] = citations
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
    search_params = _build_search_params(config)
    metadata: dict = {
        "stage": "perplexity",
        "mode": "prompt",
        "model": PERPLEXITY_MODEL,
        "prompt_hash": discovery_hash(),
        "prompt_text": f"{DISCOVERY_SYSTEM_PROMPT}\n---\n{prompt}",
    }

    start = time.perf_counter()
    try:
        result, citations = await _call_with_retry(
            DISCOVERY_SYSTEM_PROMPT, prompt, search_params=search_params
        )
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "success" if result else "validation_failed"
        if result is not None:
            metadata["raw_response"] = result.model_dump_json()
        if citations:
            metadata["citations"] = citations
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
    search_params = _build_search_params(config)
    metadata: dict = {
        "stage": "perplexity",
        "mode": "analysis",
        "model": PERPLEXITY_MODEL,
        "prompt_hash": analysis_hash(),
        "prompt_text": f"{ANALYSIS_SYSTEM_PROMPT}\n---\n{user_prompt}",
    }

    start = time.perf_counter()
    try:
        result, citations = await _call_with_retry(
            ANALYSIS_SYSTEM_PROMPT, user_prompt, search_params=search_params
        )
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "success" if result else "validation_failed"
        if result is not None:
            metadata["raw_response"] = result.model_dump_json()
        if citations:
            metadata["citations"] = citations
        return result, metadata
    except Exception as exc:
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "api_error"
        metadata["error"] = str(exc)
        logger.exception("Perplexity analysis failed")
        return None, metadata
