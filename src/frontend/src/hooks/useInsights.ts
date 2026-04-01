import { useState, useCallback, useRef } from "react";
import { api } from "../api/client";
import { notifyFeedbackChanged, useFeedbackSync } from "../lib/feedbackSync";
import type {
  ReflectionResponse,
  PerformanceOverview,
  RecommendationWithStatus,
  DecisionCreate,
  OutcomeCreate,
  TradeHistoryEntry,
} from "../types";

const PAGE_SIZE = 50;

export interface JournalFilters {
  action: string[];
  confidenceMin: number;
  confidenceMax: number;
}

const DEFAULT_FILTERS: JournalFilters = { action: [], confidenceMin: 0, confidenceMax: 1 };

export function useInsights() {
  const [overview, setOverview] = useState<PerformanceOverview | null>(null);
  const [recommendations, setRecommendations] = useState<RecommendationWithStatus[]>([]);
  const [reflection, setReflection] = useState<ReflectionResponse | null>(null);
  const [tradeHistory, setTradeHistory] = useState<TradeHistoryEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [filters, setFilters] = useState<JournalFilters>(DEFAULT_FILTERS);
  const pageRef = useRef(0);
  const filtersRef = useRef<JournalFilters>(DEFAULT_FILTERS);

  const fetchAll = useCallback(async (targetPage?: number, newFilters?: JournalFilters) => {
    const p = targetPage ?? pageRef.current;
    const f = newFilters ?? filtersRef.current;
    pageRef.current = p;
    filtersRef.current = f;
    setPage(p);
    setIsLoading(true);
    setError(null);
    try {
      const apiFilters =
        f.action.length > 0 || f.confidenceMin > 0 || f.confidenceMax < 1
          ? {
              action: f.action.length > 0 ? f.action : undefined,
              confidenceMin: f.confidenceMin > 0 ? f.confidenceMin : undefined,
              confidenceMax: f.confidenceMax < 1 ? f.confidenceMax : undefined,
            }
          : undefined;

      const [ov, recs, history] = await Promise.all([
        api.getPerformanceOverview(),
        api.listRecommendations(PAGE_SIZE, p * PAGE_SIZE, apiFilters),
        api.getTradeHistory().catch(() => [] as TradeHistoryEntry[]),
      ]);
      setOverview(ov);
      setRecommendations(recs);
      setTradeHistory(history);
      setHasMore(recs.length === PAGE_SIZE);

      try {
        const ref = await api.getLatestReflection();
        setReflection(ref);
      } catch {
        setReflection(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load insights");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useFeedbackSync(fetchAll);

  const recordDecision = useCallback(
    async (recommendationId: string, body: DecisionCreate) => {
      setError(null);
      try {
        await api.createDecision(recommendationId, body);
        notifyFeedbackChanged();
        await fetchAll();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to record decision");
        throw e;
      }
    },
    [fetchAll],
  );

  const logOutcome = useCallback(
    async (decisionId: string, body: OutcomeCreate) => {
      setError(null);
      try {
        await api.createOutcome(decisionId, body);
        notifyFeedbackChanged();
        await fetchAll();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to log outcome");
        throw e;
      }
    },
    [fetchAll],
  );

  const updateOutcome = useCallback(
    async (outcomeId: string, body: OutcomeCreate) => {
      setError(null);
      try {
        await api.updateOutcome(outcomeId, body);
        notifyFeedbackChanged();
        await fetchAll();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to update outcome");
        throw e;
      }
    },
    [fetchAll],
  );

  const undoDecision = useCallback(
    async (decisionId: string) => {
      setError(null);
      try {
        await api.deleteDecision(decisionId);
        notifyFeedbackChanged();
        await fetchAll();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to undo decision");
        throw e;
      }
    },
    [fetchAll],
  );

  const generateReflection = useCallback(async () => {
    setIsGenerating(true);
    setError(null);
    try {
      const ref = await api.triggerReflection();
      setReflection(ref);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate reflection");
    } finally {
      setIsGenerating(false);
    }
  }, []);

  const nextPage = useCallback(() => fetchAll(pageRef.current + 1), [fetchAll]);
  const prevPage = useCallback(() => fetchAll(Math.max(0, pageRef.current - 1)), [fetchAll]);
  const goToPage = useCallback((p: number) => fetchAll(Math.max(0, p)), [fetchAll]);

  const applyFilters = useCallback(
    (newFilters: JournalFilters) => {
      setFilters(newFilters);
      fetchAll(0, newFilters);
    },
    [fetchAll],
  );

  return {
    overview,
    recommendations,
    reflection,
    tradeHistory,
    isLoading,
    isGenerating,
    error,
    fetchAll,
    recordDecision,
    logOutcome,
    updateOutcome,
    undoDecision,
    generateReflection,
    page,
    hasMore,
    pageSize: PAGE_SIZE,
    nextPage,
    prevPage,
    goToPage,
    filters,
    applyFilters,
  };
}
