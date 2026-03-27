import { useState, useCallback } from "react";
import { api } from "../api/client";
import { notifyFeedbackChanged, useFeedbackSync } from "../lib/feedbackSync";
import type {
  ReflectionResponse,
  PerformanceOverview,
  RecommendationWithStatus,
  DecisionCreate,
  OutcomeCreate,
} from "../types";

export function useInsights() {
  const [overview, setOverview] = useState<PerformanceOverview | null>(null);
  const [recommendations, setRecommendations] = useState<RecommendationWithStatus[]>([]);
  const [reflection, setReflection] = useState<ReflectionResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [ov, recs] = await Promise.all([
        api.getPerformanceOverview(),
        api.listRecommendations(),
      ]);
      setOverview(ov);
      setRecommendations(recs);

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

  return {
    overview,
    recommendations,
    reflection,
    isLoading,
    isGenerating,
    error,
    fetchAll,
    recordDecision,
    logOutcome,
    undoDecision,
    generateReflection,
  };
}
