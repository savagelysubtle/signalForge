"""Position health vs planned risk levels (IBKR + open outcomes)."""

from __future__ import annotations

import json
from typing import Any

from mcp_server.backend.client import get_backend_client
from mcp_server.ibkr.portfolio import get_open_orders, get_positions


def _bare_symbol(ticker: str) -> str:
    t = ticker.strip().upper()
    return t.split(":", 1)[-1] if ":" in t else t


async def check_position_health() -> str:
    """Compare IBKR stock positions to open SignalForge outcomes (stop / target / brackets).

    Flags distance to planned stop and take-profit, and whether any open orders
    exist for the symbol (heuristic bracket health).
    """
    client = get_backend_client()
    try:
        open_outcomes = await client.list_open_outcomes(source="ibkr", limit=200)
    except Exception as exc:
        return json.dumps({"error": f"Failed to list open outcomes: {exc}"})

    positions = await get_positions()
    orders = await get_open_orders()

    stks = [
        p
        for p in positions
        if p.get("sec_type") == "STK" and abs(float(p.get("quantity") or 0)) > 1e-6
    ]
    sym_to_pos = {_bare_symbol(str(p.get("ticker", ""))): p for p in stks}

    orders_by_sym: dict[str, list[dict[str, Any]]] = {}
    for o in orders:
        sym = _bare_symbol(str(o.get("ticker", "")))
        orders_by_sym.setdefault(sym, []).append(o)

    items: list[dict[str, Any]] = []
    for row in open_outcomes:
        sym = _bare_symbol(str(row.get("ticker", "")))
        pos = sym_to_pos.get(sym)
        entry = row.get("entry_price")
        stop = row.get("stop_loss")
        tp = row.get("take_profit")
        if pos is None:
            items.append(
                {
                    "outcome_id": row.get("id"),
                    "symbol": sym,
                    "status": "no_matching_ibkr_position",
                    "detail": "Open outcome but no STK position — run sync_brokerage_exits or verify ticker.",
                }
            )
            continue

        qty = float(pos.get("quantity") or 0)
        last = float(pos.get("market_price") or 0.0)
        if last <= 0:
            last = float(pos.get("avg_cost") or 0.0)

        health: dict[str, Any] = {
            "outcome_id": row.get("id"),
            "symbol": sym,
            "ibkr_quantity": qty,
            "market_price": round(last, 4) if last else None,
            "entry_price": entry,
            "stop_loss": stop,
            "take_profit": tp,
            "open_orders_for_symbol": len(orders_by_sym.get(sym, [])),
        }

        if qty > 0 and entry and stop and float(entry) > float(stop):
            risk_1r = float(entry) - float(stop)
            if risk_1r > 0 and last:
                cushion = (last - float(stop)) / risk_1r
                health["distance_to_stop_in_R"] = round(cushion, 3)
        if qty > 0 and tp and last:
            health["distance_to_target_pct"] = round((float(tp) - last) / last * 100, 2)

        olist = orders_by_sym.get(sym, [])
        if not olist:
            health["bracket_warning"] = (
                "No open orders visible for symbol — verify bracket still attached in TWS."
            )
        items.append(health)

    for sym, pos in sym_to_pos.items():
        if not any(_bare_symbol(str(r.get("ticker", ""))) == sym for r in open_outcomes):
            items.append(
                {
                    "symbol": sym,
                    "status": "untracked_ibkr_position",
                    "ibkr_quantity": pos.get("quantity"),
                    "detail": "Position exists without matching open ibkr outcome row.",
                }
            )

    return json.dumps({"positions_checked": len(stks), "items": items}, indent=2)
