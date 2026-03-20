// ---------------------------------------------------------------------------
// Perplexity Stage (the only active stage in Phase 1)
// ---------------------------------------------------------------------------

export interface FundamentalData {
  ticker: string;
  company_name: string;
  asset_type: "stock" | "etf" | "crypto";
  sector: string;
  market_cap: string | null;
  pe_ratio: number | null;
  revenue_growth: string | null;
  free_cash_flow: string | null;
  key_highlights: string[];
  risk_factors: string[];
  sources: string[];
  news_urls: string[];
}

export interface ScreeningResult {
  mode: "discovery" | "analysis" | "prompt";
  strategy_name: string | null;
  tickers: FundamentalData[];
  screening_summary: string;
  timestamp: string; // ISO 8601
}

// ---------------------------------------------------------------------------
// Claude Vision Stage (Phase 3 — define now, render later)
// ---------------------------------------------------------------------------

export interface TechnicalLevel {
  price: number;
  level_type: "support" | "resistance";
  strength: "strong" | "moderate" | "weak";
}

export interface IndicatorReading {
  indicator: string;
  value: string;
  signal: "bullish" | "bearish" | "neutral";
  notes: string;
}

export interface ChartAnalysis {
  ticker: string;
  timeframe: string;
  trend_direction: "bullish" | "bearish" | "neutral" | "transitioning";
  trend_strength: "strong" | "moderate" | "weak";
  key_levels: TechnicalLevel[];
  patterns_detected: string[];
  indicator_readings: IndicatorReading[];
  volume_analysis: string;
  overall_bias: "strongly_bullish" | "bullish" | "neutral" | "bearish" | "strongly_bearish";
  confidence: "high" | "medium" | "low";
  summary: string;
  chart_image_path: string;
}

// ---------------------------------------------------------------------------
// Gemini Sentiment Stage (Phase 2)
// ---------------------------------------------------------------------------

export interface NewsCatalyst {
  headline: string;
  source: string;
  url: string;
  impact: "positive" | "negative" | "neutral";
  significance: "high" | "medium" | "low";
}

export interface SentimentAnalysis {
  ticker: string;
  sentiment_score: number; // -1.0 to 1.0
  sentiment_label: "strongly_bearish" | "bearish" | "neutral" | "bullish" | "strongly_bullish";
  key_catalysts: NewsCatalyst[];
  news_recency: string;
  sector_sentiment: string;
  summary: string;
}

// ---------------------------------------------------------------------------
// GPT Debate Stage (Phase 4 — define now, render later)
// ---------------------------------------------------------------------------

export interface DebateCase {
  ticker: string;
  stance: "bull" | "bear";
  key_arguments: string[];
  strongest_signal: string;
  weakest_counter: string;
  confidence: number; // 0.0 to 1.0
}

export interface Recommendation {
  ticker: string;
  action: "BUY" | "SELL" | "HOLD";
  confidence: number; // 0.0 to 1.0
  entry_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  position_size_pct: number;
  risk_reward_ratio: number | null;
  holding_period: string;
  bull_case: DebateCase | null;
  bear_case: DebateCase | null;
  judge_reasoning: string;
  key_factors: string[];
  warnings: string[];
}

// ---------------------------------------------------------------------------
// Pipeline Result (full run output)
// ---------------------------------------------------------------------------

export interface PipelineResult {
  run_id: string;
  timestamp: string; // ISO 8601
  strategy_name: string | null;
  mode: "discovery" | "analysis" | "combined" | "prompt";
  input_tickers: string[];
  screening: ScreeningResult | null;
  chart_analyses: ChartAnalysis[];       // Phase 3
  sentiment_analyses: SentimentAnalysis[]; // Phase 2 (Gemini)
  recommendations: Recommendation[];     // Phase 4
  stage_errors: StageError[];
  total_duration_seconds: number;
  prompt_versions: Record<string, string>;
}

export interface StageError {
  stage: string;
  error: string;
  type: string;
}

// ---------------------------------------------------------------------------
// Pipeline Run Summary (for listing)
// ---------------------------------------------------------------------------

export interface PipelineRunSummary {
  id: string;
  strategy_id: string | null;
  mode: string;
  status: string; // "running" | "completed" | "failed" | "partial"
  started_at: string;
  duration_seconds: number | null;
  tickers: string[];
}

// ---------------------------------------------------------------------------
// Strategy Config
// ---------------------------------------------------------------------------

export interface RiskParams {
  max_position_pct: number;
  min_risk_reward: number;
  max_portfolio_risk_pct: number;
}

export interface StrategyConfig {
  id: string;
  name: string;
  description: string;
  screening_prompt: string;
  constraint_style: "tight" | "loose";
  max_tickers: number;
  chart_indicators: string[];
  chart_timeframe: string;
  ta_focus: string | null;
  news_recency: "today" | "week" | "month";
  news_scope: "company" | "sector" | "macro";
  trading_style: string;
  risk_params: RiskParams;
  enable_debate: boolean;
  is_template: boolean;
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export interface ApiKeyStatus {
  keys: Record<string, boolean>;
}
