"""Token budget management for LLM prompts.

Counts tokens in composed prompts and truncates lower-priority sections
when the prompt exceeds the model's context budget. Uses tiktoken when
available; falls back to a conservative character-based estimator.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_encoder: Any = None
_USE_TIKTOKEN = False

try:
    import tiktoken

    _encoder = tiktoken.encoding_for_model("gpt-4o")
    _USE_TIKTOKEN = True
except Exception:
    logger.debug("tiktoken not available, using character-based token estimation")


def count_tokens(text: str) -> int:
    """Count tokens in a string.

    Uses tiktoken for accuracy when available, otherwise estimates
    at ~4 characters per token (conservative for English text).
    """
    if _USE_TIKTOKEN and _encoder is not None:
        return len(_encoder.encode(text))
    return len(text) // 4


_MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "gpt-5.4": 128_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
}

BUDGET_FRACTION = 0.80
OUTPUT_RESERVE = 8_192

_TRUNCATION_ORDER = [
    "## HISTORICAL PERFORMANCE CONTEXT",
    "## SECTOR SENTIMENT CONSENSUS",
    "## BULL CASE ARGUMENTS",
    "## BEAR CASE ARGUMENTS",
    "## QUANTITATIVE DATA (FMP)",
    "## === RAW NUMERICAL DATA",
]


def enforce_token_budget(
    system_prompt: str,
    user_prompt: str,
    model: str = "gpt-5.4",
) -> str:
    """Truncate user prompt sections if the total exceeds the model budget.

    Removes sections in priority order (lowest value first) until the
    prompt fits within the budget. Logs a warning whenever truncation occurs.

    Args:
        system_prompt: The system prompt (not truncated).
        user_prompt: The user prompt (may be truncated).
        model: Model name for context limit lookup.

    Returns:
        The user prompt, possibly with sections removed.
    """
    context_limit = _MODEL_CONTEXT_LIMITS.get(model, 128_000)
    max_input_tokens = int(context_limit * BUDGET_FRACTION) - OUTPUT_RESERVE

    total = count_tokens(system_prompt) + count_tokens(user_prompt)
    if total <= max_input_tokens:
        return user_prompt

    logger.warning(
        "Prompt exceeds token budget: %d tokens (limit %d for %s). Truncating.",
        total,
        max_input_tokens,
        model,
    )

    lines = user_prompt.split("\n")
    for section_header in _TRUNCATION_ORDER:
        start_idx = None
        end_idx = None
        for i, line in enumerate(lines):
            if section_header in line:
                start_idx = i
            elif start_idx is not None and line.startswith("## ") and i > start_idx:
                end_idx = i
                break

        if start_idx is not None:
            if end_idx is None:
                end_idx = len(lines)

            removed_text = "\n".join(lines[start_idx:end_idx])
            removed_tokens = count_tokens(removed_text)
            lines = [
                *lines[:start_idx],
                f"{section_header} [TRUNCATED — {removed_tokens} tokens removed to fit budget]",
                "",
                *lines[end_idx:],
            ]

            new_prompt = "\n".join(lines)
            new_total = count_tokens(system_prompt) + count_tokens(new_prompt)
            logger.info(
                "Removed '%s' (%d tokens). New total: %d/%d",
                section_header,
                removed_tokens,
                new_total,
                max_input_tokens,
            )
            if new_total <= max_input_tokens:
                return new_prompt

    return "\n".join(lines)
