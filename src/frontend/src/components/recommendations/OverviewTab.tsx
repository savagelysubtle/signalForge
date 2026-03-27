import type { FundamentalData } from '../../types';

interface OverviewTabProps {
  data: FundamentalData;
}

export function OverviewTab({ data }: OverviewTabProps) {
  const formatValue = (val: string | number | null) => {
    if (val === null || val === undefined) return 'N/A';
    return val;
  };

  return (
    <div className="p-6 overflow-y-auto h-full">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <div className="bg-bg-concrete p-4 rounded-lg border border-border-gutter">
          <div className="text-xs text-text-muted mb-1 font-body">Market Cap</div>
          <div className="text-lg font-display font-semibold">{formatValue(data.market_cap)}</div>
        </div>
        <div className="bg-bg-concrete p-4 rounded-lg border border-border-gutter">
          <div className="text-xs text-text-muted mb-1 font-body">P/E Ratio</div>
          <div className="text-lg font-display font-semibold">{formatValue(data.pe_ratio)}</div>
        </div>
        <div className="bg-bg-concrete p-4 rounded-lg border border-border-gutter">
          <div className="text-xs text-text-muted mb-1 font-body">Revenue Growth</div>
          <div className="text-lg font-display font-semibold">{formatValue(data.revenue_growth)}</div>
        </div>
        <div className="bg-bg-concrete p-4 rounded-lg border border-border-gutter">
          <div className="text-xs text-text-muted mb-1 font-body">Free Cash Flow</div>
          <div className="text-lg font-display font-semibold">{formatValue(data.free_cash_flow)}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-8">
        <div>
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2 font-body">
            <span className="w-2 h-2 rounded-full bg-accent-profit"></span>
            Key Highlights
          </h3>
          <ul className="space-y-3">
            {data.key_highlights.length > 0 ? (
              data.key_highlights.map((highlight, i) => (
                <li key={i} className="text-sm text-text-primary leading-relaxed">
                  {highlight}
                </li>
              ))
            ) : (
              <li className="text-sm text-text-muted">No highlights available.</li>
            )}
          </ul>
        </div>

        <div>
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2 font-body">
            <span className="w-2 h-2 rounded-full bg-accent-loss"></span>
            Risk Factors
          </h3>
          <ul className="space-y-3">
            {data.risk_factors.length > 0 ? (
              data.risk_factors.map((risk, i) => (
                <li key={i} className="text-sm text-text-primary leading-relaxed">
                  {risk}
                </li>
              ))
            ) : (
              <li className="text-sm text-text-muted">No risk factors identified.</li>
            )}
          </ul>
        </div>
      </div>

      {data.sources.length > 0 && (
        <div className="mt-8 pt-6 border-t border-border-gutter">
          <h4 className="text-sm font-semibold text-text-secondary mb-3 font-body">Sources</h4>
          <div className="flex flex-wrap gap-2">
            {data.sources.map((source, i) => (
              <span key={i} className="text-xs bg-bg-concrete px-2 py-1 rounded text-text-muted border border-border-subtle">
                {source}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
