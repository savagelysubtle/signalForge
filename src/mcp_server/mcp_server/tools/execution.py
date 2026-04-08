"""MCP tools for IBKR order execution with confirm-first safety pattern."""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp_server.backend.client import get_backend_client
from mcp_server.config import settings
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
    quantity = calculate_quantity(equity, size_pct, entry_price, settings.max_position_size_pct)

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
    }

    if quantity == 0:
        preview["warning"] = "Calculated quantity is 0 — position size too small for entry price"

    # Run risk gates
    positions = await get_positions()
    risk_result = await run_risk_gates(rec, account, positions)
    preview["risk_gates"] = risk_result.to_dict()
    if not risk_result.passed:
        preview["risk_blocked"] = True

    return json.dumps(preview, indent=2)


async def place_order(
    rec_id: str, confirmed: bool = False, size_override_pct: float | None = None
) -> str:
    """Place a bracket order for a recommendation on IBKR.

    REQUIRES confirmed=true. Call preview_order first to review the trade,
    then call this with confirmed=true after user approval.

    Args:
        rec_id: The recommendation ID from a pipeline result.
        confirmed: Must be true to actually place the order. Safety gate.
        size_override_pct: Override position size percent (optional, max 5%).
    """
    if not confirmed:
        return json.dumps(
            {
                "error": "Order not confirmed. Call preview_order first, then place_order with confirmed=true after user approval.",
                "hint": "This is a safety gate — orders require explicit confirmation.",
            }
        )

    rec = await _fetch_recommendation(rec_id)
    if "error" in rec:
        return json.dumps(rec)

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
    quantity = calculate_quantity(equity, size_pct, entry_price, settings.max_position_size_pct)

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
    contract = build_contract(rec.get("ticker", ""))
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

    contract = build_contract(ticker)
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
