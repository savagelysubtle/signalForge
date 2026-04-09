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
  trend_strength: string;
  key_levels: TechnicalLevel[];
  patterns_detected: string[];
  indicator_readings: IndicatorReading[];
  volume_analysis: string;
  overall_bias: string;
  confidence: number | string; // float in v2, "high"/"medium"/"low" in v1
  summary: string;
  chart_image_path: string;
  annotated_chart_path: string;
  // v2 fields (TechnicalAssessment)
  ema_assessment?: string;
  momentum_assessment?: string;
  volume_assessment?: string;
  trend_assessment?: string;
  chart_confirms_data?: boolean;
  chart_discrepancies?: string[];
  nearest_support?: number | null;
  nearest_resistance?: number | null;
  suggested_stop_zone?: string;
  timeframe_alignment_note?: string;
}

export type TechnicalAssessment = ChartAnalysis;

// ---------------------------------------------------------------------------
// Gemini Sentiment Stage (Phase 2)
// ---------------------------------------------------------------------------

export interface NewsCatalyst {
  headline: string;
  source: string;
  url: string;
  impact: "positive" | "negative" | "neutral";
  significance: "high" | "medium" | "low";
  published_date: string;
  hours_ago: number | null;
}

export type SentimentBucket =
  | "strongly_bearish"
  | "bearish"
  | "mildly_bearish"
  | "neutral"
  | "mildly_bullish"
  | "bullish"
  | "strongly_bullish";

export interface SectorSentiment {
  label: "strongly_bearish" | "bearish" | "neutral" | "bullish" | "strongly_bullish";
  score: number; // -1.0 to 1.0
  key_driver: string;
}

export interface SentimentAnalysis {
  ticker: string;
  sentiment_score: number; // -1.0 to 1.0
  sentiment_label: "strongly_bearish" | "bearish" | "neutral" | "bullish" | "strongly_bullish";
  confidence: number; // 0.0 to 1.0 — Gemini's self-assessed confidence in the score
  sentiment_bucket: SentimentBucket;
  key_catalysts: NewsCatalyst[];
  news_recency: string;
  sector_sentiment: SectorSentiment;
  summary: string;
}

// ---------------------------------------------------------------------------
// Recommendation Action + Track Agreement
// ---------------------------------------------------------------------------

export type RecommendationAction = "BUY" | "SHORT" | "HOLD" | "NO_TRADE" | "WATCH";

export interface TrackAgreement {
  perplexity_direction: "bullish" | "bearish" | "neutral";
  gemini_direction: "bullish" | "bearish" | "neutral";
  claude_direction: "bullish" | "bearish" | "neutral";
  agreement_score: number; // 0.0 (full disagreement) to 1.0 (unanimous)
  conflicts: string[];
}

export interface ConfidenceBreakdown {
  track_agreement: number; // 0.00–0.30
  technical_strength: number; // 0.00–0.20
  trend_alignment: number; // 0.00–0.20
  historical_pattern: number; // 0.00–0.20
  regime_fit: number; // 0.00–0.10
  total: number; // 0.0–1.0
  penalties_applied: string[];
}

export type SignalStrength = "strong" | "moderate" | "weak" | "no_edge";

// ---------------------------------------------------------------------------
// Regime Classifier (Stage 0.5)
// ---------------------------------------------------------------------------

export type RegimeType =
  | "trending_bull"
  | "trending_bear"
  | "range_bound"
  | "high_volatility"
  | "risk_off";

export interface RegimeOutput {
  regime_type: RegimeType;
  vix_estimate: number | null;
  breadth_estimate: string | null;
  key_sectors: string[];
  reasoning: string;
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
  action: RecommendationAction;
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
  risk_violations: string[];
  risk_approved: boolean;
  track_agreement: TrackAgreement | null;
  confidence_adjustment: string;
  confidence_breakdown: ConfidenceBreakdown | null;
  signal_strength: SignalStrength | null;
  raw_gpt_confidence: number | null;
  // Entry precision — produced by the GPT judge for actionable trade plans
  entry_trigger: string | null; // "market", "limit", "breakout", "pullback", or custom
  scaling_plan: string | null;
  invalidation_conditions: string[];

