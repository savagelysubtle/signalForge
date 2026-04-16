"""Pydantic models for audit records, grade results, and reports."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RecommendationAction(StrEnum):
    """Possible pipeline recommendation actions."""

    BUY = "BUY"
    SHORT = "SHORT"
    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"
    WATCH = "WATCH"


class TradeGradeLabel(StrEnum):
    """Outcome label for active trade grading (BUY/SHORT)."""

    TP_HIT = "TP_HIT"
    SL_HIT = "SL_HIT"
    TIME_EXIT = "TIME_EXIT"


class WatchGradeLabel(StrEnum):
    """Outcome label for WATCH / entry-trigger grading."""

    ENTRY_REACHED_PROFITABLE = "ENTRY_REACHED_PROFITABLE"
    ENTRY_REACHED_UNPROFITABLE = "ENTRY_REACHED_UNPROFITABLE"
    ENTRY_NEVER_REACHED = "ENTRY_NEVER_REACHED"


class TimingLabel(StrEnum):
    """How the actual resolution timing compared to the predicted holding period."""

    EARLY = "EARLY"
    ON_TIME = "ON_TIME"
    LATE = "LATE"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Grade result models
# ---------------------------------------------------------------------------


class TradeGrade(BaseModel):
    """Result of active-trade grading (BUY/SHORT)."""

    label: TradeGradeLabel
    profitable: bool
    actual_return_pct: float
    bars_to_resolution: int
    mfe_pct: float = 0.0
    mae_pct: float = 0.0


class WatchGrade(BaseModel):
    """Result of watch / entry-trigger grading."""

    label: WatchGradeLabel
    entry_price_target: float | None = None
    price_reached: float | None = None
    bars_to_entry: int | None = None
    hypothetical_return_pct: float | None = None


class DirectionGrade(BaseModel):
    """Whether the price moved in the predicted direction."""

    predicted_direction: str  # "UP", "DOWN", "FLAT"
    actual_direction: str
    actual_return_pct: float
    correct: bool
    horizon_bars: int


class TimingGrade(BaseModel):
    """How accurately the pipeline predicted the holding period."""

    label: TimingLabel
    predicted_bars: int | None = None
    actual_bars: int | None = None


# ---------------------------------------------------------------------------
# Audit record (one per recommendation)
# ---------------------------------------------------------------------------


class AuditRecord(BaseModel):
    """Full audit of a single recommendation, combining all grading dimensions."""

    recommendation_id: str
    ticker: str
    action: str
    confidence: float | None = None
    confidence_label: str | None = None

    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    holding_period: str | None = None
    price_at_signal: float | None = None

    signal_date: datetime | None = None
    strategy_name: str | None = None
    pipeline_mode: str | None = None

    user_decision: str | None = None
    logged_pnl_pct: float | None = None

    trade_grade: TradeGrade | None = None
    watch_grade: WatchGrade | None = None
    direction_grade: DirectionGrade | None = None
    timing_grade: TimingGrade | None = None

    skip_reason: str | None = None
    audited_at: datetime | None = None


# ---------------------------------------------------------------------------
# Aggregated report models
# ---------------------------------------------------------------------------


class BucketStats(BaseModel):
    """Win/loss stats for a single grouping bucket."""

    total: int = 0
    wins: int = 0
    losses: int = 0
    skipped: int = 0
    win_rate: float = 0.0
    avg_return_pct: float = 0.0
    avg_confidence: float = 0.0


class CalibrationBucket(BaseModel):
    """Confidence calibration for one confidence range."""

    range_label: str  # e.g. "60-70%"
    predicted_confidence: float
    actual_win_rate: float
    count: int
    calibration_error: float  # |predicted - actual|


class AuditReport(BaseModel):
    """Aggregated audit report across all graded recommendations."""

    generated_at: datetime = Field(default_factory=datetime.now)
    total_recommendations: int = 0
    total_graded: int = 0
    total_skipped: int = 0

    overall_win_rate: float = 0.0
    overall_avg_return_pct: float = 0.0
    overall_direction_accuracy: float = 0.0

    by_action: dict[str, BucketStats] = Field(default_factory=dict)
    by_strategy: dict[str, BucketStats] = Field(default_factory=dict)
    by_confidence_bucket: dict[str, BucketStats] = Field(default_factory=dict)

    calibration: list[CalibrationBucket] = Field(default_factory=list)
    calibration_error_mean: float = 0.0

    timing_breakdown: dict[str, int] = Field(default_factory=dict)

    top_winners: list[dict[str, Any]] = Field(default_factory=list)
    top_losers: list[dict[str, Any]] = Field(default_factory=list)
