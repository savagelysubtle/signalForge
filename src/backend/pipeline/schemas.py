"""Pydantic models defining the data contracts for every pipeline stage.

Every LLM output must be validated against these schemas before flowing
downstream. If it's not a validated model, it's a bug.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from utils.ticker import normalize_ticker

# ---------------------------------------------------------------------------
# Recommendation Action Enum
# ---------------------------------------------------------------------------


class RecommendationAction(StrEnum):
    """Valid recommendation actions for the pipeline judge."""

    BUY = "BUY"
    SHORT = "SHORT"
    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"
    WATCH = "WATCH"


# ---------------------------------------------------------------------------
# Confidence Label Enum (replaces raw float from LLM output)
# ---------------------------------------------------------------------------


class ConfidenceLabel(StrEnum):
    """Ordered confidence labels for LLM output.

    LLMs produce one of these categorical labels instead of a raw float.
    The ``CONFIDENCE_LABEL_MAP`` below converts to a deterministic numeric
    value owned by the application, not the model.
    """

    C0_NO_CONFIDENCE = "c0_no_confidence"
    C1_VERY_LOW = "c1_very_low"
    C2_LOW = "c2_low"
    C3_SLIGHTLY_LOW = "c3_slightly_low"
    C4_LEAN_LOW = "c4_lean_low"
    C5_NEUTRAL = "c5_neutral"
    C6_LEAN_HIGH = "c6_lean_high"
    C7_SLIGHTLY_HIGH = "c7_slightly_high"
    C8_HIGH = "c8_high"
    C9_VERY_HIGH = "c9_very_high"
    C10_MAX_CONFIDENCE = "c10_max_confidence"


CONFIDENCE_LABEL_MAP: dict[ConfidenceLabel, float] = {
    ConfidenceLabel.C0_NO_CONFIDENCE: 0.00,
    ConfidenceLabel.C1_VERY_LOW: 0.10,
    ConfidenceLabel.C2_LOW: 0.20,
    ConfidenceLabel.C3_SLIGHTLY_LOW: 0.30,
    ConfidenceLabel.C4_LEAN_LOW: 0.40,
    ConfidenceLabel.C5_NEUTRAL: 0.50,
    ConfidenceLabel.C6_LEAN_HIGH: 0.60,
    ConfidenceLabel.C7_SLIGHTLY_HIGH: 0.70,
    ConfidenceLabel.C8_HIGH: 0.80,
    ConfidenceLabel.C9_VERY_HIGH: 0.90,
    ConfidenceLabel.C10_MAX_CONFIDENCE: 1.00,
}


def confidence_label_to_float(label: ConfidenceLabel | str) -> float:
    """Convert a confidence label to its mapped float value.

    Args:
        label: A ``ConfidenceLabel`` member or its string value.

    Returns:
        The deterministic float value from ``CONFIDENCE_LABEL_MAP``.

    Raises:
        ValueError: If the label is not a valid ``ConfidenceLabel``.
    """
    if isinstance(label, str):
        label = ConfidenceLabel(label)
    return CONFIDENCE_LABEL_MAP[label]


# ---------------------------------------------------------------------------
# Track Agreement (v2 pipeline — independent track alignment)
# ---------------------------------------------------------------------------

_DIRECTION = Literal["bullish", "bearish", "neutral"]


class TrackAgreement(BaseModel):
    """How the three independent analysis tracks aligned."""

    perplexity_direction: _DIRECTION = "neutral"
    gemini_direction: _DIRECTION = "neutral"
    claude_direction: _DIRECTION = "neutral"
    agreement_score: float = Field(
        ge=0.0, le=1.0, default=0.0, description="0.0 = full disagreement, 1.0 = unanimous"
    )
    conflicts: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Confidence Calibration (v2 pipeline — Phase 7)
# ---------------------------------------------------------------------------


class ConfidenceBreakdown(BaseModel):
    """Structured confidence decomposition for the v2 confidence engine.

    Replaces the fixed-weight sub-component model with a prior→boosters→ML
    architecture. Each field represents a distinct contributor to the final
    ``win_probability``.
    """

    prior_base_rate: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Starting probability from strategy/regime lookup table",
    )
    setup_quality_score: float = Field(
        default=0.0,
        ge=-0.15,
        le=0.15,
        description="Net effect of positive/negative evidence boosters",
    )
    ml_agreement: Literal["agree", "disagree", "neutral", "unavailable"] = "unavailable"
    llm_conviction: Literal["low", "medium", "high"] | None = None
    win_probability: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Final calibrated probability used for EV and sizing",
    )
    confidence_drivers: list[str] = Field(
        default_factory=list,
        description="Top 2-3 factors that moved the number, e.g. 'Strong RVOL (+6%)'",
    )
    penalties_applied: list[str] = Field(default_factory=list)


class SignalStrength(StrEnum):
    """Position-sizing hint derived from calibrated confidence."""

    STRONG = "strong"  # confidence >= 0.7, full position
    MODERATE = "moderate"  # confidence 0.5-0.7, half position
    WEAK = "weak"  # confidence 0.3-0.5, quarter position / WATCH
    NO_EDGE = "no_edge"  # confidence < 0.3, NO_TRADE


# ---------------------------------------------------------------------------
# Regime Classifier (Stage 0.5)
# ---------------------------------------------------------------------------


class RegimeOutput(BaseModel):
    """Market regime assessment from Perplexity web search.

    Provides macro context that flows into all downstream stage prompts
    to influence screening, sentiment weighting, and confidence thresholds.
    """

    regime_type: Literal[
        "trending_bull",
        "trending_bear",
        "range_bound",
        "high_volatility",
        "risk_off",
        "sector_rotation",
    ]
    vix_estimate: Literal["calm", "normal", "elevated", "fear"]
    breadth_estimate: Literal["strong", "moderate", "weak", "deteriorating"]
    dominant_sectors: list[str] = Field(default_factory=list)
    defensive_rotation: bool = False
    summary: str = ""
    implications: str = ""


# ---------------------------------------------------------------------------
# Perplexity Stage (Stage 1)
# ---------------------------------------------------------------------------


class FundamentalData(BaseModel):
    """Fundamental data for a single ticker from Perplexity screening."""

    ticker: str
    company_name: str = ""

    @field_validator("ticker", mode="before")
    @classmethod
    def _clean_ticker(cls, v: str) -> str:
        return normalize_ticker(v) if isinstance(v, str) else v

    asset_type: Literal["stock", "etf", "crypto"] = "stock"
    sector: str = ""
    market_cap: str | None = None
    pe_ratio: float | None = None
    revenue_growth: str | None = None
    free_cash_flow: str | None = None
    relative_volume: float | None = None
    price_change_pct: float | None = None
    price: float | None = None
    week_52_high: float | None = None
    week_52_low: float | None = None
    key_highlights: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    sources: list[str] = Field(
        default_factory=list,
        description=(
            "LLM-generated source references (publication names, not verified URLs). "
            "These are contextual references from the Perplexity response text — they "
            "may not correspond to navigable URLs. For verified URLs, use news_urls "
            "which come from the API-level SearchResultsOutputItem citations."
        ),
    )
    news_urls: list[str] = Field(default_factory=list)


class ScreeningResult(BaseModel):
    """Complete output from Perplexity screening/research stage."""

    mode: Literal["discovery", "analysis", "prompt"]
    strategy_name: str | None = None
    tickers: list[FundamentalData]
    screening_summary: str
    citations: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)
    fmp_pre_screened: list[str] = Field(
        default_factory=list,
        description="Ticker symbols that came from FMP pre-screening (empty if FMP was skipped).",
    )


# ---------------------------------------------------------------------------
# Claude Vision Stage (Stage 3) — future phases
# ---------------------------------------------------------------------------


class TechnicalLevel(BaseModel):
    """A support or resistance price level."""

    price: float
    level_type: Literal["support", "resistance"]
    strength: Literal["strong", "moderate", "weak"]


class IndicatorReading(BaseModel):
    """Reading from a single technical indicator."""

    indicator: str
    value: str
    signal: Literal["bullish", "bearish", "neutral"]
    notes: str = ""


class TechnicalAssessment(BaseModel):
    """Claude's technical analysis output — unified v1/v2 model.

    Backward-compatible with v1 ``ChartAnalysis`` data.  When deserializing
    old v1 records, string confidence values ("high"/"medium"/"low") are
    auto-converted to floats via the ``_normalize_confidence`` validator.
    New v2 fields default to ``None``/empty so old data deserializes cleanly.
    """

    ticker: str
    timeframe: str

    @field_validator("ticker", mode="before")
    @classmethod
    def _clean_ticker(cls, v: str) -> str:
        return normalize_ticker(v) if isinstance(v, str) else v

    # --- Shared fields (both v1 and v2) ---
    current_price: float | None = None
    trend_direction: Literal["bullish", "bearish", "neutral", "transitioning"] = "neutral"
    key_levels: list[TechnicalLevel] = Field(default_factory=list)
    patterns_detected: list[str] = Field(default_factory=list)
    indicator_readings: list[IndicatorReading] = Field(default_factory=list)
    volume_analysis: str = ""
    overall_bias: str = "neutral"
    summary: str = ""
    chart_image_path: str = ""
    annotated_chart_path: str = ""

    # --- Confidence (float in v2, auto-converted from string for v1) ---
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, v: object) -> float:
        """Accept v1 string literals and convert to float."""
        if isinstance(v, str):
            return {"high": 0.85, "medium": 0.6, "low": 0.35}.get(v, 0.5)
        if isinstance(v, (int, float)):
            return float(v)
        return 0.5

    # --- v1-only fields (preserved for backward compat, defaults for v2) ---
    trend_strength: str = "moderate"

    # --- v2-only fields (new in Phase 4) ---
    ema_assessment: str = ""
    momentum_assessment: str = ""
    volume_assessment: str = ""
    trend_assessment: str = ""
    chart_confirms_data: bool = True
    chart_discrepancies: list[str] = Field(default_factory=list)
    nearest_support: float | None = None
    nearest_resistance: float | None = None
    suggested_stop_zone: str = ""
    timeframe_alignment_note: str = ""


# Backward compat: old imports and v1 pipeline code keep working
ChartAnalysis = TechnicalAssessment


# ---------------------------------------------------------------------------
# Gemini Sentiment Stage (Stage 2)
# ---------------------------------------------------------------------------


class NewsCatalyst(BaseModel):
    """A single news catalyst affecting sentiment.

    Attributes:
        headline: News headline or event description.
        source: Publication or source name.
        url: Article URL if available.
        impact: Directional impact on the stock.
        significance: Significance to near-term price action.
        published_date: Article publication date (YYYY-MM-DD) or "unknown".
        hours_ago: Approximate hours since publication, or None if unknown.
    """

    headline: str
    source: str
    url: str = ""
    impact: Literal["positive", "negative", "neutral"]
    significance: Literal["high", "medium", "low"]
    published_date: str = ""
    hours_ago: int | None = None


class SectorSentiment(BaseModel):
    """Structured sector/industry sentiment assessment.

    Attributes:
        label: Categorical sentiment label for the sector.
        score: Numeric sentiment score from -1.0 (bearish) to 1.0 (bullish).
        key_driver: Primary driver of sector sentiment.
    """

    label: Literal["strongly_bearish", "bearish", "neutral", "bullish", "strongly_bullish"] = (
        "neutral"
    )
    score: float = Field(ge=-1.0, le=1.0, default=0.0)
    key_driver: str = ""


_SENTIMENT_BUCKET = Literal[
    "strongly_bearish",
    "bearish",
    "mildly_bearish",
    "neutral",
    "mildly_bullish",
    "bullish",
    "strongly_bullish",
]


class SentimentAnalysis(BaseModel):
    """Complete output from Gemini news sentiment analysis.

    Attributes:
        sentiment_bucket: Fine-grained bucket computed from sentiment_score.
            7 levels vs. the 5 in sentiment_label. Used by GPT for more
            consistent thresholding.
        confidence: Gemini's self-assessed confidence in the sentiment score
            (0.0-1.0). Based on source authority, count, recency, and
            consistency of the underlying evidence.
    """

    ticker: str
    sentiment_score: float = Field(ge=-1.0, le=1.0)

    @field_validator("ticker", mode="before")
    @classmethod
    def _clean_ticker(cls, v: str) -> str:
        return normalize_ticker(v) if isinstance(v, str) else v

    sentiment_label: Literal[
        "strongly_bearish", "bearish", "neutral", "bullish", "strongly_bullish"
    ]
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    sentiment_bucket: _SENTIMENT_BUCKET = "neutral"
    key_catalysts: list[NewsCatalyst] = Field(default_factory=list)
    news_recency: str = ""
    sector_sentiment: SectorSentiment = Field(default_factory=SectorSentiment)
    summary: str = ""

    @field_validator("sector_sentiment", mode="before")
    @classmethod
    def _coerce_sector_sentiment(cls, v: str | dict | SectorSentiment) -> SectorSentiment | dict:
        """Accept a plain string for backward compatibility with old pipeline runs."""
        if isinstance(v, str):
            return SectorSentiment(label="neutral", score=0.0, key_driver=v)
        return v

    @model_validator(mode="after")
    def _compute_bucket(self) -> SentimentAnalysis:
        """Derive sentiment_bucket deterministically from sentiment_score."""
        s = self.sentiment_score
        if s <= -0.6:
            self.sentiment_bucket = "strongly_bearish"
        elif s <= -0.3:
            self.sentiment_bucket = "bearish"
        elif s <= -0.1:
            self.sentiment_bucket = "mildly_bearish"
        elif s <= 0.1:
            self.sentiment_bucket = "neutral"
        elif s <= 0.3:
            self.sentiment_bucket = "mildly_bullish"
        elif s <= 0.6:
            self.sentiment_bucket = "bullish"
        else:
            self.sentiment_bucket = "strongly_bullish"
        return self


# ---------------------------------------------------------------------------
# GPT Debate Stage (Stage 4)
# ---------------------------------------------------------------------------


class DebateCase(BaseModel):
    """Bull or Bear argument for a single ticker."""

    ticker: str
    stance: Literal["bull", "bear"]

    @field_validator("ticker", mode="before")
    @classmethod
    def _clean_ticker(cls, v: str) -> str:
        return normalize_ticker(v) if isinstance(v, str) else v

    key_arguments: list[str] = Field(default_factory=list)
    strongest_signal: str = ""
    weakest_counter: str = ""
    confidence_label: ConfidenceLabel = ConfidenceLabel.C5_NEUTRAL
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)

    @model_validator(mode="after")
    def _sync_confidence_from_label(self) -> DebateCase:
        """Derive numeric confidence from the label if the default wasn't overridden."""
        self.confidence = confidence_label_to_float(self.confidence_label)
        return self


