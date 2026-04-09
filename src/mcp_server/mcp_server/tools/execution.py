"""MCP tools for IBKR order execution with confirm-first safety pattern."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from mcp_server.backend.client import get_backend_client
from mcp_server.config import REGIME_POSITION_MULTIPLIERS, settings
from mcp_server.ibkr.client import get_ibkr_client
from mcp_server.ibkr.orders import (
    build_bracket_order,
    build_close_order,
    build_contract,
    calculate_quantity,
    close_action_for_position,
    map_action_to_ib,
)
from mcp_server.ibkr.portfolio import get_account_summary, get_positions
from mcp_server.ibkr.risk_gates import record_order_placed, run_risk_gates

logger = logging.getLogger(__name__)


async def _regime_adjusted_quantity(base_qty: int) -> tuple[int, str, float]:
    """Scale share count by backend heartbeat regime when enabled."""
    if not settings.regime_sizing_enabled or base_qty <= 0:
        return base_qty, "off", 1.0
    try:
        hb = await get_backend_client().get_market_heartbeat()
        rt = str(hb.get("regime_type") or "")
    except Exception as exc:
        logger.warning("Regime heartbeat failed: %s", exc)
        return base_qty, "heartbeat_error", 1.0
    mult = REGIME_POSITION_MULTIPLIERS.get(rt, 1.0)
    return max(0, int(base_qty * mult)), rt, mult


async def preview_order(rec_id: str, size_override_pct: float | None = None) -> str:
    """Preview an order for a recommendation WITHOUT placing it.

    Shows what would be traded: ticker, action, quantity, entry price, stop loss,
    take profit, estimated cost, and risk check results. Use this before place_order
    to review the trade with the user.

    Args:
        rec_id: The recommendation ID from a pipeline result.
        size_override_pct: Override position size percent (optional, max 5%).
    """
    rec = await _fetch_recommendation(rec_id)
    if "error" in rec:
        return json.dumps(rec)

    ib_action = map_action_to_ib(rec.get("action", ""))
    if not ib_action:
        return json.dumps(
            {
                "error": f"Action '{rec.get('action')}' is not tradeable (only BUY/SHORT)",
                "recommendation": _rec_summary(rec),
            }
        )

    missing = _check_required_fields(rec)
    if missing:
        return json.dumps({"error": f"Missing required fields: {', '.join(missing)}"})

    account = await get_account_summary()
    equity = account.get("net_liquidation", 0.0)

    size_pct = (
        size_override_pct if size_override_pct is not None else rec.get("position_size_pct", 0.0)
    )
    entry_price = rec["entry_price"]
    base_quantity = calculate_quantity(
        equity, size_pct, entry_price, settings.max_position_size_pct
    )
    quantity, regime_type, regime_mult = await _regime_adjusted_quantity(base_quantity)

    estimated_cost = quantity * entry_price
    risk_per_share = abs(entry_price - rec["stop_loss"])
    total_risk = risk_per_share * quantity

    preview: dict[str, Any] = {
        "recommendation_id": rec_id,
        "ticker": rec.get("ticker"),
        "action": ib_action,
        "quantity": quantity,
        "entry_price": entry_price,
        "stop_loss": rec["stop_loss"],
        "take_profit": rec["take_profit"],
        "estimated_cost": round(estimated_cost, 2),
        "total_risk": round(total_risk, 2),
        "risk_reward_ratio": rec.get("risk_reward_ratio"),
        "position_size_pct": round(size_pct, 2),
        "confidence": rec.get("confidence"),
        "ml_blocked": rec.get("ml_blocked", False),
        "account_equity": round(equity, 2),
        "buying_power": account.get("buying_power", 0.0),
        "paper_account": settings.ibkr_paper,
        "order_type": "BRACKET (limit entry + stop loss + take profit)",
        "base_quantity": base_quantity,
        "regime_type": regime_type,
        "regime_multiplier": regime_mult,
        "regime_sizing_enabled": settings.regime_sizing_enabled,
    }

    if base_quantity > 0 and quantity == 0:
        preview["warning"] = (
            "Regime sizing reduced quantity to 0 — increase size or disable REGIME_SIZING_ENABLED"
        )
    elif quantity == 0:
        preview["warning"] = "Calculated quantity is 0 — position size too small for entry price"

    # Run risk gates
    positions = await get_positions()
    risk_result = await run_risk_gates(rec, account, positions)
    preview["risk_gates"] = risk_result.to_dict()
    if not risk_result.passed:
        preview["risk_blocked"] = True

    return json.dumps(preview, indent=2)


async def place_order(
    rec_id: str,
    confirmed: bool = False,
    auto: bool = False,
    size_override_pct: float | None = None,
) -> str:
    """Place a bracket order for a recommendation on IBKR.

    Default: ``confirmed=true`` after human approval. Optional automation: set
    environment ``AUTO_EXECUTE_ENABLED=true`` and call with ``auto=true``; the
    order proceeds only if confidence is at least ``AUTO_EXECUTE_MIN_CONFIDENCE``
    (default 0.75) and every risk gate passes.

    Args:
        rec_id: The recommendation ID from a pipeline result.
        confirmed: Must be true unless auto-execute path applies.
        auto: Request auto-execute (requires env opt-in + confidence threshold).
        size_override_pct: Override position size percent (optional, max 5%).
    """
    rec = await _fetch_recommendation(rec_id)
    if "error" in rec:
        return json.dumps(rec)

    conf = float(rec.get("confidence") or 0.0)
    allow_auto = (
        settings.auto_execute_enabled and auto and conf >= settings.auto_execute_min_confidence
    )
    if not confirmed and not allow_auto:
        if auto and not settings.auto_execute_enabled:
            return json.dumps(
                {
                    "error": "Auto-execute is disabled. Set AUTO_EXECUTE_ENABLED=true in the MCP environment.",
                }
            )
        if auto and conf < settings.auto_execute_min_confidence:
            return json.dumps(
                {
                    "error": (
                        f"Confidence {conf:.2f} is below auto-execute minimum "
                        f"{settings.auto_execute_min_confidence:.2f}"
                    ),
                }
            )
        return json.dumps(
            {
                "error": "Order not confirmed. Call preview_order first, then place_order with confirmed=true after user approval.",
                "hint": "This is a safety gate — orders require explicit confirmation (or auto=true with AUTO_EXECUTE_ENABLED).",
            }
        )

    ib_action = map_action_to_ib(rec.get("action", ""))
    if not ib_action:
        return json.dumps({"error": f"Action '{rec.get('action')}' is not tradeable"})

    missing = _check_required_fields(rec)
    if missing:
        return json.dumps({"error": f"Missing required fields: {', '.join(missing)}"})

    account = await get_account_summary()
    equity = account.get("net_liquidation", 0.0)

    size_pct = (
        size_override_pct if size_override_pct is not None else rec.get("position_size_pct", 0.0)
    )
    entry_price = rec["entry_price"]
    base_quantity = calculate_quantity(
        equity, size_pct, entry_price, settings.max_position_size_pct
    )
    quantity, regime_type, regime_mult = await _regime_adjusted_quantity(base_quantity)

    if base_quantity > 0 and quantity == 0:
        return json.dumps(
            {
                "error": "Regime sizing reduced quantity to 0 — cannot place order",
                "regime_type": regime_type,
                "regime_multiplier": regime_mult,
            }
        )
    if quantity == 0:
        return json.dumps({"error": "Calculated quantity is 0 — cannot place order"})

    # Run risk gates — block if any fail
    positions = await get_positions()
    risk_result = await run_risk_gates(rec, account, positions)
    if not risk_result.passed:
        failed = [c for c in risk_result.checks if not c.passed]
        return json.dumps(
            {
                "error": "Risk gates blocked this order",
                "failed_checks": [{"name": c.name, "message": c.message} for c in failed],
                "all_checks": risk_result.to_dict(),
            }
        )

    # Build order components
    try:
        contract = build_contract(rec.get("ticker", ""))
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    bracket = build_bracket_order(
        action=ib_action,
        quantity=quantity,
        entry_price=entry_price,
        stop_loss=rec["stop_loss"],
        take_profit=rec["take_profit"],
    )

    # Submit to IBKR
    ib = await get_ibkr_client().ensure_connected()
    trades = []
    for order in bracket:
        trade = ib.placeOrder(contract, order)
        trades.append(trade)

    parent_trade = trades[0]
    record_order_placed()
    mode = "PAPER" if settings.ibkr_paper else "LIVE"
    logger.info(
        "[%s] Placed bracket order: %s %s x%s @ $%s (stop $%s / target $%s)",
        mode,
        ib_action,
        rec.get("ticker"),
        quantity,
        entry_price,
        rec["stop_loss"],
        rec["take_profit"],
    )

    outcome_note = ""
    try:
        bc = get_backend_client()
        sig_px = rec.get("entry_price")
        sig_px_f = float(sig_px) if sig_px is not None else None
        created = rec.get("created_at")
        await bc.post_brokerage_open(
            {
                "recommendation_id": rec_id,
                "shares": quantity,
                "entry_price": entry_price,
                "brokerage_order_id": str(parent_trade.order.orderId),
                "stop_loss": rec.get("stop_loss"),
                "take_profit": rec.get("take_profit"),
                "currency": "USD",
                "entry_timestamp": datetime.now(UTC).isoformat(),
                "notes": "MCP IBKR bracket submission",
                "signal_entry_price": sig_px_f,
                "signal_created_at": str(created) if created else None,
            }
        )
        outcome_note = "Recorded open outcome in SignalForge (brokerage-open)."
    except Exception as exc:
        logger.warning("Brokerage outcome logging failed (order still placed): %s", exc)
        outcome_note = f"Outcome logging failed: {exc}"

    return json.dumps(
        {
            "status": "submitted",
            "mode": mode,
            "order_id": parent_trade.order.orderId,
            "ticker": rec.get("ticker"),
            "action": ib_action,
            "quantity": quantity,
            "entry_price": entry_price,
            "stop_loss": rec["stop_loss"],
            "take_profit": rec["take_profit"],
            "order_status": parent_trade.orderStatus.status,
            "auto_executed": allow_auto,
            "outcome_log": outcome_note,
            "base_quantity": base_quantity,
            "regime_type": regime_type,
            "regime_multiplier": regime_mult,
        },
        indent=2,
    )


async def cancel_order(order_id: int) -> str:
    """Cancel a pending IBKR order.

    Args:
        order_id: The IBKR order ID to cancel.
    """
    ib = await get_ibkr_client().ensure_connected()

    target_order = None
    for trade in ib.openTrades():
        if trade.order.orderId == order_id:
            target_order = trade.order
            break

    if target_order is None:
        return json.dumps({"error": f"Order {order_id} not found in open orders"})

    ib.cancelOrder(target_order)
    logger.info("Cancelled order %s", order_id)
    return json.dumps({"status": "cancel_requested", "order_id": order_id})


async def close_position(ticker: str) -> str:
    """Close an entire position with a market order.

    Args:
        ticker: The ticker symbol to close (e.g. "AAPL" or "NASDAQ:AAPL").
    """
    positions = await get_positions()
    symbol = ticker.split(":")[-1].strip().upper() if ":" in ticker else ticker.strip().upper()

    target = None
    for pos in positions:
        if pos["ticker"].upper() == symbol:
            target = pos
            break

    if target is None:
        return json.dumps({"error": f"No open position found for {symbol}"})

    quantity = target["quantity"]
    action = close_action_for_position(quantity)
    if action is None:
        return json.dumps({"error": f"Position for {symbol} is flat (quantity=0)"})

    try:
        contract = build_contract(ticker)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    order = build_close_order(action, int(abs(quantity)))

    ib = await get_ibkr_client().ensure_connected()
    trade = ib.placeOrder(contract, order)

    mode = "PAPER" if settings.ibkr_paper else "LIVE"
    logger.info("[%s] Closing position: %s %s x%s", mode, action, symbol, abs(quantity))

    return json.dumps(
        {
            "status": "submitted",
            "mode": mode,
            "order_id": trade.order.orderId,
            "ticker": symbol,
            "action": action,
            "quantity": int(abs(quantity)),
            "order_type": "MARKET",
            "order_status": trade.orderStatus.status,
        },
        indent=2,
    )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


async def _fetch_recommendation(rec_id: str) -> dict[str, Any]:
    """Fetch a recommendation from the backend.

    Args:
        rec_id: Recommendation ID.

    Returns:
        Recommendation dict or error dict.
    """
    try:
        client = get_backend_client()
        return await client.get_recommendation(rec_id)
    except Exception as exc:
        return {"error": f"Failed to fetch recommendation {rec_id}: {exc}"}


def _check_required_fields(rec: dict[str, Any]) -> list[str]:
    """Check that a recommendation has the fields needed for order placement.

    Args:
        rec: Recommendation dict.

    Returns:
        List of missing field names (empty if all present).
    """
    missing = []
    for field in ("entry_price", "stop_loss", "take_profit"):
        if rec.get(field) is None:
            missing.append(field)
    return missing


def _rec_summary(rec: dict[str, Any]) -> dict[str, Any]:
    """Build a brief recommendation summary for error responses.

    Args:
        rec: Recommendation dict.

    Returns:
        Summary with key fields only.
    """
    return {
        "ticker": rec.get("ticker"),
        "action": rec.get("action"),
        "confidence": rec.get("confidence"),
        "entry_price": rec.get("entry_price"),
    }
