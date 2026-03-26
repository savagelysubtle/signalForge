"""Pydantic models defining the data contracts for every pipeline stage.

Every LLM output must be validated against these schemas before flowing
downstream. If it's not a validated model, it's a bug.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

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
    relative_volume: float | None = None
    price_change_pct: float | None = None
    price: float | None = None
    week_52_high: float | None = None
    week_52_low: float | None = None
    key_highlights: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
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
    annotated_chart_path: str = ""


# ---------------------------------------------------------------------------
# Gemini Sentiment Stage (Stage 2)
# ---------------------------------------------------------------------------


class NewsCatalyst(BaseModel):
    """A single news catalyst affecting sentiment."""

    headline: str
    source: str
    url: str = ""
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


class ChartError(BaseModel):
    """Per-ticker error from the Claude chart analysis stage."""

    ticker: str
    status: str
    error: str = ""


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
    stage_errors: list[dict] = Field(default_factory=list)
    total_duration_seconds: float = 0.0
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    chart_indicators: list[str] = Field(
        default_factory=lambda: ["RSI", "MACD", "Volume", "EMA_50", "EMA_200"]
    )


# ---------------------------------------------------------------------------
# FMP Screener Config
# ---------------------------------------------------------------------------


class FmpScreenerConfig(BaseModel):
    """Strategy-level FMP stock screener configuration.

    Defines both the API-level screener filters (sent directly to FMP)
    and ratio-based post-filters (applied client-side after fetching
    ratios-ttm). When ``enabled`` is ``False`` (or the field is ``None``
    on StrategyConfig), the FMP pre-screening stage is skipped entirely.

    For crypto strategies, set ``is_crypto=True``. This routes to a
    different FMP workflow: ``/stable/cryptocurrency-list`` +
    ``/stable/batch-crypto-quotes`` with client-side filtering instead
    of the stock-only ``/stable/company-screener`` endpoint.
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

    enrich_with_ratios: bool = True


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
        default_factory=lambda: ["RSI", "MACD", "Volume", "EMA_50", "EMA_200"]
    )
    chart_timeframe: str = "D"
    secondary_timeframe: str = "4H"
    additional_timeframes: list[str] = Field(default_factory=lambda: ["4H", "W"])
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
