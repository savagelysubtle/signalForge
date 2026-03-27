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
  Send,
  X,
} from "lucide-react";
import { useInsights } from "../hooks/useInsights";
import type {
  PerformanceOverview,
  RecommendationWithStatus,
  DecisionCreate,
  OutcomeCreate,
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
    generateReflection,
  } = useInsights();

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

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
        className="flex items-center justify-between"
      >
        <div>
          <h1 className="text-2xl font-display font-bold">Insights</h1>
          <p className="text-text-muted text-sm font-body mt-1">
            Track decisions, log outcomes, and let the system learn from your results.
          </p>
        </div>
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

      {overview && <StatsGrid overview={overview} />}

      <RecommendationJournal
        recommendations={recommendations}
        onRecordDecision={recordDecision}
        onLogOutcome={logOutcome}
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
}: {
  recommendations: RecommendationWithStatus[];
  onRecordDecision: (recId: string, body: DecisionCreate) => Promise<void>;
  onLogOutcome: (decisionId: string, body: OutcomeCreate) => Promise<void>;
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

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
        <span className="text-xs text-text-muted font-display">
          {recommendations.length} recommendation{recommendations.length !== 1 ? "s" : ""}
        </span>
      </div>

      {recommendations.length === 0 ? (
        <div className="p-8 text-center">
          <div className="w-12 h-12 rounded-xl bg-accent-signal-dim flex items-center justify-center mx-auto mb-3">
            <BarChart3 className="w-6 h-6 text-accent-signal" />
          </div>
          <p className="text-sm text-text-muted font-body">
            No recommendations yet. Run a pipeline analysis to get started.
          </p>
        </div>
      ) : (
        <div className="divide-y divide-border-subtle">
          {recommendations.map((rec, i) => (
            <JournalRow
              key={rec.id}
              rec={rec}
              index={i}
              isExpanded={expandedId === rec.id}
              onToggle={() => setExpandedId(expandedId === rec.id ? null : rec.id)}
              onRecordDecision={onRecordDecision}
              onLogOutcome={onLogOutcome}
            />
          ))}
        </div>
      )}
    </motion.div>
  );
}

type RowStatus = "pending" | "following" | "passed" | "closed";

function getRowStatus(rec: RecommendationWithStatus): RowStatus {
  if (rec.outcome_id) return "closed";
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
}: {
  rec: RecommendationWithStatus;
  index: number;
  isExpanded: boolean;
  onToggle: () => void;
  onRecordDecision: (recId: string, body: DecisionCreate) => Promise<void>;
  onLogOutcome: (decisionId: string, body: OutcomeCreate) => Promise<void>;
}) {
  const status = getRowStatus(rec);

  const borderColor = {
    pending: "border-l-border-gutter",
    following: "border-l-accent-profit",
    passed: "border-l-text-muted",
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
              rec.action === "SELL" && "bg-accent-loss-dim text-accent-loss",
              rec.action === "HOLD" && "bg-accent-alert-dim text-accent-alert",
            )}
          >
            {rec.action}
          </span>
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
}: {
  rec: RecommendationWithStatus;
  status: RowStatus;
  onRecordDecision: (recId: string, body: DecisionCreate) => Promise<void>;
  onLogOutcome: (decisionId: string, body: OutcomeCreate) => Promise<void>;
}) {
  return (
    <div className="px-5 pb-4 pt-1 bg-bg-concrete/50 border-t border-border-subtle">
      {/* Trade params summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        <TradeParam label="Entry" value={rec.entry_price != null ? `$${rec.entry_price.toFixed(2)}` : "—"} />
        <TradeParam label="Stop" value={rec.stop_loss != null ? `$${rec.stop_loss.toFixed(2)}` : "—"} />
        <TradeParam label="Target" value={rec.take_profit != null ? `$${rec.take_profit.toFixed(2)}` : "—"} />
        <TradeParam label="R:R" value={rec.risk_reward_ratio != null ? `${rec.risk_reward_ratio.toFixed(1)}` : "—"} />
      </div>

      {rec.judge_reasoning && (
        <p className="text-xs text-text-secondary font-body mb-4 leading-relaxed line-clamp-3">
          {rec.judge_reasoning}
        </p>
      )}

      {status === "pending" && <DecisionForm recId={rec.id} onSubmit={onRecordDecision} />}

      {status === "following" && rec.decision_id && (
        <OutcomeForm decisionId={rec.decision_id} onSubmit={onLogOutcome} />
      )}

      {status === "passed" && rec.decision_reason && (
        <div className="bg-bg-concrete rounded-lg px-3 py-2 border border-border-subtle">
          <span className="text-[10px] text-text-muted font-display uppercase tracking-wider">
            Reason for passing
          </span>
          <p className="text-xs text-text-secondary font-body mt-1">{rec.decision_reason}</p>
        </div>
      )}

      {status === "closed" && (
        <div className="bg-bg-concrete rounded-lg px-3 py-2 border border-border-subtle">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-text-muted font-display uppercase tracking-wider">
              Trade Result
            </span>
            <span
              className={clsx(
                "text-sm font-display font-bold",
                (rec.outcome_pnl_dollars ?? 0) >= 0 ? "text-accent-profit" : "text-accent-loss",
              )}
            >
              {(rec.outcome_pnl_dollars ?? 0) >= 0 ? "+" : ""}$
              {(rec.outcome_pnl_dollars ?? 0).toLocaleString(undefined, {
                minimumFractionDigits: 2,
              })}
              {rec.outcome_pnl_percent != null && (
                <span className="text-xs ml-1 opacity-70">
                  ({rec.outcome_pnl_percent >= 0 ? "+" : ""}
                  {rec.outcome_pnl_percent.toFixed(2)}%)
                </span>
              )}
            </span>
          </div>
          {rec.outcome_exit_reason && (
            <p className="text-xs text-text-muted font-body mt-1">
              Exit: {rec.outcome_exit_reason}
            </p>
          )}
        </div>
      )}
    </div>
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
  recId,
  onSubmit,
}: {
  recId: string;
  onSubmit: (recId: string, body: DecisionCreate) => Promise<void>;
}) {
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

  return (
    <div className="flex items-center gap-2">
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
  onSubmit,
}: {
  decisionId: string;
  onSubmit: (decisionId: string, body: OutcomeCreate) => Promise<void>;
}) {
  const [entryPrice, setEntryPrice] = useState("");
  const [exitPrice, setExitPrice] = useState("");
  const [shares, setShares] = useState("");
  const [pnlDollars, setPnlDollars] = useState("");
  const [pnlPercent, setPnlPercent] = useState("");
  const [holdingDays, setHoldingDays] = useState("");
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

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        <InputField label="Entry Price" value={entryPrice} onChange={setEntryPrice} placeholder="0.00" type="number" />
        <InputField label="Exit Price" value={exitPrice} onChange={setExitPrice} placeholder="0.00" type="number" />
        <InputField label="Shares" value={shares} onChange={setShares} placeholder="0" type="number" />
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
