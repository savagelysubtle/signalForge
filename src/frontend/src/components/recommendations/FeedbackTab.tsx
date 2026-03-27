import { useEffect, useState, useCallback } from "react";
import { motion, AnimatePresence } from "motion/react";
import clsx from "clsx";
import {
  Loader2,
  CheckCircle2,
  XCircle,
  Send,
  ArrowUpRight,
  ArrowDownRight,
  Target,
  ShieldAlert,
  Clock,
  Pencil,
  Undo2,
  X,
} from "lucide-react";
import { api } from "../../api/client";
import { notifyFeedbackChanged, useFeedbackSync } from "../../lib/feedbackSync";
import type {
  Recommendation,
  RecommendationWithStatus,
  DecisionCreate,
  OutcomeCreate,
} from "../../types";

interface FeedbackTabProps {
  recommendation: Recommendation | null;
}

export function FeedbackTab({ recommendation }: FeedbackTabProps) {
  const [status, setStatus] = useState<RecommendationWithStatus | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [isUndoing, setIsUndoing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    if (!recommendation?.id) return;
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.getRecommendationStatus(recommendation.id);
      setStatus(data);
      setIsEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load feedback status");
    } finally {
      setIsLoading(false);
    }
  }, [recommendation?.id]);

  const handleUndo = useCallback(async () => {
    if (!status?.decision_id) return;
    setIsUndoing(true);
    try {
      await api.deleteDecision(status.decision_id);
      notifyFeedbackChanged();
      await fetchStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to undo decision");
    } finally {
      setIsUndoing(false);
    }
  }, [status?.decision_id, fetchStatus]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  useFeedbackSync(fetchStatus);

  if (!recommendation || !recommendation.id) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted">
        <div className="text-center">
          <h3 className="text-lg font-semibold mb-2 font-body">No Recommendation</h3>
          <p className="text-sm font-body">GPT analysis was not available for this ticker.</p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted">
        <Loader2 className="w-6 h-6 animate-spin text-accent-signal" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <p className="text-sm text-accent-loss font-body mb-2">{error}</p>
          <button
            onClick={fetchStatus}
            className="text-xs text-accent-signal hover:underline font-display"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const currentStatus = getStatus(status);

  return (
    <div className="p-6 overflow-y-auto h-full space-y-6">
      {/* Recommendation Summary */}
      <div className="bg-bg-concrete rounded-lg border border-border-gutter p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <span
              className={clsx(
                "text-xl font-display font-bold px-4 py-1.5 rounded-lg",
                recommendation.action === "BUY" && "bg-accent-profit/15 text-accent-profit",
                recommendation.action === "SELL" && "bg-accent-loss/15 text-accent-loss",
                recommendation.action === "HOLD" && "bg-accent-alert/15 text-accent-alert",
              )}
            >
              {recommendation.action}
            </span>
            <span className="text-2xl font-display font-bold text-text-primary">
              {recommendation.ticker}
            </span>
          </div>
          <div className="text-right">
            <span className="text-xs text-text-muted font-body block">Confidence</span>
            <span className="text-xl font-display font-bold tabular-nums text-text-primary">
              {(recommendation.confidence * 100).toFixed(0)}%
            </span>
          </div>
        </div>

        <div className="grid grid-cols-3 sm:grid-cols-5 gap-3">
          <ParamBlock
            label="Entry"
            value={recommendation.entry_price != null ? `$${recommendation.entry_price.toFixed(2)}` : "—"}
          />
          <ParamBlock
            label="Stop Loss"
            value={recommendation.stop_loss != null ? `$${recommendation.stop_loss.toFixed(2)}` : "—"}
            icon={<ShieldAlert className="w-3 h-3 text-accent-loss" />}
          />
          <ParamBlock
            label="Target"
            value={recommendation.take_profit != null ? `$${recommendation.take_profit.toFixed(2)}` : "—"}
            icon={<Target className="w-3 h-3 text-accent-profit" />}
          />
          <ParamBlock
            label="R:R"
            value={recommendation.risk_reward_ratio != null ? recommendation.risk_reward_ratio.toFixed(1) : "—"}
          />
          <ParamBlock
            label="Hold"
            value={recommendation.holding_period || "—"}
            icon={<Clock className="w-3 h-3 text-accent-alert" />}
          />
        </div>
      </div>

      {/* Decision Section */}
      <AnimatePresence mode="wait">
        {currentStatus === "pending" && (
          <motion.div
            key="pending"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
          >
            <DecisionSection recId={recommendation.id} onComplete={fetchStatus} />
          </motion.div>
        )}

        {currentStatus === "following" && status && (
          <motion.div
            key="following"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="space-y-4"
          >
            <DecisionBadge decision="following" decidedAt={status.decided_at} />
            <OutcomeSection decisionId={status.decision_id!} onComplete={fetchStatus} />
            <UndoDecisionButton isUndoing={isUndoing} onUndo={handleUndo} label="Undo Follow" />
          </motion.div>
        )}

        {currentStatus === "passed" && status && (
          <motion.div
            key="passed"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="space-y-3"
          >
            <DecisionBadge
              decision="passing"
              decidedAt={status.decided_at}
              reason={status.decision_reason}
            />
            <UndoDecisionButton isUndoing={isUndoing} onUndo={handleUndo} label="Undo Pass" />
          </motion.div>
        )}

        {currentStatus === "closed" && status && !isEditing && (
          <motion.div
            key="closed"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="space-y-4"
          >
            <DecisionBadge decision="following" decidedAt={status.decided_at} />
            <OutcomeResult status={status} onEdit={() => setIsEditing(true)} />
          </motion.div>
        )}

        {currentStatus === "closed" && status && isEditing && (
          <motion.div
            key="editing"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="space-y-4"
          >
            <DecisionBadge decision="following" decidedAt={status.decided_at} />
            <OutcomeSection
              decisionId={status.decision_id!}
              outcomeId={status.outcome_id!}
              initialValues={{
                entryPrice: status.outcome_entry_price,
                exitPrice: status.outcome_exit_price,
                shares: status.outcome_shares,
                pnlDollars: status.outcome_pnl_dollars,
                pnlPercent: status.outcome_pnl_percent,
                holdingDays: status.outcome_holding_days,
                exitReason: status.outcome_exit_reason,
                notes: status.outcome_notes,
              }}
              onComplete={fetchStatus}
              onCancel={() => setIsEditing(false)}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type FeedbackStatus = "pending" | "following" | "passed" | "closed";

function getStatus(status: RecommendationWithStatus | null): FeedbackStatus {
  if (!status) return "pending";
  if (status.outcome_id) return "closed";
  if (status.decision === "following") return "following";
  if (status.decision === "passing") return "passed";
  return "pending";
}

function ParamBlock({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="bg-bg-void rounded-lg p-3 border border-border-gutter">
      <div className="flex items-center gap-1 mb-1">
        {icon}
        <span className="text-[10px] text-text-muted font-display uppercase tracking-wider">
          {label}
        </span>
      </div>
      <span className="text-sm font-display font-semibold text-text-primary tabular-nums">
        {value}
      </span>
    </div>
  );
}

function DecisionBadge({
  decision,
  decidedAt,
  reason,
}: {
  decision: "following" | "passing";
  decidedAt: string | null;
  reason?: string;
}) {
  const isFollowing = decision === "following";
  return (
    <div
      className={clsx(
        "rounded-lg p-4 border",
        isFollowing
          ? "bg-accent-profit-dim border-accent-profit/30"
          : "bg-bg-steel border-border-gutter",
      )}
    >
      <div className="flex items-center gap-2 mb-1">
        {isFollowing ? (
          <CheckCircle2 className="w-4 h-4 text-accent-profit" />
        ) : (
          <XCircle className="w-4 h-4 text-text-muted" />
        )}
        <span
          className={clsx(
            "text-sm font-display font-bold",
            isFollowing ? "text-accent-profit" : "text-text-muted",
          )}
        >
          {isFollowing ? "Following This Trade" : "Passed"}
        </span>
      </div>
      {decidedAt && (
        <p className="text-[10px] text-text-muted font-display ml-6">
          {new Date(decidedAt).toLocaleString()}
        </p>
      )}
      {reason && (
        <p className="text-xs text-text-secondary font-body mt-2 ml-6">{reason}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Decision Section (Follow / Pass)
// ---------------------------------------------------------------------------

const REASON_CATEGORIES = [
  "conviction",
  "risk_too_high",
  "timing",
  "position_sizing",
  "already_exposed",
  "other",
];

function DecisionSection({
  recId,
  onComplete,
}: {
  recId: string;
  onComplete: () => void;
}) {
  const [showPassForm, setShowPassForm] = useState(false);
  const [reason, setReason] = useState("");
  const [category, setCategory] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFollow = async () => {
    setIsSaving(true);
    setError(null);
    try {
      await api.createDecision(recId, { decision: "following" });
      notifyFeedbackChanged();
      onComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to record decision");
    } finally {
      setIsSaving(false);
    }
  };

  const handlePass = async () => {
    setIsSaving(true);
    setError(null);
    try {
      const body: DecisionCreate = {
        decision: "passing",
        reason: reason || undefined,
        reason_category: category || undefined,
      };
      await api.createDecision(recId, body);
      notifyFeedbackChanged();
      onComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to record decision");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="bg-bg-concrete rounded-lg border border-border-gutter p-5 space-y-4">
      <h3 className="text-sm font-display font-semibold text-text-secondary">
        What did you do with this recommendation?
      </h3>

      {error && (
        <p className="text-xs text-accent-loss font-body">{error}</p>
      )}

      {!showPassForm ? (
        <div className="flex items-center gap-3">
          <button
            onClick={handleFollow}
            disabled={isSaving}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-display font-semibold bg-accent-profit-dim text-accent-profit hover:bg-accent-profit/20 transition-all active:scale-95"
          >
            {isSaving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <CheckCircle2 className="w-4 h-4" />
            )}
            Took the Trade
          </button>
          <button
            onClick={() => setShowPassForm(true)}
            disabled={isSaving}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-display font-semibold bg-bg-steel text-text-muted hover:text-text-secondary transition-all active:scale-95"
          >
            <XCircle className="w-4 h-4" />
            Passed
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-display font-semibold text-text-secondary">
              Why did you pass?
            </span>
            <button
              onClick={() => setShowPassForm(false)}
              className="text-text-muted hover:text-text-secondary"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="flex flex-wrap gap-2">
            {REASON_CATEGORIES.map((cat) => (
              <button
                key={cat}
                onClick={() => setCategory(cat === category ? "" : cat)}
                className={clsx(
                  "px-3 py-1.5 rounded-md text-xs font-display transition-colors",
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
            placeholder="Any additional notes on why you passed..."
            rows={2}
            className="w-full bg-bg-void border border-border-gutter rounded-lg px-3 py-2 text-sm font-body text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-signal resize-none"
          />

          <button
            onClick={handlePass}
            disabled={isSaving}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-display font-medium bg-bg-steel text-text-secondary hover:text-text-primary transition-colors"
          >
            {isSaving ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Send className="w-3.5 h-3.5" />
            )}
            Record Pass
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Outcome Section (create or edit)
// ---------------------------------------------------------------------------

const EXIT_REASONS = ["hit_target", "hit_stop", "manual_exit", "time_exit"];

interface OutcomeInitialValues {
  entryPrice: number | null;
  exitPrice: number | null;
  shares: number | null;
  pnlDollars: number | null;
  pnlPercent: number | null;
  holdingDays: number | null;
  exitReason: string;
  notes: string;
}

function numToStr(v: number | null | undefined): string {
  return v != null ? String(v) : "";
}

function OutcomeSection({
  decisionId,
  outcomeId,
  initialValues,
  onComplete,
  onCancel,
}: {
  decisionId: string;
  outcomeId?: string;
  initialValues?: OutcomeInitialValues;
  onComplete: () => void;
  onCancel?: () => void;
}) {
  const isEdit = !!outcomeId;
  const [entryPrice, setEntryPrice] = useState(numToStr(initialValues?.entryPrice));
  const [exitPrice, setExitPrice] = useState(numToStr(initialValues?.exitPrice));
  const [shares, setShares] = useState(numToStr(initialValues?.shares));
  const [pnlDollars, setPnlDollars] = useState(numToStr(initialValues?.pnlDollars));
  const [pnlPercent, setPnlPercent] = useState(numToStr(initialValues?.pnlPercent));
  const [holdingDays, setHoldingDays] = useState(numToStr(initialValues?.holdingDays));
  const [exitReason, setExitReason] = useState(initialValues?.exitReason || "");
  const [notes, setNotes] = useState(initialValues?.notes || "");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    setIsSaving(true);
    setError(null);
    try {
      const body: OutcomeCreate = {
        entry_price: entryPrice ? parseFloat(entryPrice) : null,
        exit_price: exitPrice ? parseFloat(exitPrice) : null,
        shares: shares ? parseInt(shares) : null,
        pnl_dollars: pnlDollars ? parseFloat(pnlDollars) : null,
        pnl_percent: pnlPercent ? parseFloat(pnlPercent) : null,
        holding_days: holdingDays ? parseInt(holdingDays) : null,
        exit_reason: exitReason || undefined,
        notes: notes || undefined,
      };
      if (isEdit) {
        await api.updateOutcome(outcomeId, body);
      } else {
        await api.createOutcome(decisionId, body);
      }
      notifyFeedbackChanged();
      onComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save outcome");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="bg-bg-concrete rounded-lg border border-accent-profit/20 p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-display font-semibold text-accent-profit">
          {isEdit ? "Edit Trade Outcome" : "How did this trade go?"}
        </h3>
        {onCancel && (
          <button
            onClick={onCancel}
            className="text-text-muted hover:text-text-secondary transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {error && <p className="text-xs text-accent-loss font-body">{error}</p>}

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <FormInput label="Entry Price" value={entryPrice} onChange={setEntryPrice} placeholder="0.00" type="number" />
        <FormInput label="Exit Price" value={exitPrice} onChange={setExitPrice} placeholder="0.00" type="number" />
        <FormInput label="Shares" value={shares} onChange={setShares} placeholder="0" type="number" />
        <FormInput label="P&L ($)" value={pnlDollars} onChange={setPnlDollars} placeholder="0.00" type="number" />
        <FormInput label="P&L (%)" value={pnlPercent} onChange={setPnlPercent} placeholder="0.00" type="number" />
        <FormInput label="Hold (days)" value={holdingDays} onChange={setHoldingDays} placeholder="0" type="number" />
      </div>

      <div>
        <span className="text-[10px] text-text-muted font-display uppercase tracking-wider block mb-2">
          What happened?
        </span>
        <div className="flex flex-wrap gap-2">
          {EXIT_REASONS.map((er) => (
            <button
              key={er}
              onClick={() => setExitReason(er === exitReason ? "" : er)}
              className={clsx(
                "px-3 py-1.5 rounded-md text-xs font-display transition-colors",
                er === exitReason
                  ? er === "hit_target"
                    ? "bg-accent-profit text-white"
                    : er === "hit_stop"
                      ? "bg-accent-loss text-white"
                      : "bg-accent-signal text-white"
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
        placeholder="Notes on this trade — what went right, what you'd do differently..."
        rows={3}
        className="w-full bg-bg-void border border-border-gutter rounded-lg px-3 py-2 text-sm font-body text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-signal resize-none"
      />

      <div className="flex items-center gap-3">
        <button
          onClick={handleSubmit}
          disabled={isSaving}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-display font-semibold bg-accent-profit-dim text-accent-profit hover:bg-accent-profit/20 transition-all active:scale-95"
        >
          {isSaving ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Send className="w-4 h-4" />
          )}
          {isEdit ? "Update Outcome" : "Save Outcome"}
        </button>
        {onCancel && (
          <button
            onClick={onCancel}
            className="px-4 py-2.5 rounded-lg text-sm font-display text-text-muted hover:text-text-secondary transition-colors"
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}

function FormInput({
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
      <span className="text-[10px] text-text-muted font-display uppercase tracking-wider block mb-1.5">
        {label}
      </span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-bg-void border border-border-gutter rounded-lg px-3 py-2 text-sm font-display text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-signal tabular-nums"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Outcome Result (closed trade — with edit button)
// ---------------------------------------------------------------------------

function OutcomeResult({
  status,
  onEdit,
}: {
  status: RecommendationWithStatus;
  onEdit: () => void;
}) {
  const pnl = status.outcome_pnl_dollars ?? 0;
  const isWin = pnl > 0;
  const isLoss = pnl < 0;

  return (
    <div
      className={clsx(
        "rounded-lg p-5 border",
        isWin
          ? "bg-accent-profit-dim border-accent-profit/30"
          : isLoss
            ? "bg-accent-loss-dim border-accent-loss/30"
            : "bg-bg-steel border-border-gutter",
      )}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {isWin ? (
            <ArrowUpRight className="w-5 h-5 text-accent-profit" />
          ) : isLoss ? (
            <ArrowDownRight className="w-5 h-5 text-accent-loss" />
          ) : null}
          <span className="text-sm font-display font-semibold text-text-secondary">
            Trade Result
          </span>
        </div>
        <div className="flex items-center gap-4">
          <button
            onClick={onEdit}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-display font-medium text-text-muted hover:text-text-secondary bg-bg-void/50 hover:bg-bg-void border border-border-gutter transition-colors"
          >
            <Pencil className="w-3 h-3" />
            Edit
          </button>
          <div className="text-right">
            <span
              className={clsx(
                "text-2xl font-display font-bold tabular-nums",
                isWin ? "text-accent-profit" : isLoss ? "text-accent-loss" : "text-text-primary",
              )}
            >
              {pnl >= 0 ? "+" : ""}${pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </span>
            {status.outcome_pnl_percent != null && (
              <p
                className={clsx(
                  "text-sm font-display tabular-nums",
                  isWin ? "text-accent-profit/70" : isLoss ? "text-accent-loss/70" : "text-text-muted",
                )}
              >
                {status.outcome_pnl_percent >= 0 ? "+" : ""}
                {status.outcome_pnl_percent.toFixed(2)}%
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Detail grid for recorded outcome data */}
      <div className="grid grid-cols-3 sm:grid-cols-5 gap-2 mt-3">
        {status.outcome_entry_price != null && (
          <MiniStat label="Entry" value={`$${status.outcome_entry_price.toFixed(2)}`} />
        )}
        {status.outcome_exit_price != null && (
          <MiniStat label="Exit" value={`$${status.outcome_exit_price.toFixed(2)}`} />
        )}
        {status.outcome_shares != null && (
          <MiniStat label="Shares" value={String(status.outcome_shares)} />
        )}
        {status.outcome_holding_days != null && (
          <MiniStat label="Days" value={String(status.outcome_holding_days)} />
        )}
        {status.outcome_exit_reason && (
          <div className="flex flex-col">
            <span className="text-[10px] text-text-muted font-display uppercase tracking-wider">Exit</span>
            <span
              className={clsx(
                "text-xs font-display font-semibold mt-0.5",
                status.outcome_exit_reason === "hit_target" && "text-accent-profit",
                status.outcome_exit_reason === "hit_stop" && "text-accent-loss",
                status.outcome_exit_reason !== "hit_target" &&
                  status.outcome_exit_reason !== "hit_stop" &&
                  "text-text-secondary",
              )}
            >
              {status.outcome_exit_reason.replace(/_/g, " ")}
            </span>
          </div>
        )}
      </div>

      {status.outcome_notes && (
        <p className="text-xs text-text-secondary font-body mt-3 border-t border-border-gutter pt-3">
          {status.outcome_notes}
        </p>
      )}

      {status.outcome_logged_at && (
        <p className="text-[10px] text-text-muted font-display mt-2">
          Logged {new Date(status.outcome_logged_at).toLocaleString()}
        </p>
      )}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] text-text-muted font-display uppercase tracking-wider">{label}</span>
      <span className="text-xs font-display font-semibold text-text-primary tabular-nums mt-0.5">{value}</span>
    </div>
  );
}

function UndoDecisionButton({
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
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-display font-medium text-text-muted hover:text-accent-loss transition-colors"
    >
      {isUndoing ? <Loader2 className="w-3 h-3 animate-spin" /> : <Undo2 className="w-3 h-3" />}
      {label}
    </button>
  );
}