class GptJudgeRecommendation(BaseModel):
    """Slim GPT judge output schema — only fields the LLM should produce.

    Backend-computed fields (ML gate, confidence v2, signal freshness, etc.)
    are NOT included here. After parsing, these are mapped to the full
    ``Recommendation`` model.

    GPT outputs ``confidence_label`` (a categorical string from
    ``ConfidenceLabel``) instead of a raw float. The numeric ``confidence``
    is derived deterministically via ``CONFIDENCE_LABEL_MAP``.
    """

    ticker: str

    @field_validator("ticker", mode="before")
    @classmethod
    def _clean_ticker(cls, v: str) -> str:
        return normalize_ticker(v) if isinstance(v, str) else v

    action: RecommendationAction
    confidence_label: ConfidenceLabel
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    llm_conviction: Literal["low", "medium", "high"] | None = None

    @model_validator(mode="after")
    def _sync_confidence_from_label(self) -> GptJudgeRecommendation:
        """Derive numeric confidence from the label."""
        self.confidence = confidence_label_to_float(self.confidence_label)
        return self

    setup_type: str | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    position_size_pct: float = 0.0
    risk_reward_ratio: float | None = None
    holding_period: str = ""
    bull_case: DebateCase | None = None
    bear_case: DebateCase | None = None
    judge_reasoning: str = ""
    key_factors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    track_agreement: TrackAgreement | None = None
    confidence_adjustment: str = ""
    entry_trigger: str | None = None
    scaling_plan: str | None = None
    invalidation_conditions: list[str] = Field(default_factory=list)
    entry_valid_window: str = ""


