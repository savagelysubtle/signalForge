import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { usePipeline } from '../hooks/usePipeline';
import { Loader2 } from 'lucide-react';
import { motion } from 'motion/react';
import clsx from 'clsx';

export function HistoryView() {
  const { history, isLoadingHistory, fetchHistory } = usePipeline();
  const navigate = useNavigate();

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  if (isLoadingHistory) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted">
        <Loader2 className="w-8 h-8 animate-spin text-accent-signal" />
      </div>
    );
  }

  if (history.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted font-body">
        No past runs yet.
      </div>
    );
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-display font-bold mb-6">Run History</h1>
      <div className="bg-bg-asphalt border border-border-gutter rounded-lg overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead className="bg-bg-concrete border-b border-border-gutter">
            <tr>
              <th className="px-4 py-3 font-medium text-text-muted font-body">Date</th>
              <th className="px-4 py-3 font-medium text-text-muted font-body">Strategy</th>
              <th className="px-4 py-3 font-medium text-text-muted font-body">Tickers</th>
              <th className="px-4 py-3 font-medium text-text-muted font-body">Mode</th>
              <th className="px-4 py-3 font-medium text-text-muted font-body">Status</th>
              <th className="px-4 py-3 font-medium text-text-muted font-body">Duration</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-subtle">
            {history.map((run, i) => (
              <motion.tr
                key={run.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, delay: i * 0.03, ease: 'easeOut' }}
                onClick={() => navigate(`/?run=${run.id}`)}
                className="hover:bg-bg-steel cursor-pointer transition-colors"
              >
                <td className="px-4 py-3 text-text-primary font-display text-xs">
                  {new Date(run.started_at).toLocaleString()}
                </td>
                <td className="px-4 py-3 text-text-secondary text-xs font-body">
                  {run.strategy_name ?? '\u2014'}
                </td>
                <td className="px-4 py-3">
                  {run.tickers && run.tickers.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                      {run.tickers.slice(0, 5).map(t => (
                        <span key={t} className="px-1.5 py-0.5 rounded bg-accent-signal-dim text-accent-signal text-xs font-display">
                          {t}
                        </span>
                      ))}
                      {run.tickers.length > 5 && (
                        <span className="px-1.5 py-0.5 text-text-muted text-xs">
                          +{run.tickers.length - 5}
                        </span>
                      )}
                    </div>
                  ) : (
                    <span className="text-text-muted text-xs">\u2014</span>
                  )}
                </td>
                <td className="px-4 py-3 capitalize text-text-secondary">{run.mode}</td>
                <td className="px-4 py-3">
                  <span className={clsx(
                    "px-2 py-1 rounded text-xs font-medium font-display",
                    run.status === 'completed' && "bg-accent-profit-dim text-accent-profit",
                    run.status === 'failed' && "bg-accent-loss-dim text-accent-loss",
                    run.status === 'partial' && "bg-accent-alert-dim text-accent-alert",
                    run.status === 'running' && "bg-accent-signal-dim text-accent-signal"
                  )}>
                    {run.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-text-secondary font-display text-xs">
                  {run.duration_seconds ? `${run.duration_seconds.toFixed(1)}s` : '-'}
                </td>
              </motion.tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
