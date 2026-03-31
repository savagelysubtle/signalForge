import { useState, useEffect, useCallback, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { motion } from "motion/react";
import clsx from "clsx";
import { useApiKeyStatus } from "../hooks/useApiKeyStatus";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";
import type { BrokerageStatus, BrokerageAccount } from "../types";
import {
  Loader2,
  CheckCircle2,
  XCircle,
  User,
  Link2,
  Unlink,
  Shield,
  ChevronDown,
  Eye,
  EyeOff,
  ExternalLink,
  Key,
} from "lucide-react";

export function SettingsView() {
  const { status, isLoading, error } = useApiKeyStatus();
  const { user } = useAuth();

  return (
    <div className="p-6 max-w-3xl space-y-6">
      <motion.h1
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        className="text-2xl font-display font-bold"
      >
        Settings
      </motion.h1>

      {/* User Profile */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.05 }}
        className="bg-bg-asphalt border border-border-gutter rounded-lg p-6"
      >
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
      </motion.div>

      {/* Brokerage Connection */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.1 }}
      >
        <BrokerageSection />
      </motion.div>

      {/* API Keys */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.15 }}
        className="bg-bg-asphalt border border-border-gutter rounded-lg p-6"
      >
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
      </motion.div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Brokerage Connection Section
// ---------------------------------------------------------------------------