class GptJudgeRecommendationList(BaseModel):
    """Wrapper for batch judge output from GPT (slim schema)."""

    recommendations: list[GptJudgeRecommendation]


class Recommendation(BaseModel):
    """Final judge recommendation for a single ticker."""

    id: str = ""
    ticker: str
    action: RecommendationAction

    @field_validator("ticker", mode="before")
    @classmethod
    def _clean_ticker(cls, v: str) -> str:
        return normalize_ticker(v) if isinstance(v, str) else v

    confidence: float = Field(ge=0.0, le=1.0)
    confidence_label: ConfidenceLabel | None = Field(
        default=None,
        description="Categorical confidence label from GPT (before calibration)",
    )
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    position_size_pct: float = 0.0
    risk_reward_ratio: float | None = None
    holding_period: str = ""
    bull_case: DebateCase | None = None
    bear_case: DebateCase | None = None
    judge_reasoning: str = ""
    key_factors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    risk_violations: list[str] = Field(default_factory=list)
    risk_approved: bool = True
    track_agreement: TrackAgreement | None = None
    confidence_adjustment: str = ""
    confidence_breakdown: ConfidenceBreakdown | None = None
    signal_strength: SignalStrength | None = None
    raw_gpt_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Original GPT confidence before calibration adjustments",
    )
    # Entry precision — produced by the GPT judge for actionable trade plans
    entry_trigger: str | None = Field(
        default=None,
        description="How to enter: 'market', 'limit', 'breakout', 'pullback', or custom",
    )
    scaling_plan: str | None = Field(
        default=None,
        description="Position scaling instructions, e.g. '50% now, 50% on pullback to $187'",
    )
    invalidation_conditions: list[str] = Field(
        default_factory=list,
        description="Conditions that void this signal before entry",
    )

    # Signal freshness — set by the orchestrator at recommendation-save time
    signal_generated_at: str | None = None
    price_at_signal: float | None = None
    entry_valid_window: str = Field(
        default="",
        description="Time window the entry remains valid, e.g. '2 hours', '1-2 trading days'",
    )

    # Original GPT position size before ML gate adjustment
    raw_gpt_position_size_pct: float | None = None

    # ML gate fields — set by the independent model at Stage 4.8
    ml_probability: float | None = None
    ml_size_multiplier: float | None = None
    ml_blocked: bool = False
    ml_conformal_set: list[str] = Field(default_factory=list)
    ml_model_version: str | None = None

    # Independent ML at signal time (before GPT) — for training / UI transparency
    pre_gpt_ml_probability: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="P(profitable) from independent model before GPT ran",
    )
    pre_gpt_ml_direction: Literal["UP", "DOWN", "FLAT"] | None = None

    # Expected value: confidence * R:R - (1 - confidence)
    expected_value: float | None = Field(
        default=None,
        description="Expected value per unit risk: confidence * R:R - (1 - confidence)",
    )

    # Confidence Engine v2 fields
    win_probability: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Calibrated probability from prior + boosters + ML blend",
    )
    setup_quality_score: float | None = Field(
        default=None,
        description="Net effect of positive/negative evidence boosters",
    )
    llm_conviction: Literal["low", "medium", "high"] | None = Field(
        default=None,
        description="GPT's ordinal conviction bucket (replaces numeric authority)",
    )
    prior_base_rate: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Starting probability from strategy/regime prior table",
    )
    confidence_v2: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Shadow confidence from v2 engine (for validation before cutover)",
    )
    setup_type: str | None = Field(
        default=None,
        description="Setup archetype label from strategy's allowed list",
    )
    confidence_drivers: list[str] = Field(
        default_factory=list,
        description="Top factors that moved the number, e.g. 'Strong RVOL (+6%)'",
    )


