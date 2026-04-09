import { ExternalLink } from 'lucide-react';

import type { FundamentalData } from '../../types';

interface OverviewTabProps {
  data: FundamentalData;
}

export function OverviewTab({ data }: OverviewTabProps) {
  const formatValue = (val: string | number | null) => {
    if (val === null || val === undefined) return 'N/A';
    return val;
  };

  const hasPriceRow = data.price != null || data.price_change_pct != null;
  const has52WeekRange = data.week_52_low != null && data.week_52_high != null;
  const hasRvol = data.relative_volume != null;
  const hasMarketDataSection = hasPriceRow || has52WeekRange || hasRvol;

  const changePctClass =
    data.price_change_pct == null
      ? ''
      : data.price_change_pct > 0
        ? 'text-[var(--accent-profit)]'
        : data.price_change_pct < 0
          ? 'text-[var(--accent-loss)]'
          : 'text-text-secondary';

  return (
    <div className="p-6 overflow-y-auto h-full">
      {hasMarketDataSection && (
        <div className="bg-bg-concrete rounded-lg border border-border-gutter p-6 mb-8">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2 font-body">
            <span className="w-2 h-2 rounded-full bg-accent-signal"></span>
            Market Data
          </h3>
          <div className="flex flex-col gap-4">
            {hasPriceRow && (
              <div className="flex flex-wrap items-baseline gap-3">
                {data.price != null && (
                  <span className="text-2xl font-semibold font-mono tabular-nums text-text-primary">
                    ${data.price.toFixed(2)}
                  </span>
                )}
                {data.price_change_pct != null && (
                  <span className={`text-lg font-mono tabular-nums ${changePctClass}`}>
                    {data.price_change_pct > 0 ? '+' : ''}
                    {data.price_change_pct.toFixed(2)}%
                  </span>
                )}
              </div>
            )}
            {has52WeekRange && (
              <div>
                <div className="text-xs text-text-muted mb-1 font-body">52-week range</div>
                <div className="text-sm font-mono tabular-nums text-text-primary">
                  ${data.week_52_low!.toFixed(2)} - ${data.week_52_high!.toFixed(2)}
                </div>
              </div>
            )}
            {hasRvol && (
              <div>
                <div className="text-xs text-text-muted mb-1 font-body">Volume</div>
                <div className="text-sm font-mono tabular-nums text-text-primary">
                  RVOL {data.relative_volume!.toFixed(1)}x
                </div>
              </div>
            )}
          </div>
        </div>
      )}

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

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
        <div className="bg-bg-concrete rounded-lg border border-border-gutter p-6">
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

        <div id="risk-factors" className="bg-bg-concrete rounded-lg border border-border-gutter p-6">
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

      {(data.sources.length > 0 || data.news_urls.some((u) => u.trim())) && (
        <div className="bg-bg-concrete rounded-lg border border-border-gutter p-6">
          <h4 className="text-sm font-semibold text-text-secondary mb-3 font-body">Sources</h4>
          <div className="flex flex-col gap-4">
            {data.sources.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {data.sources.map((source, i) => (
                  <span
                    key={i}
                    className="text-xs bg-bg-void px-2 py-1 rounded text-text-secondary border border-border-subtle"
                  >
                    {source}
                  </span>
                ))}
              </div>
            )}
            {data.news_urls.filter((u) => u.trim()).length > 0 && (
              <div className="flex flex-col gap-2">
                <span className="text-xs text-text-muted font-body">News links</span>
                <div className="flex flex-col gap-2">
                  {data.news_urls
                    .filter((u) => u.trim())
                    .map((url, i) => (
                      <a
                        key={`${url}-${i}`}
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="group inline-flex items-center gap-2 text-sm font-mono text-accent-signal hover:text-accent-signal/90 break-all"
                      >
                        <ExternalLink className="w-3.5 h-3.5 shrink-0 text-accent-signal opacity-80 group-hover:opacity-100" />
                        <span className="underline-offset-2 group-hover:underline">{url}</span>
                      </a>
                    ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
