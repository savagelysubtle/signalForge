"""Stage 0.5: Market regime classification via Perplexity web search.

A single lightweight Perplexity call that assesses the current macro
environment. The result is injected as context into all downstream
stage prompts.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from perplexity import AsyncPerplexity

from pipeline.model_config import REGIME_MODEL as AGENT_MODEL
from pipeline.prompts.regime_classifier import (
    REGIME_SYSTEM_PROMPT,
    build_regime_prompt,
)
from pipeline.schemas import RegimeOutput
from pipeline.validation import with_validation_retry
from services.keyring_service import get_api_key

logger = logging.getLogger(__name__)

_semaphore = asyncio.Semaphore(3)


def _get_client() -> AsyncPerplexity:
    """Build an AsyncPerplexity client."""
    api_key = get_api_key("perplexity")
    if not api_key:
        raise RuntimeError("Perplexity API key not configured for regime classifier.")
    return AsyncPerplexity(api_key=api_key)


def _extract_text(output_items: list) -> str:
    """Extract assistant text from Agent API output items."""
    parts: list[str] = []
    for item in output_items:
        if getattr(item, "type", None) == "message":
            for content_part in getattr(item, "content", None) or []:
                text = getattr(content_part, "text", "")
                if text:
                    parts.append(text)
    return "\n".join(parts)


@with_validation_retry(schema=RegimeOutput, max_retries=1, provider="perplexity")
async def _call_regime_api(
    system_prompt: str,
    user_prompt: str,
    *,
    error_context: str = "",
) -> str:
    """Make a single regime classification API call.

    Args:
        system_prompt: System instruction for regime classification.
        user_prompt: Prompt with ground-truth data and classification request.
        error_context: Appended on retries for self-correction.

    Returns:
        Raw response text from the API.
    """
    client = _get_client()

    full_prompt = user_prompt
    if error_context:
        full_prompt = f"{user_prompt}\n\n---\nCORRECTION: {error_context}"

    tools = [
        {
            "type": "web_search",
            "filters": {
                "search_domain_filter": [
                    "reuters.com",
                    "bloomberg.com",
                    "cnbc.com",
                    "marketwatch.com",
                    "finance.yahoo.com",
                    "barrons.com",
                ],
                "search_recency_filter": "day",
            },
        }
    ]

    api_kwargs: dict[str, Any] = {
        "model": AGENT_MODEL,
        "instructions": system_prompt,
        "input": full_prompt,
        "tools": tools,
    }

    async with _semaphore:
        response = await client.responses.create(**api_kwargs)

    return _extract_text(response.output)


async def classify_regime(
    run_id: str,
    sector_data: list[dict] | None = None,
    vix_value: float | None = None,
    vix_label: str | None = None,
) -> tuple[RegimeOutput | None, dict]:
    """Classify the current market regime via Perplexity web search.

    When ground-truth FMP data is provided (sector performance, VIX),
    it is embedded in the prompt so the LLM interprets rather than estimates.

    Args:
        run_id: Pipeline run identifier for logging.
        sector_data: Optional sector performance dicts from FMP.
        vix_value: Optional current VIX value from FMP.
        vix_label: Optional pre-classified VIX label.

    Returns:
        Tuple of (RegimeOutput or None on failure, stage metadata dict).
    """
    start = time.perf_counter()
    user_prompt = build_regime_prompt(
        sector_data=sector_data,
        vix_value=vix_value,
        vix_label=vix_label,
    )

    metadata: dict = {
        "stage": "regime",
        "ticker": "_market",
        "prompt_text": user_prompt,
        "model": AGENT_MODEL,
        "model_used": AGENT_MODEL,
        "status": "pending",
    }

    try:
        regime = await _call_regime_api(REGIME_SYSTEM_PROMPT, user_prompt)
        elapsed = time.perf_counter() - start
        metadata["duration_ms"] = int(elapsed * 1000)

        if regime is not None:
            metadata["status"] = "success"
            metadata["raw_response"] = regime.model_dump_json()
            metadata["parsed_output"] = regime.model_dump()
            logger.info(
                "Regime classified: %s (VIX=%s, breadth=%s) in %.1fs",
                regime.regime_type,
                regime.vix_estimate,
                regime.breadth_estimate,
                elapsed,
            )
            return regime, metadata

        metadata["status"] = "validation_failed"
        logger.warning("Regime classifier validation failed after retries")
        return None, metadata

    except Exception:
        elapsed = time.perf_counter() - start
        metadata["status"] = "failed"
        metadata["duration_ms"] = int(elapsed * 1000)
        logger.exception("Regime classifier failed")
        return None, metadata