class DebateCaseList(BaseModel):
    """Wrapper for batch bull/bear debate output from GPT."""

    cases: list[DebateCase]


class RecommendationList(BaseModel):
    """Wrapper for batch judge recommendation output from GPT."""

    recommendations: list[Recommendation]


# ---------------------------------------------------------------------------
# Pipeline Result (full run output)
# ---------------------------------------------------------------------------


class ChartError(BaseModel):
    """Per-ticker error from the Claude chart analysis stage."""

    ticker: str
    status: str
    error: str = ""


class StageError(BaseModel):
    """Structured error from a failed pipeline stage."""

    stage: str
    error: str
    type: str = ""


class PipelineResult(BaseModel):
    """Complete output from a full pipeline run."""

    run_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    strategy_name: str | None = None
    mode: Literal["discovery", "analysis", "combined", "prompt"]
    input_tickers: list[str] = Field(default_factory=list)
    screening: ScreeningResult | None = None
    chart_analyses: list[ChartAnalysis] = Field(default_factory=list)
    chart_errors: list[ChartError] = Field(default_factory=list)
    sentiment_analyses: list[SentimentAnalysis] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    stage_errors: list[StageError] = Field(default_factory=list)
    total_duration_seconds: float = 0.0
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    chart_indicators: list[str] = Field(
        default_factory=lambda: ["RSI", "MACD", "Volume", "EMA_50", "EMA_200", "ATR"]
    )
    meta: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# FMP Screener Config
