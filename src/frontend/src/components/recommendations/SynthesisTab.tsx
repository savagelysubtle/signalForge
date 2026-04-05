import { useState, useEffect } from 'react';
import type { Recommendation, DebateCase, TrackAgreement, ConfidenceBreakdown, SignalStrength } from '../../types';
import { motion, AnimatePresence } from 'motion/react';
import { ShieldAlert, ChevronDown, ChevronUp, Ban, Eye, Gauge, Clock, AlertTriangle, BrainCircuit, ShieldOff } from 'lucide-react';
import clsx from 'clsx';

interface SynthesisTabProps {
  recommendation: Recommendation | null;
}

const ACTION_CONFIG: Record<string, { text: string; color: string; bg: string; border: string }> = {
  BUY:      { text: 'BUY',      color: 'text-accent-profit',   bg: 'bg-accent-profit/25',   border: 'border border-accent-profit/40'   },
  SHORT:    { text: 'SHORT',    color: 'text-accent-loss',     bg: 'bg-accent-loss/25',     border: 'border border-accent-loss/40'     },
  HOLD:     { text: 'HOLD',     color: 'text-accent-alert',    bg: 'bg-accent-alert/25',    border: 'border border-accent-alert/40'    },
  NO_TRADE: { text: 'NO TRADE', color: 'text-text-muted',      bg: 'bg-text-muted/25',      border: 'border border-text-muted/40'      },
  WATCH:    { text: 'WATCH',    color: 'text-accent-electric', bg: 'bg-accent-electric/25', border: 'border border-accent-electric/40' },
};

function confidenceBarColor(action: string): string {
  if (action === 'BUY') return 'bg-accent-profit';
  if (action === 'SHORT') return 'bg-accent-loss';
  if (action === 'NO_TRADE') return 'bg-text-muted';
  if (action === 'WATCH') return 'bg-accent-electric';
  return 'bg-accent-alert';
}

const DIRECTION_COLOR: Record<string, string> = {
  bullish: 'text-accent-profit',
  bearish: 'text-accent-loss',
  neutral: 'text-text-muted',
};

function agreementColor(score: number): string {
  if (score >= 0.9) return 'text-accent-profit';
  if (score >= 0.5) return 'text-accent-alert';
  return 'text-accent-loss';
}

