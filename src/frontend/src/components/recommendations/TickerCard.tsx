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
        "p-4 border rounded-lg cursor-pointer transition-all",
        isSelected 
          ? "bg-bg-tertiary border-accent-blue" 
          : "bg-bg-secondary border-border hover:border-text-secondary hover:bg-bg-tertiary/50"
      )}
    >
      <div className="flex justify-between items-start mb-2">
        <div>
          <h3 className="text-xl font-bold text-text-primary">{data.ticker}</h3>
          <p className="text-sm text-text-secondary truncate w-32" title={data.company_name}>
            {data.company_name}
          </p>
        </div>
        <AssetTypeBadge type={data.asset_type} />
      </div>
      
      <div className="text-xs text-text-secondary mb-3">
        {data.sector}
      </div>

      {data.key_highlights.length > 0 && (
        <div className="text-sm text-text-primary mb-3 line-clamp-2">
          {data.key_highlights[0]}
        </div>
      )}

      {data.risk_factors.length > 0 && (
        <div className="flex items-center gap-1 text-xs text-accent-red mt-auto">
          <AlertTriangle className="w-3 h-3" />
          <span>{data.risk_factors.length} risk factors</span>
        </div>
      )}
    </div>
  );
}
