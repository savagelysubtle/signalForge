import { useApiKeyStatus } from '../hooks/useApiKeyStatus';
import { Loader2, CheckCircle2, XCircle, RefreshCw } from 'lucide-react';

export function SettingsView() {
  const { status, isLoading, error, reloadKeys } = useApiKeyStatus();

  return (
    <div className="p-6 max-w-3xl">
      <h1 className="text-2xl font-bold mb-6">Settings</h1>

      <div className="bg-bg-secondary border border-border rounded-lg p-6">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h2 className="text-lg font-semibold text-text-primary">API Keys</h2>
            <p className="text-sm text-text-secondary">
              Keys are configured in the <code className="bg-bg-tertiary px-1 py-0.5 rounded">.env</code> file at the project root.
            </p>
          </div>
          <button
            onClick={reloadKeys}
            disabled={isLoading}
            className="flex items-center gap-2 bg-bg-tertiary hover:bg-border border border-border px-3 py-1.5 rounded text-sm font-medium transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
            Reload Keys
          </button>
        </div>

        {error && (
          <div className="bg-accent-red/10 text-accent-red p-3 rounded mb-4 text-sm border border-accent-red/20">
            {error}
          </div>
        )}

        {isLoading && !status ? (
          <div className="flex items-center justify-center py-8 text-text-secondary">
            <Loader2 className="w-6 h-6 animate-spin" />
          </div>
        ) : status ? (
          <div className="space-y-3">
            {Object.entries(status.keys).map(([provider, isSet]) => (
              <div key={provider} className="flex items-center justify-between p-3 bg-bg-tertiary rounded border border-border">
                <span className="capitalize font-medium text-text-primary">{provider}</span>
                <div className="flex items-center gap-2">
                  {isSet ? (
                    <>
                      <CheckCircle2 className="w-5 h-5 text-accent-green" />
                      <span className="text-sm text-accent-green font-medium">Configured</span>
                    </>
                  ) : (
                    <>
                      <XCircle className="w-5 h-5 text-accent-red" />
                      <span className="text-sm text-accent-red font-medium">Missing</span>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
