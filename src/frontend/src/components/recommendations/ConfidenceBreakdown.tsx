import clsx from 'clsx';
import type { ConfidenceBreakdown as ConfidenceBreakdownScores } from '../../types';

export interface ConfidenceBreakdownProps {
  breakdown: ConfidenceBreakdownScores | null;
  className?: string;
}

const SEGMENTS: {
  key: keyof Pick<
    ConfidenceBreakdownScores,
    'track_agreement' | 'technical_strength' | 'trend_alignment' | 'historical_pattern' | 'regime_fit'
  >;
  label: string;
  max: number;
  colorVar: string;
}[] = [
  { key: 'track_agreement', label: 'Track Agreement', max: 0.3, colorVar: 'var(--accent-signal)' },
  { key: 'technical_strength', label: 'Technical Strength', max: 0.2, colorVar: 'var(--accent-profit)' },
  { key: 'trend_alignment', label: 'Trend Alignment', max: 0.2, colorVar: 'var(--accent-electric)' },
  { key: 'historical_pattern', label: 'Historical Pattern', max: 0.2, colorVar: 'var(--accent-alert)' },
  { key: 'regime_fit', label: 'Regime Fit', max: 0.1, colorVar: 'var(--text-secondary)' },
];

export function ConfidenceBreakdown({ breakdown, className }: ConfidenceBreakdownProps) {
  if (!breakdown) return null;

  const values = SEGMENTS.map(s => breakdown[s.key] as number);
  const sum = values.reduce((a, b) => a + b, 0);

  return (
    <div className={clsx('space-y-3', className)}>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-bg-void">
        {sum > 0 ? (
          SEGMENTS.map(s => {
            const v = breakdown[s.key] as number;
            const pct = (v / sum) * 100;
            if (pct <= 0) return null;
            return (
              <div
                key={s.key}
                className="min-w-px h-full"
                style={{ width: `${pct}%`, backgroundColor: s.colorVar }}
                title={`${s.label}: ${v.toFixed(2)}`}
              />
            );
          })
        ) : (
          <div className="h-full w-full bg-bg-steel/50" />
        )}
      </div>

      <div className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
        {SEGMENTS.map(s => {
          const v = breakdown[s.key] as number;
          return (
            <div key={s.key} className="flex items-center gap-2 min-w-0">
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: s.colorVar }}
                aria-hidden
              />
              <span className="truncate text-[11px] text-text-muted font-body">{s.label}</span>
              <span className="ml-auto shrink-0 font-mono text-[11px] tabular-nums text-text-secondary">
                {v.toFixed(2)} / {s.max.toFixed(2)}
              </span>
            </div>
          );
        })}
      </div>

      {breakdown.penalties_applied.length > 0 && (
        <ul className="space-y-1 pt-1">
          {breakdown.penalties_applied.map((p, i) => (
            <li key={i} className="font-body text-[11px] text-accent-loss">
              - {p}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
