import { motion, AnimatePresence } from 'motion/react';
import { CheckCircle2, Circle, AlertCircle, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import type { PipelineProgress, StageProgress } from '../../types';

interface PipelineProgressBarProps {
  progress: PipelineProgress | null;
  isRunning: boolean;
  runningLabel: string;
}

function StageIcon({ status }: { status: StageProgress['status'] }) {
  switch (status) {
    case 'done':
      return <CheckCircle2 className="w-3.5 h-3.5 text-accent-profit shrink-0" />;
    case 'running':
      return <Loader2 className="w-3.5 h-3.5 text-accent-signal shrink-0 animate-spin" />;
    case 'error':
      return <AlertCircle className="w-3.5 h-3.5 text-accent-loss shrink-0" />;
    default:
      return <Circle className="w-3.5 h-3.5 text-text-muted/30 shrink-0" />;
  }
}

export function PipelineProgressBar({ progress, isRunning, runningLabel }: PipelineProgressBarProps) {
  const stages = progress?.stages ?? [];
  const doneCount = stages.filter((s) => s.status === 'done').length;
  const totalCount = stages.length;
  const pct = totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0;
  const connecting = !progress && isRunning;

  return (
    <AnimatePresence>
      {isRunning && (
        <motion.div
          key="progress"
          initial={{ opacity: 0, y: 8, height: 0 }}
          animate={{ opacity: 1, y: 0, height: 'auto' }}
          exit={{ opacity: 0, y: -8, height: 0 }}
          transition={{ duration: 0.3, ease: 'easeOut' }}
          className="w-full max-w-3xl overflow-hidden"
        >
          <div className="bg-bg-concrete border border-border-gutter rounded-lg p-4 mt-4">
            {/* Header */}
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-signal opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-accent-signal" />
                </span>
                <span className="text-xs font-display text-text-secondary">{runningLabel}</span>
              </div>
              <span className="text-[11px] font-display text-text-muted tabular-nums">
                {connecting ? 'Starting…' : `${doneCount}/${totalCount} stages`}
              </span>
            </div>

            {/* Progress bar */}
            <div className="h-1 bg-bg-steel rounded-full overflow-hidden mb-3">
              {connecting ? (
                <div className="h-full bg-accent-signal/40 rounded-full animate-pulse w-full" />
              ) : (
                <motion.div
                  className="h-full bg-accent-signal rounded-full"
                  initial={{ width: 0 }}
                  animate={{ width: `${pct}%` }}
                  transition={{ duration: 0.5, ease: 'easeInOut' }}
                />
              )}
            </div>

            {/* Stage list — skeleton placeholders until first poll returns */}
            {connecting ? (
              <div className="grid grid-cols-3 gap-1.5">
                {['FMP Pre-Screening', 'Perplexity Screening', 'Gemini Sentiment',
                  'Claude Chart Analysis', 'GPT Synthesis', 'Annotated Charts'].map((label) => (
                  <div
                    key={label}
                    className="flex items-center gap-1.5 px-2 py-1.5 rounded-md border border-border-gutter bg-transparent text-[11px] font-display text-text-muted/40 animate-pulse"
                  >
                    <Circle className="w-3.5 h-3.5 shrink-0 opacity-30" />
                    <span className="truncate">{label}</span>
                  </div>
                ))}
              </div>
            ) : stages.length > 0 && (
              <div className="grid grid-cols-3 gap-1.5">
                {stages.map((stage) => (
                  <div
                    key={stage.stage}
                    className={clsx(
                      'flex items-center gap-1.5 px-2 py-1.5 rounded-md border text-[11px] font-display transition-colors duration-300',
                      stage.status === 'done'
                        ? 'border-accent-profit/20 bg-accent-profit/5 text-accent-profit'
                        : stage.status === 'running'
                        ? 'border-accent-signal/30 bg-accent-signal/8 text-accent-signal'
                        : stage.status === 'error'
                        ? 'border-accent-loss/20 bg-accent-loss/5 text-accent-loss'
                        : 'border-border-gutter bg-transparent text-text-muted/50',
                    )}
                  >
                    <StageIcon status={stage.status} />
                    <span className="truncate">{stage.label}</span>
                    {stage.count > 0 && stage.status === 'done' && (
                      <span className="ml-auto text-[9px] opacity-60 tabular-nums shrink-0">
                        {stage.count}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
