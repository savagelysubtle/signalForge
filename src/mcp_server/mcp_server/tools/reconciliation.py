"""Reconcile IBKR portfolio state with Supabase trade outcomes."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from mcp_server.backend.client import get_backend_client
from mcp_server.ibkr.fills import aggregate_exit_leg, get_fills_snapshot, parse_fill_time
from mcp_server.ibkr.portfolio import get_positions

logger = logging.getLogger(__name__)


def _bare_symbol(ticker: str) -> str:
    t = ticker.strip().upper()
    return t.split(":", 1)[-1] if ":" in t else t


def _parse_entry_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return parse_fill_time(raw)


async def sync_brokerage_exits() -> str:
    """Close open ``ibkr`` outcomes when IBKR shows a flat position.

    Uses SLD fills after the outcome entry time to estimate exit VWAP, commission,
    and P&amp;L, then PATCHes the outcome. Rows stay unchanged if the symbol is
    still held, or if no matching sell fills are found (see status in output).
    """
    client = get_backend_client()
    try:
        open_rows = await client.list_open_outcomes(source="ibkr", limit=200)
    except Exception as exc:
        return json.dumps({"error": f"Failed to list open outcomes: {exc}"})

    if not open_rows:
        return json.dumps({"updated": [], "skipped": [], "message": "No open ibkr outcomes"})

    positions = await get_positions()
    qty_by_sym: dict[str, float] = {}
    for p in positions:
        if p.get("sec_type") != "STK":
            continue
        sym = _bare_symbol(str(p.get("ticker", "")))
        qty_by_sym[sym] = float(p.get("quantity") or 0)

    fills = await get_fills_snapshot()
    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for row in open_rows:
        oid = row.get("id")
        ticker = str(row.get("ticker", ""))
        sym = _bare_symbol(ticker)
        shares = int(row.get("shares") or 0)
        entry_px = float(row.get("entry_price") or 0.0)
        if not oid or shares <= 0 or entry_px <= 0:
            skipped.append({"id": oid, "reason": "invalid_open_row"})
            continue

        held = qty_by_sym.get(sym, 0.0)
        if abs(held) > 1e-6:
            skipped.append(
                {"id": oid, "symbol": sym, "status": "still_open", "ibkr_quantity": held}
            )
            continue

        entry_dt = _parse_entry_ts(
            str(row["entry_timestamp"]) if row.get("entry_timestamp") else None
        )
        vwap, commission, last_fill_t = aggregate_exit_leg(fills, sym, entry_dt, shares)
        if vwap is None or last_fill_t is None:
            skipped.append(
                {
                    "id": oid,
                    "symbol": sym,
                    "status": "flat_no_exit_fills",
                    "hint": "Close may be unsettled in IBKR fills or outside API window — log exit manually.",
                }
            )
            continue

        gross = (vwap - entry_px) * shares
        net = gross - commission
        pnl_pct = ((vwap - entry_px) / entry_px * 100) if entry_px else 0.0
        exit_ts = last_fill_t.astimezone(UTC).isoformat()
        hold_days = 0
        if entry_dt:
            hold_days = max(0, (last_fill_t.date() - entry_dt.date()).days)

        tp = row.get("take_profit")
        exit_vs_tp_pct: float | None = None
        if tp is not None and float(tp) > 0:
            exit_vs_tp_pct = round((float(tp) - vwap) / float(tp) * 100, 4)

        prior_struct = row.get("structured_analysis")
        struct: dict[str, Any] = dict(prior_struct) if isinstance(prior_struct, dict) else {}
        struct["ibkr_exit"] = {
            "vwap": round(vwap, 4),
            "commission": round(commission, 4),
            "exit_vs_take_profit_pct": exit_vs_tp_pct,
            "matched_shares": shares,
        }

        payload = {
            "exit_price": round(vwap, 4),
            "exit_timestamp": exit_ts,
            "pnl_dollars": round(net, 2),
            "pnl_percent": round(pnl_pct, 4),
            "gross_pnl": round(gross, 2),
            "net_pnl": round(net, 2),
            "commission": round(commission, 4),
            "holding_days": hold_days,
            "exit_reason": "ibkr_sync_flat",
            "structured_analysis": struct,
        }

        try:
            out = await client.patch_outcome(str(oid), payload)
            updated.append({"id": oid, "symbol": sym, "outcome": out})
        except Exception as exc:
            logger.warning("patch outcome %s failed: %s", oid, exc)
            skipped.append({"id": oid, "symbol": sym, "status": "patch_failed", "error": str(exc)})

    return json.dumps(
        {
            "updated_count": len(updated),
            "skipped_count": len(skipped),
            "updated": updated,
            "skipped": skipped,
        },
        indent=2,
    )
