"""Centralized PnL calculation engine.

Provides a single source of truth for profit/loss calculations used by both
the Questrade auto-confirm flow and the manual outcome endpoints.  All PnL
logic — direction awareness, SL-as-exit fallback, R-multiple, holding days —
lives here so it stays consistent everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PnLResult:
    """Immutable result of a PnL calculation.

    Attributes:
        gross_pnl: Raw profit/loss before commissions.
        net_pnl: Profit/loss after commissions.
        pnl_percent: Return percentage on entry price.
        r_multiple: Risk-adjusted return (PnL / risk-per-share). ``None`` if
            stop loss was not provided or entry equals stop.
    """

    gross_pnl: float
    net_pnl: float
    pnl_percent: float | None
    r_multiple: float | None


def calculate_pnl(
    action: str,
    entry_price: float,
    exit_price: float,
    shares: int | float,
    *,
    commission: float = 0.0,
    stop_loss: float | None = None,
) -> PnLResult:
    """Calculate trade PnL with direction awareness.

    For BUY trades, profit = (exit - entry).
    For SHORT trades, profit = (entry - exit).

    Args:
        action: Trade direction — ``"BUY"``, ``"SHORT"``, or ``"HOLD"``
            (treated as BUY).
        entry_price: Average entry price per share.
        exit_price: Average exit price per share (or SL price if SL was hit).
        shares: Number of shares/contracts.
        commission: Total commissions and fees (entry + exit combined).
        stop_loss: Planned stop-loss price for R-multiple calculation.

    Returns:
        Populated ``PnLResult`` with gross, net, percent, and optional R-multiple.
    """
    sign = -1 if action == "SHORT" else 1
    gross = round(sign * (exit_price - entry_price) * shares, 2)
    net = round(gross - commission, 2)

    pnl_percent: float | None = None
    if entry_price > 0:
        pnl_percent = round(sign * ((exit_price - entry_price) / entry_price) * 100, 2)

    r_multiple: float | None = None
    if stop_loss is not None and entry_price > 0:
        risk_per_share = abs(entry_price - stop_loss)
        if risk_per_share > 0:
            pnl_per_share = sign * (exit_price - entry_price)
            r_multiple = round(pnl_per_share / risk_per_share, 2)

    return PnLResult(
        gross_pnl=gross,
        net_pnl=net,
        pnl_percent=pnl_percent,
        r_multiple=r_multiple,
    )


def resolve_exit_price(
    exit_price: float | None,
    stop_loss: float | None,
) -> float | None:
    """Return the effective exit price, falling back to stop loss.

    Args:
        exit_price: Explicit exit price (preferred).
        stop_loss: Stop-loss price used as fallback if exit_price is absent.

    Returns:
        The price to use for PnL calculation, or ``None`` if neither is set.
    """
    if exit_price is not None:
        return exit_price
    return stop_loss


def calculate_holding_days(
    entry_ts: str | None,
    exit_ts: str | None,
) -> int | None:
    """Compute the number of calendar days between entry and exit.

    Args:
        entry_ts: ISO-format entry timestamp string.
        exit_ts: ISO-format exit timestamp string.

    Returns:
        Non-negative day count, or ``None`` if either timestamp is missing or
        unparseable.
    """
    if not entry_ts or not exit_ts:
        return None
    try:
        dt_entry = datetime.fromisoformat(str(entry_ts))
        dt_exit = datetime.fromisoformat(str(exit_ts))
        return max(0, (dt_exit.date() - dt_entry.date()).days)
    except ValueError, TypeError:
        return None
