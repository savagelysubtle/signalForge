import { supabase } from "../lib/supabase";
import type {
  PipelineResult,
  PipelineRunSummary,
  PipelineProgress,
  StrategyConfig,
  ApiKeyStatus,
  ScreenerOverrides,
  DecisionCreate,
  DecisionResponse,
  OutcomeCreate,
  OutcomeResponse,
  ReflectionResponse,
  PerformanceOverview,
  RecommendationWithStatus,
  BrokerageAuthorizeResponse,
  BrokerageConnectResponse,
  BrokerageStatus,
  BrokerageAccount,
  PendingMatch,
  SyncResultResponse,
  TradeHistoryEntry,
  ScannerLatestResponse,
  ScannerFilters,
  MarketStateResponse,
  ScanRunStatus,
} from "../types";

const BASE_URL = import.meta.env.VITE_API_URL || "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (session?.access_token) {
    headers["Authorization"] = `Bearer ${session.access_token}`;
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    headers,
    ...options,
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || response.statusText);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export const api = {
  health: () => request<{ status: string; version: string }>("/health"),

  // Pipeline
  runPipeline: (body: {
    strategy_id?: string;
    manual_tickers?: string[];
    user_prompt?: string;
    screener_overrides?: ScreenerOverrides;
    mode_override?: string;
  }) =>
    request<{ run_id: string; status: string }>("/api/pipeline/run", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getPipelineResult: (runId: string) =>
    request<PipelineResult>(`/api/pipeline/status/${runId}`),
  getPipelineProgress: (runId: string) =>
    request<PipelineProgress>(`/api/pipeline/progress/${runId}`),
  listPipelineRuns: () =>
    request<PipelineRunSummary[]>("/api/pipeline/runs"),

  // Strategies
  listStrategies: () => request<StrategyConfig[]>("/api/strategies"),
  listTemplates: () => request<StrategyConfig[]>("/api/strategies/templates"),
  getStrategy: (id: string) => request<StrategyConfig>(`/api/strategies/${id}`),
  createStrategy: (config: StrategyConfig) =>
    request<StrategyConfig>("/api/strategies", {
      method: "POST",
      body: JSON.stringify(config),
    }),
  updateStrategy: (id: string, config: StrategyConfig) =>
    request<StrategyConfig>(`/api/strategies/${id}`, {
      method: "PUT",
      body: JSON.stringify(config),
    }),
  deleteStrategy: (id: string) =>
    request<void>(`/api/strategies/${id}`, { method: "DELETE" }),

  // Charts
  fetchChart: (body: { ticker: string; timeframe: string; indicators?: string[] }) =>
    request<{ ticker: string; timeframe: string; image_url: string }>("/api/charts/fetch", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Decisions
  createDecision: (recommendationId: string, body: DecisionCreate) =>
    request<DecisionResponse>(`/api/decisions/recommendations/${recommendationId}/decision`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listDecisions: (limit = 50, offset = 0, filter?: string) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (filter) params.set("decision_filter", filter);
    return request<DecisionResponse[]>(`/api/decisions?${params}`);
  },
  getDecision: (id: string) => request<DecisionResponse>(`/api/decisions/${id}`),
  deleteDecision: (id: string) =>
    request<void>(`/api/decisions/${id}`, { method: "DELETE" }),

  // Outcomes
  createOutcome: (decisionId: string, body: OutcomeCreate) =>
    request<OutcomeResponse>(`/api/outcomes/decisions/${decisionId}/outcome`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateOutcome: (outcomeId: string, body: OutcomeCreate) =>
    request<OutcomeResponse>(`/api/outcomes/${outcomeId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  listOutcomes: (limit = 50, offset = 0) =>
    request<OutcomeResponse[]>(`/api/outcomes?limit=${limit}&offset=${offset}`),

  // Recommendations (trade journal)
  listRecommendations: (
    limit = 50,
    offset = 0,
    filters?: { action?: string[]; confidenceMin?: number; confidenceMax?: number },
  ) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (filters?.action?.length) {
      for (const a of filters.action) params.append("action", a);
    }
    if (filters?.confidenceMin != null && filters.confidenceMin > 0)
      params.set("confidence_min", String(filters.confidenceMin));
    if (filters?.confidenceMax != null && filters.confidenceMax < 1)
      params.set("confidence_max", String(filters.confidenceMax));
    return request<RecommendationWithStatus[]>(`/api/recommendations?${params.toString()}`);
  },
  getRecommendationStatus: (id: string) =>
    request<RecommendationWithStatus>(`/api/recommendations/${id}`),

  // Insights
  getPerformanceOverview: () => request<PerformanceOverview>("/api/insights/overview"),
  getTradeHistory: () => request<TradeHistoryEntry[]>("/api/insights/trade-history"),
  triggerReflection: () =>
    request<ReflectionResponse>("/api/insights/reflect", { method: "POST" }),
  getLatestReflection: () => request<ReflectionResponse>("/api/insights/reflections/latest"),
  deleteReflection: (id: string) =>
    request<{ status: string }>(`/api/insights/reflections/${id}`, { method: "DELETE" }),

  // Brokerage
  getBrokerageAuthorizeUrl: (redirectUri: string, isPractice = false, state = "") => {
    const params = new URLSearchParams({
      redirect_uri: redirectUri,
      is_practice: String(isPractice),
      ...(state ? { state } : {}),
    });
    return request<BrokerageAuthorizeResponse>(`/api/brokerage/authorize-url?${params}`);
  },
  connectBrokerageOAuth: (body: { code: string; redirect_uri: string; is_practice: boolean }) =>
    request<BrokerageConnectResponse>("/api/brokerage/connect-oauth", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  connectBrokerage: (body: { refresh_token: string; is_practice: boolean }) =>
    request<BrokerageConnectResponse>("/api/brokerage/connect", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  disconnectBrokerage: () =>
    request<void>("/api/brokerage/disconnect", { method: "DELETE" }),
  getBrokerageStatus: () =>
    request<BrokerageStatus>("/api/brokerage/status"),
  getBrokerageAccounts: () =>
    request<BrokerageAccount[]>("/api/brokerage/accounts"),
  selectBrokerageAccount: (body: { account_id: string; account_type: string }) =>
    request<void>("/api/brokerage/select-account", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  syncTrades: (daysBack = 30) =>
    request<SyncResultResponse>("/api/brokerage/sync", {
      method: "POST",
      body: JSON.stringify({ days_back: daysBack }),
    }),
  smartSync: (daysBack = 30) =>
    request<SyncResultResponse>("/api/brokerage/smart-sync", {
      method: "POST",
      body: JSON.stringify({ days_back: daysBack }),
    }),
  getPendingMatches: () =>
    request<PendingMatch[]>("/api/brokerage/pending-matches"),
  confirmMatch: (matchId: string) =>
    request<void>("/api/brokerage/confirm-match", {
      method: "POST",
      body: JSON.stringify({ match_id: matchId }),
    }),
  rejectMatch: (matchId: string) =>
    request<void>(`/api/brokerage/reject-match/${matchId}`, { method: "DELETE" }),

  // Settings
  getApiKeyStatus: () =>
    request<ApiKeyStatus>("/api/settings/api-keys/status"),

  // Scanner / Prescreener
  runScan: (filters?: ScannerFilters) =>
    request<{ scan_run_id: string; status: string }>("/api/scanner/run", {
      method: "POST",
      ...(filters && Object.keys(filters).length > 0
        ? { body: JSON.stringify(filters) }
        : {}),
    }),
  getScanStatus: (scanRunId: string) =>
    request<ScanRunStatus>(`/api/scanner/status/${scanRunId}`),
  getScannerLatest: (strategyType?: string, minScore = 0.5, actionableOnly = false) => {
    const params = new URLSearchParams({ min_score: String(minScore) });
    if (strategyType) params.set("strategy_type", strategyType);
    if (actionableOnly) params.set("actionable_only", "true");
    return request<ScannerLatestResponse>(`/api/scanner/latest?${params}`);
  },
  getHeartbeat: () =>
    request<MarketStateResponse>("/api/scanner/heartbeat"),
};
