import { useState, useCallback, useRef, useEffect } from 'react';
import { api } from '../api/client';
import type { ScannerLatestResponse, ScannerFilters, MarketStateResponse, ScanRunStatus } from '../types';

const POLL_MS = 3000;
const DONE_STATUSES = new Set(['completed', 'failed', 'unknown']);

export function useScanner() {
  const [isScanning, setIsScanning] = useState(false);
  const [scanStatus, setScanStatus] = useState<ScanRunStatus | null>(null);
  const [latestResults, setLatestResults] = useState<ScannerLatestResponse | null>(null);
  const [marketState, setMarketState] = useState<MarketStateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const fetchLatest = useCallback(async (actionableOnly = false) => {
    try {
      const data = await api.getScannerLatest(undefined, 0.5, actionableOnly);
      setLatestResults(data);
    } catch {
      // Non-fatal — scanner may not have run yet
    }
  }, []);

  const fetchHeartbeat = useCallback(async () => {
    try {
      const data = await api.getHeartbeat();
      setMarketState(data);
    } catch {
      // Heartbeat may not be initialized yet
    }
  }, []);

  const runScan = useCallback(async (filters?: ScannerFilters) => {
    cancelledRef.current = false;
    setIsScanning(true);
    setError(null);
    setScanStatus(null);

    try {
      const { scan_run_id } = await api.runScan(filters);

      while (!cancelledRef.current) {
        await new Promise<void>((resolve) => setTimeout(resolve, POLL_MS));
        if (cancelledRef.current) break;

        try {
          const status = await api.getScanStatus(scan_run_id);
          setScanStatus(status);
          if (DONE_STATUSES.has(status.status)) break;
        } catch {
          // Transient polling errors are non-fatal
        }
      }

      if (!cancelledRef.current) {
        await fetchLatest();
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to run scan';
      setError(msg);
    } finally {
      setIsScanning(false);
    }
  }, [fetchLatest]);

  useEffect(() => {
    fetchLatest();
    fetchHeartbeat();
  }, [fetchLatest, fetchHeartbeat]);

  return {
    isScanning,
    scanStatus,
    latestResults,
    marketState,
    error,
    runScan,
    fetchLatest,
    fetchHeartbeat,
  };
}
