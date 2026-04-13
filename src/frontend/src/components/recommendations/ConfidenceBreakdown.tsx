import clsx from 'clsx';
import type { ConfidenceBreakdown as ConfidenceBreakdownModel, Recommendation } from '../../types';

/** Merged view for v2 confidence UI — each field optional; rows render only when set */
export type ConfidenceBreakdownView = {
  setup_type?: string | null;
  prior_base_rate?: number | null;
  setup_quality_score?: number | null;
  ml_agreement: ConfidenceBreakdownModel['ml_agreement'];
  llm_conviction: ConfidenceBreakdownModel['llm_conviction'];
  win_probability?: number | null;
  confidence_drivers: string[];
  penalties_applied: string[];
};

export function buildConfidenceBreakdownView(rec: Recommendation): ConfidenceBreakdownView | null {
  const b = rec.confidence_breakdown;
  const drivers =
    b && b.confidence_drivers.length > 0 ? b.confidence_drivers : rec.confidence_drivers ?? [];
  const penalties = b?.penalties_applied ?? [];

  const prior = b?.prior_base_rate ?? rec.prior_base_rate;
  const sq = b?.setup_quality_score ?? rec.setup_quality_score;
  const ml = b?.ml_agreement ?? 'unavailable';
  const llm = b?.llm_conviction ?? rec.llm_conviction;
  const win = b?.win_probability ?? rec.win_probability ?? rec.confidence_v2;
  const setupType = rec.setup_type;

  const hasV2 =
    b != null ||
    prior != null ||
    sq != null ||
    llm != null ||
    win != null ||
    drivers.length > 0 ||
    penalties.length > 0 ||
    setupType != null ||
    rec.confidence_v2 != null;

  if (!hasV2) return null;

  return {
    setup_type: setupType,
    prior_base_rate: prior,
    setup_quality_score: sq,
    ml_agreement: ml,
    llm_conviction: llm,
    win_probability: win,
    confidence_drivers: drivers,
    penalties_applied: penalties,
  };
}

export interface ConfidenceBreakdownProps {
  view: ConfidenceBreakdownView;
  className?: string;
}

function mlAgreementStyle(
  v: ConfidenceBreakdownModel['ml_agreement'],
): { dot: string; text: string } {
  switch (v) {
    case 'agree':
      return { dot: 'bg-[var(--accent-profit)]', text: 'text-[var(--accent-profit)]' };
    case 'disagree':
      return { dot: 'bg-[var(--accent-loss)]', text: 'text-[var(--accent-loss)]' };
    case 'neutral':
    case 'unavailable':
    default:
      return { dot: 'bg-[var(--text-secondary)]', text: 'text-[var(--text-secondary)]' };
  }
}

function mlAgreementLabel(v: ConfidenceBreakdownModel['ml_agreement']): string {
  switch (v) {
    case 'agree':
      return 'Agree';
    case 'disagree':
      return 'Disagree';
    case 'neutral':
      return 'Neutral';
    case 'unavailable':
      return 'Unavailable';
    default:
      return String(v);
  }
}

function convictionBadgeClasses(
  v: NonNullable<ConfidenceBreakdownModel['llm_conviction']>,
): string {
  switch (v) {
    case 'high':
      return 'border-[var(--accent-profit)]/50 bg-[rgba(0,229,155,0.12)] text-[var(--accent-profit)]';
    case 'medium':
      return 'border-[var(--accent-alert)]/50 bg-[rgba(255,178,36,0.12)] text-[var(--accent-alert)]';
    case 'low':
      return 'border-[var(--text-secondary)]/50 bg-bg-void text-[var(--text-secondary)]';
    default:
      return 'border-border-gutter bg-bg-void text-text-muted';
  }
}

function driverChipClass(text: string): string {
  const t = text.trim();
  if (t.startsWith('+') || t.startsWith('(+')) {
    return 'border-[var(--accent-profit)]/35 bg-[rgba(0,229,155,0.08)] text-[var(--accent-profit)]';
  }
  if (t.startsWith('-') || t.startsWith('(-') || t.startsWith('−')) {
    return 'border-[var(--accent-loss)]/35 bg-[rgba(255,59,92,0.08)] text-[var(--accent-loss)]';
  }
  return 'border-border-gutter bg-bg-void text-[var(--text-secondary)]';
}

