/**
 * Centralized PnL calculation matching the backend `services/pnl.py` logic.
 *
 * Used by OutcomeForm, EditOutcomeForm, and FeedbackTab to auto-fill PnL
 * fields when entry/exit/shares change.
 */

export interface PnLResult {
  grossPnl: number;
  netPnl: number;
  pnlPercent: number | null;
  rMultiple: number | null;
}

/**
 * Direction-aware PnL calculation.
 *
 * BUY profits when price rises, SHORT profits when price falls.
 */
export function calculatePnl(
  action: string,
  entryPrice: number,
  exitPrice: number,
  shares: number,
  commission = 0,
  stopLoss?: number | null,
): PnLResult {
  const sign = action === "SHORT" ? -1 : 1;
  const gross = Math.round(sign * (exitPrice - entryPrice) * shares * 100) / 100;
  const net = Math.round((gross - commission) * 100) / 100;

  let pnlPercent: number | null = null;
  if (entryPrice > 0) {
    pnlPercent =
      Math.round(sign * ((exitPrice - entryPrice) / entryPrice) * 100 * 100) / 100;
  }

  let rMultiple: number | null = null;
  if (stopLoss != null && entryPrice > 0) {
    const riskPerShare = Math.abs(entryPrice - stopLoss);
    if (riskPerShare > 0) {
      const pnlPerShare = sign * (exitPrice - entryPrice);
      rMultiple = Math.round((pnlPerShare / riskPerShare) * 100) / 100;
    }
  }

  return { grossPnl: gross, netPnl: net, pnlPercent, rMultiple };
}

/** Return exit price if set, otherwise fall back to stop loss. */
export function resolveExitPrice(
  exitPrice: number | null | undefined,
  stopLoss: number | null | undefined,
): number | null {
  if (exitPrice != null && !isNaN(exitPrice)) return exitPrice;
  if (stopLoss != null && !isNaN(stopLoss)) return stopLoss;
  return null;
}
