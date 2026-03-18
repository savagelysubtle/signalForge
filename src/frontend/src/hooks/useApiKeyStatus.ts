import { useState, useCallback, useEffect } from 'react';
import { api } from '../api/client';
import type { ApiKeyStatus } from '../types';

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
    } catch (err: any) {
      setError(err.message || 'Failed to fetch API key status');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const reloadKeys = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      await api.reloadApiKeys();
      await fetchStatus();
    } catch (err: any) {
      setError(err.message || 'Failed to reload API keys');
    } finally {
      setIsLoading(false);
    }
  }, [fetchStatus]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  return {
    status,
    isLoading,
    error,
    reloadKeys,
    refresh: fetchStatus,
  };
}
