import clsx from 'clsx';

interface AssetTypeBadgeProps {
  type: 'stock' | 'etf' | 'crypto';
}

export function AssetTypeBadge({ type }: AssetTypeBadgeProps) {
  const styles = {
    stock: 'bg-accent-blue/10 text-accent-blue border-accent-blue/20',
    etf: 'bg-accent-green/10 text-accent-green border-accent-green/20',
    crypto: 'bg-accent-yellow/10 text-accent-yellow border-accent-yellow/20',
  };

  return (
    <span className={clsx(
      "px-2 py-0.5 text-xs font-medium rounded border uppercase tracking-wider",
      styles[type]
    )}>
      {type}
    </span>
  );
}
