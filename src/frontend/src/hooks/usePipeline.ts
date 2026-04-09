import { useState, useCallback, useRef, useEffect } from 'react';
import { api } from '../api/client';
import type { PipelineProgress, PipelineResult, PipelineRunSummary, ScreenerOverrides } from '../types';

/** How often to poll the progress endpoint while a run is active (ms). */
const POLL_MS = 3000;

/** Terminal statuses that mean the pipeline is no longer running. */
const DONE_STATUSES = new Set(['completed', 'partial', 'failed']);

/** Maximum time to poll before assuming the pipeline is stuck (ms). */
const POLL_TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes

/** Number of consecutive poll failures before surfacing an error. */
const MAX_CONSECUTIVE_POLL_FAILURES = 5;

export function usePipeline() {
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentResult, setCurrentResult] = useState<PipelineResult | null>(null);
  const [history, setHistory] = useState<PipelineRunSummary[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [progress, setProgress] = useState<PipelineProgress | null>(null);

  /** Set to true when the component unmounts or the user cancels — stops the poll loop. */
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const runPipeline = useCallback(async (
    strategyId?: string,
    manualTickers?: string[],
    userPrompt?: string,
    screenerOverrides?: ScreenerOverrides,
    modeOverride?: string,
  ) => {
    cancelledRef.current = false;
    setIsRunning(true);
    setError(null);
    setProgress(null);

    try {
      // POST returns immediately with run_id; pipeline runs in background on server
      const { run_id } = await api.runPipeline({
        strategy_id: strategyId,
        manual_tickers: manualTickers,
        user_prompt: userPrompt,
        screener_overrides: screenerOverrides,
        mode_override: modeOverride,
      });

      // Poll progress until the run reaches a terminal status
      const pollStart = Date.now();
      let consecutiveFailures = 0;
      while (!cancelledRef.current) {
        await new Promise<void>((resolve) => setTimeout(resolve, POLL_MS));
        if (cancelledRef.current) break;

        // Timeout guard — stop polling if the pipeline seems stuck
        if (Date.now() - pollStart > POLL_TIMEOUT_MS) {
          setError('Pipeline timed out — it may still be running on the server. Check history later.');
          break;
        }

        try {
          const p = await api.getPipelineProgress(run_id);
          consecutiveFailures = 0;
          setProgress(p);
          if (DONE_STATUSES.has(p.run_status)) break;
        } catch {
          consecutiveFailures++;
          if (consecutiveFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
            setError('Lost connection to the server. The pipeline may still be running — check history later.');
            break;
          }
          // Transient network errors during polling are non-fatal — keep waiting
        }
      }

      if (cancelledRef.current) return null as unknown as PipelineResult;

      // Fetch the full result now that the run has completed
      const result = await api.getPipelineResult(run_id);
      setCurrentResult(result);
      return result;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to run pipeline';
      setError(msg);
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
    } catch (err: unknown) {
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
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to fetch pipeline result';
      setError(msg);
      throw err;
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return {
    isRunning,
    error,
    currentResult,
    history,
    isLoadingHistory,
    progress,
    runPipeline,
    fetchHistory,
    getResult,
    setError,
    clearError,
  };
}
