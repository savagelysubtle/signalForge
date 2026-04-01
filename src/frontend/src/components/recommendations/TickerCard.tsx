import type { FundamentalData } from '../../types';
import { AssetTypeBadge } from '../shared/AssetTypeBadge';
import clsx from 'clsx';
import { AlertTriangle } from 'lucide-react';

const ACTION_PILL: Record<string, { text: string; bg: string; border: string; text_color: string }> = {
  BUY:   { text: 'BUY',   bg: 'bg-accent-profit/20',  border: 'border-accent-profit/35',  text_color: 'text-accent-profit'  },
  SHORT: { text: 'SHORT', bg: 'bg-accent-loss/20',    border: 'border-accent-loss/35',    text_color: 'text-accent-loss'    },
  HOLD:  { text: 'HOLD',  bg: 'bg-accent-alert/20',   border: 'border-accent-alert/35',   text_color: 'text-accent-alert'   },
};

interface TickerCardProps {
  data: FundamentalData;
  action?: string;
  isSelected: boolean;
  onClick: () => void;
  onRiskClick?: () => void;
}

export function TickerCard({ data, action, isSelected, onClick, onRiskClick }: TickerCardProps) {
  const pill = action ? ACTION_PILL[action] : null;

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
        <div className="flex flex-col items-end gap-1">
          <AssetTypeBadge type={data.asset_type} />
          {pill && (
            <span className={clsx(
              'text-[10px] font-display font-bold px-1.5 py-0.5 rounded border uppercase tracking-wider',
              pill.bg, pill.border, pill.text_color,
            )}>
              {pill.text}
            </span>
          )}
        </div>
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
        <button
          onClick={e => {
            e.stopPropagation();
            onClick();
            onRiskClick?.();
          }}
          className="flex items-center gap-1 text-xs text-accent-loss mt-auto hover:text-accent-loss/70 transition-colors"
          title="View risk factors"
        >
          <AlertTriangle className="w-3 h-3" />
          <span>{data.risk_factors.length} risk {data.risk_factors.length === 1 ? 'factor' : 'factors'}</span>
        </button>
      )}
    </div>
  );
}