/** Confidence engine v2 breakdown — Urban Finance tokens; Satoshi labels, JetBrains Mono numbers */
export function ConfidenceBreakdown({ view, className }: ConfidenceBreakdownProps) {
  const ml = mlAgreementStyle(view.ml_agreement);

  const showPrior = view.prior_base_rate != null;
  const showSetupQ = view.setup_quality_score != null;
  const showWin = view.win_probability != null;

  return (
    <div className={clsx('space-y-4', className)}>
      {view.setup_type != null && view.setup_type !== '' && (
        <div className="text-[11px] text-[var(--text-secondary)] font-body">
          <span className="text-text-muted">Setup type </span>
          <span className="font-medium text-text-primary">{view.setup_type}</span>
        </div>
      )}

      {(showPrior || showSetupQ) && (
        <div className="grid gap-3 sm:grid-cols-2">
          {showPrior && (
            <div className="rounded-lg border border-border-gutter bg-bg-void/80 px-3 py-2.5">
              <div className="text-[11px] font-medium text-[var(--text-secondary)] font-body tracking-wide">
                Prior base rate
              </div>
              <div className="mt-0.5 font-mono text-lg tabular-nums text-text-primary">
                {((view.prior_base_rate as number) * 100).toFixed(1)}%
              </div>
              <div className="mt-0.5 text-[10px] text-[var(--text-secondary)] font-body">
                Starting probability
              </div>
            </div>
          )}
          {showSetupQ && (
            <div className="rounded-lg border border-border-gutter bg-bg-void/80 px-3 py-2.5">
              <div className="text-[11px] font-medium text-[var(--text-secondary)] font-body tracking-wide">
                Setup quality
              </div>
              <div className="mt-0.5 flex items-baseline gap-2">
                <span
                  className={clsx(
                    'inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-sm tabular-nums font-semibold',
                    (view.setup_quality_score as number) >= 0
                      ? 'border-[var(--accent-profit)]/40 bg-[rgba(0,229,155,0.1)] text-[var(--accent-profit)]'
                      : 'border-[var(--accent-loss)]/40 bg-[rgba(255,59,92,0.1)] text-[var(--accent-loss)]',
                  )}
                >
                  {(view.setup_quality_score as number) >= 0 ? '+' : ''}
                  {((view.setup_quality_score as number) * 100).toFixed(1)} pts
                </span>
              </div>
              <div className="mt-0.5 text-[10px] text-[var(--text-secondary)] font-body">
                Net booster effect (−15 to +15)
              </div>
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className={clsx('h-2 w-2 shrink-0 rounded-full', ml.dot)} aria-hidden />
          <span className="text-[11px] text-[var(--text-secondary)] font-body">ML agreement</span>
          <span className={clsx('text-xs font-semibold uppercase tracking-wide font-body', ml.text)}>
            {mlAgreementLabel(view.ml_agreement)}
          </span>
        </div>
        {view.llm_conviction != null && (
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-[var(--text-secondary)] font-body">LLM conviction</span>
            <span
              className={clsx(
                'rounded-md border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide font-body',
                convictionBadgeClasses(view.llm_conviction),
              )}
            >
              {view.llm_conviction}
            </span>
          </div>
        )}
      </div>

      {view.confidence_drivers.length > 0 && (
        <div>
          <div className="mb-1.5 text-[11px] font-medium text-[var(--text-secondary)] font-body">
            Drivers
          </div>
          <div className="flex flex-wrap gap-1.5">
            {view.confidence_drivers.map((d, i) => (
              <span
                key={i}
                className={clsx(
                  'rounded-md border px-2 py-1 text-[11px] font-body leading-tight',
                  driverChipClass(d),
                )}
              >
                {d}
              </span>
            ))}
          </div>
        </div>
      )}

      {showWin && (
        <div className="rounded-lg border border-border-gutter/80 bg-bg-void/60 px-3 py-3">
          <div className="text-[11px] font-medium text-[var(--text-secondary)] font-body">
            Win probability
          </div>
          <div className="mt-1 font-mono text-2xl tabular-nums font-semibold text-text-primary">
            {((view.win_probability as number) * 100).toFixed(1)}%
          </div>
          <div className="mt-0.5 text-[10px] text-[var(--text-secondary)] font-body">
            Final calibrated probability
          </div>
        </div>
      )}

      {view.penalties_applied.length > 0 && (
        <ul className="space-y-1 border-t border-border-gutter pt-3">
          <li className="text-[11px] font-medium text-[var(--accent-loss)] font-body mb-1">Penalties</li>
          {view.penalties_applied.map((p, i) => (
            <li
              key={i}
              className="flex items-start gap-2 text-[11px] text-[var(--accent-loss)] font-body"
            >
              <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[var(--accent-loss)]" />
              {p}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
