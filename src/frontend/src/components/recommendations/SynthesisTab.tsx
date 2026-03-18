import { useState } from 'react';
import type { Recommendation, DebateCase } from '../../types';
import clsx from 'clsx';

interface SynthesisTabProps {
  recommendation: Recommendation | null;
}

const ACTION_CONFIG: Record<string, { text: string; color: string; bg: string }> = {
  BUY: { text: 'BUY', color: 'text-accent-green', bg: 'bg-accent-green/15' },
  SELL: { text: 'SELL', color: 'text-accent-red', bg: 'bg-accent-red/15' },
  HOLD: { text: 'HOLD', color: 'text-accent-yellow', bg: 'bg-accent-yellow/15' },
};

function confidenceBarColor(confidence: number): string {
  if (confidence >= 0.7) return 'bg-accent-green';
  if (confidence >= 0.55) return 'bg-accent-yellow';
  return 'bg-accent-red';
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
        <div key={p.label} className="bg-bg-primary rounded-lg p-3 border border-border">
          <div className="text-xs text-text-secondary mb-1">{p.label}</div>
          <div className="text-sm font-semibold text-text-primary tabular-nums">{p.value}</div>
        </div>
      ))}
    </div>
  );
}

function DebateCaseSection({ debateCase, title }: { debateCase: DebateCase; title: string }) {
  const [isOpen, setIsOpen] = useState(false);
  const isBull = debateCase.stance === 'bull';
  const stanceColor = isBull ? 'text-accent-green' : 'text-accent-red';
  const stanceBg = isBull ? 'bg-accent-green/10' : 'bg-accent-red/10';

  return (
    <div className="bg-bg-tertiary rounded-lg border border-border overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-bg-primary/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className={clsx('text-sm font-semibold', stanceColor)}>{title}</span>
          <span className={clsx('text-xs px-2 py-0.5 rounded', stanceBg, stanceColor)}>
            {(debateCase.confidence * 100).toFixed(0)}% confident
          </span>
        </div>
        <span className="text-text-secondary text-sm">{isOpen ? '\u25B2' : '\u25BC'}</span>
      </button>

      {isOpen && (
        <div className="px-4 pb-4 border-t border-border pt-3 space-y-3">
          {debateCase.key_arguments.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-text-secondary mb-2">Key Arguments</h4>
              <ul className="space-y-1.5">
                {debateCase.key_arguments.map((arg, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-text-primary">
                    <span className={clsx('mt-1.5 w-1.5 h-1.5 rounded-full shrink-0', isBull ? 'bg-accent-green' : 'bg-accent-red')} />
                    {arg}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {debateCase.strongest_signal && (
            <div>
              <h4 className="text-xs font-semibold text-text-secondary mb-1">Strongest Signal</h4>
              <p className="text-sm text-text-primary">{debateCase.strongest_signal}</p>
            </div>
          )}

          {debateCase.weakest_counter && (
            <div>
              <h4 className="text-xs font-semibold text-text-secondary mb-1">Weakest Counter</h4>
              <p className="text-sm text-text-secondary">{debateCase.weakest_counter}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function SynthesisTab({ recommendation }: SynthesisTabProps) {
  if (!recommendation) {
    return (
      <div className="flex items-center justify-center h-full text-text-secondary">
        <div className="text-center">
          <h3 className="text-lg font-semibold mb-2">No Synthesis Data</h3>
          <p>GPT analysis was not available for this ticker.</p>
        </div>
      </div>
    );
  }

  const action = ACTION_CONFIG[recommendation.action] ?? ACTION_CONFIG.HOLD;
  const confidencePct = Math.round(recommendation.confidence * 100);

  return (
    <div className="p-6 overflow-y-auto h-full">
      {/* Action + Confidence Header */}
      <div className="bg-bg-tertiary rounded-lg border border-border p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <div className={clsx('text-3xl font-bold px-5 py-2 rounded-lg', action.bg, action.color)}>
            {action.text}
          </div>
          <div className="text-right">
            <div className="text-xs text-text-secondary mb-1">Confidence</div>
            <div className="text-3xl font-bold tabular-nums text-text-primary">
              {confidencePct}%
            </div>
          </div>
        </div>
        {/* Confidence bar */}
        <div className="w-full h-2 bg-bg-primary rounded-full overflow-hidden">
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
          <h3 className="text-sm font-semibold text-text-secondary mb-2">Judge Reasoning</h3>
          <p className="text-sm text-text-primary leading-relaxed">{recommendation.judge_reasoning}</p>
        </div>
      )}

      {/* Key Factors */}
      {recommendation.key_factors.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-text-secondary mb-2">
            Key Factors
            <span className="ml-2 text-xs font-normal">({recommendation.key_factors.length})</span>
          </h3>
          <ul className="space-y-1.5">
            {recommendation.key_factors.map((factor, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-text-primary">
                <span className="mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 bg-accent-blue" />
                {factor}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Warnings */}
      {recommendation.warnings.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-accent-yellow mb-2">
            Warnings
            <span className="ml-2 text-xs font-normal">({recommendation.warnings.length})</span>
          </h3>
          <div className="bg-accent-yellow/5 border border-accent-yellow/20 rounded-lg p-4">
            <ul className="space-y-1.5">
              {recommendation.warnings.map((warning, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-accent-yellow">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 bg-accent-yellow" />
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
