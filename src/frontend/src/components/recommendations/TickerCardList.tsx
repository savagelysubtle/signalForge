import { useEffect, useMemo, useState } from 'react';
import type { FundamentalData } from '../../types';
import { canonicalTickerMatchKey } from '../../utils/ticker';
import { TickerCard } from './TickerCard';
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { motion } from 'motion/react';
import clsx from 'clsx';

const ACTION_DOT: Record<string, string> = {
  BUY: 'bg-accent-profit',
  SHORT: 'bg-accent-loss',
  HOLD: 'bg-accent-alert',
  WATCH: 'bg-accent-electric',
  NO_TRADE: 'bg-text-muted',
};

/** Sort order: BUY first, then SHORT, HOLD, WATCH, NO_TRADE; unknown last. */
const ACTION_SORT_RANK: Record<string, number> = {
  BUY: 0,
  SHORT: 1,
  HOLD: 2,
  WATCH: 3,
  NO_TRADE: 4,
};

const FILTER_OPTIONS = ['ALL', 'BUY', 'SHORT', 'HOLD', 'WATCH', 'NO_TRADE'] as const;
type ActionFilter = (typeof FILTER_OPTIONS)[number];

type SortMode = 'confidence' | 'action' | 'alphabetical';

interface TickerCardListProps {
  tickers: FundamentalData[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  onRiskClick?: (ticker: string) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  actionMap?: Record<string, string>;
  confidenceMap?: Record<string, number>;
}

function confidencePercentClass(confidence: number): string {
  if (confidence >= 0.7) return 'text-[var(--accent-profit)]';
  if (confidence >= 0.5) return 'text-[var(--accent-alert)]';
  return 'text-[var(--accent-loss)]';
}

export function TickerCardList({
  tickers,
  selectedTicker,
  onSelect,
  onRiskClick,
  collapsed,
  onToggleCollapse,
  actionMap = {},
  confidenceMap = {},
}: TickerCardListProps) {
  const [sortMode, setSortMode] = useState<SortMode>('confidence');
  const [actionFilter, setActionFilter] = useState<ActionFilter>('ALL');

  const displayTickers = useMemo(() => {
    let list = [...tickers];
    if (actionFilter !== 'ALL') {
      list = list.filter(t => actionMap[canonicalTickerMatchKey(t.ticker)] === actionFilter);
    }

    const rank = (sym: string) => {
      const a = actionMap[canonicalTickerMatchKey(sym)];
      return a !== undefined && a in ACTION_SORT_RANK ? ACTION_SORT_RANK[a] : 99;
    };
    const conf = (sym: string) => confidenceMap[canonicalTickerMatchKey(sym)] ?? -1;

    list.sort((a, b) => {
      if (sortMode === 'alphabetical') {
        return a.ticker.localeCompare(b.ticker);
      }
      if (sortMode === 'confidence') {
        const diff = conf(b.ticker) - conf(a.ticker);
        if (diff !== 0) return diff;
        return a.ticker.localeCompare(b.ticker);
      }
      const ra = rank(a.ticker);
      const rb = rank(b.ticker);
      if (ra !== rb) return ra - rb;
      return a.ticker.localeCompare(b.ticker);
    });

    return list;
  }, [tickers, actionFilter, sortMode, actionMap, confidenceMap]);

  useEffect(() => {
    if (displayTickers.length === 0) return;
    if (selectedTicker && !displayTickers.some(t => t.ticker === selectedTicker)) {
      onSelect(displayTickers[0].ticker);
    }
  }, [displayTickers, selectedTicker, onSelect]);

  const sortRow = (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[10px] font-body text-text-muted uppercase tracking-wider shrink-0">Sort</span>
      <div className="flex flex-wrap gap-1">
        {(
          [
            ['confidence', 'Confidence'],
            ['action', 'Action'],
            ['alphabetical', 'A–Z'],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setSortMode(id)}
            className={clsx(
              'px-2 py-0.5 text-[10px] font-body rounded transition-colors',
              sortMode === id
                ? 'bg-accent-signal-dim text-accent-signal'
                : 'bg-bg-concrete text-text-muted hover:text-text-primary hover:bg-bg-steel'
            )}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );

  const filterRow = (
    <div className="flex flex-wrap gap-1">
      {FILTER_OPTIONS.map(opt => (
        <button
          key={opt}
          type="button"
          onClick={() => setActionFilter(opt)}
          className={clsx(
            'px-2 py-0.5 text-[10px] font-display font-semibold rounded border transition-colors',
            actionFilter === opt
              ? 'border-accent-signal/50 bg-accent-signal-dim text-accent-signal'
              : 'border-border-gutter bg-bg-concrete text-text-muted hover:border-border-strong hover:text-text-primary'
          )}
        >
          {opt === 'ALL' ? 'ALL' : opt.replace('_', ' ')}
        </button>
      ))}
    </div>
  );

  const mobileStrip = (
    <div className="flex md:hidden flex-col border-b border-border-subtle bg-bg-asphalt shrink-0">
      <div className="px-3 pt-2 pb-1 border-b border-border-subtle/60">{sortRow}</div>
      <div className="px-3 pb-2 pt-2">{filterRow}</div>
      <div className="flex overflow-x-auto">
        <div className="flex gap-1.5 px-3 py-2">
          {displayTickers.map(ticker => {
            const action = actionMap[canonicalTickerMatchKey(ticker.ticker)];
            const dotColor = action ? ACTION_DOT[action] : null;
            const c = confidenceMap[canonicalTickerMatchKey(ticker.ticker)];
            return (
              <button
                key={ticker.ticker}
                onClick={() => onSelect(ticker.ticker)}
                className={clsx(
                  'flex items-center gap-1 text-xs font-display font-bold px-2.5 py-1.5 rounded-md whitespace-nowrap transition-colors',
                  selectedTicker === ticker.ticker
                    ? 'bg-accent-signal-dim text-accent-signal'
                    : 'bg-bg-concrete text-text-muted hover:text-text-primary'
                )}
              >
                {dotColor && <span className={clsx('w-1.5 h-1.5 rounded-full shrink-0', dotColor)} />}
                {ticker.ticker.replace(/^(TSX|TSXV|LSE|ASX|XETR):/, '')}
                {c !== undefined && !Number.isNaN(c) && (
                  <span className={clsx('text-[10px] font-mono tabular-nums', confidencePercentClass(c))}>
                    {Math.round(c * 100)}%
                  </span>
                )}
              </button>
            );
          })}
        </div>
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
            {displayTickers.map(ticker => {
              const action = actionMap[canonicalTickerMatchKey(ticker.ticker)];
              const dotColor = action ? ACTION_DOT[action] : null;
              const c = confidenceMap[canonicalTickerMatchKey(ticker.ticker)];
              return (
                <button
                  key={ticker.ticker}
                  onClick={() => onSelect(ticker.ticker)}
                  title={`${ticker.ticker} — ${ticker.company_name}${action ? ` · ${action}` : ''}`}
                  className={clsx(
                    'flex flex-col items-center gap-0.5 text-[10px] font-display font-bold px-1 py-1.5 rounded transition-colors leading-tight',
                    selectedTicker === ticker.ticker
                      ? 'bg-accent-signal-dim text-accent-signal'
                      : 'text-text-muted hover:text-text-primary hover:bg-bg-steel'
                  )}
                >
                  {ticker.ticker.replace(/^(TSX|TSXV|LSE|ASX|XETR):/, '')}
                  {c !== undefined && !Number.isNaN(c) && (
                    <span className={clsx('font-mono tabular-nums text-[9px]', confidencePercentClass(c))}>
                      {Math.round(c * 100)}%
                    </span>
                  )}
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
        <div className="flex items-center justify-between px-4 pt-3 pb-1 shrink-0">
          <span className="text-xs font-display text-text-muted uppercase tracking-wider">
            Tickers <span className="text-text-secondary">({displayTickers.length})</span>
          </span>
          <button
            onClick={onToggleCollapse}
            className="p-1.5 rounded text-text-muted hover:text-text-primary hover:bg-bg-steel transition-colors"
            title="Collapse ticker list"
          >
            <PanelLeftClose className="w-4 h-4" />
          </button>
        </div>

        <div className="px-4 shrink-0 space-y-2 border-b border-border-subtle/80 pb-3 pt-1">
          {sortRow}
          {filterRow}
        </div>

        {displayTickers.length === 0 ? (
          <div className="flex-1 flex items-center justify-center text-text-muted p-4 font-body text-sm">
            No tickers match this filter.
          </div>
        ) : (
          <div className="flex flex-col gap-2 p-3 pt-2">
            {displayTickers.map((ticker, i) => (
              <motion.div
                key={ticker.ticker}
                initial={{ opacity: 0, x: -12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.3, delay: i * 0.04, ease: 'easeOut' }}
              >
                <TickerCard
                  data={ticker}
                  action={actionMap[canonicalTickerMatchKey(ticker.ticker)]}
                  confidence={confidenceMap[canonicalTickerMatchKey(ticker.ticker)]}
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