# ---------------------------------------------------------------------------


class ScoringWeights(BaseModel):
    """Per-strategy weights for the FMP composite scoring engine.

    Each weight is 0.0-1.0 and they should sum to 1.0 (enforced at
    scoring time via normalisation). Strategies can bias the score
    toward dimensions that matter most for their trading style.

    Attributes:
        fundamental: Weight for ROE, margins, Piotroski score.
        momentum: Weight for price changes and relative volume.
        sentiment: Weight for insider activity and analyst consensus.
        quality: Weight for Altman Z-score, debt/equity, current ratio.
    """

    fundamental: float = 0.25
    momentum: float = 0.25
    sentiment: float = 0.25
    quality: float = 0.25


class FmpScreenerConfig(BaseModel):
    """Strategy-level FMP stock screener configuration.

    Defines API-level screener filters (sent directly to FMP),
    ratio-based post-filters (applied client-side), quality/momentum
    gates, insider trading requirements, and multi-factor scoring
    weights. When ``enabled`` is ``False`` (or the field is ``None``
    on StrategyConfig), the FMP pre-screening stage is skipped entirely.

    For crypto strategies, set ``is_crypto=True``. This routes to a
    different FMP workflow using ``/stable/batch-crypto-quotes`` with
    client-side filtering instead of the stock-only
    ``/stable/company-screener`` endpoint.

    Attributes:
        weight_fundamental: Scoring weight for fundamental dimension (0-100).
        weight_momentum: Scoring weight for momentum dimension (0-100).
        weight_sentiment: Scoring weight for sentiment dimension (0-100).
        weight_quality: Scoring weight for quality dimension (0-100).
    """

    enabled: bool = False
    is_crypto: bool = False

    # API-level screener filters (stocks only — ignored when is_crypto=True)
    country: str | None = None
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap_min: int | None = None
    market_cap_max: int | None = None
    price_min: float | None = None
    price_max: float | None = None
    volume_min: int | None = None
    beta_min: float | None = None
    beta_max: float | None = None
    is_actively_trading: bool = True
    is_etf: bool = False
    limit: int = 50

    # Ratio-based post-filters (applied after ratios-ttm fetch, stocks only)
    pe_max: float | None = None
    pe_min: float | None = None
    roe_min: float | None = None
    debt_equity_max: float | None = None
    pb_max: float | None = None
    pb_min: float | None = None
    ps_max: float | None = None
    ps_min: float | None = None
    peg_max: float | None = None
    net_profit_margin_min: float | None = None
    dividend_yield_min: float | None = None

    # Quality score filters (from /stable/financial-scores)
    piotroski_min: int | None = None
    altman_z_min: float | None = None

    # Price change filters (from /stable/stock-price-change, % values)
    price_change_1d_min: float | None = None
    price_change_1m_min: float | None = None
    price_change_1m_max: float | None = None
    price_change_3m_min: float | None = None

    # Insider activity filter (from /stable/insider-trading/statistics)
    require_insider_buying: bool = False

    # Relative volume filter (volume / avgVolume from quote data)
    rvol_min: float | None = None

    # Earnings calendar (from /stable/earnings-calendar)
    earnings_within_days: int | None = None
    min_earnings_beat_pct: float | None = None

    # Portfolio construction
    max_sector_concentration: int | None = None

    # Multi-factor scoring weights (0-100, strategy-specific tuning)
    weight_fundamental: float | None = None
    weight_momentum: float | None = None
    weight_sentiment: float | None = None
    weight_quality: float | None = None

    enrich_with_ratios: bool = True


class ScreenerOverrides(BaseModel):
    """Runtime overrides for FMP screener filters.

    Sent from the dashboard UI to override strategy-level defaults
    for country, exchange, sector, industry, and market cap range.
    ``None`` values are ignored (strategy defaults apply).

    Attributes:
        country: ISO country code override (e.g. "CA", "US").
        exchange: Exchange override (e.g. "TSX", "NYSE", "NASDAQ").
        sector: FMP sector override (e.g. "Technology", "Energy").
        industry: FMP industry override.
        market_cap_min: Minimum market cap override.
        market_cap_max: Maximum market cap override.
    """

    country: str | None = None
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap_min: int | None = None
    market_cap_max: int | None = None

    def apply_to(self, config: FmpScreenerConfig) -> FmpScreenerConfig:
        """Return a copy of *config* with non-None overrides merged in.

        Args:
            config: The base FMP screener config from the strategy.

        Returns:
            New FmpScreenerConfig with overrides applied.
        """
        data = config.model_dump()
        for field in (
            "country",
            "exchange",
            "sector",
            "industry",
            "market_cap_min",
            "market_cap_max",
        ):
            val = getattr(self, field)
            if val is not None:
                data[field] = val
        return FmpScreenerConfig.model_validate(data)

    def has_any(self) -> bool:
        """Return True if at least one override field is set."""
        return any(
            getattr(self, f) is not None
            for f in (
                "country",
                "exchange",
                "sector",
                "industry",
                "market_cap_min",
                "market_cap_max",
            )
        )


