import { useApiKeyStatus } from "../hooks/useApiKeyStatus";
import { useAuth } from "../context/AuthContext";
import { Loader2, CheckCircle2, XCircle, User } from "lucide-react";

export function SettingsView() {
  const { status, isLoading, error } = useApiKeyStatus();
  const { user } = useAuth();

  return (
    <div className="p-6 max-w-3xl space-y-6">
      <h1 className="text-2xl font-display font-bold">Settings</h1>

      {/* User Profile */}
      <div className="bg-bg-asphalt border border-border-gutter rounded-lg p-6">
        <h2 className="text-lg font-semibold text-text-primary mb-4 flex items-center gap-2 font-body">
          <User className="w-5 h-5" />
          Account
        </h2>
        <div>
          <p className="text-sm text-text-primary font-medium font-body">
            {user?.email}
          </p>
          <p className="text-xs text-text-muted mt-0.5 font-display">
            ID: {user?.id?.slice(0, 8)}...
          </p>
        </div>
      </div>

      {/* API Keys */}
      <div className="bg-bg-asphalt border border-border-gutter rounded-lg p-6">
        <div className="mb-6">
          <h2 className="text-lg font-semibold text-text-primary font-body">API Keys</h2>
          <p className="text-sm text-text-muted mt-1 font-body">
            Keys are configured as environment variables on the server.
          </p>
        </div>

        {error && (
          <div className="bg-accent-loss-dim text-accent-loss p-3 rounded-lg mb-4 text-sm border border-accent-loss/20">
            {error}
          </div>
        )}

        {isLoading && !status ? (
          <div className="flex items-center justify-center py-8 text-text-muted">
            <Loader2 className="w-6 h-6 animate-spin" />
          </div>
        ) : status ? (
          <div className="space-y-3">
            {Object.entries(status.keys).map(([provider, isSet]) => (
              <div
                key={provider}
                className="flex items-center justify-between p-3 bg-bg-concrete rounded-lg border border-border-gutter"
              >
                <span className="capitalize font-medium text-text-primary font-body">
                  {provider}
                </span>
                <div className="flex items-center gap-2">
                  {isSet ? (
                    <>
                      <CheckCircle2 className="w-5 h-5 text-accent-profit" />
                      <span className="text-sm text-accent-profit font-medium font-display">
                        Configured
                      </span>
                    </>
                  ) : (
                    <>
                      <XCircle className="w-5 h-5 text-accent-loss" />
                      <span className="text-sm text-accent-loss font-medium font-display">
                        Missing
                      </span>
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
