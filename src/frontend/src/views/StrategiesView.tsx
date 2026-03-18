import { useStrategies } from '../hooks/useStrategies';
import { Loader2 } from 'lucide-react';

export function StrategiesView() {
  const { templates, strategies, isLoading } = useStrategies();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-text-secondary">
        <Loader2 className="w-8 h-8 animate-spin text-accent-blue" />
      </div>
    );
  }

  return (
    <div className="p-6 h-full overflow-y-auto">
      <h1 className="text-2xl font-bold mb-6">Strategies</h1>
      
      <section className="mb-12">
        <h2 className="text-xl font-semibold mb-4 text-text-secondary">Templates</h2>
        {templates.length === 0 ? (
          <p className="text-text-secondary">No templates available.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {templates.map(template => (
              <div key={template.id} className="bg-bg-secondary border border-border rounded-lg p-5 hover:border-text-secondary transition-colors">
                <h3 className="text-lg font-bold text-text-primary mb-2">{template.name}</h3>
                <p className="text-sm text-text-secondary mb-4 h-10 line-clamp-2">{template.description}</p>
                <div className="flex flex-wrap gap-2 text-xs">
                  <span className="bg-bg-tertiary px-2 py-1 rounded">Max Tickers: {template.max_tickers}</span>
                  <span className="bg-bg-tertiary px-2 py-1 rounded capitalize">Constraint: {template.constraint_style}</span>
                  <span className="bg-bg-tertiary px-2 py-1 rounded">Timeframe: {template.chart_timeframe}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-xl font-semibold mb-4 text-text-secondary">My Strategies</h2>
        {strategies.length === 0 ? (
          <p className="text-text-secondary">Create a strategy from a template.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {strategies.map(strategy => (
              <div key={strategy.id} className="bg-bg-secondary border border-border rounded-lg p-5 hover:border-text-secondary transition-colors">
                <h3 className="text-lg font-bold text-text-primary mb-2">{strategy.name}</h3>
                <p className="text-sm text-text-secondary mb-4 h-10 line-clamp-2">{strategy.description}</p>
                <div className="flex flex-wrap gap-2 text-xs">
                  <span className="bg-bg-tertiary px-2 py-1 rounded">Max Tickers: {strategy.max_tickers}</span>
                  <span className="bg-bg-tertiary px-2 py-1 rounded capitalize">Constraint: {strategy.constraint_style}</span>
                  <span className="bg-bg-tertiary px-2 py-1 rounded">Timeframe: {strategy.chart_timeframe}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
