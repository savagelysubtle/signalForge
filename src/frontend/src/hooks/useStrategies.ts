import { useState, useCallback, useEffect } from 'react';
import { api } from '../api/client';
import type { StrategyConfig } from '../types';

export function useStrategies() {
  const [templates, setTemplates] = useState<StrategyConfig[]>([]);
  const [strategies, setStrategies] = useState<StrategyConfig[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStrategiesAndTemplates = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [fetchedTemplates, fetchedStrategies] = await Promise.all([
        api.listTemplates(),
        api.listStrategies()
      ]);
      setTemplates(fetchedTemplates);
      setStrategies(fetchedStrategies);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch strategies');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStrategiesAndTemplates();
  }, [fetchStrategiesAndTemplates]);

  return {
    templates,
    strategies,
    isLoading,
    error,
    refresh: fetchStrategiesAndTemplates,
  };
}
