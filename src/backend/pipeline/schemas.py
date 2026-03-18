"""Pydantic models defining the data contracts for every pipeline stage.

Every LLM output must be validated against these schemas before flowing
downstream. If it's not a validated model, it's a bug.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Perplexity Stage (Stage 1)
# ---------------------------------------------------------------------------


class FundamentalData(BaseModel):
    """Fundamental data for a single ticker from Perplexity screening."""

    ticker: str
    company_name: str = ""
    asset_type: Literal["stock", "etf", "crypto"] = "stock"
    sector: str = ""
    market_cap: str | None = None
    pe_ratio: float | None = None
    revenue_growth: str | None = None
    free_cash_flow: str | None = None
    key_highlights: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class ScreeningResult(BaseModel):
    """Complete output from Perplexity screening/research stage."""

    mode: Literal["discovery", "analysis", "prompt"]
    strategy_name: str | None = None
    tickers: list[FundamentalData]
    screening_summary: str
    timestamp: datetime = Field(default_factory=datetime.now)


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


class ChartAnalysis(BaseModel):
    """Complete output from Claude Vision chart analysis."""

    ticker: str
    timeframe: str
    current_price: float | None = None
    trend_direction: Literal["bullish", "bearish", "neutral", "transitioning"]
    trend_strength: Literal["strong", "moderate", "weak"]
    key_levels: list[TechnicalLevel] = Field(default_factory=list)
    patterns_detected: list[str] = Field(default_factory=list)
    indicator_readings: list[IndicatorReading] = Field(default_factory=list)
    volume_analysis: str = ""
    overall_bias: Literal["strongly_bullish", "bullish", "neutral", "bearish", "strongly_bearish"]
    confidence: Literal["high", "medium", "low"]
    summary: str
    chart_image_path: str = ""


# ---------------------------------------------------------------------------
# Gemini Sentiment Stage (Stage 2)
# ---------------------------------------------------------------------------


class NewsCatalyst(BaseModel):
    """A single news catalyst affecting sentiment."""

    headline: str
    source: str
    impact: Literal["positive", "negative", "neutral"]
    significance: Literal["high", "medium", "low"]


class SentimentAnalysis(BaseModel):
    """Complete output from Gemini news sentiment analysis."""

    ticker: str
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    sentiment_label: Literal[
        "strongly_bearish", "bearish", "neutral", "bullish", "strongly_bullish"
    ]
    key_catalysts: list[NewsCatalyst] = Field(default_factory=list)
    news_recency: str = ""
    sector_sentiment: str = ""
    summary: str = ""


# ---------------------------------------------------------------------------
# GPT Debate Stage (Stage 4)
# ---------------------------------------------------------------------------


class DebateCase(BaseModel):
    """Bull or Bear argument for a single ticker."""

    ticker: str
    stance: Literal["bull", "bear"]
    key_arguments: list[str] = Field(default_factory=list)
    strongest_signal: str = ""
    weakest_counter: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class Recommendation(BaseModel):
    """Final judge recommendation for a single ticker."""

    ticker: str
    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float = Field(ge=0.0, le=1.0)
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


class DebateCaseList(BaseModel):
    """Wrapper for batch bull/bear debate output from GPT."""

    cases: list[DebateCase]


class RecommendationList(BaseModel):
    """Wrapper for batch judge recommendation output from GPT."""

    recommendations: list[Recommendation]


# ---------------------------------------------------------------------------
# Pipeline Result (full run output)
# ---------------------------------------------------------------------------


class PipelineResult(BaseModel):
    """Complete output from a full pipeline run."""

    run_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    strategy_name: str | None = None
    mode: Literal["discovery", "analysis", "combined", "prompt"]
    input_tickers: list[str] = Field(default_factory=list)
    screening: ScreeningResult | None = None
    chart_analyses: list[ChartAnalysis] = Field(default_factory=list)
    sentiment_analyses: list[SentimentAnalysis] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    stage_errors: list[dict] = Field(default_factory=list)
    total_duration_seconds: float = 0.0
    prompt_versions: dict[str, str] = Field(default_factory=dict)


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

    # Perplexity Stage
    screening_prompt: str
    constraint_style: Literal["tight", "loose"] = "tight"
    max_tickers: int = 10

    # Claude Stage
    chart_indicators: list[str] = Field(default_factory=lambda: ["RSI", "MACD", "Volume"])
    chart_timeframe: str = "D"
    ta_focus: str | None = None

    # Gemini Stage
    news_recency: Literal["today", "week", "month"] = "week"
    news_scope: Literal["company", "sector", "macro"] = "company"

    # GPT Stage
    trading_style: str = ""
    risk_params: RiskParams = Field(default_factory=RiskParams)
    enable_debate: bool = True

    # Metadata
    is_template: bool = False