  // Signal freshness — set by the orchestrator at recommendation-save time
  signal_generated_at: string | null; // ISO 8601 UTC
  price_at_signal: number | null;
  entry_valid_window: string; // e.g. "1-2 hours", "1-2 trading days"
  // Original GPT position size before ML gate adjustment
  raw_gpt_position_size_pct: number | null;
  // ML gate fields — set by the independent LightGBM model at Stage 4.8
  ml_probability: number | null;
  ml_size_multiplier: number | null;
  ml_blocked: boolean;
  ml_model_version: string | null;
  ml_conformal_set: string[];
  /** Independent ML before GPT (training / transparency) */
  pre_gpt_ml_probability: number | null;
  pre_gpt_ml_direction: "UP" | "DOWN" | "FLAT" | null;
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
  meta: Record<string, unknown>;
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

export interface StageProgress {
  stage: string;
  label: string;
  status: 'pending' | 'running' | 'done' | 'error' | 'skipped';
  count: number;
}

export interface PipelineProgress {
  run_id: string;
  run_status: string;
  elapsed_seconds: number | null;
  stages: StageProgress[];
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
  recommended?: boolean;
  strategy_type?: string;
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
  source?: string;
  brokerage_order_id?: string | null;
  commission?: number | null;
  fees?: number | null;
  currency?: string | null;
  gross_pnl?: number | null;
  net_pnl?: number | null;
  entry_timestamp?: string | null;
  exit_timestamp?: string | null;
  stop_loss?: number | null;
  take_profit?: number | null;
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
  source: string;
  brokerage_order_id: string | null;
  commission: number | null;
  fees: number | null;
  currency: string | null;
  gross_pnl: number | null;
  net_pnl: number | null;
  entry_timestamp: string | null;
  exit_timestamp: string | null;
  stop_loss: number | null;
  take_profit: number | null;
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

export interface TradeHistoryEntry {
  date: string;
  ticker: string;
  pnl_dollars: number;
  pnl_percent: number | null;
  cumulative_pnl: number;
  action: string;
  confidence: number;
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
  action: RecommendationAction;
  confidence: number;
  entry_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  risk_reward_ratio: number | null;
  holding_period: string;
  judge_reasoning: string;
  created_at: string;
  strategy_name: string;
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
  outcome_source: string;
  outcome_commission: number | null;
  outcome_net_pnl: number | null;
  outcome_gross_pnl: number | null;
  outcome_stop_loss: number | null;
  outcome_take_profit: number | null;
  outcome_entry_timestamp: string | null;
}

// ---------------------------------------------------------------------------
// Brokerage Integration
// ---------------------------------------------------------------------------

export interface BrokerageConnectRequest {
  refresh_token: string;
  is_practice: boolean;
}

export interface BrokerageConnectResponse {
  connected: boolean;
  accounts: Array<{
    type: string;
    number: string;
    status: string;
    isPrimary: boolean;
    clientAccountType: string;
  }>;
}

export interface BrokerageAuthorizeResponse {
  url: string | null;
  oauth_enabled: boolean;
}

export interface BrokerageStatus {
  connected: boolean;
  account_id: string | null;
  account_type: string | null;
  is_practice: boolean;
  connected_at: string | null;
  updated_at: string | null;
}

export interface BrokerageAccount {
  type: string;
  number: string;
  status: string;
  isPrimary: boolean;
  clientAccountType: string;
}

export interface PendingMatch {
  id: string;
  recommendation_id: string;
  questrade_order_id: string;
  ticker: string;
  side: string;
  avg_price: number;
  total_shares: number;
  total_commission: number;
  currency: string;
  executed_at: string;
  match_score: number;
  match_reason: string;
  status: string;
  auto_confirmed?: boolean;
  rec_ticker: string;
  rec_action: string;
  rec_confidence: number;
  rec_entry_price: number | null;
}

export interface SyncResultResponse {
  auto_confirmed: PendingMatch[];
  pending_review: PendingMatch[];
  skipped_reason: string | null;
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export interface ApiKeyStatus {
  keys: Record<string, boolean>;
}

// ---------------------------------------------------------------------------
// Scanner / Prescreener
// ---------------------------------------------------------------------------

export interface ScannerFilters {
  country?: string;
  exchange?: string;
  sector?: string;
  market_cap_min?: number;
  market_cap_max?: number;
  limit?: number;
}

export interface ScannerResultItem {
  ticker: string;
  combined_score: number;
  ml_probability: number | null;
  rule_score: number;
  rsi: number | null;
  volume_ratio: number | null;
  momentum_score: number | null;
  atr_pct: number | null;
  ema_alignment: string | null;
  matched_rules: string[];
  earnings_within_5d: boolean;
  is_actionable: boolean;
}

export interface ScannerLatestResponse {
  strategies: Record<string, ScannerResultItem[]>;
  total_setups: number;
  strategies_with_setups: string[];
  regime_type: string | null;
  last_scan_at: string | null;
}

export interface MarketStateResponse {
  regime_type: string;
  regime_confidence: number;
  vix_spot: number | null;
  vix_structure: string;
  vix_estimate: string;
  pc_ratio: number | null;
  pc_signal: string;
  spy_price: number | null;
  spy_above_50ma: boolean | null;
  spy_5d_return: number | null;
  spy_20d_return: number | null;
  breadth_score: number | null;
  breadth_estimate: string;
  leading_sectors: string[];
  lagging_sectors: string[];
  market_session: string;
  next_macro_event: string | null;
  last_updated: string | null;
}

export interface ScanRunStatus {
  id: string;
  status: string;
  triggered_by?: string;
  started_at?: string;
  completed_at?: string;
  duration_seconds?: number;
  universe_size?: number;
  setups_found?: number;
  strategies_with_setups?: Record<string, number>;
  regime_type?: string;
}
