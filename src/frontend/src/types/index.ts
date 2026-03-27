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
  relative_volume: number | null;
  price_change_pct: number | null;
  price: number | null;
  week_52_high: number | null;
  week_52_low: number | null;
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
  fmp_pre_screened: string[];
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
  current_price: number | null;
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
  annotated_chart_path: string;
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
  id: string;
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

export interface ChartError {
  ticker: string;
  status: string;
  error: string;
}

export interface PipelineResult {
  run_id: string;
  timestamp: string; // ISO 8601
  strategy_name: string | null;
  mode: "discovery" | "analysis" | "combined" | "prompt";
  input_tickers: string[];
  screening: ScreeningResult | null;
  chart_analyses: ChartAnalysis[];
  chart_errors: ChartError[];
  sentiment_analyses: SentimentAnalysis[];
  recommendations: Recommendation[];
  stage_errors: StageError[];
  total_duration_seconds: number;
  prompt_versions: Record<string, string>;
  chart_indicators: string[];
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
  strategy_name: string | null;
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

export interface ScreenerOverrides {
  country?: string | null;
  exchange?: string | null;
  sector?: string | null;
  industry?: string | null;
  market_cap_min?: number | null;
  market_cap_max?: number | null;
}

export interface ScoringWeights {
  fundamental: number;
  momentum: number;
  sentiment: number;
  quality: number;
}

export interface FmpScreenerConfig {
  enabled: boolean;
  is_crypto: boolean;

  // API-level screener filters
  country: string | null;
  exchange: string | null;
  sector: string | null;
  industry: string | null;
  market_cap_min: number | null;
  market_cap_max: number | null;
  price_min: number | null;
  price_max: number | null;
  volume_min: number | null;
  beta_min: number | null;
  beta_max: number | null;
  is_actively_trading: boolean;
  is_etf: boolean;
  limit: number;

  // Ratio-based post-filters
  pe_max: number | null;
  pe_min: number | null;
  roe_min: number | null;
  debt_equity_max: number | null;
  pb_max: number | null;
  pb_min: number | null;
  ps_max: number | null;
  ps_min: number | null;
  peg_max: number | null;
  net_profit_margin_min: number | null;
  dividend_yield_min: number | null;

  // Quality score filters
  piotroski_min: number | null;
  altman_z_min: number | null;

  // Price change filters
  price_change_1d_min: number | null;
  price_change_1m_min: number | null;
  price_change_1m_max: number | null;
  price_change_3m_min: number | null;

  // Insider activity
  require_insider_buying: boolean;

  // Relative volume
  rvol_min: number | null;

  // Earnings
  earnings_within_days: number | null;
  min_earnings_beat_pct: number | null;

  // Portfolio construction
  max_sector_concentration: number | null;

  // Scoring weights
  weight_fundamental: number | null;
  weight_momentum: number | null;
  weight_sentiment: number | null;
  weight_quality: number | null;

  enrich_with_ratios: boolean;

  // Composite scoring weights
  scoring_weights: ScoringWeights;

  // Sector concentration guard
  max_per_sector: number | null;
}

export interface StrategyConfig {
  id: string;
  name: string;
  description: string;
  fmp_screener: FmpScreenerConfig | null;
  screening_prompt: string;
  constraint_style: "tight" | "loose";
  max_tickers: number;
  chart_indicators: string[];
  chart_timeframe: string;
  secondary_timeframe: string;
  additional_timeframes: string[];
  short_timeframes: string[];
  short_tf_indicators: string[];
  ta_focus: string | null;
  news_recency: "today" | "week" | "month";
  news_scope: "company" | "sector" | "macro";
  trading_style: string;
  risk_params: RiskParams;
  enable_debate: boolean;
  is_template: boolean;
}

// ---------------------------------------------------------------------------
// Feedback Loop (Phase 5)
// ---------------------------------------------------------------------------

export interface DecisionCreate {
  decision: "following" | "passing";
  reason?: string;
  reason_category?: string;
}

export interface DecisionResponse {
  id: string;
  user_id: string;
  recommendation_id: string;
  decision: "following" | "passing";
  reason: string;
  reason_category: string;
  decided_at: string;
  ticker: string;
  action: string;
  confidence: number;
}

export interface OutcomeCreate {
  entry_price?: number | null;
  exit_price?: number | null;
  shares?: number | null;
  pnl_dollars?: number | null;
  pnl_percent?: number | null;
  holding_days?: number | null;
  exit_reason?: string;
  notes?: string;
}

export interface OutcomeResponse {
  id: string;
  user_id: string;
  decision_id: string;
  recommendation_id: string;
  ticker: string;
  entry_price: number | null;
  exit_price: number | null;
  shares: number | null;
  pnl_dollars: number | null;
  pnl_percent: number | null;
  holding_days: number | null;
  exit_reason: string;
  notes: string;
  logged_at: string;
}

export interface ReflectionResponse {
  id: string;
  generated_at: string;
  recommendations_analyzed: number;
  decisions_analyzed: number;
  outcomes_analyzed: number;
  date_range_start: string | null;
  date_range_end: string | null;
  summary_text: string;
  injection_prompt: string;
  metrics: Record<string, unknown>;
}

export interface ConfidenceCalibration {
  bucket: string;
  count: number;
  win_rate: number;
}

export interface PerformanceOverview {
  total_recommendations: number;
  total_decisions: number;
  total_following: number;
  total_passing: number;
  total_outcomes: number;
  wins: number;
  losses: number;
  breakeven: number;
  win_rate: number | null;
  total_pnl_dollars: number;
  avg_pnl_percent: number | null;
  avg_holding_days: number | null;
  best_trade: { ticker: string; pnl_dollars: number; pnl_percent: number | null } | null;
  worst_trade: { ticker: string; pnl_dollars: number; pnl_percent: number | null } | null;
  confidence_calibration: ConfidenceCalibration[];
}

export interface RecommendationWithStatus {
  id: string;
  run_id: string;
  ticker: string;
  action: "BUY" | "SELL" | "HOLD";
  confidence: number;
  entry_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  risk_reward_ratio: number | null;
  holding_period: string;
  judge_reasoning: string;
  created_at: string;
  decision: "following" | "passing" | null;
  decision_id: string | null;
  decision_reason: string;
  decided_at: string | null;
  outcome_id: string | null;
  outcome_entry_price: number | null;
  outcome_exit_price: number | null;
  outcome_shares: number | null;
  outcome_pnl_dollars: number | null;
  outcome_pnl_percent: number | null;
  outcome_holding_days: number | null;
  outcome_exit_reason: string;
  outcome_notes: string;
  outcome_logged_at: string | null;
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export interface ApiKeyStatus {
  keys: Record<string, boolean>;
}