function BrokerageSection() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [brokerageStatus, setBrokerageStatus] = useState<BrokerageStatus | null>(null);
  const [accounts, setAccounts] = useState<BrokerageAccount[]>([]);
  const [isLoadingStatus, setIsLoadingStatus] = useState(true);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isSelectingAccount, setIsSelectingAccount] = useState(false);
  const [showManualFallback, setShowManualFallback] = useState(false);
  const [tokenInput, setTokenInput] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [isPractice, setIsPractice] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAccountPicker, setShowAccountPicker] = useState(false);
  const oauthProcessed = useRef(false);

  const fetchStatus = useCallback(async () => {
    try {
      const status = await api.getBrokerageStatus();
      setBrokerageStatus(status);
    } catch {
      setBrokerageStatus(null);
    } finally {
      setIsLoadingStatus(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Handle OAuth callback — detect ?code= in URL after Questrade redirect
  useEffect(() => {
    const code = searchParams.get("code");
    if (!code || oauthProcessed.current) return;
    oauthProcessed.current = true;

    const savedState = sessionStorage.getItem("qt_oauth_state");
    const returnedState = searchParams.get("state");
    if (savedState && returnedState !== savedState) {
      setError("OAuth state mismatch — possible CSRF. Please try again.");
      setSearchParams({}, { replace: true });
      return;
    }

    const savedPractice = sessionStorage.getItem("qt_oauth_practice") === "true";
    const redirectUri = window.location.origin + "/settings";

    setIsConnecting(true);
    setError(null);
    setSearchParams({}, { replace: true });

    sessionStorage.removeItem("qt_oauth_state");
    sessionStorage.removeItem("qt_oauth_practice");

    api
      .connectBrokerageOAuth({ code, redirect_uri: redirectUri, is_practice: savedPractice })
      .then((resp) => {
        if (resp.accounts?.length) {
          setAccounts(
            resp.accounts.map((a: Record<string, string | boolean>) => ({
              type: a.type as string,
              number: a.number as string,
              status: a.status as string,
              isPrimary: a.isPrimary as boolean,
              clientAccountType: (a.clientAccountType as string) || "",
            })),
          );
          setShowAccountPicker(true);
        }
        return fetchStatus();
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "OAuth connection failed");
      })
      .finally(() => setIsConnecting(false));
  }, [searchParams, setSearchParams, fetchStatus]);

  const handleOAuthConnect = async () => {
    setError(null);
    const redirectUri = window.location.origin + "/settings";
    const state = crypto.randomUUID();
    sessionStorage.setItem("qt_oauth_state", state);
    sessionStorage.setItem("qt_oauth_practice", String(isPractice));

    try {
      const resp = await api.getBrokerageAuthorizeUrl(redirectUri, isPractice, state);
      if (resp.url) {
        window.location.href = resp.url;
      } else {
        setError(
          "OAuth not configured — set QUESTRADE_CLIENT_ID in your server environment. " +
            "Register an app at Questrade API Centre to get your consumer key.",
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start OAuth flow");
    }
  };

  const handleManualConnect = async () => {
    if (!tokenInput.trim()) return;
    setIsConnecting(true);
    setError(null);
    try {
      const resp = await api.connectBrokerage({
        refresh_token: tokenInput.trim(),
        is_practice: isPractice,
      });
      if (resp.accounts?.length) {
        setAccounts(
          resp.accounts.map((a: Record<string, string | boolean>) => ({
            type: a.type as string,
            number: a.number as string,
            status: a.status as string,
            isPrimary: a.isPrimary as boolean,
            clientAccountType: (a.clientAccountType as string) || "",
          })),
        );
        setShowAccountPicker(true);
      }
      setTokenInput("");
      await fetchStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connection failed");
    } finally {
      setIsConnecting(false);
    }
  };

  const handleSelectAccount = async (account: BrokerageAccount) => {
    setIsSelectingAccount(true);
    setError(null);
    try {
      await api.selectBrokerageAccount({
        account_id: account.number,
        account_type: account.type,
      });
      setShowAccountPicker(false);
      setAccounts([]);
      await fetchStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to select account");
    } finally {
      setIsSelectingAccount(false);
    }
  };

  const handleDisconnect = async () => {
    setIsDisconnecting(true);
    setError(null);
    try {
      await api.disconnectBrokerage();
      setBrokerageStatus(null);
      setAccounts([]);
      setShowAccountPicker(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to disconnect");
    } finally {
      setIsDisconnecting(false);
    }
  };

  const maskAccountNumber = (num: string) => {
    if (num.length <= 4) return num;
    return "••••" + num.slice(-4);
  };

  const isConnected = brokerageStatus?.connected === true;
  const hasAccount = isConnected && brokerageStatus?.account_id;

  return (
    <div className="bg-bg-asphalt border border-border-gutter rounded-lg p-6">
      <h2 className="text-lg font-semibold text-text-primary mb-1 flex items-center gap-2 font-body">
        <Link2 className="w-5 h-5 text-accent-signal" />
        Brokerage Connection
      </h2>
      <p className="text-sm text-text-muted font-body mb-5">
        Connect your Questrade account to auto-import trades.
      </p>

      {error && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          className="bg-accent-loss-dim border border-accent-loss/20 rounded-lg px-4 py-3 text-accent-loss text-sm font-body mb-4"
        >
          {error}
        </motion.div>
      )}

      {isLoadingStatus ? (
        <div className="flex items-center justify-center py-6 text-text-muted">
          <Loader2 className="w-5 h-5 animate-spin" />
        </div>
      ) : isConnecting ? (
        <div className="flex flex-col items-center justify-center py-8 gap-3 text-text-muted">
          <Loader2 className="w-6 h-6 animate-spin text-accent-signal" />
          <span className="text-sm font-body">Connecting to Questrade...</span>
        </div>
      ) : hasAccount ? (
        <ConnectedState
          status={brokerageStatus!}
          onDisconnect={handleDisconnect}
          isDisconnecting={isDisconnecting}
          maskAccountNumber={maskAccountNumber}
        />
      ) : showAccountPicker && accounts.length > 0 ? (
        <AccountPicker
          accounts={accounts}
          onSelect={handleSelectAccount}
          isSelecting={isSelectingAccount}
          onCancel={() => {
            setShowAccountPicker(false);
            setAccounts([]);
          }}
        />
      ) : isConnected && !hasAccount ? (
        <div className="space-y-4">
          <div className="bg-accent-signal-dim border border-accent-signal/20 rounded-lg px-4 py-3 text-accent-signal text-sm font-body">
            Connected — select an account to complete setup.
          </div>
          <button
            onClick={async () => {
              setError(null);
              try {
                const accts = await api.getBrokerageAccounts();
                setAccounts(accts);
                setShowAccountPicker(true);
              } catch (e) {
                setError(e instanceof Error ? e.message : "Failed to fetch accounts");
              }
            }}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-display font-semibold bg-accent-signal text-white hover:bg-accent-signal/80 transition-all active:scale-95"
          >
            <ChevronDown className="w-4 h-4" />
            Select Account
          </button>
        </div>
      ) : (
        <div className="space-y-5">
          {/* Practice toggle */}
          <label className="flex items-center gap-3 cursor-pointer group">
            <div
              className={clsx(
                "relative w-9 h-5 rounded-full transition-colors",
                isPractice ? "bg-accent-alert" : "bg-bg-steel",
              )}
              onClick={() => setIsPractice(!isPractice)}
            >
              <div
                className={clsx(
                  "absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform",
                  isPractice ? "translate-x-4" : "translate-x-0.5",
                )}
              />
            </div>
            <div>
              <span className="text-sm font-body text-text-primary group-hover:text-text-secondary transition-colors">
                Practice account
              </span>
              <span className="text-xs text-text-muted font-body block">
                Use Questrade paper trading environment
              </span>
            </div>
          </label>

          {/* Primary: OAuth sign-in button (always visible) */}
          <button
            onClick={handleOAuthConnect}
            className="w-full flex items-center justify-center gap-2.5 px-5 py-3 rounded-lg text-sm font-display font-semibold bg-accent-signal text-white hover:bg-accent-signal/80 transition-all active:scale-95"
          >
            <ExternalLink className="w-4 h-4" />
            Sign in with Questrade
          </button>

          {/* Secondary: manual token entry (collapsible) */}
          {showManualFallback ? (
            <ConnectForm
              tokenInput={tokenInput}
              showToken={showToken}
              isConnecting={isConnecting}
              onTokenChange={setTokenInput}
              onToggleShow={() => setShowToken(!showToken)}
              onConnect={handleManualConnect}
            />
          ) : (
            <button
              onClick={() => setShowManualFallback(true)}
              className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text-secondary transition-colors font-display"
            >
              <Key className="w-3 h-3" />
              Use manual token instead
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Connected State
// ---------------------------------------------------------------------------

function ConnectedState({
  status,
  onDisconnect,
  isDisconnecting,
  maskAccountNumber,
}: {
  status: BrokerageStatus;
  onDisconnect: () => void;
  isDisconnecting: boolean;
  maskAccountNumber: (n: string) => string;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-accent-profit" />
          <span className="text-sm font-display font-semibold text-accent-profit">
            Connected
          </span>
        </div>
        {status.account_type && (
          <span className="px-2.5 py-1 rounded-md text-xs font-display font-bold bg-accent-profit-dim text-accent-profit border border-accent-profit/20">
            {status.account_type}
          </span>
        )}
        {status.is_practice && (
          <span className="px-2.5 py-1 rounded-md text-xs font-display font-bold bg-accent-alert-dim text-accent-alert border border-accent-alert/20">
            <Shield className="w-3 h-3 inline mr-1" />
            Practice
          </span>
        )}
      </div>

      <div className="bg-bg-concrete rounded-lg p-4 border border-border-gutter space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-text-muted font-display uppercase tracking-wider">
            Account
          </span>
          <span className="text-sm font-display font-semibold text-text-primary tabular-nums">
            {status.account_id ? maskAccountNumber(status.account_id) : "—"}
          </span>
        </div>
        {status.connected_at && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-text-muted font-display uppercase tracking-wider">
              Connected
            </span>
            <span className="text-xs font-display text-text-muted">
              {new Date(status.connected_at).toLocaleDateString()}
            </span>
          </div>
        )}
      </div>

      <button
        onClick={onDisconnect}
        disabled={isDisconnecting}
        className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-display font-medium text-accent-loss hover:bg-accent-loss-dim transition-all active:scale-95"
      >
        {isDisconnecting ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Unlink className="w-4 h-4" />
        )}
        Disconnect
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Account Picker
// ---------------------------------------------------------------------------

function AccountPicker({
  accounts,
  onSelect,
  isSelecting,
  onCancel,
}: {
  accounts: BrokerageAccount[];
  onSelect: (account: BrokerageAccount) => void;
  isSelecting: boolean;
  onCancel: () => void;
}) {
  return (
    <div className="space-y-3">
      <span className="text-sm font-display font-semibold text-text-secondary">
        Select an account
      </span>
      <div className="space-y-2">
        {accounts.map((account) => (
          <button
            key={account.number}
            onClick={() => onSelect(account)}
            disabled={isSelecting}
            className={clsx(
              "w-full flex items-center justify-between p-3 rounded-lg border transition-all text-left",
              "bg-bg-concrete border-border-gutter hover:border-accent-signal hover:bg-bg-steel",
              isSelecting && "opacity-50 cursor-not-allowed",
            )}
          >
            <div className="flex items-center gap-3">
              <span className="px-2 py-0.5 rounded text-[10px] font-display font-bold bg-accent-signal-dim text-accent-signal">
                {account.type}
              </span>
              <span className="text-sm font-display text-text-primary tabular-nums">
                ••••{account.number.slice(-4)}
              </span>
            </div>
            <div className="flex items-center gap-2">
              {account.isPrimary && (
                <span className="text-[10px] text-text-muted font-display">Primary</span>
              )}
              <span className="text-xs text-text-muted font-display capitalize">
                {account.status}
              </span>
            </div>
          </button>
        ))}
      </div>
      <button
        onClick={onCancel}
        className="text-xs font-display text-text-muted hover:text-text-secondary transition-colors"
      >
        Cancel
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Connect Form
// ---------------------------------------------------------------------------

function ConnectForm({
  tokenInput,
  showToken,
  isConnecting,
  onTokenChange,
  onToggleShow,
  onConnect,
}: {
  tokenInput: string;
  showToken: boolean;
  isConnecting: boolean;
  onTokenChange: (v: string) => void;
  onToggleShow: () => void;
  onConnect: () => void;
}) {
  return (
    <div className="space-y-3 border-t border-border-gutter pt-4">
      <span className="text-xs text-text-muted font-display uppercase tracking-wider">
        Manual Token
      </span>
      <div className="relative">
        <input
          type={showToken ? "text" : "password"}
          value={tokenInput}
          onChange={(e) => onTokenChange(e.target.value)}
          placeholder="Paste your Questrade API refresh token"
          className="w-full bg-bg-concrete border border-border-gutter rounded-lg px-4 py-2.5 pr-10 text-sm font-display text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-signal transition-colors"
        />
        <button
          type="button"
          onClick={onToggleShow}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary transition-colors"
        >
          {showToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={onConnect}
          disabled={isConnecting || !tokenInput.trim()}
          className={clsx(
            "flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-display font-semibold transition-all active:scale-95",
            tokenInput.trim()
              ? "bg-accent-signal text-white hover:bg-accent-signal/80"
              : "bg-bg-steel text-text-muted cursor-not-allowed",
          )}
        >
          {isConnecting ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Key className="w-4 h-4" />
          )}
          Connect with Token
        </button>
      </div>

      <p className="text-xs text-text-muted font-body">
        Generate a token from your{" "}
        <a
          href="https://login.questrade.com/APIAccess/UserApps.aspx"
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent-signal hover:underline"
        >
          Questrade API Centre
        </a>
      </p>
    </div>
  );
}
