"""Perplexity Agent API integration for stock/crypto screening and research.

Uses the official ``perplexityai`` SDK's Agent API (``responses.create``)
with web search and optional FMP function-calling tool. Citations are
extracted from ``SearchResultsOutputItem`` in the API response.

Supports three modes:
- **Discovery:** Screen the market for tickers matching strategy criteria.
- **Analysis:** Research user-provided tickers with fundamental data.
- **Prompt:** User free-form prompt drives the screening.

When FMP pre-screened candidates are provided, they are included in the
prompt as context. The FMP screener is also exposed as a function tool
so Perplexity can dynamically adjust screening parameters.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

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
    build_system_prompt,
)
from pipeline.prompts.perplexity_discovery import get_prompt_hash as discovery_hash
from pipeline.schemas import ScreeningResult, StrategyConfig
from pipeline.tools.fmp_tool import FMP_TOOL_DEFINITION, execute_fmp_tool
from pipeline.validation import validate_llm_json
from services.keyring_service import get_api_key

if TYPE_CHECKING:
    from services.fmp_service import FmpEnrichedStock

logger = logging.getLogger(__name__)

AGENT_MODEL = "perplexity/sonar-pro"
MAX_RETRIES = 2
MAX_TOOL_ROUNDS = 3

_semaphore = asyncio.Semaphore(3)


def _get_client() -> AsyncPerplexity:
    """Build an AsyncPerplexity client."""
    api_key = get_api_key("perplexity")
    if not api_key:
        raise RuntimeError(
            "Perplexity API key not configured. Set PERPLEXITY_API_KEY in .env (see .env.example)."
        )
    return AsyncPerplexity(api_key=api_key)


# ---------------------------------------------------------------------------
# Domain / search filter helpers
# ---------------------------------------------------------------------------


_CRYPTO_KEYWORDS = frozenset(
    {"crypt", "bitcoin", "btc", "eth", "defi", "token", "coin", "web3", "blockchain"}
)


def _is_crypto_strategy(config: StrategyConfig) -> bool:
    """Detect whether a strategy targets crypto assets."""
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


_MACRO_DOMAINS: list[str] = [
    "federalreserve.gov",
    "bls.gov",
    "statscan.gc.ca",
    "imf.org",
    "worldbank.org",
]


def _get_domain_set(config: StrategyConfig) -> list[str]:
    """Select the best domain filter set for the given strategy."""
    if _is_crypto_strategy(config):
        return _DOMAIN_SETS["crypto"]
    if "earnings" in config.name.lower():
        return _DOMAIN_SETS["earnings"]

    fmp = config.fmp_screener
    if fmp:
        if fmp.is_crypto:
            return _DOMAIN_SETS["crypto"]
        if fmp.country == "US" or fmp.exchange in ("NYSE", "NASDAQ", "AMEX"):
            base = list(_DOMAIN_SETS["us_stock"])
        elif fmp.country == "CA" or fmp.exchange in ("TSX", "TSXV"):
            base = list(_DOMAIN_SETS["canadian"])
        else:
            base = list(_DOMAIN_SETS["us_stock"])
    else:
        text = config.screening_prompt.lower()
        if "canadian" in text or "tsx" in text:
            base = list(_DOMAIN_SETS["canadian"])
        else:
            base = list(_DOMAIN_SETS["us_stock"])

    if config.news_scope == "macro":
        base.extend(d for d in _MACRO_DOMAINS if d not in base)

    return base


_CONSTRAINT_TO_CONTEXT_SIZE: dict[str, str] = {
    "tight": "high",
    "loose": "medium",
}


def _build_web_search_tool(config: StrategyConfig | None) -> dict:
    """Build the web_search tool definition with domain/recency filters.

    Args:
        config: Strategy configuration (None for defaults).

    Returns:
        Tool dict for the ``tools`` array in ``responses.create``.
    """
    recency_map = {"today": "day", "week": "week", "month": "month"}
    recency = recency_map.get(config.news_recency, "week") if config else "week"
    domains = _get_domain_set(config) if config else _DOMAIN_SETS["us_stock"]

    tool: dict = {
        "type": "web_search",
        "filters": {
            "search_domain_filter": domains,
            "search_recency_filter": recency,
        },
    }

    if config:
        ctx_size = _CONSTRAINT_TO_CONTEXT_SIZE.get(config.constraint_style, "high")
        tool["search_context_size"] = ctx_size

    return tool


def _build_tools(
    config: StrategyConfig | None,
    *,
    include_fmp: bool = False,
) -> list[dict]:
    """Build the tools array for the Agent API request.

    Args:
        config: Strategy configuration for web search filters.
        include_fmp: Whether to include the FMP screener function tool.

    Returns:
        List of tool definitions.
    """
    tools: list[dict] = [_build_web_search_tool(config)]
    if include_fmp:
        tools.append(FMP_TOOL_DEFINITION)
    return tools


# ---------------------------------------------------------------------------
# Citation extraction
# ---------------------------------------------------------------------------


def _extract_citations(output_items: list) -> list[str]:
    """Extract citation URLs from Agent API SearchResultsOutputItem objects.

    Args:
        output_items: The ``response.output`` list from Agent API.

    Returns:
        Deduplicated list of citation URLs.
    """
    urls: list[str] = []
    seen: set[str] = set()
    for item in output_items:
        if getattr(item, "type", None) == "search_results":
            for result in getattr(item, "results", None) or []:
                url = getattr(result, "url", "")
                if url and url not in seen:
                    urls.append(url)
                    seen.add(url)
    return urls


def _extract_text(output_items: list) -> str:
    """Extract the assistant's text content from Agent API output items.

    Args:
        output_items: The ``response.output`` list from Agent API.

    Returns:
        Concatenated text from all MessageOutputItem content parts.
    """
    parts: list[str] = []
    for item in output_items:
        if getattr(item, "type", None) == "message":
            for content_part in getattr(item, "content", None) or []:
                text = getattr(content_part, "text", "")
                if text:
                    parts.append(text)
    return "\n".join(parts)


def _audit_sources(result: ScreeningResult, citations: list[str]) -> None:
    """Flag LLM-generated sources that don't match any API citation.

    The ``sources`` field on ``FundamentalData`` is populated by the LLM's
    generated JSON — these are contextual references, not verified URLs.
    This function cross-checks them against the API-level citations and
    logs a warning for unmatched entries so operators can track
    hallucination rates.

    Args:
        result: Validated screening result.
        citations: Flat list of verified citation URLs from the API.
    """
    if not citations:
        return
    citation_text = " ".join(citations).lower()
    for td in result.tickers:
        for src in td.sources:
            slug = src.lower().replace(" ", "").replace(".", "")[:15]
            if slug and slug not in citation_text:
                logger.debug(
                    "Unverified source for %s: '%s' (not in API citations)",
                    td.ticker,
                    src,
                )


def _distribute_citations(result: ScreeningResult, citations: list[str]) -> None:
    """Match citation URLs to tickers by symbol or company name slug.

    Populates each ``FundamentalData.news_urls`` in-place. When no URL
    matches a ticker, the first 3 citations are used as a fallback.

    Args:
        result: Validated screening result with ticker data.
        citations: Flat list of citation URLs.
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