function TrackAgreementPanel({ agreement }: { agreement: TrackAgreement }) {
  const tracks = [
    { label: 'Perplexity', direction: agreement.perplexity_direction },
    { label: 'Gemini', direction: agreement.gemini_direction },
    { label: 'Claude', direction: agreement.claude_direction },
  ];
  const scorePct = Math.round(agreement.agreement_score * 100);

  return (
    <div className="bg-bg-concrete rounded-lg border border-border-gutter p-6 mb-6">
      <h3 className="text-sm font-semibold text-text-secondary mb-3 font-body">Track Agreement</h3>
      <div className="grid grid-cols-3 gap-3 mb-4">
        {tracks.map(t => (
          <div key={t.label} className="bg-bg-void rounded-lg p-3 border border-border-gutter text-center">
            <div className="text-xs text-text-muted mb-1 font-body">{t.label}</div>
            <div className={clsx('text-sm font-display font-semibold capitalize', DIRECTION_COLOR[t.direction] ?? 'text-text-muted')}>
              {t.direction}
            </div>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-3 mb-3">
        <span className="text-xs text-text-muted font-body">Agreement</span>
        <div className="flex-1 h-2 bg-bg-void rounded-full overflow-hidden">
          <div
            className={clsx('h-full rounded-full transition-all', scorePct >= 80 ? 'bg-accent-profit' : scorePct >= 50 ? 'bg-accent-alert' : 'bg-accent-loss')}
            style={{ width: `${scorePct}%` }}
          />
        </div>
        <span className={clsx('text-sm font-display font-semibold tabular-nums', agreementColor(agreement.agreement_score))}>
          {scorePct}%
        </span>
      </div>
      {agreement.conflicts.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-accent-alert mb-1.5 font-body">Conflicts</h4>
          <ul className="space-y-1">
            {agreement.conflicts.map((c, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-accent-alert">
                <span className="mt-1 w-1.5 h-1.5 rounded-full shrink-0 bg-accent-alert" />
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

const SIGNAL_STRENGTH_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  strong:   { label: 'STRONG',   color: 'text-accent-profit',   bg: 'bg-accent-profit/15' },
  moderate: { label: 'MODERATE', color: 'text-accent-alert',    bg: 'bg-accent-alert/15' },
  weak:     { label: 'WEAK',     color: 'text-accent-loss',     bg: 'bg-accent-loss/15' },
  no_edge:  { label: 'NO EDGE',  color: 'text-text-muted',      bg: 'bg-text-muted/15' },
};

const BREAKDOWN_COMPONENTS: { key: keyof ConfidenceBreakdown; label: string; max: number }[] = [
  { key: 'track_agreement',    label: 'Track Agreement',    max: 0.30 },
  { key: 'technical_strength', label: 'Technical Strength', max: 0.20 },
  { key: 'trend_alignment',    label: 'Trend Alignment',    max: 0.20 },
  { key: 'historical_pattern', label: 'Historical Pattern', max: 0.20 },
  { key: 'regime_fit',         label: 'Regime Fit',         max: 0.10 },
];

function ConfidenceBreakdownPanel({ breakdown, rawConfidence, signalStrength }: {
  breakdown: ConfidenceBreakdown;
  rawConfidence: number | null;
  signalStrength: SignalStrength | null;
}) {
  const strengthCfg = signalStrength ? SIGNAL_STRENGTH_CONFIG[signalStrength] : null;

  return (
    <div className="bg-bg-concrete rounded-lg border border-border-gutter p-6 mb-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Gauge className="w-4 h-4 text-accent-signal" />
          <h3 className="text-sm font-semibold text-text-secondary font-body">Confidence Breakdown</h3>
        </div>
        {strengthCfg && (
          <span className={clsx('text-xs font-display font-semibold px-2.5 py-1 rounded', strengthCfg.bg, strengthCfg.color)}>
            {strengthCfg.label}
          </span>
        )}
      </div>

      {rawConfidence != null && (
        <div className="flex items-center gap-2 mb-4 text-xs text-text-muted font-body">
          <span>GPT raw: {Math.round(rawConfidence * 100)}%</span>
          <span className="text-text-muted/50">→</span>
          <span className="text-text-primary font-semibold">Calibrated: {Math.round(breakdown.total * 100)}%</span>
        </div>
      )}

      <div className="space-y-3 mb-4">
        {BREAKDOWN_COMPONENTS.map(({ key, label, max }) => {
          const value = breakdown[key] as number;
          const fillPct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
          return (
            <div key={key}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-text-muted font-body">{label}</span>
                <span className="text-xs font-display font-semibold text-text-secondary tabular-nums">
                  {value.toFixed(2)} / {max.toFixed(2)}
                </span>
              </div>
              <div className="h-1.5 bg-bg-void rounded-full overflow-hidden">
                <div
                  className={clsx(
                    'h-full rounded-full transition-all',
                    fillPct >= 70 ? 'bg-accent-profit' : fillPct >= 40 ? 'bg-accent-alert' : 'bg-accent-loss',
                  )}
                  style={{ width: `${fillPct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {breakdown.penalties_applied.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-accent-alert mb-1.5 font-body">Penalties Applied</h4>
          <ul className="space-y-1">
            {breakdown.penalties_applied.map((p, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-accent-alert">
                <span className="mt-1 w-1.5 h-1.5 rounded-full shrink-0 bg-accent-alert" />
                {p}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function mlProbColor(prob: number): string {
  if (prob >= 0.65) return 'text-accent-profit';
  if (prob >= 0.52) return 'text-accent-alert';
  return 'text-accent-loss';
}

function mlProbBarColor(prob: number): string {
  if (prob >= 0.65) return 'bg-accent-profit';
  if (prob >= 0.52) return 'bg-accent-alert';
  return 'bg-accent-loss';
}

function MLGatePanel({ rec }: { rec: Recommendation }) {
  if (rec.ml_probability == null) return null;

  const probPct = Math.round(rec.ml_probability * 100);
  const wasAdjusted = rec.raw_gpt_position_size_pct != null
    && rec.raw_gpt_position_size_pct !== rec.position_size_pct;
  const multPct = rec.ml_size_multiplier != null ? Math.round(rec.ml_size_multiplier * 100) : null;

  return (
    <div className="bg-bg-concrete rounded-lg border border-border-gutter p-6 mb-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <BrainCircuit className="w-4 h-4 text-accent-electric" />
          <h3 className="text-sm font-semibold text-text-secondary font-body">ML Gate</h3>
        </div>
        {rec.ml_model_version && (
          <span className="text-[11px] font-display text-text-muted bg-bg-void px-2 py-0.5 rounded">
            {rec.ml_model_version}
          </span>
        )}
      </div>

      {/* Probability bar */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs text-text-muted font-body">P(profitable)</span>
          <span className={clsx('text-lg font-display font-bold tabular-nums', mlProbColor(rec.ml_probability))}>
            {probPct}%
          </span>
        </div>
        <div className="h-2 bg-bg-void rounded-full overflow-hidden">
          <div
            className={clsx('h-full rounded-full transition-all', mlProbBarColor(rec.ml_probability))}
            style={{ width: `${probPct}%` }}
          />
        </div>
      </div>

      {/* Size multiplier + position delta */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {multPct != null && (
          <div className="bg-bg-void rounded-lg p-3 border border-border-gutter">
            <div className="text-xs text-text-muted mb-1 font-body">Size Multiplier</div>
            <div className={clsx(
              'text-sm font-display font-semibold tabular-nums',
              multPct >= 100 ? 'text-accent-profit' : multPct >= 50 ? 'text-accent-alert' : 'text-accent-loss',
            )}>
              {multPct}%
            </div>
          </div>
        )}

        {wasAdjusted && rec.raw_gpt_position_size_pct != null && (
          <>
            <div className="bg-bg-void rounded-lg p-3 border border-border-gutter">
              <div className="text-xs text-text-muted mb-1 font-body">GPT Size</div>
              <div className="text-sm font-display font-semibold tabular-nums text-text-secondary line-through decoration-text-muted/40">
                {rec.raw_gpt_position_size_pct.toFixed(1)}%
              </div>
            </div>
            <div className="bg-bg-void rounded-lg p-3 border border-border-gutter">
              <div className="text-xs text-text-muted mb-1 font-body">Adjusted Size</div>
              <div className={clsx('text-sm font-display font-semibold tabular-nums', mlProbColor(rec.ml_probability))}>
                {rec.position_size_pct.toFixed(1)}%
              </div>
            </div>
          </>
        )}
      </div>

      {/* Conformal set */}
      {rec.ml_conformal_set.length > 0 && (
        <div className="mt-3 flex items-center gap-2">
          <span className="text-xs text-text-muted font-body">Conformal set:</span>
          <div className="flex gap-1.5">
            {rec.ml_conformal_set.map(s => (
              <span key={s} className="text-[11px] font-display font-semibold px-2 py-0.5 rounded bg-accent-electric/15 text-accent-electric">
                {s}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function MLBlockedBanner({ rec }: { rec: Recommendation }) {
  if (!rec.ml_blocked) return null;

  const probPct = rec.ml_probability != null ? Math.round(rec.ml_probability * 100) : null;

  return (
    <div className="mb-6 rounded-lg border border-accent-loss/40 bg-accent-loss/8 p-4 flex items-start gap-3">
      <ShieldOff className="w-5 h-5 text-accent-loss shrink-0 mt-0.5" />
      <div>
        <h3 className="text-sm font-display font-semibold text-accent-loss mb-1">
          ML Gate Blocked
        </h3>
        <p className="text-xs text-accent-loss/80">
          The independent LightGBM model assigned this trade a low probability of success
          {probPct != null && <> (<span className="font-display font-semibold tabular-nums">{probPct}%</span>)</>}.
          Position sizing has been zeroed. Consider skipping this trade or waiting for better conditions.
        </p>
      </div>
    </div>
  );
}

function TradeParams({ rec }: { rec: Recommendation }) {
  const params = [
    { label: 'Entry', value: rec.entry_price != null ? `$${rec.entry_price.toFixed(2)}` : null },
    { label: 'Stop Loss', value: rec.stop_loss != null ? `$${rec.stop_loss.toFixed(2)}` : null },
    { label: 'Target', value: rec.take_profit != null ? `$${rec.take_profit.toFixed(2)}` : null },
    { label: 'R/R Ratio', value: rec.risk_reward_ratio != null ? rec.risk_reward_ratio.toFixed(1) : null },
    { label: 'Position', value: rec.position_size_pct > 0 ? `${rec.position_size_pct.toFixed(1)}%` : null },
    { label: 'Hold', value: rec.holding_period || null },
    { label: 'Entry Window', value: rec.entry_valid_window && rec.entry_valid_window !== 'N/A' ? rec.entry_valid_window : null },
  ].filter(p => p.value != null);

  if (params.length === 0) return null;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
      {params.map(p => (
        <div key={p.label} className="bg-bg-void rounded-lg p-3 border border-border-gutter min-w-0">
          <div className="text-xs text-text-muted mb-1 font-body truncate">{p.label}</div>
          <div className="text-sm font-display font-semibold text-text-primary tabular-nums truncate">{p.value}</div>
        </div>
      ))}
    </div>
  );
}

function DebateCaseSection({ debateCase, title }: { debateCase: DebateCase; title: string }) {
  const [isOpen, setIsOpen] = useState(false);
  const isBull = debateCase.stance === 'bull';
  const stanceColor = isBull ? 'text-accent-profit' : 'text-accent-loss';
  const stanceBg = isBull ? 'bg-accent-profit/10' : 'bg-accent-loss/10';

  return (
    <div className="bg-bg-concrete rounded-lg border border-border-gutter overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-bg-steel/30 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className={clsx('text-sm font-semibold font-body', stanceColor)}>{title}</span>
          <span className={clsx('text-xs font-display px-2 py-0.5 rounded', stanceBg, stanceColor)}>
            {(debateCase.confidence * 100).toFixed(0)}% confident
          </span>
        </div>
        <span className="text-text-muted text-sm">{isOpen ? '\u25B2' : '\u25BC'}</span>
      </button>

      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeInOut' }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 border-t border-border-gutter pt-3 space-y-3">
              {debateCase.key_arguments.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold text-text-muted mb-2 font-body">Key Arguments</h4>
                  <ul className="space-y-1.5">
                    {debateCase.key_arguments.map((arg, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-text-primary">
                        <span className={clsx('mt-1.5 w-1.5 h-1.5 rounded-full shrink-0', isBull ? 'bg-accent-profit' : 'bg-accent-loss')} />
                        {arg}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {debateCase.strongest_signal && (
                <div>
                  <h4 className="text-xs font-semibold text-text-muted mb-1 font-body">Strongest Signal</h4>
                  <p className="text-sm text-text-primary">{debateCase.strongest_signal}</p>
                </div>
              )}

              {debateCase.weakest_counter && (
                <div>
                  <h4 className="text-xs font-semibold text-text-muted mb-1 font-body">Weakest Counter</h4>
                  <p className="text-sm text-text-secondary">{debateCase.weakest_counter}</p>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function useSignalAge(signalGeneratedAt: string | null): { label: string; minutes: number } {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);
  if (!signalGeneratedAt) return { label: 'Unknown age', minutes: -1 };
  const minutes = Math.floor((now - new Date(signalGeneratedAt).getTime()) / 60_000);
  if (minutes < 1) return { label: 'Just now', minutes: 0 };
  if (minutes < 60) return { label: `${minutes}m ago`, minutes };
  const hours = Math.floor(minutes / 60);
  const rem = minutes % 60;
  return { label: rem > 0 ? `${hours}h ${rem}m ago` : `${hours}h ago`, minutes };
}

function SignalFreshnessBar({ rec }: { rec: Recommendation }) {
  const isActionable = rec.action === 'BUY' || rec.action === 'SHORT';
  const { label: ageLabel, minutes } = useSignalAge(rec.signal_generated_at);

  // Only show for actionable signals with freshness data
  if (!isActionable || (!rec.signal_generated_at && !rec.entry_valid_window)) return null;

  const isStale = minutes >= 120;
  const isWarning = minutes >= 45 && minutes < 120;

  const barColor = isStale
    ? 'border-accent-loss/40 bg-accent-loss/8'
    : isWarning
      ? 'border-accent-alert/40 bg-accent-alert/8'
      : 'border-accent-profit/40 bg-accent-profit/8';

  const iconColor = isStale ? 'text-accent-loss' : isWarning ? 'text-accent-alert' : 'text-accent-profit';
  const labelColor = isStale ? 'text-accent-loss' : isWarning ? 'text-accent-alert' : 'text-accent-profit';

  return (
    <div className={clsx('rounded-lg border p-4 mb-6 flex flex-wrap items-center gap-x-6 gap-y-2', barColor)}>
      <div className="flex items-center gap-2 min-w-0">
        {isStale ? (
          <AlertTriangle className={clsx('w-4 h-4 shrink-0', iconColor)} />
        ) : (
          <Clock className={clsx('w-4 h-4 shrink-0', iconColor)} />
        )}
        <div>
          <div className="text-xs text-text-muted font-body">Signal age</div>
          <div className={clsx('text-sm font-display font-semibold tabular-nums', labelColor)}>
            {ageLabel}
          </div>
        </div>
      </div>

      {rec.price_at_signal != null && (
        <div className="min-w-0">
          <div className="text-xs text-text-muted font-body">Price at signal</div>
          <div className="text-sm font-display font-semibold tabular-nums text-text-primary">
            ${rec.price_at_signal.toFixed(2)}
          </div>
        </div>
      )}

      {rec.entry_valid_window && rec.entry_valid_window !== 'N/A' && (
        <div className="min-w-0">
          <div className="text-xs text-text-muted font-body">Valid window</div>
          <div className="text-sm font-display font-semibold text-text-primary">
            {rec.entry_valid_window}
          </div>
        </div>
      )}

      {isStale && (
        <div className="w-full text-xs text-accent-loss font-body mt-1">
          Entry conditions may have changed — verify current price before acting.
        </div>
      )}
    </div>
  );
}

export function SynthesisTab({ recommendation }: SynthesisTabProps) {
  const [reasoningExpanded, setReasoningExpanded] = useState(false);

  if (!recommendation) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted">
        <div className="text-center">
          <h3 className="text-lg font-semibold mb-2 font-body">No Synthesis Data</h3>
          <p className="text-sm">GPT analysis was not available for this ticker.</p>
        </div>
      </div>
    );
  }

  const action = ACTION_CONFIG[recommendation.action] ?? ACTION_CONFIG.HOLD;
  const confidencePct = Math.round(recommendation.confidence * 100);

  return (
    <div className="p-6 overflow-y-auto h-full">
      {/* Action + Confidence Header */}
      <div className="bg-bg-concrete rounded-lg border border-border-gutter p-6 mb-6">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
          <div className={clsx('text-3xl font-display font-bold px-5 py-2 rounded-lg', action.bg, action.color, action.border)}>
            {action.text}
          </div>
          <div className="text-right">
            <div className="text-xs text-text-muted mb-1 font-body">Confidence</div>
            <div className={clsx('text-3xl font-display font-bold tabular-nums', action.color)}>
              {confidencePct}%
            </div>
          </div>
        </div>
        {/* Confidence bar — color matches signal direction */}
        <div className="w-full h-2 bg-bg-void rounded-full overflow-hidden">
          <div
            className={clsx('h-full rounded-full transition-all', confidenceBarColor(recommendation.action))}
            style={{ width: `${confidencePct}%` }}
          />
        </div>
      </div>

      {/* Signal Freshness */}
      <SignalFreshnessBar rec={recommendation} />

      {/* NO_TRADE / WATCH callout */}
      {(recommendation.action === 'NO_TRADE' || recommendation.action === 'WATCH') && (
        <div className={clsx(
          'mb-6 rounded-lg border p-4 flex items-start gap-3',
          recommendation.action === 'NO_TRADE'
            ? 'bg-text-muted/10 border-text-muted/30'
            : 'bg-accent-electric/10 border-accent-electric/30',
        )}>
          {recommendation.action === 'NO_TRADE' ? (
            <Ban className="w-5 h-5 text-text-muted shrink-0 mt-0.5" />
          ) : (
            <Eye className="w-5 h-5 text-accent-electric shrink-0 mt-0.5" />
          )}
          <div>
            <h3 className={clsx('text-sm font-display font-semibold mb-1', recommendation.action === 'NO_TRADE' ? 'text-text-muted' : 'text-accent-electric')}>
              {recommendation.action === 'NO_TRADE' ? 'No Trade — Insufficient Conviction' : 'Watchlist — Monitor for Entry'}
            </h3>
            {recommendation.confidence_adjustment && (
              <p className="text-xs text-text-secondary">{recommendation.confidence_adjustment}</p>
            )}
          </div>
        </div>
      )}

      {/* ML Gate — Blocked Banner */}
      <MLBlockedBanner rec={recommendation} />

      {/* Track Agreement */}
      {recommendation.track_agreement && (
        <TrackAgreementPanel agreement={recommendation.track_agreement} />
      )}

      {/* Confidence Breakdown (Phase 7) */}
      {recommendation.confidence_breakdown && (
        <ConfidenceBreakdownPanel
          breakdown={recommendation.confidence_breakdown}
          rawConfidence={recommendation.raw_gpt_confidence ?? null}
          signalStrength={recommendation.signal_strength ?? null}
        />
      )}

      {/* ML Gate — Probability, Sizing, Conformal Set */}
      <MLGatePanel rec={recommendation} />

      {/* Confidence Adjustment */}
      {recommendation.confidence_adjustment && recommendation.action !== 'NO_TRADE' && recommendation.action !== 'WATCH' && (
        <div className="bg-bg-concrete rounded-lg border border-border-gutter p-4 mb-6">
          <h3 className="text-xs font-semibold text-text-muted mb-1 font-body">Confidence Adjustment</h3>
          <p className="text-sm text-text-secondary">{recommendation.confidence_adjustment}</p>
        </div>
      )}

      {/* Risk Violations */}
      {recommendation.risk_violations && recommendation.risk_violations.length > 0 && (
        <div className="mb-6 bg-accent-alert-dim border border-accent-alert/30 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <ShieldAlert className="w-4 h-4 text-accent-alert" />
            <h3 className="text-sm font-display font-semibold text-accent-alert">
              Risk Flags
              <span className="ml-2 text-xs font-normal text-accent-alert/70">
                ({recommendation.risk_violations.length})
              </span>
            </h3>
          </div>
          <ul className="space-y-1.5">
            {recommendation.risk_violations.map((v, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-accent-alert">
                <span className="mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 bg-accent-alert" />
                {v}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Trade Parameters */}
      <div className="mb-6">
        <TradeParams rec={recommendation} />
      </div>

      {/* Judge Reasoning */}
      {recommendation.judge_reasoning && (
        <div className="bg-bg-concrete rounded-lg border border-border-gutter p-6 mb-6">
          <h3 className="text-sm font-semibold text-text-secondary mb-2 font-body">Judge Reasoning</h3>
          <AnimatePresence initial={false}>
            <motion.p
              key={reasoningExpanded ? 'expanded' : 'collapsed'}
              className={clsx(
                'text-sm text-text-primary leading-relaxed',
                !reasoningExpanded && 'line-clamp-4',
              )}
            >
              {recommendation.judge_reasoning}
            </motion.p>
          </AnimatePresence>
          <button
            onClick={() => setReasoningExpanded(prev => !prev)}
            className="mt-2 flex items-center gap-1 text-xs text-accent-signal hover:text-accent-signal/80 transition-colors font-body"
          >
            {reasoningExpanded ? (
              <>
                <ChevronUp className="w-3.5 h-3.5" />
                Show less
              </>
            ) : (
              <>
                <ChevronDown className="w-3.5 h-3.5" />
                Read full reasoning
              </>
            )}
          </button>
        </div>
      )}

      {/* Key Factors */}
      {recommendation.key_factors.length > 0 && (
        <div className="bg-bg-concrete rounded-lg border border-border-gutter p-6 mb-6">
          <h3 className="text-sm font-semibold text-text-secondary mb-2 font-body">
            Key Factors
            <span className="ml-2 text-xs font-normal text-text-muted">({recommendation.key_factors.length})</span>
          </h3>
          <ul className="space-y-1.5">
            {recommendation.key_factors.map((factor, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-text-primary">
                <span className="mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 bg-accent-signal" />
                {factor}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Warnings */}
      {recommendation.warnings.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-accent-alert mb-2 font-body">
            Warnings
            <span className="ml-2 text-xs font-normal text-accent-alert/70">({recommendation.warnings.length})</span>
          </h3>
          <div className="bg-accent-alert-dim border border-accent-alert/20 rounded-lg p-4">
            <ul className="space-y-1.5">
              {recommendation.warnings.map((warning, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-accent-alert">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 bg-accent-alert" />
                  {warning}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Debate Cases */}
      <div className="space-y-3">
        {recommendation.bull_case && (
          <DebateCaseSection debateCase={recommendation.bull_case} title="Bull Case" />
        )}
        {recommendation.bear_case && (
          <DebateCaseSection debateCase={recommendation.bear_case} title="Bear Case" />
        )}
      </div>
    </div>
  );
}
