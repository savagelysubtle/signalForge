import { useMemo } from 'react';
import { useStrategies } from '../hooks/useStrategies';
import { Loader2, Star } from 'lucide-react';
import { motion } from 'motion/react';
import type { StrategyConfig } from '../types';

type TradingStyleLabel = 'Intraday' | 'Swing' | 'Position' | 'Event' | 'Mean Reversion' | 'Value' | 'Crypto';

const STRATEGY_TYPE_MAP: Record<string, TradingStyleLabel> = {
  intraday: 'Intraday',
  crypto_intraday: 'Intraday',
  swing: 'Swing',
  crypto_swing: 'Crypto',
  value: 'Value',
  position: 'Position',
  event: 'Event',
  mean_reversion: 'Mean Reversion',
};

const GROUP_ORDER: TradingStyleLabel[] = [
  'Intraday',
  'Swing',
  'Mean Reversion',
  'Event',
  'Value',
  'Position',
  'Crypto',
];

function getTradingStyleLabel(strategyType?: string, tradingStyle?: string): TradingStyleLabel {
  if (strategyType && STRATEGY_TYPE_MAP[strategyType]) return STRATEGY_TYPE_MAP[strategyType];
  if (!tradingStyle) return 'Swing';
  const lower = tradingStyle.toLowerCase();
  if (lower.includes('intraday') || lower.includes('scalp')) return 'Intraday';
  if (lower.includes('position')) return 'Position';
  if (lower.includes('event')) return 'Event';
  if (lower.includes('mean') || lower.includes('reversion')) return 'Mean Reversion';
  return 'Swing';
}

const STYLE_COLORS: Record<TradingStyleLabel, string> = {
  'Intraday': 'text-accent-alert bg-accent-alert/12 border-accent-alert/30',
  'Swing': 'text-accent-signal bg-accent-signal/12 border-accent-signal/30',
  'Position': 'text-accent-electric bg-accent-electric/12 border-accent-electric/30',
  'Event': 'text-accent-profit bg-accent-profit/12 border-accent-profit/30',
  'Mean Reversion': 'text-accent-alert bg-accent-alert/12 border-accent-alert/30',
  'Value': 'text-accent-electric bg-accent-electric/12 border-accent-electric/30',
  'Crypto': 'text-accent-profit bg-accent-profit/12 border-accent-profit/30',
};

const GROUP_DESCRIPTIONS: Record<TradingStyleLabel, string> = {
  'Intraday': '15-min to 3-hour holds — fast momentum, VWAP, and opening range setups',
  'Swing': '2-day to 4-week holds — trend following, breakouts, and EMA crossovers',
  'Mean Reversion': '3-7 day holds — oversold bounces with quality filters',
  'Event': '1-5 day holds — earnings catalysts and analyst-driven setups',
  'Value': '2-8 week holds — undervalued accumulation with insider buying',
  'Position': '2-8 week holds — longer-term accumulation at discount',
  'Crypto': '15-min to 14-day holds — momentum and on-chain driven crypto setups',
};

function groupAndSort(items: StrategyConfig[]): Map<TradingStyleLabel, StrategyConfig[]> {
  const groups = new Map<TradingStyleLabel, StrategyConfig[]>();

  for (const item of items) {
    const label = getTradingStyleLabel(item.strategy_type, item.trading_style);
    const list = groups.get(label) ?? [];
    list.push(item);
    groups.set(label, list);
  }

  for (const [, list] of groups) {
    list.sort((a, b) => {
      if (a.recommended && !b.recommended) return -1;
      if (!a.recommended && b.recommended) return 1;
      return a.name.localeCompare(b.name);
    });
  }

  const ordered = new Map<TradingStyleLabel, StrategyConfig[]>();
  for (const label of GROUP_ORDER) {
    const list = groups.get(label);
    if (list?.length) ordered.set(label, list);
  }
  return ordered;
}

function StrategyCard({ strategy, index }: { strategy: StrategyConfig; index: number }) {
  const label = getTradingStyleLabel(strategy.strategy_type, strategy.trading_style);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.04, ease: 'easeOut' }}
      className={`bg-bg-asphalt border rounded-lg p-5 transition-colors ${strategy.recommended ? 'border-accent-alert/40 hover:border-accent-alert/60' : 'border-border-gutter hover:border-border-strong'}`}
    >
      <div className="flex items-center gap-2 mb-2">
        <h3 className="text-lg font-display font-bold text-text-primary">{strategy.name}</h3>
        <span className={`px-2 py-0.5 rounded text-[10px] font-display font-bold uppercase tracking-wider border ${STYLE_COLORS[label]}`}>
          {label}
        </span>
        {strategy.recommended && (
          <Star className="w-3.5 h-3.5 text-accent-alert fill-accent-alert shrink-0" />
        )}
      </div>
      <p className="text-sm text-text-secondary mb-4 h-10 line-clamp-2 font-body">{strategy.description}</p>
      <div className="flex flex-wrap gap-2 text-xs">
        <span className="bg-bg-concrete px-2 py-1 rounded text-text-secondary border border-border-subtle font-display">Max Tickers: {strategy.max_tickers}</span>
        <span className="bg-bg-concrete px-2 py-1 rounded capitalize text-text-secondary border border-border-subtle font-body">Constraint: {strategy.constraint_style}</span>
        <span className="bg-bg-concrete px-2 py-1 rounded text-text-secondary border border-border-subtle font-display">
          Charts: {[...new Set([strategy.chart_timeframe, ...(strategy.additional_timeframes ?? []), ...(strategy.short_timeframes ?? [])])].join(' / ')}
        </span>
      </div>
    </motion.div>
  );
}

function StrategyGroup({ label, items }: { label: TradingStyleLabel; items: StrategyConfig[] }) {
  return (
    <div className="mb-8">
      <div className="flex items-baseline gap-3 mb-3">
        <h3 className="text-lg font-display font-bold text-text-primary">{label}</h3>
        <span className="text-xs text-text-muted font-body">{GROUP_DESCRIPTIONS[label]}</span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((item, i) => (
          <StrategyCard key={item.id} strategy={item} index={i} />
        ))}
      </div>
    </div>
  );
}

export function StrategiesView() {
  const { templates, strategies, isLoading } = useStrategies();

  const groupedTemplates = useMemo(() => groupAndSort(templates), [templates]);
  const groupedStrategies = useMemo(() => groupAndSort(strategies), [strategies]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted">
        <Loader2 className="w-8 h-8 animate-spin text-accent-signal" />
      </div>
    );
  }

  return (
    <div className="p-6 h-full overflow-y-auto">
      <h1 className="text-2xl font-display font-bold mb-6">Strategies</h1>

      <section className="mb-12">
        <h2 className="text-xl font-semibold mb-6 text-text-secondary font-body">Templates</h2>
        {templates.length === 0 ? (
          <p className="text-text-muted">No templates available.</p>
        ) : (
          [...groupedTemplates.entries()].map(([label, items]) => (
            <StrategyGroup key={label} label={label} items={items} />
          ))
        )}
      </section>

      <section>
        <h2 className="text-xl font-semibold mb-6 text-text-secondary font-body">My Strategies</h2>
        {strategies.length === 0 ? (
          <p className="text-text-muted font-body">Create a strategy from a template.</p>
        ) : (
          [...groupedStrategies.entries()].map(([label, items]) => (
            <StrategyGroup key={label} label={label} items={items} />
          ))
        )}
      </section>
    </div>
  );
}
