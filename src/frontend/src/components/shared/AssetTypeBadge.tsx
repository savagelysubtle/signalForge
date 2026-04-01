import clsx from 'clsx';

interface AssetTypeBadgeProps {
  type: 'stock' | 'etf' | 'crypto';
}

export function AssetTypeBadge({ type }: AssetTypeBadgeProps) {
  const styles = {
    stock: 'bg-accent-signal-dim text-accent-signal border-accent-signal/20',
    etf: 'bg-accent-profit-dim text-accent-profit border-accent-profit/20',
    crypto: 'bg-accent-alert-dim text-accent-alert border-accent-alert/20',
  };

  return (
    <span className={clsx(
      "px-2 py-0.5 text-xs font-display font-medium rounded border uppercase tracking-wider",
      styles[type]
    )}>
      {type}
    </span>
  );
}
