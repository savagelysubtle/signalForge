import { useState } from 'react';
import type { Recommendation, DebateCase, TrackAgreement } from '../../types';
import { motion, AnimatePresence } from 'motion/react';
import { ShieldAlert, ChevronDown, ChevronUp, Ban, Eye } from 'lucide-react';
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

function TradeParams({ rec }: { rec: Recommendation }) {
  const params = [
    { label: 'Entry', value: rec.entry_price != null ? `$${rec.entry_price.toFixed(2)}` : null },
    { label: 'Stop Loss', value: rec.stop_loss != null ? `$${rec.stop_loss.toFixed(2)}` : null },
    { label: 'Target', value: rec.take_profit != null ? `$${rec.take_profit.toFixed(2)}` : null },
    { label: 'R/R Ratio', value: rec.risk_reward_ratio != null ? rec.risk_reward_ratio.toFixed(1) : null },
    { label: 'Position', value: rec.position_size_pct > 0 ? `${rec.position_size_pct.toFixed(1)}%` : null },
    { label: 'Hold', value: rec.holding_period || null },
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

      {/* Track Agreement */}
      {recommendation.track_agreement && (
        <TrackAgreementPanel agreement={recommendation.track_agreement} />
      )}

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
