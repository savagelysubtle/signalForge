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

from pipeline.prompts.regime_classifier import (
    REGIME_SYSTEM_PROMPT,
    build_regime_prompt,
)
from pipeline.schemas import RegimeOutput
from pipeline.validation import validate_llm_json
from services.keyring_service import get_api_key

logger = logging.getLogger(__name__)

AGENT_MODEL = "perplexity/sonar"
MAX_RETRIES = 1

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


async def classify_regime(run_id: str) -> tuple[RegimeOutput | None, dict]:
    """Classify the current market regime via Perplexity web search.

    Args:
        run_id: Pipeline run identifier for logging.

    Returns:
        Tuple of (RegimeOutput or None on failure, stage metadata dict).
    """
    start = time.perf_counter()
    user_prompt = build_regime_prompt()

    metadata: dict = {
        "stage": "regime",
        "ticker": "_market",
        "prompt_text": user_prompt,
        "model_used": AGENT_MODEL,
        "status": "pending",
    }

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

    client = _get_client()

    api_kwargs: dict[str, Any] = {
        "model": AGENT_MODEL,
        "instructions": REGIME_SYSTEM_PROMPT,
        "input": user_prompt,
        "tools": tools,
    }

    for attempt in range(MAX_RETRIES + 1):
        try:
            async with _semaphore:
                response = await client.responses.create(**api_kwargs)

            raw_text = _extract_text(response.output)
            metadata["raw_response"] = raw_text

            regime = validate_llm_json(raw_text, RegimeOutput)
            if regime is not None:
                elapsed = time.perf_counter() - start
                metadata["status"] = "success"
                metadata["duration_ms"] = int(elapsed * 1000)
                metadata["parsed_output"] = regime.model_dump()
                logger.info(
                    "Regime classified: %s (VIX=%s, breadth=%s) in %.1fs",
                    regime.regime_type,
                    regime.vix_estimate,
                    regime.breadth_estimate,
                    elapsed,
                )
                return regime, metadata

            if attempt < MAX_RETRIES:
                logger.warning("Regime validation failed, retrying (attempt %d)", attempt + 1)

        except Exception:
            logger.exception("Regime classifier call failed (attempt %d)", attempt)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(1)

    elapsed = time.perf_counter() - start
    metadata["status"] = "failed"
    metadata["duration_ms"] = int(elapsed * 1000)
    logger.warning("Regime classifier failed after %d attempts", MAX_RETRIES + 1)
    return None, metadata
