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

PERPLEXITY_MODEL = "sonar-reasoning-pro"
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


_CRYPTO_KEYWORDS = frozenset(
    {"crypt", "bitcoin", "btc", "eth", "defi", "token", "coin", "web3", "blockchain"}
)


def _is_crypto_strategy(config: StrategyConfig) -> bool:
    """Detect whether a strategy targets crypto assets.

    Checks both the strategy name and screening prompt against a broad
    keyword set so custom strategy names like "BTC Scalper" are caught.

    Args:
        config: Strategy configuration to inspect.

    Returns:
        True if the strategy appears to target crypto assets.
    """
    text = f"{config.name} {config.screening_prompt}".lower()
    return any(kw in text for kw in _CRYPTO_KEYWORDS)


_DOMAIN_SETS: dict[str, list[str]] = {
    "canadian": [
        "theglobeandmail.com",
        "financialpost.com",
        "bnnbloomberg.ca",
        "marketwatch.com",
        "finance.yahoo.com",
        "reuters.com",
    ],
    "us_stock": [
        "reuters.com",
        "bloomberg.com",
        "marketwatch.com",
        "finance.yahoo.com",
        "seekingalpha.com",
        "barrons.com",
        "cnbc.com",
    ],
    "crypto": [
        "coindesk.com",
        "cointelegraph.com",
        "theblock.co",
        "coingecko.com",
        "decrypt.co",
        "cryptoslate.com",
    ],
    "earnings": [
        "reuters.com",
        "bloomberg.com",
        "finance.yahoo.com",
        "seekingalpha.com",
        "earningswhispers.com",
        "benzinga.com",
    ],
}


def _get_domain_set(config: StrategyConfig) -> list[str]:
    """Select the best domain filter set for the given strategy.

    Checks crypto first, then earnings, then Canadian/TSX keywords in
    the screening prompt, falling back to the US stock set.

    Args:
        config: Strategy configuration to inspect.

    Returns:
        List of domain strings for ``search_domain_filter``.
    """
    if _is_crypto_strategy(config):
        return _DOMAIN_SETS["crypto"]
    if "earnings" in config.name.lower():
        return _DOMAIN_SETS["earnings"]
    text = config.screening_prompt.lower()
    if "canadian" in text or "tsx" in text:
        return _DOMAIN_SETS["canadian"]
    return _DOMAIN_SETS["us_stock"]


def _build_search_params(config: StrategyConfig | None) -> dict:
    """Build Sonar search parameters from strategy config.

    Args:
        config: Strategy configuration (None for defaults).

    Returns:
        Dict of API parameters for search filtering.
    """
    context_size = "high" if (not config or config.constraint_style == "tight") else "medium"
    params: dict = {
        "web_search_options": {"search_context_size": context_size},
    }

    recency_map = {"today": "day", "week": "week", "month": "month"}
    if config:
        params["search_recency_filter"] = recency_map.get(config.news_recency, "week")
    else:
        params["search_recency_filter"] = "week"

    params["search_domain_filter"] = _get_domain_set(config) if config else _DOMAIN_SETS["us_stock"]

    return params


def _distribute_citations(result: ScreeningResult, citations: list[str]) -> None:
    """Match citation URLs to tickers by symbol or company name slug.

    Populates each ``FundamentalData.news_urls`` in-place. When no URL
    matches a ticker, the first 3 citations are used as a fallback so
    every ticker gets at least some context for downstream stages.

    Args:
        result: Validated screening result with ticker data.
        citations: Flat list of citation URLs from the API response.
    """
    if not citations:
        return

    for td in result.tickers:
        symbol = td.ticker.split(":")[-1].lower()
        slug = td.company_name.lower().replace(" ", "")[:8]
        matched = [
            url for url in citations if symbol in url.lower() or (slug and slug in url.lower())
        ]
        td.news_urls = matched[:4] if matched else citations[:3]


async def _call_perplexity_raw(
    system_prompt: str,
    user_prompt: str,
    *,
    search_params: dict | None = None,
    model: str = PERPLEXITY_MODEL,
) -> tuple[str, list[str]]:
    """Make a single call to Perplexity Sonar and return text + citations.

    Args:
        system_prompt: The system prompt defining output format.
        user_prompt: The user prompt (search-query-style).
        search_params: API search parameters (domain filter, recency, etc.).
        model: Perplexity model identifier (e.g. sonar-pro, sonar-reasoning-pro).

    Returns:
        Tuple of (raw response text, list of citation URLs from the API).
    """
    client = _get_client()

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    api_kwargs: dict = {
        "model": model,
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
    model: str = PERPLEXITY_MODEL,
) -> tuple[ScreeningResult | None, list[str]]:
    """Call Perplexity with validation retry logic and return result + citations.

    Retries up to MAX_RETRIES times on validation failure, appending the
    error details so the LM can self-correct.

    Args:
        system_prompt: The system prompt defining output format.
        user_prompt: The user prompt.
        search_params: API search parameters.
        model: Perplexity model identifier.

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
                model=model,
            )
            if citations:
                all_citations = citations

            logger.debug("Perplexity raw response (first 500 chars): %s", raw_text[:500])

            result = validate_llm_json(raw_text, ScreeningResult)

            if not result.tickers:
                logger.warning(
                    "Perplexity returned valid JSON but 0 tickers (attempt %d). "
                    "Raw response (first 1000 chars): %s",
                    attempt + 1,
                    raw_text[:1000],
                )
                last_error = (
                    "You returned an empty tickers array. This is not acceptable. "
                    "You HAVE web search — use it to find current stocks. "
                    "Return your best candidates even if data is partial."
                )
                continue

            result.citations = all_citations
            _distribute_citations(result, all_citations)
            return result, all_citations

        except (ValueError, json.JSONDecodeError) as exc:
            last_error = f"JSON parse error: {exc}"
            logger.warning("Perplexity JSON parse failed: %s. Raw: %s", exc, raw_text[:500])
        except ValidationError as exc:
            last_error = f"Schema validation error: {exc}"
            logger.warning("Perplexity validation failed: %s. Raw: %s", exc, raw_text[:500])

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
