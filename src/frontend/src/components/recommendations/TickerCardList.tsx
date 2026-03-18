import type { FundamentalData } from '../../types';
import { TickerCard } from './TickerCard';

interface TickerCardListProps {
  tickers: FundamentalData[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
}

export function TickerCardList({ tickers, selectedTicker, onSelect }: TickerCardListProps) {
  if (tickers.length === 0) {
    return (
      <div className="w-80 border-r border-border bg-bg-secondary p-4 flex items-center justify-center text-text-secondary h-full">
        No tickers found.
      </div>
    );
  }

  return (
    <div className="w-80 border-r border-border bg-bg-secondary overflow-y-auto h-full flex flex-col gap-3 p-4 shrink-0">
      {tickers.map(ticker => (
        <TickerCard
          key={ticker.ticker}
          data={ticker}
          isSelected={selectedTicker === ticker.ticker}
          onClick={() => onSelect(ticker.ticker)}
        />
      ))}
    </div>
  );
}
