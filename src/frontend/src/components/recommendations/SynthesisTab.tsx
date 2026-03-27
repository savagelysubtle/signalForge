import { useState } from 'react';
import type { Recommendation, DebateCase } from '../../types';
import { motion, AnimatePresence } from 'motion/react';
import clsx from 'clsx';

interface SynthesisTabProps {
  recommendation: Recommendation | null;
}

const ACTION_CONFIG: Record<string, { text: string; color: string; bg: string }> = {
  BUY: { text: 'BUY', color: 'text-accent-profit', bg: 'bg-accent-profit/15' },
  SELL: { text: 'SELL', color: 'text-accent-loss', bg: 'bg-accent-loss/15' },
  HOLD: { text: 'HOLD', color: 'text-accent-alert', bg: 'bg-accent-alert/15' },
};

function confidenceBarColor(confidence: number): string {
  if (confidence >= 0.7) return 'bg-accent-profit';
  if (confidence >= 0.55) return 'bg-accent-alert';
  return 'bg-accent-loss';
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
    <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
      {params.map(p => (
        <div key={p.label} className="bg-bg-void rounded-lg p-3 border border-border-gutter">
          <div className="text-xs text-text-muted mb-1 font-body">{p.label}</div>
          <div className="text-sm font-display font-semibold text-text-primary tabular-nums">{p.value}</div>
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
        <div className="flex items-center justify-between mb-4">
          <div className={clsx('text-3xl font-display font-bold px-5 py-2 rounded-lg', action.bg, action.color)}>
            {action.text}
          </div>
          <div className="text-right">
            <div className="text-xs text-text-muted mb-1 font-body">Confidence</div>
            <div className="text-3xl font-display font-bold tabular-nums text-text-primary">
              {confidencePct}%
            </div>
          </div>
        </div>
        {/* Confidence bar */}
        <div className="w-full h-2 bg-bg-void rounded-full overflow-hidden">
          <div
            className={clsx('h-full rounded-full transition-all', confidenceBarColor(recommendation.confidence))}
            style={{ width: `${confidencePct}%` }}
          />
        </div>
      </div>

      {/* Trade Parameters */}
      <div className="mb-6">
        <TradeParams rec={recommendation} />
      </div>

      {/* Judge Reasoning */}
      {recommendation.judge_reasoning && (
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-text-secondary mb-2 font-body">Judge Reasoning</h3>
          <p className="text-sm text-text-primary leading-relaxed">{recommendation.judge_reasoning}</p>
        </div>
      )}

      {/* Key Factors */}
      {recommendation.key_factors.length > 0 && (
        <div className="mb-6">
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
            <span className="ml-2 text-xs font-normal text-text-muted">({recommendation.warnings.length})</span>
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
