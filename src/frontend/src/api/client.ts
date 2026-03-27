import { supabase } from "../lib/supabase";
import type {
  PipelineResult,
  PipelineRunSummary,
  StrategyConfig,
  ApiKeyStatus,
  DecisionCreate,
  DecisionResponse,
  OutcomeCreate,
  OutcomeResponse,
  ReflectionResponse,
  PerformanceOverview,
  RecommendationWithStatus,
} from "../types";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8420";

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
  }) =>
    request<{ run_id: string; status: string }>("/api/pipeline/run", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getPipelineResult: (runId: string) =>
    request<PipelineResult>(`/api/pipeline/status/${runId}`),
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
  listRecommendations: (limit = 50, offset = 0) =>
    request<RecommendationWithStatus[]>(`/api/recommendations?limit=${limit}&offset=${offset}`),
  getRecommendationStatus: (id: string) =>
    request<RecommendationWithStatus>(`/api/recommendations/${id}`),

  // Insights
  getPerformanceOverview: () => request<PerformanceOverview>("/api/insights/overview"),
  triggerReflection: () =>
    request<ReflectionResponse>("/api/insights/reflect", { method: "POST" }),
  getLatestReflection: () => request<ReflectionResponse>("/api/insights/reflections/latest"),

  // Settings
  getApiKeyStatus: () =>
    request<ApiKeyStatus>("/api/settings/api-keys/status"),
};
