import type { FundamentalData } from '../../types';
import { AssetTypeBadge } from '../shared/AssetTypeBadge';
import clsx from 'clsx';
import { AlertTriangle } from 'lucide-react';

interface TickerCardProps {
  data: FundamentalData;
  isSelected: boolean;
  onClick: () => void;
}

export function TickerCard({ data, isSelected, onClick }: TickerCardProps) {
  return (
    <div
      onClick={onClick}
      className={clsx(
        "relative p-3.5 border rounded-lg cursor-pointer transition-all duration-200",
        isSelected
          ? "bg-bg-steel border-accent-signal shadow-[0_0_12px_rgba(77,141,255,0.1)]"
          : "bg-bg-concrete border-border-gutter hover:border-border-strong hover:bg-bg-steel/50"
      )}
    >
      {isSelected && (
        <span className="absolute left-0 top-2 bottom-2 w-0.5 rounded-r bg-accent-signal" />
      )}
      <div className="flex justify-between items-start mb-2">
        <div>
          <h3 className="text-lg font-display font-bold text-text-primary">{data.ticker}</h3>
          <p className="text-xs text-text-secondary truncate w-36" title={data.company_name}>
            {data.company_name}
          </p>
        </div>
        <AssetTypeBadge type={data.asset_type} />
      </div>

      <div className="text-xs text-text-muted mb-2">
        {data.sector}
      </div>

      {data.key_highlights.length > 0 && (
        <div className="text-sm text-text-secondary mb-2 line-clamp-2">
          {data.key_highlights[0]}
        </div>
      )}

      {data.risk_factors.length > 0 && (
        <div className="flex items-center gap-1 text-xs text-accent-loss mt-auto">
          <AlertTriangle className="w-3 h-3" />
          <span>{data.risk_factors.length} risk factors</span>
        </div>
      )}
    </div>
  );
}
