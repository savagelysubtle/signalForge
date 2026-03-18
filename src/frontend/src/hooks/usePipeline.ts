import { useState, useCallback } from 'react';
import { api } from '../api/client';
import type { PipelineResult, PipelineRunSummary } from '../types';

export function usePipeline() {
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentResult, setCurrentResult] = useState<PipelineResult | null>(null);
  const [history, setHistory] = useState<PipelineRunSummary[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);

  const runPipeline = useCallback(async (
    strategyId?: string,
    manualTickers?: string[],
    userPrompt?: string,
  ) => {
    setIsRunning(true);
    setError(null);
    try {
      const response = await api.runPipeline({
        strategy_id: strategyId,
        manual_tickers: manualTickers,
        user_prompt: userPrompt,
      });
      
      // After run completes, fetch the full result
      const result = await api.getPipelineResult(response.run_id);
      setCurrentResult(result);
      return result;
    } catch (err: any) {
      setError(err.message || 'Failed to run pipeline');
      throw err;
    } finally {
      setIsRunning(false);
    }
  }, []);

  const fetchHistory = useCallback(async () => {
    setIsLoadingHistory(true);
    try {
      const runs = await api.listPipelineRuns();
      setHistory(runs);
    } catch (err: any) {
      console.error('Failed to fetch history:', err);
    } finally {
      setIsLoadingHistory(false);
    }
  }, []);

  const getResult = useCallback(async (runId: string) => {
    try {
      const result = await api.getPipelineResult(runId);
      setCurrentResult(result);
      return result;
    } catch (err: any) {
      setError(err.message || 'Failed to fetch pipeline result');
      throw err;
    }
  }, []);

  return {
    isRunning,
    error,
    currentResult,
    history,
    isLoadingHistory,
    runPipeline,
    fetchHistory,
    getResult,
  };
}
