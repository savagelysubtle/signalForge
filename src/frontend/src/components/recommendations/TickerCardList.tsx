import type { FundamentalData } from '../../types';
import { TickerCard } from './TickerCard';
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { motion } from 'motion/react';
import clsx from 'clsx';

const ACTION_DOT: Record<string, string> = {
  BUY:   'bg-accent-profit',
  SHORT: 'bg-accent-loss',
  HOLD:  'bg-accent-alert',
};

interface TickerCardListProps {
  tickers: FundamentalData[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  onRiskClick?: (ticker: string) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  actionMap?: Record<string, string>;
}

export function TickerCardList({
  tickers,
  selectedTicker,
  onSelect,
  onRiskClick,
  collapsed,
  onToggleCollapse,
  actionMap = {},
}: TickerCardListProps) {
  const mobileStrip = (
    <div className="flex md:hidden border-b border-border-subtle bg-bg-asphalt shrink-0 overflow-x-auto">
      <div className="flex gap-1.5 px-3 py-2">
        {tickers.map(ticker => {
          const action = actionMap[ticker.ticker];
          const dotColor = action ? ACTION_DOT[action] : null;
          return (
            <button
              key={ticker.ticker}
              onClick={() => onSelect(ticker.ticker)}
              className={clsx(
                "flex items-center gap-1 text-xs font-display font-bold px-2.5 py-1.5 rounded-md whitespace-nowrap transition-colors",
                selectedTicker === ticker.ticker
                  ? "bg-accent-signal-dim text-accent-signal"
                  : "bg-bg-concrete text-text-muted hover:text-text-primary"
              )}
            >
              {dotColor && <span className={clsx('w-1.5 h-1.5 rounded-full shrink-0', dotColor)} />}
              {ticker.ticker.replace(/^(TSX|TSXV|LSE|ASX|XETR):/, "")}
            </button>
          );
        })}
      </div>
    </div>
  );

  if (collapsed) {
    return (
      <>
        {mobileStrip}
        <div className="hidden md:flex w-12 border-r border-border-subtle bg-bg-asphalt h-full flex-col items-center shrink-0">
        <button
          onClick={onToggleCollapse}
          className="p-3 text-text-muted hover:text-text-primary transition-colors"
          title="Expand ticker list"
        >
          <PanelLeftOpen className="w-5 h-5" />
        </button>
        <div className="flex flex-col gap-2 mt-2 overflow-y-auto px-1">
          {tickers.map(ticker => {
            const action = actionMap[ticker.ticker];
            const dotColor = action ? ACTION_DOT[action] : null;
            return (
              <button
                key={ticker.ticker}
                onClick={() => onSelect(ticker.ticker)}
                title={`${ticker.ticker} — ${ticker.company_name}${action ? ` · ${action}` : ''}`}
                className={clsx(
                  "flex flex-col items-center gap-0.5 text-[10px] font-display font-bold px-1 py-1.5 rounded transition-colors leading-tight",
                  selectedTicker === ticker.ticker
                    ? "bg-accent-signal-dim text-accent-signal"
                    : "text-text-muted hover:text-text-primary hover:bg-bg-steel"
                )}
              >
                {ticker.ticker.replace(/^(TSX|TSXV|LSE|ASX|XETR):/, "")}
                {dotColor && <span className={clsx('w-1.5 h-1.5 rounded-full', dotColor)} />}
              </button>
            );
          })}
        </div>
      </div>
      </>
    );
  }

  return (
    <>
    {mobileStrip}
    <div className="hidden md:flex w-80 border-r border-border-subtle bg-bg-asphalt overflow-y-auto h-full flex-col shrink-0">
      <div className="flex items-center justify-between px-4 pt-3 pb-1">
        <span className="text-xs font-display text-text-muted uppercase tracking-wider">
          Tickers <span className="text-text-secondary">({tickers.length})</span>
        </span>
        <button
          onClick={onToggleCollapse}
          className="p-1.5 rounded text-text-muted hover:text-text-primary hover:bg-bg-steel transition-colors"
          title="Collapse ticker list"
        >
          <PanelLeftClose className="w-4 h-4" />
        </button>
      </div>

      {tickers.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-text-muted p-4 font-body text-sm">
          No tickers found.
        </div>
      ) : (
        <div className="flex flex-col gap-2 p-3 pt-2">
          {tickers.map((ticker, i) => (
            <motion.div
              key={ticker.ticker}
              initial={{ opacity: 0, x: -12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.3, delay: i * 0.04, ease: 'easeOut' }}
            >
              <TickerCard
                data={ticker}
                action={actionMap[ticker.ticker]}
                isSelected={selectedTicker === ticker.ticker}
                onClick={() => onSelect(ticker.ticker)}
                onRiskClick={onRiskClick ? () => onRiskClick(ticker.ticker) : undefined}
              />
            </motion.div>
          ))}
        </div>
      )}
    </div>
    </>
  );
}