# ---------------------------------------------------------------------------
# Strategy Config
# ---------------------------------------------------------------------------


class RiskParams(BaseModel):
    """Risk parameters for the GPT decision engine."""

    max_position_pct: float = 5.0
    min_risk_reward: float = 1.5
    max_portfolio_risk_pct: float = 15.0


class StrategyConfig(BaseModel):
    """Complete strategy configuration driving all pipeline stages."""

    id: str
    name: str
    description: str = ""

    # FMP Pre-Screening (None = skip FMP)
    fmp_screener: FmpScreenerConfig | None = None

    # Perplexity Stage
    screening_prompt: str
    constraint_style: Literal["tight", "loose"] = "tight"
    max_tickers: int = 10

    # Claude Stage
    chart_indicators: list[str] = Field(
        default_factory=lambda: ["RSI", "MACD", "Volume", "EMA_50", "EMA_200", "ATR"]
    )
    chart_timeframe: str = "4H"
    secondary_timeframe: str = "D"
    additional_timeframes: list[str] = Field(default_factory=lambda: ["D", "W"])
    short_timeframes: list[str] = Field(default_factory=lambda: ["15m", "1H"])
    short_tf_indicators: list[str] = Field(
        default_factory=lambda: ["VWAP", "Stochastic", "EMA_20", "ATR", "Volume"]
    )
    ta_focus: str | None = None

    @model_validator(mode="after")
    def _sync_timeframes(self) -> StrategyConfig:
        """Ensure additional_timeframes is populated from secondary_timeframe if empty."""
        if not self.additional_timeframes and self.secondary_timeframe:
            self.additional_timeframes = [self.secondary_timeframe]
        return self

    # Gemini Stage
    news_recency: Literal["today", "week", "month"] = "week"
    news_scope: Literal["company", "sector", "macro"] = "company"

    # GPT Stage
    trading_style: str = ""
    risk_params: RiskParams = Field(default_factory=RiskParams)
    enable_debate: bool = True

    # Metadata
    is_template: bool = False
    recommended: bool = False
    strategy_type: str = "swing"

    # Signal freshness: how long (hours) a signal from this strategy stays actionable
    signal_half_life_hours: int = 48

    # Allowed setup types for this strategy (WATCH/BUY/SHORT must match one)
    setup_archetypes: list[str] = Field(default_factory=list)

    #: Primary listing currency for equities — drives FMP ``country`` / ``exchange``
    #: for non-crypto screeners (USD → US markets, CAD → Canada / TSX).
    listing_currency: Literal["USD", "CAD"] = "CAD"


# ---------------------------------------------------------------------------
# Risk Assessment (Pipeline v2 post-filter)
# ---------------------------------------------------------------------------


class RiskAssessment(BaseModel):
    """Per-ticker risk assessment from the post-filter stage.

    In v2 pipeline, the risk screener runs AFTER all three parallel tracks
    complete. Instead of removing tickers, it enriches GPT's input with
    risk flags so GPT can factor risk into NO_TRADE/WATCH decisions.
    """

    ticker: str
    risk_flags: list[str] = Field(default_factory=list)
    risk_approved: bool = True
    risk_score: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = ""

    @field_validator("ticker", mode="before")
    @classmethod
    def _clean_ticker(cls, v: str) -> str:
        return normalize_ticker(v) if isinstance(v, str) else v


# ---------------------------------------------------------------------------
# Feedback Loop (Phase 5)
# ---------------------------------------------------------------------------


class DecisionCreate(BaseModel):
    """Request body for recording a decision on a recommendation."""

    decision: Literal["following", "passing"]
    reason: str = ""
    reason_category: str = ""


class DecisionResponse(BaseModel):
    """Decision record returned from the API."""

    id: str
    user_id: str
    recommendation_id: str
    decision: Literal["following", "passing"]
    reason: str = ""
    reason_category: str = ""
    decided_at: str
    ticker: str = ""
    action: str = ""
    confidence: float = 0.0


class BrokerageOpenRequest(BaseModel):
    """Record an open position from IBKR execution (MCP automation)."""

    recommendation_id: str
    shares: int = Field(ge=1)
    entry_price: float = Field(gt=0)
    brokerage_order_id: str = Field(min_length=1)
    stop_loss: float | None = None
    take_profit: float | None = None
    currency: str = "USD"
    entry_timestamp: str | None = None
    notes: str = ""
    signal_entry_price: float | None = Field(
        default=None,
        description="Pipeline signal entry; with entry_price, slippage_pct is stored on the outcome.",
    )
    signal_created_at: str | None = Field(
        default=None,
        description="Recommendation created_at ISO; with entry_timestamp, time_to_execution_minutes is stored.",
    )


class OutcomePatch(BaseModel):
    """Partial update for an outcome (only sent fields are applied)."""

    entry_price: float | None = None
    exit_price: float | None = None
    shares: int | None = None
    pnl_dollars: float | None = None
    pnl_percent: float | None = None
    holding_days: int | None = None
    exit_reason: str | None = None
    notes: str | None = None
    source: str | None = None
    brokerage_order_id: str | None = None
    commission: float | None = None
    fees: float | None = None
    currency: str | None = None
    gross_pnl: float | None = None
    net_pnl: float | None = None
    entry_timestamp: str | None = None
    exit_timestamp: str | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    slippage_pct: float | None = None
    time_to_execution_minutes: float | None = None
    failure_mode: str | None = None
    structured_analysis: dict | None = None


