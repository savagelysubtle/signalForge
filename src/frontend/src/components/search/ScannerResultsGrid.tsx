import { Play, TrendingUp, BarChart3, Zap } from 'lucide-react';
import { motion } from 'motion/react';
import clsx from 'clsx';
import type { ScannerLatestResponse, ScannerResultItem } from '../../types';

const STRATEGY_LABELS: Record<string, string> = {
  swing: 'Swing',
  mean_reversion: 'Mean Reversion',
  momentum_breakout: 'Momentum Breakout',
  bollinger_band_squeeze_breakout: 'BB Squeeze',
  vwap_reversal_scalp: 'VWAP Reversal',
  earnings_play: 'Earnings Play',
  ema_stack_momentum: 'EMA Stack',
  ema_21_pullback: 'EMA 21 Pullback',
  value_accumulation: 'Value Accum.',
  intraday_scalp: 'Intraday Scalp',
};

const STRATEGY_COLORS: Record<string, string> = {
  swing: 'border-accent-signal/30 bg-accent-signal/5',
  mean_reversion: 'border-accent-alert/30 bg-accent-alert/5',
  momentum_breakout: 'border-accent-profit/30 bg-accent-profit/5',
  bollinger_band_squeeze_breakout: 'border-accent-electric/30 bg-accent-electric/5',
  vwap_reversal_scalp: 'border-accent-loss/30 bg-accent-loss/5',
  earnings_play: 'border-accent-alert/30 bg-accent-alert/5',
  ema_stack_momentum: 'border-accent-profit/30 bg-accent-profit/5',
  ema_21_pullback: 'border-accent-signal/30 bg-accent-signal/5',
  value_accumulation: 'border-accent-electric/30 bg-accent-electric/5',
  intraday_scalp: 'border-accent-alert/30 bg-accent-alert/5',
};

function ScoreBar({ value, max = 1 }: { value: number; max?: number }) {
  const pct = Math.min(100, (value / max) * 100);
  const color =
    pct >= 70 ? 'bg-accent-profit' : pct >= 50 ? 'bg-accent-signal' : 'bg-accent-alert';
  return (
    <div className="w-full h-1 bg-bg-steel rounded-full overflow-hidden">
      <div className={clsx('h-full rounded-full transition-all', color)} style={{ width: `${pct}%` }} />
    </div>
  );
}

function TickerRow({ item }: { item: ScannerResultItem }) {
  return (
    <div className={clsx(
      'flex items-center gap-2 py-1 px-1.5 rounded hover:bg-bg-steel/50 transition-colors',
      !item.is_actionable && 'opacity-60',
    )}>
      <span className="font-display text-[11px] font-bold text-text-primary w-14 shrink-0">
        {item.ticker}
      </span>
      <div className="flex-1 min-w-0">
        <ScoreBar value={item.combined_score} />
      </div>
      <span className="text-[10px] font-display text-text-secondary w-8 text-right">
        {(item.combined_score * 100).toFixed(0)}
      </span>
      {!item.is_actionable && (
        <span className="text-[8px] font-display text-text-muted bg-bg-steel px-1 py-0.5 rounded">
          WATCH
        </span>
      )}
      {item.rsi != null && (
        <span className={clsx(
          'text-[9px] font-display px-1 py-0.5 rounded',
          item.rsi < 35 ? 'text-accent-profit bg-accent-profit/10' :
          item.rsi > 70 ? 'text-accent-loss bg-accent-loss/10' :
          'text-text-muted bg-bg-steel',
        )}>
          RSI {item.rsi.toFixed(0)}
        </span>
      )}
      {item.volume_ratio != null && item.volume_ratio > 1.3 && (
        <span className="text-[9px] font-display text-accent-alert bg-accent-alert/10 px-1 py-0.5 rounded">
          {item.volume_ratio.toFixed(1)}x
        </span>
      )}
    </div>
  );
}

interface ScannerResultsGridProps {
  results: ScannerLatestResponse;
  onSelectStrategy: (strategyType: string, tickers: string[]) => void;
  disabled?: boolean;
}

export function ScannerResultsGrid({ results, onSelectStrategy, disabled }: ScannerResultsGridProps) {
  const strategies = Object.entries(results.strategies);
  if (strategies.length === 0) return null;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2.5">
      {strategies.map(([strategyType, items], idx) => (
        <motion.div
          key={strategyType}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, delay: idx * 0.05 }}
          className={clsx(
            'rounded-lg border p-3 bg-bg-concrete transition-all',
            STRATEGY_COLORS[strategyType] ?? 'border-border-gutter',
          )}
        >
          {/* Card header */}
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1.5">
              <StrategyIcon type={strategyType} />
              <span className="font-display text-xs font-bold text-text-primary">
                {STRATEGY_LABELS[strategyType] ?? strategyType}
              </span>
              <span className="text-[9px] font-display text-text-muted bg-bg-steel px-1.5 py-0.5 rounded-full">
                {items.length}
              </span>
            </div>
            <button
              onClick={() => onSelectStrategy(strategyType, items.map(i => i.ticker))}
              disabled={disabled}
              className="flex items-center gap-1 text-[10px] font-display text-accent-signal hover:text-accent-signal/80 transition-colors disabled:opacity-40"
            >
              <Play className="w-2.5 h-2.5" />
              Run
            </button>
          </div>

          {/* Ticker list */}
          <div className="space-y-0.5">
            {items.slice(0, 5).map((item) => (
              <TickerRow key={item.ticker} item={item} />
            ))}
            {items.length > 5 && (
              <div className="text-[9px] text-text-muted font-body text-center pt-1">
                +{items.length - 5} more
              </div>
            )}
          </div>

          {/* Matched rules summary */}
          {items[0]?.matched_rules.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2 pt-2 border-t border-border-subtle">
              {[...new Set(items.flatMap(i => i.matched_rules))].slice(0, 3).map((rule) => (
                <span
                  key={rule}
                  className="text-[8px] font-display text-text-muted bg-bg-steel px-1.5 py-0.5 rounded"
                >
                  {rule}
                </span>
              ))}
            </div>
          )}
        </motion.div>
      ))}
    </div>
  );
}

function StrategyIcon({ type }: { type: string }) {
  const cls = "w-3 h-3 text-text-secondary";
  if (type.includes('momentum') || type.includes('breakout')) return <Zap className={cls} />;
  if (type.includes('ema') || type.includes('swing')) return <TrendingUp className={cls} />;
  return <BarChart3 className={cls} />;
}
