import { useEffect, useState, useCallback } from 'react';
import { usePipeline } from '../../hooks/usePipeline';
import { TickerCardList } from '../recommendations/TickerCardList';
import { DetailView } from '../recommendations/DetailView';
import { TabContentSkeleton } from '../shared/Skeleton';

interface ResultsScreenProps {
  runId: string;
}

export function ResultsScreen({ runId }: ResultsScreenProps) {
  const { getResult, currentResult, isRunning } = usePipeline();

  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jumpToRiskTicker, setJumpToRiskTicker] = useState<string | null>(null);

  useEffect(() => {
    setIsLoading(true);
    setError(null);
    getResult(runId)
      .catch(err => setError(err.message))
      .finally(() => setIsLoading(false));
  }, [runId, getResult]);

  // Auto-select ticker when result loads — default matches sidebar (confidence descending)
  useEffect(() => {
    const screeningTickers = currentResult?.screening?.tickers;
    if (!screeningTickers || screeningTickers.length === 0) {
      setSelectedTicker(null);
      return;
    }
    if (selectedTicker && screeningTickers.some(t => t.ticker === selectedTicker)) {
      return;
    }
    const confByTicker = Object.fromEntries(
      (currentResult.recommendations ?? []).map(r => [r.ticker, r.confidence])
    );
    const deduped = screeningTickers.filter(
      (t, i, arr) => arr.findIndex(x => x.ticker === t.ticker) === i
    );
    const sorted = [...deduped].sort((a, b) => {
      const ca = confByTicker[a.ticker] ?? -1;
      const cb = confByTicker[b.ticker] ?? -1;
      if (cb !== ca) return cb - ca;
      return a.ticker.localeCompare(b.ticker);
    });
    setSelectedTicker(sorted[0]?.ticker ?? null);
  }, [currentResult, selectedTicker]);

  const handleRiskClick = useCallback((ticker: string) => {
    setSelectedTicker(ticker);
    setJumpToRiskTicker(ticker);
    // Scroll to risk section after a short tick for tab transition
    setTimeout(() => {
      document.getElementById('risk-factors')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      setJumpToRiskTicker(null);
    }, 200);
  }, []);

  if (isRunning || isLoading) {
    return (
      <div className="flex flex-col md:flex-row h-full w-full overflow-hidden">
        {/* Sidebar skeleton */}
        <div className="hidden md:flex w-80 border-r border-border-subtle bg-bg-asphalt h-full flex-col shrink-0 p-3 space-y-2">
          <div className="flex items-center justify-between px-1 pb-1">
            <div className="h-3 w-16 animate-pulse rounded bg-bg-steel" />
          </div>
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="p-3.5 border border-border-gutter rounded-lg bg-bg-concrete space-y-2.5 animate-pulse">
              <div className="flex justify-between items-start">
                <div className="space-y-1.5">
                  <div className="h-5 w-20 rounded bg-bg-steel" />
                  <div className="h-3 w-32 rounded bg-bg-steel" />
                </div>
                <div className="h-5 w-12 rounded-full bg-bg-steel" />
              </div>
              <div className="h-3 w-16 rounded bg-bg-steel" />
              <div className="h-8 w-full rounded bg-bg-steel" />
            </div>
          ))}
        </div>
        {/* Detail panel skeleton */}
        <div className="flex-1 flex flex-col">
          <div className="px-6 py-4 border-b border-border-gutter bg-bg-asphalt/70 space-y-2">
            <div className="h-7 w-32 animate-pulse rounded bg-bg-steel" />
            <div className="h-3 w-48 animate-pulse rounded bg-bg-steel" />
          </div>
          <div className="border-b border-border-gutter bg-bg-asphalt px-4 py-3 flex gap-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-4 w-16 animate-pulse rounded bg-bg-steel" />
            ))}
          </div>
          <TabContentSkeleton />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-accent-loss">
        <p>Error: {error}</p>
      </div>
    );
  }

  if (!currentResult) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted">
        <p className="font-display text-sm">No results found for this run.</p>
      </div>
    );
  }

  const tickers = (currentResult.screening?.tickers || []).filter(
    (t, i, arr) => arr.findIndex(x => x.ticker === t.ticker) === i
  );
  const selectedTickerData = tickers.find(t => t.ticker === selectedTicker);

  const actionMap = Object.fromEntries(
    (currentResult.recommendations || []).map(r => [r.ticker, r.action])
  );
  const confidenceMap = Object.fromEntries(
    (currentResult.recommendations || []).map(r => [r.ticker, r.confidence])
  );

  return (
    <div className="flex flex-col md:flex-row h-full w-full overflow-hidden">
      <TickerCardList
        tickers={tickers}
        selectedTicker={selectedTicker}
        onSelect={setSelectedTicker}
        onRiskClick={handleRiskClick}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(prev => !prev)}
        actionMap={actionMap}
        confidenceMap={confidenceMap}
      />

      {selectedTickerData ? (
        <DetailView
          key={`${selectedTickerData.ticker}-${jumpToRiskTicker === selectedTickerData.ticker ? 'risk' : 'normal'}`}
          tickerData={selectedTickerData}
          fullResult={currentResult}
          initialTab={jumpToRiskTicker === selectedTickerData.ticker ? 'overview' : undefined}
        />
      ) : (
        <div className="flex-1 flex items-center justify-center text-text-muted bg-bg-void">
          <span className="font-display text-sm">Select a ticker to view details.</span>
        </div>
      )}
    </div>
  );
}
