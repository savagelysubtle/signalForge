import { useStrategies } from '../hooks/useStrategies';
import { Loader2, Star } from 'lucide-react';
import { motion } from 'motion/react';

type TradingStyleLabel = 'Intraday' | 'Swing Trade' | 'Position' | 'Event-Driven';

function getTradingStyleLabel(tradingStyle: string | undefined): TradingStyleLabel {
  if (!tradingStyle) return 'Swing Trade';
  const lower = tradingStyle.toLowerCase();
  if (lower.includes('intraday') || lower.includes('scalp')) return 'Intraday';
  if (lower.includes('position')) return 'Position';
  if (lower.includes('event')) return 'Event-Driven';
  return 'Swing Trade';
}

const STYLE_COLORS: Record<TradingStyleLabel, string> = {
  'Intraday': 'text-accent-alert bg-accent-alert/12 border-accent-alert/30',
  'Swing Trade': 'text-accent-signal bg-accent-signal/12 border-accent-signal/30',
  'Position': 'text-accent-electric bg-accent-electric/12 border-accent-electric/30',
  'Event-Driven': 'text-accent-profit bg-accent-profit/12 border-accent-profit/30',
};

export function StrategiesView() {
  const { templates, strategies, isLoading } = useStrategies();

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
        <h2 className="text-xl font-semibold mb-4 text-text-secondary font-body">Templates</h2>
        {templates.length === 0 ? (
          <p className="text-text-muted">No templates available.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {templates.map((template, i) => (
              <motion.div
                key={template.id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: i * 0.05, ease: 'easeOut' }}
                className={`bg-bg-asphalt border rounded-lg p-5 transition-colors ${template.recommended ? 'border-accent-alert/40 hover:border-accent-alert/60' : 'border-border-gutter hover:border-border-strong'}`}
              >
                <div className="flex items-center gap-2 mb-2">
                  <h3 className="text-lg font-display font-bold text-text-primary">{template.name}</h3>
                  {(() => {
                    const label = getTradingStyleLabel(template.trading_style);
                    return (
                      <span className={`px-2 py-0.5 rounded text-[10px] font-display font-bold uppercase tracking-wider border ${STYLE_COLORS[label]}`}>
                        {label}
                      </span>
                    );
                  })()}
                  {template.recommended && (
                    <Star className="w-3.5 h-3.5 text-accent-alert fill-accent-alert shrink-0" />
                  )}
                </div>
                <p className="text-sm text-text-secondary mb-4 h-10 line-clamp-2 font-body">{template.description}</p>
                <div className="flex flex-wrap gap-2 text-xs">
                  <span className="bg-bg-concrete px-2 py-1 rounded text-text-secondary border border-border-subtle font-display">Max Tickers: {template.max_tickers}</span>
                  <span className="bg-bg-concrete px-2 py-1 rounded capitalize text-text-secondary border border-border-subtle font-body">Constraint: {template.constraint_style}</span>
                  <span className="bg-bg-concrete px-2 py-1 rounded text-text-secondary border border-border-subtle font-display">
                    Charts: {[...new Set([template.chart_timeframe, ...(template.additional_timeframes ?? []), ...(template.short_timeframes ?? [])])].join(' / ')}
                  </span>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-xl font-semibold mb-4 text-text-secondary font-body">My Strategies</h2>
        {strategies.length === 0 ? (
          <p className="text-text-muted font-body">Create a strategy from a template.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {strategies.map((strategy, i) => (
              <motion.div
                key={strategy.id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: i * 0.05, ease: 'easeOut' }}
                className={`bg-bg-asphalt border rounded-lg p-5 transition-colors ${strategy.recommended ? 'border-accent-alert/40 hover:border-accent-alert/60' : 'border-border-gutter hover:border-border-strong'}`}
              >
                <div className="flex items-center gap-2 mb-2">
                  <h3 className="text-lg font-display font-bold text-text-primary">{strategy.name}</h3>
                  {(() => {
                    const label = getTradingStyleLabel(strategy.trading_style);
                    return (
                      <span className={`px-2 py-0.5 rounded text-[10px] font-display font-bold uppercase tracking-wider border ${STYLE_COLORS[label]}`}>
                        {label}
                      </span>
                    );
                  })()}
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
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
