import type { FundamentalData } from '../../types';
import { TickerCard } from './TickerCard';
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import clsx from 'clsx';

interface TickerCardListProps {
  tickers: FundamentalData[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export function TickerCardList({
  tickers,
  selectedTicker,
  onSelect,
  collapsed,
  onToggleCollapse,
}: TickerCardListProps) {
  if (collapsed) {
    return (
      <div className="w-12 border-r border-border bg-bg-secondary h-full flex flex-col items-center shrink-0">
        <button
          onClick={onToggleCollapse}
          className="p-3 text-text-secondary hover:text-text-primary transition-colors"
          title="Expand ticker list"
        >
          <PanelLeftOpen className="w-5 h-5" />
        </button>
        <div className="flex flex-col gap-2 mt-2 overflow-y-auto px-1">
          {tickers.map(ticker => (
            <button
              key={ticker.ticker}
              onClick={() => onSelect(ticker.ticker)}
              title={`${ticker.ticker} — ${ticker.company_name}`}
              className={clsx(
                "text-[10px] font-bold px-1 py-1.5 rounded transition-colors leading-tight",
                selectedTicker === ticker.ticker
                  ? "bg-accent-blue/20 text-accent-blue"
                  : "text-text-secondary hover:text-text-primary hover:bg-bg-tertiary"
              )}
            >
              {ticker.ticker.replace(/^(TSX|TSXV|LSE|ASX|XETR):/, "")}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="w-80 border-r border-border bg-bg-secondary overflow-y-auto h-full flex flex-col shrink-0">
      <div className="flex items-center justify-between px-4 pt-3 pb-1">
        <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
          Tickers ({tickers.length})
        </span>
        <button
          onClick={onToggleCollapse}
          className="p-1.5 rounded text-text-secondary hover:text-text-primary hover:bg-bg-tertiary transition-colors"
          title="Collapse ticker list"
        >
          <PanelLeftClose className="w-4 h-4" />
        </button>
      </div>

      {tickers.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-text-secondary p-4">
          No tickers found.
        </div>
      ) : (
        <div className="flex flex-col gap-3 p-4 pt-2">
          {tickers.map(ticker => (
            <TickerCard
              key={ticker.ticker}
              data={ticker}
              isSelected={selectedTicker === ticker.ticker}
              onClick={() => onSelect(ticker.ticker)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
