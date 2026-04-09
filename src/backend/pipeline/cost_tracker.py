"""Per-run LLM cost tracking.

Accumulates estimated cost per LLM API call based on input/output token
counts and model pricing. Persisted to ``pipeline_runs.meta`` at run end.

Pricing is approximate and should be updated when model pricing changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Stages whose outputs represent LLM token streams (prompt + completion text).
_LLM_TOKEN_COST_STAGES: frozenset[str] = frozenset(
    {
        "perplexity",
        "gemini",
        "claude",
        "gpt_bull",
        "gpt_bear",
        "gpt_judge",
        "regime",
    }
)

# model / model_used values that are not billed per token like chat LLMs.
_NON_TOKEN_COST_MODELS: frozenset[str] = frozenset(
    {
        "fmp-api",
        "heartbeat-cache",
        "deterministic",
        "chart-img-v2",
        "lightgbm",
    }
)


def should_estimate_cost_from_metadata(metadata: dict[str, Any]) -> bool:
    """Return True if stage metadata should contribute to token-based cost estimates.

    Skips FMP JSON blobs, cached regime, ML gates, chart APIs, etc. Those saves
    often carry huge ``raw_response`` strings; counting tokens on them is slow
    and produces meaningless USD figures.
    """
    if not metadata:
        return False
    if metadata.get("status") == "api_error":
        return False
    stage = metadata.get("stage") or ""
    if stage not in _LLM_TOKEN_COST_STAGES:
        return False
    model = (metadata.get("model") or metadata.get("model_used") or "").strip()
    if not model:
        return False
    if model in _NON_TOKEN_COST_MODELS:
        return False
    return not model.lower().startswith("lightgbm")


# Approximate per-million-token pricing (USD). Update as needed.
_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_M, output_per_M)
    "gpt-5.4": (2.50, 10.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "claude-opus-4-6": (15.00, 75.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "gemini-2.5-pro": (1.25, 10.00),
    "openai/gpt-5.4": (2.50, 10.00),
    "perplexity/sonar": (1.00, 1.00),
}


@dataclass
class CostEntry:
    """A single LLM API call cost record."""

    stage: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class PipelineCostTracker:
    """Accumulates cost across all LLM calls in a pipeline run."""

    entries: list[CostEntry] = field(default_factory=list)

    def record(
        self,
        stage: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> CostEntry:
        """Record a single API call's token usage and estimated cost.

        Args:
            stage: Pipeline stage name (e.g. "gpt_judge", "claude", "gemini").
            model: Model identifier.
            input_tokens: Number of input/prompt tokens.
            output_tokens: Number of output/completion tokens.

        Returns:
            The recorded CostEntry.
        """
        input_rate, output_rate = _PRICING.get(model, (5.0, 15.0))
        cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000

        entry = CostEntry(
            stage=stage,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
        )
        self.entries.append(entry)
        return entry

    @property
    def total_cost_usd(self) -> float:
        return round(sum(e.cost_usd for e in self.entries), 6)

    @property
    def total_input_tokens(self) -> int:
        return sum(e.input_tokens for e in self.entries)

    @property
    def total_output_tokens(self) -> int:
        return sum(e.output_tokens for e in self.entries)

    def summary(self) -> dict[str, Any]:
        """Return a JSON-serializable summary for persistence."""
        return {
            "total_cost_usd": self.total_cost_usd,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "call_count": len(self.entries),
            "by_stage": {
                stage: {
                    "calls": len(stage_entries),
                    "input_tokens": sum(e.input_tokens for e in stage_entries),
                    "output_tokens": sum(e.output_tokens for e in stage_entries),
                    "cost_usd": round(sum(e.cost_usd for e in stage_entries), 6),
                }
                for stage in dict.fromkeys(e.stage for e in self.entries)
                if (stage_entries := [e for e in self.entries if e.stage == stage])
            },
        }