class SectorConcentrationRequest(BaseModel):
    """Portfolio sector concentration check for a proposed US equity trade."""

    open_position_symbols: list[str] = Field(default_factory=list)
    proposed_symbol: str = Field(min_length=1)
    max_positions_per_sector: int = Field(default=2, ge=1, le=20)


class SectorConcentrationResponse(BaseModel):
    """Result of sector concentration analysis."""

    passed: bool
    message: str
    proposed_symbol: str
    proposed_sector: str
    positions_in_sector_after_trade: int
    max_positions_per_sector: int
    skipped: bool = False


class DailyOutcomeSummary(BaseModel):
    """Aggregated logged outcomes for the current US market calendar day (ET)."""

    trading_date_et: str
    closed_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    realized_pnl_dollars: float
    opened_trades: int
    open_tracked_positions: int


class OutcomeCreate(BaseModel):
    """Request body for logging a trade outcome."""

    entry_price: float | None = None
    exit_price: float | None = None
    shares: int | None = None
    pnl_dollars: float | None = None
    pnl_percent: float | None = None
    holding_days: int | None = None
    exit_reason: str = ""
    notes: str = ""
    source: str = "manual"
    brokerage_order_id: str | None = None
    commission: float | None = None
    fees: float | None = None
    currency: str | None = None
    gross_pnl: float | None = None
    net_pnl: float | None = None
    entry_timestamp: str | None = None
    exit_timestamp: str | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    slippage_pct: float | None = None
    time_to_execution_minutes: float | None = None
    failure_mode: str | None = None
    structured_analysis: dict | None = None


class OutcomeResponse(BaseModel):
    """Outcome record returned from the API."""

    id: str
    user_id: str
    decision_id: str
    recommendation_id: str
    ticker: str
    entry_price: float | None = None
    exit_price: float | None = None
    shares: int | None = None
    pnl_dollars: float | None = None
    pnl_percent: float | None = None
    holding_days: int | None = None
    exit_reason: str = ""
    notes: str = ""
    logged_at: str
    source: str = "manual"
    brokerage_order_id: str | None = None
    commission: float | None = None
    fees: float | None = None
    currency: str | None = None
    gross_pnl: float | None = None
    net_pnl: float | None = None
    entry_timestamp: str | None = None
    exit_timestamp: str | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    slippage_pct: float | None = None
    time_to_execution_minutes: float | None = None
    failure_mode: str | None = None
    structured_analysis: dict | None = None


class ReflectionResponse(BaseModel):
    """Reflection summary returned from the API."""

    id: str
    generated_at: str
    recommendations_analyzed: int
    decisions_analyzed: int
    outcomes_analyzed: int
    date_range_start: str | None
    date_range_end: str | None
    summary_text: str
    injection_prompt: str
    metrics: dict


class PerformanceOverview(BaseModel):
    """Aggregated performance metrics for the insights dashboard."""

    total_recommendations: int = 0
    total_decisions: int = 0
    total_following: int = 0
    total_passing: int = 0
    total_outcomes: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    win_rate: float | None = None
    total_pnl_dollars: float = 0.0
    avg_pnl_percent: float | None = None
    avg_holding_days: float | None = None
    best_trade: dict | None = None
    worst_trade: dict | None = None
    confidence_calibration: list[dict] = Field(default_factory=list)


class RecommendationWithStatus(BaseModel):
    """Recommendation enriched with decision and outcome status for the trade journal."""

    id: str
    run_id: str
    ticker: str
    action: RecommendationAction
    confidence: float
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_reward_ratio: float | None = None
    holding_period: str = ""
    judge_reasoning: str = ""
    created_at: str
    strategy_name: str = ""
    decision: Literal["following", "passing"] | None = None
    decision_id: str | None = None
    decision_reason: str = ""
    decided_at: str | None = None
    outcome_id: str | None = None
    outcome_entry_price: float | None = None
    outcome_exit_price: float | None = None
    outcome_shares: int | None = None
    outcome_pnl_dollars: float | None = None
    outcome_pnl_percent: float | None = None
    outcome_holding_days: int | None = None
    outcome_exit_reason: str = ""
    outcome_notes: str = ""
    outcome_logged_at: str | None = None
    outcome_source: str = "manual"
    outcome_commission: float | None = None
    outcome_net_pnl: float | None = None
    outcome_gross_pnl: float | None = None
    outcome_stop_loss: float | None = None
    outcome_take_profit: float | None = None
    outcome_entry_timestamp: str | None = None


class TradeHistoryEntry(BaseModel):
    """Single trade in the time-series history for equity curve and calendar."""

    date: str
    ticker: str
    pnl_dollars: float
    pnl_percent: float | None = None
    cumulative_pnl: float
    action: str
    confidence: float


# ---------------------------------------------------------------------------
# Structured Outcome Analysis (Phase 6 — Feedback Loop Enhancement)
# ---------------------------------------------------------------------------

_FAILURE_MODE = Literal[
    "late_entry",
    "false_breakout",
    "sentiment_reversal",
    "regime_change",
    "correct_direction_bad_timing",
    "wrong_direction",
    "low_agreement_taken",
    "unknown",
]


