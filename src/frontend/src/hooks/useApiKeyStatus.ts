import { useState, useCallback, useEffect } from "react";
import { api } from "../api/client";
import type { ApiKeyStatus } from "../types";

export function useApiKeyStatus() {
  const [status, setStatus] = useState<ApiKeyStatus | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.getApiKeyStatus();
      setStatus(data);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to fetch API key status";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  return { status, isLoading, error, refresh: fetchStatus };
}
