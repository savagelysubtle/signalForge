import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { usePipeline } from '../hooks/usePipeline';
import { TickerCardList } from '../components/recommendations/TickerCardList';
import { DetailView } from '../components/recommendations/DetailView';
import { Loader2 } from 'lucide-react';

export function RecommendationsView() {
  const [searchParams] = useSearchParams();
  const runId = searchParams.get('run');
  const { getResult, currentResult, isRunning } = usePipeline();
  
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (runId) {
      setIsLoading(true);
      setError(null);
      getResult(runId)
        .catch(err => setError(err.message))
        .finally(() => setIsLoading(false));
    }
  }, [runId, getResult]);

  // Auto-select first ticker when result loads
  useEffect(() => {
    if (currentResult?.screening?.tickers && currentResult.screening.tickers.length > 0) {
      if (!selectedTicker || !currentResult.screening.tickers.find(t => t.ticker === selectedTicker)) {
        setSelectedTicker(currentResult.screening.tickers[0].ticker);
      }
    } else {
      setSelectedTicker(null);
    }
  }, [currentResult, selectedTicker]);

  if (isRunning || isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-text-secondary">
        <Loader2 className="w-8 h-8 animate-spin mb-4 text-accent-blue" />
        <p>Loading analysis results...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-accent-red">
        <p>Error: {error}</p>
      </div>
    );
  }

  if (!currentResult) {
    return (
      <div className="flex items-center justify-center h-full text-text-secondary">
        <p>Run an analysis to see results.</p>
      </div>
    );
  }

  const tickers = currentResult.screening?.tickers || [];
  const selectedTickerData = tickers.find(t => t.ticker === selectedTicker);

  return (
    <div className="flex h-full w-full overflow-hidden">
      <TickerCardList 
        tickers={tickers} 
        selectedTicker={selectedTicker} 
        onSelect={setSelectedTicker} 
      />
      
      {selectedTickerData ? (
        <DetailView 
          tickerData={selectedTickerData} 
          fullResult={currentResult} 
        />
      ) : (
        <div className="flex-1 flex items-center justify-center text-text-secondary bg-bg-primary">
          Select a ticker to view details.
        </div>
      )}
    </div>
  );
}
