import { useStrategies } from '../hooks/useStrategies';
import { Loader2 } from 'lucide-react';
import { motion } from 'motion/react';

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
                className="bg-bg-asphalt border border-border-gutter rounded-lg p-5 hover:border-border-strong transition-colors"
              >
                <h3 className="text-lg font-display font-bold text-text-primary mb-2">{template.name}</h3>
                <p className="text-sm text-text-secondary mb-4 h-10 line-clamp-2 font-body">{template.description}</p>
                <div className="flex flex-wrap gap-2 text-xs">
                  <span className="bg-bg-concrete px-2 py-1 rounded text-text-muted border border-border-subtle font-display">Max Tickers: {template.max_tickers}</span>
                  <span className="bg-bg-concrete px-2 py-1 rounded capitalize text-text-muted border border-border-subtle font-body">Constraint: {template.constraint_style}</span>
                  <span className="bg-bg-concrete px-2 py-1 rounded text-text-muted border border-border-subtle font-display">
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
                className="bg-bg-asphalt border border-border-gutter rounded-lg p-5 hover:border-border-strong transition-colors"
              >
                <h3 className="text-lg font-display font-bold text-text-primary mb-2">{strategy.name}</h3>
                <p className="text-sm text-text-secondary mb-4 h-10 line-clamp-2 font-body">{strategy.description}</p>
                <div className="flex flex-wrap gap-2 text-xs">
                  <span className="bg-bg-concrete px-2 py-1 rounded text-text-muted border border-border-subtle font-display">Max Tickers: {strategy.max_tickers}</span>
                  <span className="bg-bg-concrete px-2 py-1 rounded capitalize text-text-muted border border-border-subtle font-body">Constraint: {strategy.constraint_style}</span>
                  <span className="bg-bg-concrete px-2 py-1 rounded text-text-muted border border-border-subtle font-display">
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