class StructuredOutcomeAnalysis(BaseModel):
    """Rich post-trade analysis extending OutcomeResponse with v2 analytics.

    Captures the state of independent analysis tracks and numerical TA
    indicators at signal time vs outcome time, enabling targeted pattern
    learning and failure-mode classification.
    """

    ticker: str
    signal_direction: str = ""
    actual_outcome: Literal["win", "loss", "breakeven"] = "breakeven"
    pnl_pct: float = 0.0

    track_agreement_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Agreement score at signal time"
    )
    tracks_that_agreed_with_outcome: list[str] = Field(default_factory=list)
    tracks_that_disagreed_with_outcome: list[str] = Field(default_factory=list)

    ema_cross_age_at_signal: int = Field(
        default=-1, description="Candles since last EMA cross at signal time (-1 = unknown)"
    )
    rsi_at_signal: float = Field(default=50.0, description="RSI at signal time")
    rsi_at_outcome: float = Field(default=50.0, description="RSI at outcome time")
    adx_at_signal: float = Field(default=0.0, description="ADX at signal time")
    momentum_score_at_signal: float = Field(
        default=0.0, description="Composite momentum score at signal time"
    )
    momentum_score_at_outcome: float = Field(
        default=0.0, description="Composite momentum score at outcome time"
    )

    failure_mode: _FAILURE_MODE = "unknown"
    lesson: str = ""

    slippage_pct: float | None = Field(
        default=None, description="(fill_price - signal_price) / signal_price * 100"
    )
    time_to_execution_minutes: float | None = Field(
        default=None, description="Minutes from signal generation to trade execution"
    )
    trader_followed_signal: bool | None = Field(
        default=None, description="Whether the trader followed the signal exactly"
    )


# ---------------------------------------------------------------------------
# Numerical Technical Analysis (Phase 1 — Pipeline v2)
# ---------------------------------------------------------------------------


class EMASnapshot(BaseModel):
    """EMA values at the current candle for a single period."""

    period: int
    current_value: float
    previous_value: float
    slope: float = 0.0

    @model_validator(mode="after")
    def _compute_slope(self) -> EMASnapshot:
        """Derive slope from current - previous if not explicitly set."""
        if self.slope == 0.0 and self.current_value != self.previous_value:
            self.slope = self.current_value - self.previous_value
        return self


class EMACross(BaseModel):
    """Detected EMA crossover event between two periods."""

    fast_period: int
    slow_period: int
    cross_type: Literal["bullish", "bearish"]
    candles_ago: int
    spread_pct: float
    spread_direction: Literal["widening", "narrowing"]


class MACDSnapshot(BaseModel):
    """MACD state at the current candle."""

    macd_line: float
    signal_line: float
    histogram: float
    histogram_slope: Literal["expanding", "contracting"]
    signal_cross: Literal["above", "below"]


class RSISnapshot(BaseModel):
    """RSI state at the current candle."""

    current: float
    previous: float
    trend: Literal["rising", "falling", "flat"]
    zone: Literal["overbought", "neutral", "oversold"]
    divergence: Literal["bullish_divergence", "bearish_divergence", "none"] = "none"

    @model_validator(mode="after")
    def _derive_fields(self) -> RSISnapshot:
        """Compute trend and zone from values when not explicitly set."""
        delta = self.current - self.previous
        if delta > 1.0:
            self.trend = "rising"
        elif delta < -1.0:
            self.trend = "falling"
        else:
            self.trend = "flat"

        if self.current >= 70:
            self.zone = "overbought"
        elif self.current <= 30:
            self.zone = "oversold"
        else:
            self.zone = "neutral"
        return self


class VolumeSnapshot(BaseModel):
    """Volume analysis at the current candle."""

    current: int
    avg_20: float
    ratio: float = 0.0
    trend: Literal["increasing", "decreasing", "stable"] = "stable"

    @model_validator(mode="after")
    def _compute_ratio(self) -> VolumeSnapshot:
        if self.ratio == 0.0 and self.avg_20 > 0:
            self.ratio = self.current / self.avg_20
        return self


class TechnicalSnapshot(BaseModel):
    """Complete numerical TA for one ticker at one timeframe."""

    ticker: str
    timeframe: str
    timestamp: datetime
    price_current: float
    price_open: float
    price_high: float
    price_low: float

    emas: list[EMASnapshot] = Field(default_factory=list)
    ema_crosses: list[EMACross] = Field(default_factory=list)
    macd: MACDSnapshot | None = None
    rsi: RSISnapshot | None = None
    adx: float = 0.0
    atr: float = 0.0
    atr_pct: float = 0.0
    volume: VolumeSnapshot | None = None

    trend_alignment: Literal["all_bullish", "all_bearish", "mixed"] = "mixed"
    momentum_score: float = Field(default=0.0, ge=-1.0, le=1.0)

    @field_validator("ticker", mode="before")
    @classmethod
    def _clean_ticker(cls, v: str) -> str:
        return normalize_ticker(v) if isinstance(v, str) else v


class MultiTimeframeTechnical(BaseModel):
    """TA across all strategy timeframes for one ticker."""

    ticker: str
    primary: TechnicalSnapshot
    additional: list[TechnicalSnapshot] = Field(default_factory=list)
    short: list[TechnicalSnapshot] = Field(default_factory=list)
    timeframe_alignment: Literal["aligned_bullish", "aligned_bearish", "divergent"] = "divergent"

    @field_validator("ticker", mode="before")
    @classmethod
    def _clean_ticker(cls, v: str) -> str:
        return normalize_ticker(v) if isinstance(v, str) else v
