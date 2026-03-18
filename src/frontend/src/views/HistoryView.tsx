import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { usePipeline } from '../hooks/usePipeline';
import { Loader2 } from 'lucide-react';
import clsx from 'clsx';

export function HistoryView() {
  const { history, isLoadingHistory, fetchHistory } = usePipeline();
  const navigate = useNavigate();

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  if (isLoadingHistory) {
    return (
      <div className="flex items-center justify-center h-full text-text-secondary">
        <Loader2 className="w-8 h-8 animate-spin text-accent-blue" />
      </div>
    );
  }

  if (history.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-text-secondary">
        No past runs yet.
      </div>
    );
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Run History</h1>
      <div className="bg-bg-secondary border border-border rounded-lg overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead className="bg-bg-tertiary border-b border-border">
            <tr>
              <th className="px-4 py-3 font-medium text-text-secondary">Date</th>
              <th className="px-4 py-3 font-medium text-text-secondary">Tickers</th>
              <th className="px-4 py-3 font-medium text-text-secondary">Mode</th>
              <th className="px-4 py-3 font-medium text-text-secondary">Status</th>
              <th className="px-4 py-3 font-medium text-text-secondary">Duration</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {history.map(run => (
              <tr 
                key={run.id} 
                onClick={() => navigate(`/?run=${run.id}`)}
                className="hover:bg-bg-tertiary cursor-pointer transition-colors"
              >
                <td className="px-4 py-3 text-text-primary">
                  {new Date(run.started_at).toLocaleString()}
                </td>
                <td className="px-4 py-3">
                  {run.tickers && run.tickers.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                      {run.tickers.slice(0, 5).map(t => (
                        <span key={t} className="px-1.5 py-0.5 rounded bg-accent-blue/10 text-accent-blue text-xs font-mono">
                          {t}
                        </span>
                      ))}
                      {run.tickers.length > 5 && (
                        <span className="px-1.5 py-0.5 text-text-secondary text-xs">
                          +{run.tickers.length - 5}
                        </span>
                      )}
                    </div>
                  ) : (
                    <span className="text-text-secondary text-xs">—</span>
                  )}
                </td>
                <td className="px-4 py-3 capitalize">{run.mode}</td>
                <td className="px-4 py-3">
                  <span className={clsx(
                    "px-2 py-1 rounded text-xs font-medium",
                    run.status === 'completed' && "bg-accent-green/10 text-accent-green",
                    run.status === 'failed' && "bg-accent-red/10 text-accent-red",
                    run.status === 'partial' && "bg-accent-yellow/10 text-accent-yellow",
                    run.status === 'running' && "bg-accent-blue/10 text-accent-blue"
                  )}>
                    {run.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-text-secondary">
                  {run.duration_seconds ? `${run.duration_seconds.toFixed(1)}s` : '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
