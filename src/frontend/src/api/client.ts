import type {
  PipelineResult,
  PipelineRunSummary,
  StrategyConfig,
  ApiKeyStatus,
} from '../types';

const BASE_URL = "http://localhost:8420";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || response.statusText);
  }
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

  // Settings
  getApiKeyStatus: () => request<ApiKeyStatus>("/api/settings/api-keys/status"),
  reloadApiKeys: () =>
    request<{ status: string }>("/api/settings/api-keys/reload", { method: "POST" }),
};
