import { useApiKeyStatus } from "../hooks/useApiKeyStatus";
import { useAuth } from "../context/AuthContext";
import { Loader2, CheckCircle2, XCircle, LogOut, User } from "lucide-react";

export function SettingsView() {
  const { status, isLoading, error } = useApiKeyStatus();
  const { user, signOut } = useAuth();

  return (
    <div className="p-6 max-w-3xl space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      {/* User Profile */}
      <div className="bg-bg-secondary border border-border rounded-lg p-6">
        <h2 className="text-lg font-semibold text-text-primary mb-4 flex items-center gap-2">
          <User className="w-5 h-5" />
          Account
        </h2>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-text-primary font-medium">
              {user?.email}
            </p>
            <p className="text-xs text-text-secondary mt-0.5">
              ID: {user?.id?.slice(0, 8)}...
            </p>
          </div>
          <button
            onClick={signOut}
            className="flex items-center gap-2 bg-accent-red/10 hover:bg-accent-red/20 text-accent-red border border-accent-red/20 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Sign out
          </button>
        </div>
      </div>

      {/* API Keys */}
      <div className="bg-bg-secondary border border-border rounded-lg p-6">
        <div className="mb-6">
          <h2 className="text-lg font-semibold text-text-primary">API Keys</h2>
          <p className="text-sm text-text-secondary mt-1">
            Keys are configured as environment variables on the server.
          </p>
        </div>

        {error && (
          <div className="bg-accent-red/10 text-accent-red p-3 rounded-lg mb-4 text-sm border border-accent-red/20">
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
              <div
                key={provider}
                className="flex items-center justify-between p-3 bg-bg-tertiary rounded-lg border border-border"
              >
                <span className="capitalize font-medium text-text-primary">
                  {provider}
                </span>
                <div className="flex items-center gap-2">
                  {isSet ? (
                    <>
                      <CheckCircle2 className="w-5 h-5 text-accent-green" />
                      <span className="text-sm text-accent-green font-medium">
                        Configured
                      </span>
                    </>
                  ) : (
                    <>
                      <XCircle className="w-5 h-5 text-accent-red" />
                      <span className="text-sm text-accent-red font-medium">
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