# ---------------------------------------------------------------------------
# FMP context formatting
# ---------------------------------------------------------------------------


def _format_fmp_context(candidates: list[FmpEnrichedStock]) -> str:
    """Format FMP pre-screened candidates as rich text for prompt injection.

    Includes composite scores, insider activity, price momentum, analyst
    consensus, quality scores, earnings dates, and relative volume when
    available. Candidates are assumed to be sorted by composite score.

    Args:
        candidates: Enriched and scored stock data from FMP.

    Returns:
        Formatted text block for inclusion in Perplexity prompts.
    """
    if not candidates:
        return ""

    lines = ["Pre-screened candidates from FMP (ranked by composite score):"]
    for s in candidates[:30]:
        parts = [f"- {s.symbol}: {s.company_name}"]
        if s.composite_score is not None:
            parts.append(f"Score {s.composite_score:.0f}/100")
        if s.price is not None:
            parts.append(f"${s.price:.2f}")
        if s.market_cap is not None:
            if s.market_cap >= 1_000_000_000:
                parts.append(f"MCap ${s.market_cap / 1_000_000_000:.1f}B")
            else:
                parts.append(f"MCap ${s.market_cap / 1_000_000:.0f}M")
        if s.volume is not None:
            parts.append(f"Vol {s.volume:,}")
        if s.relative_volume is not None:
            parts.append(f"RVOL {s.relative_volume:.1f}x")
        if s.sector:
            parts.append(f"[{s.sector}]")
        if s.pe_ratio is not None:
            parts.append(f"P/E {s.pe_ratio:.1f}")
        if s.peg_ratio is not None:
            parts.append(f"PEG {s.peg_ratio:.1f}")
        if s.roe is not None:
            parts.append(f"ROE {s.roe:.1f}%")
        if s.insider_net_buys is not None and s.insider_net_buys > 0:
            parts.append(f"Insider NET BUY ({s.insider_net_buys})")
        elif s.insider_net_buys is not None and s.insider_net_buys < 0:
            parts.append(f"Insider net sell ({s.insider_net_buys})")
        if s.analyst_consensus:
            parts.append(f"Analyst: {s.analyst_consensus}")
        if s.analyst_target_upside is not None:
            parts.append(f"Target upside {s.analyst_target_upside:+.0f}%")
        if s.price_change_1d is not None:
            parts.append(f"1D {s.price_change_1d:+.1f}%")
        if s.price_change_1m is not None:
            parts.append(f"1M {s.price_change_1m:+.1f}%")
        if s.price_change_3m is not None:
            parts.append(f"3M {s.price_change_3m:+.1f}%")
        if s.piotroski_score is not None:
            parts.append(f"Piotroski {s.piotroski_score}/9")
        if s.earnings_date:
            parts.append(f"Earnings {s.earnings_date}")
        if s.earnings_beat_rate is not None:
            parts.append(f"Beat rate {s.earnings_beat_rate:.0f}%")
        lines.append(" | ".join(parts))

    lines.append("")
    lines.append(
        "These candidates are ranked by a multi-factor composite score combining "
        "fundamental, momentum, sentiment, and quality signals. Insider buying, "
        "analyst consensus, and price momentum are pre-validated from FMP data. "
        "Analyze these candidates and select the best matches for the strategy. "
        "You may also use the screen_stocks tool to refine screening with "
        "different parameters if the current candidates don't fit well."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent API core call
# ---------------------------------------------------------------------------


async def _call_agent_api(
    system_prompt: str,
    user_prompt: str,
    *,
    tools: list[dict] | None = None,
    model: str = AGENT_MODEL,
    response_format: dict[str, Any] | None = None,
    search_mode: str | None = None,
) -> tuple[str, list[str]]:
    """Make a call to Perplexity Agent API, handling function calls.

    If the model returns function_call items (e.g. for the FMP tool),
    this function executes them and re-submits the results for a final
    response. Supports up to MAX_TOOL_ROUNDS of tool calling.

    Args:
        system_prompt: System instructions defining output format.
        user_prompt: User prompt (search-query-style or detailed).
        tools: Tool definitions for the ``tools`` parameter.
        model: Model identifier (e.g. ``"perplexity/sonar-pro"``).
        response_format: Optional structured output spec (json_schema).
        search_mode: Optional search mode (e.g. ``"sec"`` for SEC filings).

    Returns:
        Tuple of (response text, list of citation URLs).
    """
    client = _get_client()

    api_kwargs: dict[str, Any] = {
        "model": model,
        "instructions": system_prompt,
        "input": user_prompt,
    }
    if tools:
        api_kwargs["tools"] = tools
    if response_format:
        api_kwargs["response_format"] = response_format
    if search_mode:
        api_kwargs["search_mode"] = search_mode

    all_citations: list[str] = []

    async with _semaphore:
        response = await client.responses.create(**api_kwargs)

    all_citations.extend(_extract_citations(response.output))

    for _round in range(MAX_TOOL_ROUNDS):
        function_calls = [
            item for item in response.output if getattr(item, "type", None) == "function_call"
        ]
        if not function_calls:
            break

        logger.info(
            "Agent API returned %d function call(s), executing...",
            len(function_calls),
        )

        next_input: list[dict[str, Any]] = [item.model_dump() for item in response.output]

        for fc in function_calls:
            try:
                args = json.loads(fc.arguments)
            except json.JSONDecodeError:
                args = {}

            if fc.name == "screen_stocks":
                result_str = await execute_fmp_tool(args)
            else:
                result_str = json.dumps({"error": f"Unknown tool: {fc.name}"})

            next_input.append(
                {
                    "type": "function_call_output",
                    "call_id": fc.call_id,
                    "output": result_str,
                }
            )

        followup_kwargs: dict[str, Any] = {"model": model, "input": next_input}
        if tools:
            followup_kwargs["tools"] = tools

        async with _semaphore:
            response = await client.responses.create(**followup_kwargs)

        all_citations.extend(_extract_citations(response.output))

    text = _extract_text(response.output)
    return text, all_citations


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------


async def _call_with_retry(
    system_prompt: str,
    user_prompt: str,
    *,
    tools: list[dict] | None = None,
    model: str = AGENT_MODEL,
    response_format: dict[str, Any] | None = None,
    search_mode: str | None = None,
) -> tuple[ScreeningResult | None, list[str]]:
    """Call Agent API with validation retry logic.

    Retries up to MAX_RETRIES times on validation failure, appending the
    error details so the LM can self-correct.

    Args:
        system_prompt: System instructions defining output format.
        user_prompt: User prompt.
        tools: Tool definitions.
        model: Model identifier.
        response_format: Optional structured output spec (json_schema).
        search_mode: Optional search mode (e.g. ``"sec"``).

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
            raw_text, citations = await _call_agent_api(
                system_prompt,
                effective_prompt,
                tools=tools,
                model=model,
                response_format=response_format,
                search_mode=search_mode,
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
            _audit_sources(result, all_citations)
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


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def _build_dynamic_system_prompt(config: StrategyConfig | None) -> str:
    """Build a market-context-aware system prompt from the strategy's FMP config.

    Args:
        config: Strategy config (may be None for default behavior).

    Returns:
        System prompt string tailored to the effective market/sector focus.
    """
    if not config or not config.fmp_screener:
        return build_system_prompt(ta_focus=config.ta_focus if config else None)

    fmp = config.fmp_screener
    return build_system_prompt(
        country=fmp.country,
        exchange=fmp.exchange,
        sector=fmp.sector,
        is_crypto=fmp.is_crypto,
        ta_focus=config.ta_focus,
    )


_SEC_STRATEGY_TYPES = frozenset({"event", "value"})

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {"schema": ScreeningResult.model_json_schema()},
}


def _get_search_mode(config: StrategyConfig | None) -> str | None:
    """Return ``"sec"`` for event/value strategies, else ``None``."""
    if config and config.strategy_type in _SEC_STRATEGY_TYPES:
        return "sec"
    return None


async def run_discovery(
    config: StrategyConfig,
    *,
    fmp_candidates: list[FmpEnrichedStock] | None = None,
) -> tuple[ScreeningResult | None, dict]:
    """Run Perplexity in discovery mode to screen the market.

    Args:
        config: Strategy configuration driving the screening prompt.
        fmp_candidates: Optional pre-screened stocks from FMP to include
            as context in the prompt and enable the FMP tool.

    Returns:
        Tuple of (validated ScreeningResult or None, metadata dict).
    """
    system_prompt = _build_dynamic_system_prompt(config)

    base_prompt = build_discovery_prompt(config)
    fmp_context = _format_fmp_context(fmp_candidates) if fmp_candidates else ""
    user_prompt = f"{base_prompt}\n\n{fmp_context}" if fmp_context else base_prompt

    include_fmp = bool(fmp_candidates) or (
        config.fmp_screener is not None and config.fmp_screener.enabled
    )
    tools = _build_tools(config, include_fmp=include_fmp)
    search_mode = _get_search_mode(config)

    metadata: dict = {
        "stage": "perplexity",
        "mode": "discovery",
        "model": AGENT_MODEL,
        "prompt_hash": discovery_hash(),
        "prompt_text": f"{system_prompt}\n---\n{user_prompt}",
        "fmp_candidates_count": len(fmp_candidates) if fmp_candidates else 0,
    }

    start = time.perf_counter()
    try:
        result, citations = await _call_with_retry(
            system_prompt,
            user_prompt,
            tools=tools,
            response_format=_RESPONSE_FORMAT,
            search_mode=search_mode,
        )
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "success" if result else "validation_failed"
        if result is not None:
            if fmp_candidates:
                result.fmp_pre_screened = [s.symbol for s in fmp_candidates]
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
    *,
    fmp_candidates: list[FmpEnrichedStock] | None = None,
) -> tuple[ScreeningResult | None, dict]:
    """Run Perplexity in prompt-driven discovery mode.

    The user's free-form text drives the screening. If a strategy is
    selected its constraints are layered on top. FMP candidates and
    tool are included when available.

    Args:
        user_prompt: The user's free-form screening request.
        config: Optional strategy configuration for additional context.
        fmp_candidates: Optional pre-screened stocks from FMP.

    Returns:
        Tuple of (validated ScreeningResult or None, metadata dict).
    """
    system_prompt = _build_dynamic_system_prompt(config)

    base_prompt = build_prompted_discovery_prompt(user_prompt, config)
    fmp_context = _format_fmp_context(fmp_candidates) if fmp_candidates else ""
    prompt = f"{base_prompt}\n\n{fmp_context}" if fmp_context else base_prompt

    include_fmp = bool(fmp_candidates) or (
        config is not None and config.fmp_screener is not None and config.fmp_screener.enabled
    )
    tools = _build_tools(config, include_fmp=include_fmp)
    search_mode = _get_search_mode(config)

    metadata: dict = {
        "stage": "perplexity",
        "mode": "prompt",
        "model": AGENT_MODEL,
        "prompt_hash": discovery_hash(),
        "prompt_text": f"{system_prompt}\n---\n{prompt}",
        "fmp_candidates_count": len(fmp_candidates) if fmp_candidates else 0,
    }

    start = time.perf_counter()
    try:
        result, citations = await _call_with_retry(
            system_prompt,
            prompt,
            tools=tools,
            response_format=_RESPONSE_FORMAT,
            search_mode=search_mode,
        )
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "success" if result else "validation_failed"
        if result is not None:
            if fmp_candidates:
                result.fmp_pre_screened = [s.symbol for s in fmp_candidates]
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


async def run_bull_bear_discovery(
    config: StrategyConfig,
    *,
    fmp_candidates: list[FmpEnrichedStock] | None = None,
) -> tuple[ScreeningResult | None, dict]:
    """Run parallel bull/bear Perplexity discovery when enable_debate=True.

    Makes two parallel discovery calls with opposing perspective prompts:
    - Bull call: focuses on upside catalysts, momentum, breakout potential
    - Bear call: focuses on downside risks, headwinds, overvaluation

    Results are merged: tickers found by both = high conviction,
    bull-only = speculative, bear-only = risk-flagged.

    Args:
        config: Strategy configuration driving the screening prompt.
        fmp_candidates: Optional pre-screened stocks from FMP.

    Returns:
        Tuple of (merged ScreeningResult or None, metadata dict).
    """
    system_prompt = _build_dynamic_system_prompt(config)

    base_prompt = build_discovery_prompt(config)
    fmp_context = _format_fmp_context(fmp_candidates) if fmp_candidates else ""

    bull_suffix = (
        " bullish catalysts momentum breakout insider buying analyst upgrades"
        " revenue acceleration strong relative volume"
    )
    bear_suffix = (
        " bearish risks headwinds overvaluation insider selling analyst downgrades"
        " margin compression declining volume"
    )

    bull_prompt = f"{base_prompt}{bull_suffix}"
    bear_prompt = f"{base_prompt}{bear_suffix}"

    if fmp_context:
        bull_prompt = f"{bull_prompt}\n\n{fmp_context}"
        bear_prompt = f"{bear_prompt}\n\n{fmp_context}"

    include_fmp = bool(fmp_candidates) or (
        config.fmp_screener is not None and config.fmp_screener.enabled
    )
    tools = _build_tools(config, include_fmp=include_fmp)
    search_mode = _get_search_mode(config)

    metadata: dict = {
        "stage": "perplexity",
        "mode": "bull_bear_discovery",
        "model": AGENT_MODEL,
        "prompt_hash": discovery_hash(),
        "fmp_candidates_count": len(fmp_candidates) if fmp_candidates else 0,
    }

    start = time.perf_counter()
    try:
        (bull_result, bull_cit), (bear_result, bear_cit) = await asyncio.gather(
            _call_with_retry(
                system_prompt, bull_prompt, tools=tools,
                response_format=_RESPONSE_FORMAT, search_mode=search_mode,
            ),
            _call_with_retry(
                system_prompt, bear_prompt, tools=tools,
                response_format=_RESPONSE_FORMAT, search_mode=search_mode,
            ),
        )

        merged = _merge_bull_bear(bull_result, bear_result)

        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "success" if merged else "validation_failed"
        if merged is not None:
            if fmp_candidates:
                merged.fmp_pre_screened = [s.symbol for s in fmp_candidates]
            metadata["raw_response"] = merged.model_dump_json()
            all_citations = list(dict.fromkeys(bull_cit + bear_cit))
            merged.citations = all_citations
            _distribute_citations(merged, all_citations)
            _audit_sources(merged, all_citations)
        return merged, metadata

    except Exception as exc:
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "api_error"
        metadata["error"] = str(exc)
        logger.exception("Perplexity bull/bear discovery failed")
        return None, metadata


def _merge_bull_bear(
    bull: ScreeningResult | None,
    bear: ScreeningResult | None,
) -> ScreeningResult | None:
    """Merge bull and bear screening results with conviction markers.

    Tickers found in both results are marked as high conviction.
    Bull-only tickers get a "speculative" highlight.
    Bear-only tickers get a "risk-flagged" highlight.

    Args:
        bull: Bull-perspective screening result (or None).
        bear: Bear-perspective screening result (or None).

    Returns:
        Merged ScreeningResult, or whichever is non-None.
    """
    if not bull and not bear:
        return None
    if not bull:
        return bear
    if not bear:
        return bull

    bull_tickers = {td.ticker: td for td in bull.tickers}
    bear_tickers = {td.ticker: td for td in bear.tickers}

    overlap = set(bull_tickers.keys()) & set(bear_tickers.keys())
    bull_only = set(bull_tickers.keys()) - overlap
    bear_only = set(bear_tickers.keys()) - overlap

    merged_tickers = []
    for ticker in overlap:
        td = bull_tickers[ticker]
        td.key_highlights = [
            "[HIGH CONVICTION] Found by both bull and bear analysis"
        ] + td.key_highlights
        merged_tickers.append(td)

    for ticker in bull_only:
        td = bull_tickers[ticker]
        td.key_highlights = ["[BULL ONLY] Speculative — upside catalysts"] + td.key_highlights
        merged_tickers.append(td)

    for ticker in bear_only:
        td = bear_tickers[ticker]
        td.key_highlights = ["[BEAR FLAGGED] Risk factors identified"] + td.key_highlights
        td.risk_factors = bear_tickers[ticker].risk_factors + td.risk_factors
        merged_tickers.append(td)

    return ScreeningResult(
        mode=bull.mode,
        strategy_name=bull.strategy_name,
        tickers=merged_tickers,
        screening_summary=(
            f"Bull/Bear parallel discovery: {len(overlap)} high conviction, "
            f"{len(bull_only)} bull-only speculative, {len(bear_only)} bear-flagged. "
            f"Bull: {bull.screening_summary[:200]} | Bear: {bear.screening_summary[:200]}"
        ),
    )


async def run_analysis(
    tickers: list[str],
    config: StrategyConfig | None = None,
) -> tuple[ScreeningResult | None, dict]:
    """Run Perplexity in analysis mode to research given tickers.

    Analysis mode does not use FMP pre-screening since the tickers
    are already specified by the user.

    Args:
        tickers: List of ticker symbols to research.
        config: Optional strategy configuration for context.

    Returns:
        Tuple of (validated ScreeningResult or None, metadata dict).
    """
    user_prompt = build_analysis_prompt(tickers, config)
    tools = _build_tools(config, include_fmp=False)
    search_mode = _get_search_mode(config)

    metadata: dict = {
        "stage": "perplexity",
        "mode": "analysis",
        "model": AGENT_MODEL,
        "prompt_hash": analysis_hash(),
        "prompt_text": f"{ANALYSIS_SYSTEM_PROMPT}\n---\n{user_prompt}",
    }

    start = time.perf_counter()
    try:
        result, citations = await _call_with_retry(
            ANALYSIS_SYSTEM_PROMPT,
            user_prompt,
            tools=tools,
            response_format=_RESPONSE_FORMAT,
            search_mode=search_mode,
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
