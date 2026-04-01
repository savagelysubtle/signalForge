import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import clsx from "clsx";
import {
  Loader2,
  Brain,
  TrendingUp,
  TrendingDown,
  Target,
  BarChart3,
  Trophy,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  ArrowUpRight,
  ArrowDownRight,
  Clock,
  ChevronDown,
  ChevronUp,
  ChevronLeft,
  ChevronRight,
  Send,
  X,
  RefreshCw,
  Link2,
  Pencil,
  SlidersHorizontal,
} from "lucide-react";
import { useInsights } from "../hooks/useInsights";
import type { JournalFilters } from "../hooks/useInsights";
import { api } from "../api/client";
import { notifyFeedbackChanged } from "../lib/feedbackSync";
import { calculatePnl, resolveExitPrice } from "../lib/pnl";
import type {
  PerformanceOverview,
  RecommendationWithStatus,
  DecisionCreate,
  OutcomeCreate,
  PendingMatch,
} from "../types";

export function InsightsView() {
  const {
    overview,
    recommendations,
    reflection,
    isLoading,
    isGenerating,
    error,
    fetchAll,
    recordDecision,
    logOutcome,
    updateOutcome,
    undoDecision,
    generateReflection,
    page,
    hasMore,
    pageSize,
    nextPage,
    prevPage,
    filters,
    applyFilters,
  } = useInsights();

  const [brokerageConnected, setBrokerageConnected] = useState(false);
  const [pendingMatches, setPendingMatches] = useState<PendingMatch[]>([]);
  const [isSyncing, setIsSyncing] = useState(false);
  const [showPendingBanner, setShowPendingBanner] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [autoConfirmToast, setAutoConfirmToast] = useState<string | null>(null);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  useEffect(() => {
    (async () => {
      try {
        const status = await api.getBrokerageStatus();
        const connected = status.connected && !!status.account_id;
        setBrokerageConnected(connected);

        if (connected) {
          // Auto-sync silently on mount via smart-sync (debounced, max once per 5 min)
          try {
            const syncResult = await api.smartSync();
            if (syncResult.auto_confirmed.length > 0) {
              const count = syncResult.auto_confirmed.length;
              setAutoConfirmToast(
                `${count} trade${count !== 1 ? "s" : ""} auto-linked from Questrade`,
              );
              setTimeout(() => setAutoConfirmToast(null), 5000);
              notifyFeedbackChanged();
              fetchAll();
            }
            // Load existing pending matches + any new ones from sync
            const allPending = await api.getPendingMatches();
            setPendingMatches(allPending);
            if (allPending.length > 0) setShowPendingBanner(true);
          } catch {
            // Sync unavailable — just load pending matches
            try {
              const matches = await api.getPendingMatches();
              setPendingMatches(matches);
              if (matches.length > 0) setShowPendingBanner(true);
            } catch {
              /* no pending matches */
            }
          }
        }
      } catch {
        setBrokerageConnected(false);
      }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSync = async () => {
    setIsSyncing(true);
    setSyncError(null);
    setAutoConfirmToast(null);
    try {
      const syncResult = await api.syncTrades();
      if (syncResult.auto_confirmed.length > 0) {
        const count = syncResult.auto_confirmed.length;
        setAutoConfirmToast(
          `${count} trade${count !== 1 ? "s" : ""} auto-linked from Questrade`,
        );
        setTimeout(() => setAutoConfirmToast(null), 5000);
        notifyFeedbackChanged();
        fetchAll();
      }
      const allPending = await api.getPendingMatches();
      setPendingMatches(allPending);
      if (allPending.length > 0) setShowPendingBanner(true);
    } catch (e) {
      setSyncError(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setIsSyncing(false);
    }
  };

  const handleConfirmMatch = async (matchId: string) => {
    try {
      await api.confirmMatch(matchId);
      setPendingMatches((prev) => prev.filter((m) => m.id !== matchId));
      notifyFeedbackChanged();
      fetchAll();
    } catch {
      // silently fail; user can retry
    }
  };

  const handleRejectMatch = async (matchId: string) => {
    try {
      await api.rejectMatch(matchId);
      setPendingMatches((prev) => prev.filter((m) => m.id !== matchId));
    } catch {
      // silently fail
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted">
        <Loader2 className="w-8 h-8 animate-spin text-accent-signal" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      <motion.div
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        className="flex flex-col sm:flex-row sm:items-center justify-between gap-3"
      >
        <div>
          <h1 className="text-2xl font-display font-bold">Insights</h1>
          <p className="text-text-muted text-sm font-body mt-1">
            Track decisions, log outcomes, and let the system learn from your results.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {brokerageConnected && (
            <button
              onClick={handleSync}
              disabled={isSyncing}
              className={clsx(
                "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-display font-medium transition-all",
                "bg-accent-signal text-white hover:bg-accent-signal/80 active:scale-95",
                isSyncing && "opacity-70 cursor-not-allowed",
              )}
            >
              <RefreshCw className={clsx("w-4 h-4", isSyncing && "animate-spin")} />
              Sync Trades
              {pendingMatches.length > 0 && (
                <span className="ml-1 px-1.5 py-0.5 rounded-full text-[10px] font-display font-bold bg-white/20">
                  {pendingMatches.length}
                </span>
              )}
            </button>
          )}
          <button
            onClick={generateReflection}
            disabled={isGenerating || !overview || overview.total_outcomes < 5}
            className={clsx(
              "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-display font-medium transition-all",
              overview && overview.total_outcomes >= 5
                ? "bg-accent-electric text-white hover:bg-accent-electric/80 active:scale-95"
                : "bg-bg-steel text-text-muted cursor-not-allowed",
            )}
          >
            {isGenerating ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Brain className="w-4 h-4" />
            )}
            Generate Reflection
          </button>
        </div>
      </motion.div>

      {error && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="bg-accent-loss-dim border border-accent-loss/30 rounded-lg px-4 py-3 text-accent-loss text-sm font-body"
        >
          {error}
        </motion.div>
      )}

      {syncError && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="bg-accent-loss-dim border border-accent-loss/30 rounded-lg px-4 py-3 text-accent-loss text-sm font-body"
        >
          {syncError}
        </motion.div>
      )}

      <AnimatePresence>
        {autoConfirmToast && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.3 }}
            className="bg-accent-profit-dim border border-accent-profit/30 rounded-lg px-4 py-3 flex items-center gap-2"
          >
            <CheckCircle2 className="w-4 h-4 text-accent-profit shrink-0" />
            <span className="text-accent-profit text-sm font-display font-medium">
              {autoConfirmToast}
            </span>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showPendingBanner && pendingMatches.length > 0 && (
          <PendingMatchesBanner
            matches={pendingMatches}
            onConfirm={handleConfirmMatch}
            onReject={handleRejectMatch}
            onDismiss={() => setShowPendingBanner(false)}
          />
        )}
      </AnimatePresence>

      {overview && <StatsGrid overview={overview} />}

      <RecommendationJournal
        recommendations={recommendations}
        onRecordDecision={recordDecision}
        onLogOutcome={logOutcome}
        onUpdateOutcome={updateOutcome}
        onUndoDecision={undoDecision}
        page={page}
        hasMore={hasMore}
        pageSize={pageSize}
        onNextPage={nextPage}
        onPrevPage={prevPage}
        filters={filters}
        onApplyFilters={applyFilters}
      />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <ReflectionPanel
          reflection={reflection}
          isGenerating={isGenerating}
          outcomeCount={overview?.total_outcomes ?? 0}
        />
        {overview && <CalibrationPanel overview={overview} />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pending Matches Banner
// ---------------------------------------------------------------------------

function PendingMatchesBanner({
  matches,
  onConfirm,
  onReject,
  onDismiss,
}: {
  matches: PendingMatch[];
  onConfirm: (matchId: string) => void;
  onReject: (matchId: string) => void;
  onDismiss: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.3 }}
      className="overflow-hidden"
    >
      <div className="bg-accent-alert-dim border border-accent-alert/30 rounded-lg overflow-hidden">
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full px-5 py-3.5 flex items-center justify-between hover:bg-accent-alert/5 transition-colors"
        >
          <div className="flex items-center gap-3">
            <AlertTriangle className="w-4 h-4 text-accent-alert" />
            <span className="text-sm font-display font-semibold text-accent-alert">
              {matches.length} trade{matches.length !== 1 ? "s" : ""} matched from Questrade
            </span>
            <span className="text-xs text-text-muted font-body">— Review</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDismiss();
              }}
              className="text-text-muted hover:text-text-secondary p-1"
            >
              <X className="w-3.5 h-3.5" />
            </button>
            {expanded ? (
              <ChevronUp className="w-4 h-4 text-accent-alert" />
            ) : (
              <ChevronDown className="w-4 h-4 text-accent-alert" />
            )}
          </div>
        </button>

        <AnimatePresence>
          {expanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.25 }}
              className="overflow-hidden"
            >
              <div className="px-5 pb-4 space-y-2 border-t border-accent-alert/15">
                {matches.map((match) => (
                  <MatchRow
                    key={match.id}
                    match={match}
                    onConfirm={onConfirm}
                    onReject={onReject}
                  />
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

function MatchRow({
  match,
  onConfirm,
  onReject,
}: {
  match: PendingMatch;
  onConfirm: (id: string) => void;
  onReject: (id: string) => void;
}) {
  const isExit = match.side === "Sell" || match.side === "Cov";
  const sideColor = isExit
    ? "bg-accent-alert-dim text-accent-alert"
    : match.side === "Buy"
      ? "bg-accent-profit-dim text-accent-profit"
      : "bg-accent-loss-dim text-accent-loss";

  const actionColor =
    match.rec_action === "BUY"
      ? "bg-accent-profit-dim text-accent-profit"
      : match.rec_action === "SHORT"
        ? "bg-accent-loss-dim text-accent-loss"
        : "bg-accent-alert-dim text-accent-alert";

  return (
    <motion.div
      layout
      exit={{ opacity: 0, x: -20 }}
      transition={{ duration: 0.2 }}
      className="flex items-center gap-4 bg-bg-asphalt/60 rounded-lg p-3 mt-2 first:mt-3"
    >
      {/* Questrade side */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-sm font-display font-bold text-text-primary">{match.ticker}</span>
          <span className={clsx("px-1.5 py-0.5 rounded text-[10px] font-display font-bold", sideColor)}>
            {match.side}
          </span>
          <span
            className={clsx(
              "px-1.5 py-0.5 rounded text-[9px] font-display font-bold uppercase tracking-wider",
              isExit
                ? "bg-accent-electric-dim text-accent-electric"
                : "bg-accent-signal-dim text-accent-signal",
            )}
          >
            {isExit ? "Exit" : "Entry"}
          </span>
        </div>
        <div className="flex items-center gap-3 text-xs font-display text-text-muted tabular-nums">
          <span>{match.total_shares} × ${match.avg_price.toFixed(2)}</span>
          {match.total_commission > 0 && (
            <span className="text-accent-loss">-${match.total_commission.toFixed(2)}</span>
          )}
          <span>{new Date(match.executed_at).toLocaleDateString()}</span>
        </div>
      </div>

      {/* Divider + match score */}
      <div className="flex flex-col items-center gap-0.5 px-2">
        <Link2 className="w-3.5 h-3.5 text-text-muted" />
        <span className="text-[9px] font-display text-text-muted">
          {(match.match_score * 100).toFixed(0)}%
        </span>
      </div>

      {/* Recommendation side */}
      <div className="flex-1 min-w-0 text-right">
        <div className="flex items-center justify-end gap-2 mb-1">
          <span className={clsx("px-1.5 py-0.5 rounded text-[10px] font-display font-bold", actionColor)}>
            {match.rec_action}
          </span>
          <span className="text-sm font-display font-bold text-text-primary">{match.rec_ticker}</span>
        </div>
        <div className="flex items-center justify-end gap-3 text-xs font-display text-text-muted tabular-nums">
          <span>{(match.rec_confidence * 100).toFixed(0)}% conf</span>
          {match.rec_entry_price != null && <span>Entry ${match.rec_entry_price.toFixed(2)}</span>}
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-1.5 ml-2 shrink-0">
        <button
          onClick={() => onConfirm(match.id)}
          className={clsx(
            "p-2 rounded-lg transition-colors",
            isExit
              ? "bg-accent-electric-dim text-accent-electric hover:bg-accent-electric/20"
              : "bg-accent-profit-dim text-accent-profit hover:bg-accent-profit/20",
          )}
          title={isExit ? "Confirm exit — updates PnL" : "Confirm entry"}
        >
          <CheckCircle2 className="w-4 h-4" />
        </button>
        <button
          onClick={() => onReject(match.id)}
          className="p-2 rounded-lg bg-bg-steel text-text-muted hover:text-accent-loss transition-colors"
          title="Reject match"
        >
          <XCircle className="w-4 h-4" />
        </button>
      </div>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Stats Grid
// ---------------------------------------------------------------------------

function StatsGrid({ overview }: { overview: PerformanceOverview }) {
  const stats = [
    {
      label: "Win Rate",
      value: overview.win_rate != null ? `${overview.win_rate.toFixed(1)}%` : "—",
      icon: Target,
      color: overview.win_rate != null && overview.win_rate >= 50 ? "profit" : "loss",
    },
    {
      label: "Total P&L",
      value: `$${overview.total_pnl_dollars.toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
      icon: overview.total_pnl_dollars >= 0 ? TrendingUp : TrendingDown,
      color: overview.total_pnl_dollars >= 0 ? "profit" : "loss",
    },
    {
      label: "Trades",
      value: `${overview.wins}W / ${overview.losses}L / ${overview.breakeven}BE`,
      icon: BarChart3,
      color: "signal",
    },
    {
      label: "Decisions",
      value: `${overview.total_following} follow / ${overview.total_passing} pass`,
      icon: CheckCircle2,
      color: "electric",
    },
    {
      label: "Avg Return",
      value: overview.avg_pnl_percent != null ? `${overview.avg_pnl_percent.toFixed(2)}%` : "—",
      icon:
        overview.avg_pnl_percent != null && overview.avg_pnl_percent >= 0
          ? ArrowUpRight
          : ArrowDownRight,
      color:
        overview.avg_pnl_percent != null && overview.avg_pnl_percent >= 0 ? "profit" : "loss",
    },
    {
      label: "Avg Hold",
      value: overview.avg_holding_days != null ? `${overview.avg_holding_days.toFixed(1)}d` : "—",
      icon: Clock,
      color: "alert",
    },
  ];

  const colorMap: Record<string, { bg: string; text: string; iconColor: string }> = {
    profit: {
      bg: "bg-accent-profit-dim",
      text: "text-accent-profit",
      iconColor: "text-accent-profit",
    },
    loss: { bg: "bg-accent-loss-dim", text: "text-accent-loss", iconColor: "text-accent-loss" },
    signal: {
      bg: "bg-accent-signal-dim",
      text: "text-accent-signal",
      iconColor: "text-accent-signal",
    },
    electric: {
      bg: "bg-accent-electric-dim",
      text: "text-accent-electric",
      iconColor: "text-accent-electric",
    },
    alert: {
      bg: "bg-accent-alert-dim",
      text: "text-accent-alert",
      iconColor: "text-accent-alert",
    },
  };

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
      {stats.map((stat, i) => {
        const colors = colorMap[stat.color];
        const Icon = stat.icon;
        return (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: i * 0.05 }}
            className="bg-bg-asphalt/80 backdrop-blur-sm border border-border-gutter rounded-lg p-4"
          >
            <div className="flex items-center gap-2 mb-2">
              <div
                className={clsx(
                  "w-7 h-7 rounded-md flex items-center justify-center",
                  colors.bg,
                )}
              >
                <Icon className={clsx("w-3.5 h-3.5", colors.iconColor)} />
              </div>
            </div>
            <p className={clsx("text-lg font-display font-bold", colors.text)}>{stat.value}</p>
            <p className="text-xs text-text-muted font-body mt-0.5">{stat.label}</p>
          </motion.div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Recommendation Journal
// ---------------------------------------------------------------------------

function RecommendationJournal({
  recommendations,
  onRecordDecision,
  onLogOutcome,
  onUpdateOutcome,
  onUndoDecision,
  page,
  hasMore,
  pageSize,
  onNextPage,
  onPrevPage,
  filters,
  onApplyFilters,
}: {
  recommendations: RecommendationWithStatus[];
  onRecordDecision: (recId: string, body: DecisionCreate) => Promise<void>;
  onLogOutcome: (decisionId: string, body: OutcomeCreate) => Promise<void>;
  onUpdateOutcome: (outcomeId: string, body: OutcomeCreate) => Promise<void>;
  onUndoDecision: (decisionId: string) => Promise<void>;
  page: number;
  hasMore: boolean;
  pageSize: number;
  onNextPage: () => void;
  onPrevPage: () => void;
  filters: JournalFilters;
  onApplyFilters: (f: JournalFilters) => void;
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false);

  const CONFIDENCE_STOPS = [0, 25, 50, 75, 100];

  const confidenceMinPct = Math.round(filters.confidenceMin * 100);
  const confidenceMaxPct = Math.round(filters.confidenceMax * 100);
  const hasActiveFilters =
    filters.action.length > 0 || filters.confidenceMin > 0 || filters.confidenceMax < 1;
  const activeFilterCount =
    filters.action.length + (filters.confidenceMin > 0 || filters.confidenceMax < 1 ? 1 : 0);

  const toggleAction = (action: "BUY" | "SHORT" | "HOLD") => {
    const current = new Set(filters.action);
    if (current.has(action)) current.delete(action);
    else current.add(action);
    onApplyFilters({ ...filters, action: [...current] });
  };

  const setConfidenceMin = (pct: number) => {
    const val = pct / 100;
    const maxVal = val > filters.confidenceMax ? val : filters.confidenceMax;
    onApplyFilters({ ...filters, confidenceMin: val, confidenceMax: maxVal });
  };

  const setConfidenceMax = (pct: number) => {
    const val = pct / 100;
    const minVal = val < filters.confidenceMin ? val : filters.confidenceMin;
    onApplyFilters({ ...filters, confidenceMax: val, confidenceMin: minVal });
  };

  const clearFilters = () => {
    onApplyFilters({ action: [], confidenceMin: 0, confidenceMax: 1 });
  };

  const rangeStart = page * pageSize + 1;
  const rangeEnd = page * pageSize + recommendations.length;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.15 }}
      className="bg-bg-asphalt/80 backdrop-blur-sm border border-border-gutter rounded-lg overflow-hidden"
    >
      <div className="px-5 py-3.5 border-b border-border-subtle flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-accent-signal" />
          <h2 className="text-sm font-display font-semibold">Trade Journal</h2>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={clsx(
              "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-display transition-all duration-200",
              hasActiveFilters
                ? "bg-accent-signal/15 text-accent-signal border border-accent-signal/30"
                : "text-text-muted hover:text-text-secondary hover:bg-bg-steel/50 border border-transparent",
            )}
            aria-label="Toggle filters"
          >
            <SlidersHorizontal className="w-3 h-3" />
            <span>Filters</span>
            {hasActiveFilters && (
              <span className="ml-0.5 w-4 h-4 rounded-full bg-accent-signal text-[10px] text-bg-void font-bold flex items-center justify-center">
                {activeFilterCount}
              </span>
            )}
          </button>
          <span className="text-xs text-text-muted font-display">
            {recommendations.length > 0
              ? `${rangeStart}–${rangeEnd}`
              : "0 recommendations"}
          </span>
          {(page > 0 || hasMore) && (
            <div className="flex items-center gap-1">
              <button
                onClick={onPrevPage}
                disabled={page === 0}
                className="p-1 rounded hover:bg-bg-surface disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                aria-label="Previous page"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <span className="text-xs text-text-muted font-mono min-w-[3ch] text-center">
                {page + 1}
              </span>
              <button
                onClick={onNextPage}
                disabled={!hasMore}
                className="p-1 rounded hover:bg-bg-surface disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                aria-label="Next page"
              >
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Filter bar */}
      <AnimatePresence>
        {showFilters && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden border-b border-border-subtle"
          >
            <div className="px-5 py-3 flex flex-wrap items-center gap-x-6 gap-y-3 bg-bg-concrete/50">
              {/* Action filter */}
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-text-muted font-display uppercase tracking-wider">
                  Action
                </span>
                <div className="flex items-center gap-1">
                  {(["BUY", "SHORT", "HOLD"] as const).map((action) => {
                    const active = filters.action.includes(action);
                    return (
                      <button
                        key={action}
                        onClick={() => toggleAction(action)}
                        className={clsx(
                          "px-2.5 py-1 rounded text-[11px] font-display font-semibold tracking-wide transition-all duration-150",
                          active && action === "BUY" &&
                            "bg-accent-profit/20 text-accent-profit border border-accent-profit/40",
                          active && action === "SHORT" &&
                            "bg-accent-loss/20 text-accent-loss border border-accent-loss/40",
                          active && action === "HOLD" &&
                            "bg-accent-alert/20 text-accent-alert border border-accent-alert/40",
                          !active &&
                            "bg-bg-steel/30 text-text-muted border border-transparent hover:bg-bg-steel/60 hover:text-text-secondary",
                        )}
                      >
                        {action}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Confidence range */}
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-text-muted font-display uppercase tracking-wider">
                  Confidence
                </span>
                <div className="flex items-center gap-1">
                  <select
                    value={confidenceMinPct}
                    onChange={(e) => setConfidenceMin(Number(e.target.value))}
                    className="bg-bg-concrete border border-border-gutter rounded px-2 py-1 text-xs font-display text-text-primary focus:outline-none focus:border-accent-signal/50 appearance-none cursor-pointer"
                  >
                    {CONFIDENCE_STOPS.map((s) => (
                      <option key={s} value={s}>
                        {s}%
                      </option>
                    ))}
                  </select>
                  <span className="text-text-muted text-[11px]">–</span>
                  <select
                    value={confidenceMaxPct}
                    onChange={(e) => setConfidenceMax(Number(e.target.value))}
                    className="bg-bg-concrete border border-border-gutter rounded px-2 py-1 text-xs font-display text-text-primary focus:outline-none focus:border-accent-signal/50 appearance-none cursor-pointer"
                  >
                    {CONFIDENCE_STOPS.map((s) => (
                      <option key={s} value={s}>
                        {s}%
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Clear */}
              {hasActiveFilters && (
                <button
                  onClick={clearFilters}
                  className="ml-auto flex items-center gap-1 text-[11px] text-text-muted hover:text-accent-loss font-display transition-colors"
                >
                  <X className="w-3 h-3" />
                  Clear
                </button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {recommendations.length === 0 && page === 0 ? (
        <div className="p-8 text-center">
          <div className="w-12 h-12 rounded-xl bg-accent-signal-dim flex items-center justify-center mx-auto mb-3">
            <BarChart3 className="w-6 h-6 text-accent-signal" />
          </div>
          <p className="text-sm text-text-muted font-body">
            {hasActiveFilters
              ? "No recommendations match the current filters."
              : "No recommendations yet. Run a pipeline analysis to get started."}
          </p>
        </div>
      ) : recommendations.length === 0 && page > 0 ? (
        <div className="p-8 text-center">
          <p className="text-sm text-text-muted font-body">No more recommendations.</p>
        </div>
      ) : (
        <div className="divide-y divide-border-subtle">
          {recommendations.map((rec, i) => (
            <JournalRow
              key={rec.id}
              rec={rec}
              index={page * pageSize + i}
              isExpanded={expandedId === rec.id}
              onToggle={() => setExpandedId(expandedId === rec.id ? null : rec.id)}
              onRecordDecision={onRecordDecision}
              onLogOutcome={onLogOutcome}
              onUpdateOutcome={onUpdateOutcome}
              onUndoDecision={onUndoDecision}
            />
          ))}
        </div>
      )}
    </motion.div>
  );
}

type RowStatus = "pending" | "following" | "passed" | "open" | "closed";

function getRowStatus(rec: RecommendationWithStatus): RowStatus {
  if (rec.outcome_id && rec.outcome_exit_price != null) return "closed";
  if (rec.outcome_id) return "open";
  if (rec.decision === "following") return "following";
  if (rec.decision === "passing") return "passed";
  return "pending";
}

function JournalRow({
  rec,
  index,
  isExpanded,
  onToggle,
  onRecordDecision,
  onLogOutcome,
  onUpdateOutcome,
  onUndoDecision,
}: {
  rec: RecommendationWithStatus;
  index: number;
  isExpanded: boolean;
  onToggle: () => void;
  onRecordDecision: (recId: string, body: DecisionCreate) => Promise<void>;
  onLogOutcome: (decisionId: string, body: OutcomeCreate) => Promise<void>;
  onUpdateOutcome: (outcomeId: string, body: OutcomeCreate) => Promise<void>;
  onUndoDecision: (decisionId: string) => Promise<void>;
}) {
  const status = getRowStatus(rec);

  const borderColor = {
    pending: "border-l-border-gutter",
    following: "border-l-accent-profit",
    passed: "border-l-text-muted",
    open: "border-l-accent-signal",
    closed:
      rec.outcome_pnl_dollars != null && rec.outcome_pnl_dollars >= 0
        ? "border-l-accent-profit"
        : "border-l-accent-loss",
  }[status];

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, delay: index * 0.02 }}
      className={clsx("border-l-[3px]", borderColor, status === "passed" && "opacity-60")}
    >
      <div
        className="px-5 py-3 flex items-center gap-4 cursor-pointer hover:bg-bg-steel/40 transition-colors"
        onClick={onToggle}
      >
        {/* Ticker + Action */}
        <div className="flex items-center gap-2.5 min-w-[140px]">
          <span className="text-sm font-display font-bold text-text-primary">{rec.ticker}</span>
          <span
            className={clsx(
              "px-1.5 py-0.5 rounded text-[10px] font-display font-semibold",
              rec.action === "BUY" && "bg-accent-profit-dim text-accent-profit",
              rec.action === "SHORT" && "bg-accent-loss-dim text-accent-loss",
              rec.action === "HOLD" && "bg-accent-alert-dim text-accent-alert",
            )}
          >
            {rec.action}
          </span>
          {rec.outcome_source === "questrade" && (
            <Link2 className="w-3 h-3 text-accent-signal" />
          )}
        </div>

        {/* Confidence */}
        <div className="hidden sm:flex items-center gap-2 min-w-[100px]">
          <div className="w-16 h-1.5 bg-bg-concrete rounded-full overflow-hidden">
            <div
              className={clsx(
                "h-full rounded-full",
                rec.confidence >= 0.7
                  ? "bg-accent-profit"
                  : rec.confidence >= 0.5
                    ? "bg-accent-alert"
                    : "bg-accent-loss",
              )}
              style={{ width: `${rec.confidence * 100}%` }}
            />
          </div>
          <span className="text-xs font-display text-text-muted">
            {(rec.confidence * 100).toFixed(0)}%
          </span>
        </div>

        {/* Strategy */}
        {rec.strategy_name && (
          <span className="hidden lg:block text-[10px] font-display text-text-muted truncate max-w-[120px]" title={rec.strategy_name}>
            {rec.strategy_name}
          </span>
        )}

        {/* Status badge */}
        <div className="flex-1 flex justify-end sm:justify-start">
          <StatusBadge status={status} rec={rec} />
        </div>

        {/* Date */}
        <span className="text-[10px] font-display text-text-muted hidden md:block min-w-[80px] text-right">
          {new Date(rec.created_at).toLocaleDateString()}
        </span>

        {/* Expand chevron */}
        {isExpanded ? (
          <ChevronUp className="w-4 h-4 text-text-muted shrink-0" />
        ) : (
          <ChevronDown className="w-4 h-4 text-text-muted shrink-0" />
        )}
      </div>

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            <ExpandedRow
              rec={rec}
              status={status}
              onRecordDecision={onRecordDecision}
              onLogOutcome={onLogOutcome}
              onUpdateOutcome={onUpdateOutcome}
              onUndoDecision={onUndoDecision}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function StatusBadge({
  status,
  rec,
}: {
  status: RowStatus;
  rec: RecommendationWithStatus;
}) {
  switch (status) {
    case "pending":
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-display font-semibold bg-bg-steel text-text-muted">
          Pending
        </span>
      );
    case "following":
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-display font-semibold bg-accent-profit-dim text-accent-profit">
          Following
        </span>
      );
    case "passed":
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-display font-semibold bg-bg-steel text-text-muted">
          Passed
        </span>
      );
    case "open":
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-display font-semibold bg-accent-signal-dim text-accent-signal">
          Open
        </span>
      );
    case "closed": {
      const pnl = rec.outcome_pnl_dollars ?? 0;
      const isWin = pnl > 0;
      return (
        <span
          className={clsx(
            "px-2 py-0.5 rounded text-[10px] font-display font-semibold",
            isWin ? "bg-accent-profit-dim text-accent-profit" : "bg-accent-loss-dim text-accent-loss",
          )}
        >
          {isWin ? "+" : ""}${pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
        </span>
      );
    }
  }
}

// ---------------------------------------------------------------------------
// Expanded Row (forms + details)
// ---------------------------------------------------------------------------

function ExpandedRow({
  rec,
  status,
  onRecordDecision,
  onLogOutcome,
  onUpdateOutcome,
  onUndoDecision,
}: {
  rec: RecommendationWithStatus;
  status: RowStatus;
  onRecordDecision: (recId: string, body: DecisionCreate) => Promise<void>;
  onLogOutcome: (decisionId: string, body: OutcomeCreate) => Promise<void>;
  onUpdateOutcome: (outcomeId: string, body: OutcomeCreate) => Promise<void>;
  onUndoDecision: (decisionId: string) => Promise<void>;
}) {
  const [isUndoing, setIsUndoing] = useState(false);
  const [isEditing, setIsEditing] = useState(false);

  const handleUndo = async () => {
    if (!rec.decision_id) return;
    setIsUndoing(true);
    try {
      await onUndoDecision(rec.decision_id);
    } finally {
      setIsUndoing(false);
    }
  };

  const actualEntry = rec.outcome_entry_price ?? rec.entry_price;
  const actualStop = rec.outcome_stop_loss ?? rec.stop_loss;
  const actualTarget = rec.outcome_take_profit ?? rec.take_profit;

  return (
    <div className="px-5 pb-4 pt-1 bg-bg-concrete/50 border-t border-border-subtle">
      {/* Trade params summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        <TradeParam label="Entry" value={actualEntry != null ? `$${actualEntry.toFixed(2)}` : "—"} />
        <TradeParam label="Stop" value={actualStop != null ? `$${actualStop.toFixed(2)}` : "—"} />
        <TradeParam label="Target" value={actualTarget != null ? `$${actualTarget.toFixed(2)}` : "—"} />
        <TradeParam label="R:R" value={rec.risk_reward_ratio != null ? `${rec.risk_reward_ratio.toFixed(1)}` : "—"} />
      </div>

      {rec.judge_reasoning && (
        <p className="text-xs text-text-secondary font-body mb-4 leading-relaxed line-clamp-3">
          {rec.judge_reasoning}
        </p>
      )}

      {status === "pending" && (
        <DecisionForm
          rec={rec}
          onSubmit={onRecordDecision}
          onQuickFollow={async () => {
            await onRecordDecision(rec.id, { decision: "following", reason: "Quick follow at rec prices" });
            // After follow is created, log outcome with rec's trade params
            // fetchAll will show the "following" state with outcome form
          }}
          onLogOutcome={onLogOutcome}
        />
      )}

      {status === "following" && rec.decision_id && (
        <div className="space-y-3">
          <OutcomeForm decisionId={rec.decision_id} action={rec.action} onSubmit={onLogOutcome} />
          <UndoButton isUndoing={isUndoing} onUndo={handleUndo} label="Undo Follow" />
        </div>
      )}

      {status === "passed" && (
        <div className="space-y-3">
          {rec.decision_reason && (
            <div className="bg-bg-concrete rounded-lg px-3 py-2 border border-border-subtle">
              <span className="text-[10px] text-text-muted font-display uppercase tracking-wider">
                Reason for passing
              </span>
              <p className="text-xs text-text-secondary font-body mt-1">{rec.decision_reason}</p>
            </div>
          )}
          <UndoButton isUndoing={isUndoing} onUndo={handleUndo} label="Undo Pass" />
        </div>
      )}

      {status === "open" && !isEditing && (
        <OpenPositionCard rec={rec} onEdit={() => setIsEditing(true)} />
      )}

      {status === "open" && isEditing && rec.outcome_id && (
        <EditOutcomeForm
          rec={rec}
          onSubmit={async (body) => {
            await onUpdateOutcome(rec.outcome_id!, body);
            setIsEditing(false);
          }}
          onCancel={() => setIsEditing(false)}
        />
      )}

      {status === "closed" && !isEditing && (
        <ClosedTradeCard rec={rec} onEdit={() => setIsEditing(true)} />
      )}

      {status === "closed" && isEditing && rec.outcome_id && (
        <EditOutcomeForm
          rec={rec}
          onSubmit={async (body) => {
            await onUpdateOutcome(rec.outcome_id!, body);
            setIsEditing(false);
          }}
          onCancel={() => setIsEditing(false)}
        />
      )}
    </div>
  );
}

function UndoButton({
  isUndoing,
  onUndo,
  label,
}: {
  isUndoing: boolean;
  onUndo: () => void;
  label: string;
}) {
  return (
    <button
      onClick={onUndo}
      disabled={isUndoing}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-display font-medium text-text-muted hover:text-accent-loss transition-colors"
    >
      {isUndoing ? <Loader2 className="w-3 h-3 animate-spin" /> : <X className="w-3 h-3" />}
      {label}
    </button>
  );
}

function TradeParam({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-[10px] text-text-muted font-display uppercase tracking-wider block">
        {label}
      </span>
      <span className="text-sm font-display font-semibold text-text-primary">{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Open Position Card
// ---------------------------------------------------------------------------

function OpenPositionCard({
  rec,
  onEdit,
}: {
  rec: RecommendationWithStatus;
  onEdit: () => void;
}) {
  const daysHeld = rec.outcome_entry_timestamp
    ? Math.max(
        0,
        Math.floor(
          (Date.now() - new Date(rec.outcome_entry_timestamp).getTime()) / 86400000,
        ),
      )
    : null;

  return (
    <div className="bg-bg-concrete rounded-lg p-3 border border-accent-signal/20 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-text-muted font-display uppercase tracking-wider">
            Open Position
          </span>
          {rec.outcome_source === "questrade" && (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-display font-bold text-accent-signal bg-accent-signal-dim">
              Questrade
            </span>
          )}
          {rec.outcome_source === "manual" && (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-display font-bold text-text-muted bg-bg-steel">
              Manual
            </span>
          )}
        </div>
        <button
          onClick={onEdit}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-display font-medium text-accent-alert bg-accent-alert-dim hover:bg-accent-alert/20 transition-colors"
        >
          <Target className="w-3 h-3" />
          Close Position
        </button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {rec.outcome_entry_price != null && (
          <div>
            <span className="text-[9px] text-text-muted font-display uppercase tracking-wider block">
              Entry
            </span>
            <span className="text-sm font-display font-bold text-text-primary tabular-nums">
              ${rec.outcome_entry_price.toFixed(2)}
            </span>
          </div>
        )}
        {rec.outcome_shares != null && (
          <div>
            <span className="text-[9px] text-text-muted font-display uppercase tracking-wider block">
              Shares
            </span>
            <span className="text-sm font-display font-bold text-text-primary tabular-nums">
              {rec.outcome_shares}
            </span>
          </div>
        )}
        {(rec.outcome_stop_loss ?? rec.stop_loss) != null && (
          <div>
            <span className="text-[9px] text-text-muted font-display uppercase tracking-wider block">
              Stop Loss
            </span>
            <span className="text-sm font-display font-bold text-accent-loss tabular-nums">
              ${(rec.outcome_stop_loss ?? rec.stop_loss)!.toFixed(2)}
            </span>
          </div>
        )}
        {(rec.outcome_take_profit ?? rec.take_profit) != null && (
          <div>
            <span className="text-[9px] text-text-muted font-display uppercase tracking-wider block">
              Take Profit
            </span>
            <span className="text-sm font-display font-bold text-accent-profit tabular-nums">
              ${(rec.outcome_take_profit ?? rec.take_profit)!.toFixed(2)}
            </span>
          </div>
        )}
        {daysHeld != null && (
          <div>
            <span className="text-[9px] text-text-muted font-display uppercase tracking-wider block">
              Days Held
            </span>
            <span className="text-sm font-display font-bold text-text-primary tabular-nums">
              {daysHeld}d
            </span>
          </div>
        )}
      </div>

      {rec.outcome_commission != null && rec.outcome_commission > 0 && (
        <div className="text-[10px] text-text-muted font-display tabular-nums">
          Commission: -${rec.outcome_commission.toFixed(2)}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Closed Trade Card
// ---------------------------------------------------------------------------

function ClosedTradeCard({
  rec,
  onEdit,
}: {
  rec: RecommendationWithStatus;
  onEdit: () => void;
}) {
  const pnl = rec.outcome_pnl_dollars ?? 0;
  const isWin = pnl > 0;
  const pnlColor = isWin ? "text-accent-profit" : "text-accent-loss";

  const entryPrice = rec.outcome_entry_price;
  const exitPrice = rec.outcome_exit_price;
  const sl = rec.outcome_stop_loss ?? rec.stop_loss;

  let rMultiple: number | null = null;
  if (entryPrice != null && exitPrice != null && sl != null) {
    const riskPerShare = Math.abs(entryPrice - sl);
    if (riskPerShare > 0) {
      const sign = rec.action === "SHORT" ? -1 : 1;
      rMultiple =
        Math.round((sign * (exitPrice - entryPrice) / riskPerShare) * 100) / 100;
    }
  }

  return (
    <div className="bg-bg-concrete rounded-lg p-3 border border-border-subtle space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-text-muted font-display uppercase tracking-wider">
            Trade Result
          </span>
          {rec.outcome_source === "questrade" && (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-display font-bold text-accent-signal bg-accent-signal-dim">
              Questrade
            </span>
          )}
          {rec.outcome_source === "manual" && (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-display font-bold text-text-muted bg-bg-steel">
              Manual
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className={clsx("text-base font-display font-bold", pnlColor)}>
            {isWin ? "+" : ""}${pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </span>
          {rec.outcome_pnl_percent != null && (
            <span className={clsx("text-xs font-display", pnlColor, "opacity-70")}>
              ({rec.outcome_pnl_percent >= 0 ? "+" : ""}
              {rec.outcome_pnl_percent.toFixed(2)}%)
            </span>
          )}
          <button
            onClick={onEdit}
            className="p-1.5 rounded-md text-text-muted hover:text-accent-signal hover:bg-accent-signal-dim transition-colors"
            title="Edit outcome"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {entryPrice != null && (
          <div>
            <span className="text-[9px] text-text-muted font-display uppercase tracking-wider block">
              Entry
            </span>
            <span className="text-xs font-display text-text-secondary tabular-nums">
              ${entryPrice.toFixed(2)}
            </span>
          </div>
        )}
        {exitPrice != null && (
          <div>
            <span className="text-[9px] text-text-muted font-display uppercase tracking-wider block">
              Exit
            </span>
            <span className="text-xs font-display text-text-secondary tabular-nums">
              ${exitPrice.toFixed(2)}
              {entryPrice != null && (
                <span className={clsx("ml-1", pnlColor)}>
                  {exitPrice >= entryPrice ? "↑" : "↓"}
                </span>
              )}
            </span>
          </div>
        )}
        {rec.outcome_shares != null && (
          <div>
            <span className="text-[9px] text-text-muted font-display uppercase tracking-wider block">
              Shares
            </span>
            <span className="text-xs font-display text-text-secondary tabular-nums">
              {rec.outcome_shares}
            </span>
          </div>
        )}
        {rec.outcome_holding_days != null && (
          <div>
            <span className="text-[9px] text-text-muted font-display uppercase tracking-wider block">
              Held
            </span>
            <span className="text-xs font-display text-text-secondary tabular-nums">
              {rec.outcome_holding_days}d
            </span>
          </div>
        )}
        {rMultiple != null && (
          <div>
            <span className="text-[9px] text-text-muted font-display uppercase tracking-wider block">
              R-Multiple
            </span>
            <span className={clsx("text-xs font-display font-bold tabular-nums", rMultiple >= 0 ? "text-accent-profit" : "text-accent-loss")}>
              {rMultiple >= 0 ? "+" : ""}{rMultiple.toFixed(2)}R
            </span>
          </div>
        )}
      </div>

      {(rec.outcome_commission != null && rec.outcome_commission > 0) && (
        <div className="flex items-center gap-4 text-[10px] text-text-muted font-display tabular-nums">
          <span>Comm: -${rec.outcome_commission.toFixed(2)}</span>
          {rec.outcome_net_pnl != null && (
            <span>
              Net: <span className={rec.outcome_net_pnl >= 0 ? "text-accent-profit" : "text-accent-loss"}>
                {rec.outcome_net_pnl >= 0 ? "+" : ""}${rec.outcome_net_pnl.toFixed(2)}
              </span>
            </span>
          )}
        </div>
      )}

      {rec.outcome_exit_reason && (
        <div className="text-[10px] text-text-muted font-display">
          Exit: <span className="text-text-secondary">{rec.outcome_exit_reason.replace(/_/g, " ")}</span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Decision Form (Follow / Pass)
// ---------------------------------------------------------------------------

const REASON_CATEGORIES = [
  "conviction",
  "risk_too_high",
  "timing",
  "position_sizing",
  "already_exposed",
  "other",
];

function DecisionForm({
  rec,
  onSubmit,
  onQuickFollow,
  onLogOutcome,
}: {
  rec: RecommendationWithStatus;
  onSubmit: (recId: string, body: DecisionCreate) => Promise<void>;
  onQuickFollow: () => Promise<void>;
  onLogOutcome: (decisionId: string, body: OutcomeCreate) => Promise<void>;
}) {
  const recId = rec.id;
  const [showReasonForm, setShowReasonForm] = useState(false);
  const [pendingDecision, setPendingDecision] = useState<"following" | "passing" | null>(null);
  const [reason, setReason] = useState("");
  const [category, setCategory] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  const handleQuickDecision = async (decision: "following" | "passing") => {
    if (decision === "following") {
      setIsSaving(true);
      try {
        await onSubmit(recId, { decision: "following" });
      } finally {
        setIsSaving(false);
      }
    } else {
      setPendingDecision("passing");
      setShowReasonForm(true);
    }
  };

  const handleQuickFollow = async () => {
    setIsSaving(true);
    try {
      await onQuickFollow();
    } finally {
      setIsSaving(false);
    }
  };

  const handleSubmitWithReason = async () => {
    if (!pendingDecision) return;
    setIsSaving(true);
    try {
      await onSubmit(recId, {
        decision: pendingDecision,
        reason: reason || undefined,
        reason_category: category || undefined,
      });
    } finally {
      setIsSaving(false);
      setShowReasonForm(false);
    }
  };

  if (showReasonForm) {
    return (
      <div className="bg-bg-concrete rounded-lg p-3 border border-border-subtle space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-display font-semibold text-text-secondary">
            Why are you passing?
          </span>
          <button
            onClick={() => setShowReasonForm(false)}
            className="text-text-muted hover:text-text-secondary"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {REASON_CATEGORIES.map((cat) => (
            <button
              key={cat}
              onClick={() => setCategory(cat === category ? "" : cat)}
              className={clsx(
                "px-2 py-1 rounded text-[10px] font-display transition-colors",
                cat === category
                  ? "bg-accent-signal text-white"
                  : "bg-bg-steel text-text-muted hover:text-text-secondary",
              )}
            >
              {cat.replace(/_/g, " ")}
            </button>
          ))}
        </div>

        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Optional notes..."
          rows={2}
          className="w-full bg-bg-void border border-border-gutter rounded-md px-3 py-2 text-xs font-body text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-signal resize-none"
        />

        <button
          onClick={handleSubmitWithReason}
          disabled={isSaving}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-display font-medium bg-bg-steel text-text-secondary hover:text-text-primary transition-colors"
        >
          {isSaving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />}
          Record Pass
        </button>
      </div>
    );
  }

  const hasRecPrices = rec.entry_price != null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        onClick={() => handleQuickDecision("following")}
        disabled={isSaving}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-display font-medium bg-accent-profit-dim text-accent-profit hover:bg-accent-profit/20 transition-colors"
      >
        {isSaving ? (
          <Loader2 className="w-3 h-3 animate-spin" />
        ) : (
          <CheckCircle2 className="w-3 h-3" />
        )}
        Follow Trade
      </button>
      {hasRecPrices && (
        <button
          onClick={handleQuickFollow}
          disabled={isSaving}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-display font-medium bg-accent-signal-dim text-accent-signal hover:bg-accent-signal/20 transition-colors"
          title={`Follow at $${rec.entry_price?.toFixed(2)} with rec SL/TP`}
        >
          <ArrowUpRight className="w-3 h-3" />
          Quick Follow
        </button>
      )}
      <button
        onClick={() => handleQuickDecision("passing")}
        disabled={isSaving}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-display font-medium bg-bg-steel text-text-muted hover:text-text-secondary transition-colors"
      >
        <XCircle className="w-3 h-3" />
        Pass
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Outcome Form
// ---------------------------------------------------------------------------

function OutcomeForm({
  decisionId,
  action,
  onSubmit,
}: {
  decisionId: string;
  action: "BUY" | "SHORT" | "HOLD";
  onSubmit: (decisionId: string, body: OutcomeCreate) => Promise<void>;
}) {
  const [entryPrice, setEntryPrice] = useState("");
  const [exitPrice, setExitPrice] = useState("");
  const [shares, setShares] = useState("");
  const [stopLoss, setStopLoss] = useState("");
  const [takeProfit, setTakeProfit] = useState("");
  const [pnlDollars, setPnlDollars] = useState("");
  const [pnlPercent, setPnlPercent] = useState("");
  const [holdingDays, setHoldingDays] = useState("");

  useEffect(() => {
    const entry = parseFloat(entryPrice);
    const exit = resolveExitPrice(parseFloat(exitPrice), parseFloat(stopLoss));
    const qty = parseFloat(shares);
    if (!isNaN(entry) && exit != null && !isNaN(qty) && entry > 0 && qty > 0) {
      const result = calculatePnl(action, entry, exit, qty);
      setPnlDollars(result.grossPnl.toFixed(2));
      setPnlPercent(result.pnlPercent?.toFixed(2) ?? "");
    }
  }, [entryPrice, exitPrice, stopLoss, shares, action]);
  const [exitReason, setExitReason] = useState("");
  const [notes, setNotes] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  const EXIT_REASONS = ["hit_target", "hit_stop", "manual_exit", "time_exit"];

  const handleSubmit = async () => {
    setIsSaving(true);
    try {
      await onSubmit(decisionId, {
        entry_price: entryPrice ? parseFloat(entryPrice) : null,
        exit_price: exitPrice ? parseFloat(exitPrice) : null,
        shares: shares ? parseInt(shares) : null,
        stop_loss: stopLoss ? parseFloat(stopLoss) : null,
        take_profit: takeProfit ? parseFloat(takeProfit) : null,
        pnl_dollars: pnlDollars ? parseFloat(pnlDollars) : null,
        pnl_percent: pnlPercent ? parseFloat(pnlPercent) : null,
        holding_days: holdingDays ? parseInt(holdingDays) : null,
        exit_reason: exitReason || undefined,
        notes: notes || undefined,
      });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="bg-bg-concrete rounded-lg p-3 border border-border-subtle space-y-3">
      <span className="text-xs font-display font-semibold text-accent-profit">
        Log Trade Outcome
      </span>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <InputField label="Entry Price" value={entryPrice} onChange={setEntryPrice} placeholder="0.00" type="number" />
        <InputField label="Exit Price" value={exitPrice} onChange={setExitPrice} placeholder="0.00" type="number" />
        <InputField label="Shares" value={shares} onChange={setShares} placeholder="0" type="number" />
        <InputField label="Stop Loss" value={stopLoss} onChange={setStopLoss} placeholder="0.00" type="number" />
        <InputField label="Take Profit" value={takeProfit} onChange={setTakeProfit} placeholder="0.00" type="number" />
        <InputField label="P&L ($)" value={pnlDollars} onChange={setPnlDollars} placeholder="0.00" type="number" />
        <InputField label="P&L (%)" value={pnlPercent} onChange={setPnlPercent} placeholder="0.00" type="number" />
        <InputField label="Hold (days)" value={holdingDays} onChange={setHoldingDays} placeholder="0" type="number" />
      </div>

      <div>
        <span className="text-[10px] text-text-muted font-display uppercase tracking-wider block mb-1.5">
          Exit Reason
        </span>
        <div className="flex flex-wrap gap-1.5">
          {EXIT_REASONS.map((er) => (
            <button
              key={er}
              onClick={() => setExitReason(er === exitReason ? "" : er)}
              className={clsx(
                "px-2 py-1 rounded text-[10px] font-display transition-colors",
                er === exitReason
                  ? "bg-accent-signal text-white"
                  : "bg-bg-steel text-text-muted hover:text-text-secondary",
              )}
            >
              {er.replace(/_/g, " ")}
            </button>
          ))}
        </div>
      </div>

      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="Notes on this trade..."
        rows={2}
        className="w-full bg-bg-void border border-border-gutter rounded-md px-3 py-2 text-xs font-body text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-signal resize-none"
      />

      <button
        onClick={handleSubmit}
        disabled={isSaving}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-display font-medium bg-accent-profit-dim text-accent-profit hover:bg-accent-profit/20 transition-colors"
      >
        {isSaving ? (
          <Loader2 className="w-3 h-3 animate-spin" />
        ) : (
          <Send className="w-3 h-3" />
        )}
        Save Outcome
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Edit Outcome Form (pre-filled for modifying existing outcomes)
// ---------------------------------------------------------------------------

function EditOutcomeForm({
  rec,
  onSubmit,
  onCancel,
}: {
  rec: RecommendationWithStatus;
  onSubmit: (body: OutcomeCreate) => Promise<void>;
  onCancel: () => void;
}) {
  const [entryPrice, setEntryPrice] = useState(rec.outcome_entry_price?.toString() ?? "");
  const [exitPrice, setExitPrice] = useState(rec.outcome_exit_price?.toString() ?? "");
  const [shares, setShares] = useState(rec.outcome_shares?.toString() ?? "");
  const [stopLoss, setStopLoss] = useState(rec.outcome_stop_loss?.toString() ?? "");
  const [takeProfit, setTakeProfit] = useState(rec.outcome_take_profit?.toString() ?? "");
  const [pnlDollars, setPnlDollars] = useState(rec.outcome_pnl_dollars?.toString() ?? "");
  const [pnlPercent, setPnlPercent] = useState(rec.outcome_pnl_percent?.toString() ?? "");
  const [holdingDays, setHoldingDays] = useState(rec.outcome_holding_days?.toString() ?? "");
  const [exitReason, setExitReason] = useState(rec.outcome_exit_reason ?? "");
  const [notes, setNotes] = useState(rec.outcome_notes ?? "");
  const [isSaving, setIsSaving] = useState(false);

  const EXIT_REASONS = ["hit_target", "hit_stop", "manual_exit", "time_exit"];

  useEffect(() => {
    const entry = parseFloat(entryPrice);
    const exit = resolveExitPrice(parseFloat(exitPrice), parseFloat(stopLoss));
    const qty = parseFloat(shares);
    if (!isNaN(entry) && exit != null && !isNaN(qty) && entry > 0 && qty > 0) {
      const result = calculatePnl(rec.action, entry, exit, qty);
      setPnlDollars(result.grossPnl.toFixed(2));
      setPnlPercent(result.pnlPercent?.toFixed(2) ?? "");
    }
  }, [entryPrice, exitPrice, stopLoss, shares, rec.action]);

  const handleSubmit = async () => {
    setIsSaving(true);
    try {
      await onSubmit({
        entry_price: entryPrice ? parseFloat(entryPrice) : null,
        exit_price: exitPrice ? parseFloat(exitPrice) : null,
        shares: shares ? parseInt(shares) : null,
        stop_loss: stopLoss ? parseFloat(stopLoss) : null,
        take_profit: takeProfit ? parseFloat(takeProfit) : null,
        pnl_dollars: pnlDollars ? parseFloat(pnlDollars) : null,
        pnl_percent: pnlPercent ? parseFloat(pnlPercent) : null,
        holding_days: holdingDays ? parseInt(holdingDays) : null,
        exit_reason: exitReason || undefined,
        notes: notes || undefined,
        source: rec.outcome_source,
      });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="bg-bg-concrete rounded-lg p-3 border border-accent-signal/30 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-display font-semibold text-accent-signal">
          Edit Trade Outcome
        </span>
        <button
          onClick={onCancel}
          className="text-text-muted hover:text-text-secondary transition-colors"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <InputField label="Entry Price" value={entryPrice} onChange={setEntryPrice} placeholder="0.00" type="number" />
        <InputField label="Exit Price" value={exitPrice} onChange={setExitPrice} placeholder="0.00" type="number" />
        <InputField label="Shares" value={shares} onChange={setShares} placeholder="0" type="number" />
        <InputField label="Stop Loss" value={stopLoss} onChange={setStopLoss} placeholder="0.00" type="number" />
        <InputField label="Take Profit" value={takeProfit} onChange={setTakeProfit} placeholder="0.00" type="number" />
        <InputField label="P&L ($)" value={pnlDollars} onChange={setPnlDollars} placeholder="0.00" type="number" />
        <InputField label="P&L (%)" value={pnlPercent} onChange={setPnlPercent} placeholder="0.00" type="number" />
        <InputField label="Hold (days)" value={holdingDays} onChange={setHoldingDays} placeholder="0" type="number" />
      </div>

      <div>
        <span className="text-[10px] text-text-muted font-display uppercase tracking-wider block mb-1.5">
          Exit Reason
        </span>
        <div className="flex flex-wrap gap-1.5">
          {EXIT_REASONS.map((er) => (
            <button
              key={er}
              onClick={() => setExitReason(er === exitReason ? "" : er)}
              className={clsx(
                "px-2 py-1 rounded text-[10px] font-display transition-colors",
                er === exitReason
                  ? "bg-accent-signal text-white"
                  : "bg-bg-steel text-text-muted hover:text-text-secondary",
              )}
            >
              {er.replace(/_/g, " ")}
            </button>
          ))}
        </div>
      </div>

      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="Notes on this trade..."
        rows={2}
        className="w-full bg-bg-void border border-border-gutter rounded-md px-3 py-2 text-xs font-body text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-signal resize-none"
      />

      <div className="flex items-center gap-2">
        <button
          onClick={handleSubmit}
          disabled={isSaving}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-display font-medium bg-accent-signal-dim text-accent-signal hover:bg-accent-signal/20 transition-colors"
        >
          {isSaving ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Send className="w-3 h-3" />
          )}
          Save Changes
        </button>
        <button
          onClick={onCancel}
          disabled={isSaving}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-display font-medium text-text-muted hover:text-text-secondary transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function InputField({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  type?: string;
}) {
  return (
    <div>
      <span className="text-[10px] text-text-muted font-display uppercase tracking-wider block mb-1">
        {label}
      </span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-bg-void border border-border-gutter rounded-md px-2.5 py-1.5 text-xs font-display text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-signal"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Reflection Panel
// ---------------------------------------------------------------------------

function ReflectionPanel({
  reflection,
  isGenerating,
  outcomeCount,
}: {
  reflection: ReturnType<typeof useInsights>["reflection"];
  isGenerating: boolean;
  outcomeCount: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.2 }}
      className="bg-bg-asphalt/80 backdrop-blur-sm border border-border-gutter rounded-lg overflow-hidden"
    >
      <div className="px-5 py-3.5 border-b border-border-subtle flex items-center gap-2">
        <Brain className="w-4 h-4 text-accent-electric" />
        <h2 className="text-sm font-display font-semibold">Self-Learning Reflection</h2>
      </div>

      <div className="p-5">
        {isGenerating ? (
          <div className="flex items-center gap-3 text-text-muted py-8 justify-center">
            <Loader2 className="w-5 h-5 animate-spin text-accent-electric" />
            <span className="text-sm font-body">Analyzing your trade history...</span>
          </div>
        ) : reflection ? (
          <div className="space-y-4">
            <div className="text-xs text-text-muted font-body">
              Generated {new Date(reflection.generated_at).toLocaleString()} ·{" "}
              {reflection.outcomes_analyzed} trades analyzed
            </div>
            <div className="bg-bg-concrete rounded-lg p-4 border border-border-subtle">
              <h3 className="text-xs font-display font-semibold text-accent-electric mb-2 uppercase tracking-wider">
                Injection Prompt (sent to GPT Judge)
              </h3>
              <pre className="text-xs font-display text-text-secondary whitespace-pre-wrap leading-relaxed">
                {reflection.injection_prompt}
              </pre>
            </div>
            <div>
              <h3 className="text-xs font-display font-semibold text-text-muted mb-2 uppercase tracking-wider">
                Summary
              </h3>
              <p className="text-sm text-text-secondary font-body whitespace-pre-wrap leading-relaxed">
                {reflection.summary_text}
              </p>
            </div>
          </div>
        ) : (
          <div className="text-center py-8">
            <p className="text-sm text-text-muted font-body">
              {outcomeCount < 5
                ? `Need ${5 - outcomeCount} more outcome${5 - outcomeCount === 1 ? "" : "s"} to generate a reflection.`
                : "No reflection generated yet. Click the button above to analyze your history."}
            </p>
          </div>
        )}
      </div>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Calibration Panel
// ---------------------------------------------------------------------------

function CalibrationPanel({ overview }: { overview: PerformanceOverview }) {
  const calibration = overview.confidence_calibration;
  const hasBestWorst = overview.best_trade || overview.worst_trade;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.25 }}
      className="bg-bg-asphalt/80 backdrop-blur-sm border border-border-gutter rounded-lg overflow-hidden"
    >
      <div className="px-5 py-3.5 border-b border-border-subtle flex items-center gap-2">
        <Target className="w-4 h-4 text-accent-alert" />
        <h2 className="text-sm font-display font-semibold">Confidence Calibration</h2>
      </div>

      <div className="p-5 space-y-5">
        {calibration.length > 0 ? (
          <div className="space-y-3">
            {calibration.map((bucket) => {
              const isCalibrated = bucket.win_rate >= 50;
              return (
                <div key={bucket.bucket} className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs font-body">
                    <span className="text-text-secondary capitalize">
                      {bucket.bucket} confidence
                      <span className="text-text-muted ml-1">({bucket.count} trades)</span>
                    </span>
                    <span
                      className={clsx(
                        "font-display font-bold",
                        isCalibrated ? "text-accent-profit" : "text-accent-loss",
                      )}
                    >
                      {bucket.win_rate}% actual
                    </span>
                  </div>
                  <div className="h-2 bg-bg-concrete rounded-full overflow-hidden">
                    <div
                      className={clsx(
                        "h-full rounded-full transition-all duration-700",
                        isCalibrated ? "bg-accent-profit/60" : "bg-accent-loss/60",
                      )}
                      style={{ width: `${Math.min(bucket.win_rate, 100)}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-text-muted font-body text-center py-4">
            Record more outcomes to see calibration data.
          </p>
        )}

        {hasBestWorst && (
          <div className="grid grid-cols-2 gap-3 pt-2 border-t border-border-subtle">
            {overview.best_trade && (
              <div className="bg-accent-profit-dim rounded-lg p-3">
                <div className="flex items-center gap-1.5 mb-1">
                  <Trophy className="w-3.5 h-3.5 text-accent-profit" />
                  <span className="text-xs font-display text-accent-profit font-semibold">
                    Best Trade
                  </span>
                </div>
                <p className="text-sm font-display font-bold text-accent-profit">
                  {overview.best_trade.ticker}
                </p>
                <p className="text-xs font-display text-accent-profit/70">
                  +${overview.best_trade.pnl_dollars.toLocaleString()}
                </p>
              </div>
            )}
            {overview.worst_trade && (
              <div className="bg-accent-loss-dim rounded-lg p-3">
                <div className="flex items-center gap-1.5 mb-1">
                  <AlertTriangle className="w-3.5 h-3.5 text-accent-loss" />
                  <span className="text-xs font-display text-accent-loss font-semibold">
                    Worst Trade
                  </span>
                </div>
                <p className="text-sm font-display font-bold text-accent-loss">
                  {overview.worst_trade.ticker}
                </p>
                <p className="text-xs font-display text-accent-loss/70">
                  ${overview.worst_trade.pnl_dollars.toLocaleString()}
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}
