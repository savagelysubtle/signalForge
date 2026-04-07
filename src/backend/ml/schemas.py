"""Pydantic models for ML prediction and judge report responses.

These mirror the training pipeline's data structures for the
inference and API layers.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MLPrediction(BaseModel):
    """Single ML prediction for a ticker."""

    ticker: str
    strategy_type: str
    predicted_direction: Literal["UP", "DOWN", "FLAT"]
    probability_up: float = Field(ge=0.0, le=1.0)
    probability_down: float = Field(ge=0.0, le=1.0)
    probability_flat: float = Field(ge=0.0, le=1.0)
    probability_profitable: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="P(trade hits TP before SL) — set for binary models, None for 3-class",
    )
    probability_interval: tuple[float, float] | None = None
    predicted_return_pct: float = 0.0
    prediction_set: list[str] = Field(default_factory=list)
    reliability_score: float = Field(ge=0.0, le=1.0, default=0.0)
    top_features: list[dict[str, float]] = Field(default_factory=list)
    model_version: str = ""
    wfo_fold_accuracy: float = 0.0


class MLModelInfo(BaseModel):
    """Information about the currently loaded ML model."""

    model_version: str = ""
    training_date: str = ""
    overall_accuracy: float = 0.0
    approved_strategies: list[str] = Field(default_factory=list)
    judge_verdict: str = ""
    status: str = "inactive"
    feature_count: int = 0


class GateResult(BaseModel):
    """Result from the ML gate (independent model) for one recommendation."""

    ticker: str
    ml_probability: float = Field(ge=0.0, le=1.0)
    predicted_direction: Literal["UP", "DOWN", "FLAT"]
    size_multiplier: float = Field(ge=0.0, le=1.0, default=1.0)
    blocked: bool = False
    conformal_set: list[str] = Field(default_factory=list)
    reliability_score: float = Field(ge=0.0, le=1.0, default=0.0)
    model_version: str = ""
    meta_conviction: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Meta-labeler conviction P(signal is profitable), None if no meta-labeler",
    )
    reason: str = ""


class ShadowComparison(BaseModel):
    """ML vs GPT comparison for a single prediction."""

    ticker: str
    ml_direction: str
    ml_confidence: float
    gpt_action: str
    gpt_confidence: float
    agreed: bool
    actual_direction: str | None = None
    ml_correct: bool | None = None
    gpt_correct: bool | None = None


class ShadowStats(BaseModel):
    """Aggregated shadow mode statistics."""

    total_predictions: int = 0
    predictions_with_outcomes: int = 0
    ml_accuracy: float | None = None
    gpt_accuracy: float | None = None
    agreement_rate: float = 0.0
    ml_wins_on_disagreement: int = 0
    gpt_wins_on_disagreement: int = 0
    model_version: str = ""
