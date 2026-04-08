"""IBKR account, position, and order data retrieval."""

from __future__ import annotations

from typing import Any

from mcp_server.ibkr.client import get_ibkr_client


async def get_account_summary() -> dict[str, Any]:
    """Fetch account summary from IBKR.

    Returns:
        Dict with key account metrics: net_liquidation, buying_power,
        total_cash, unrealized_pnl, realized_pnl, gross_position_value.
    """
    ib = await get_ibkr_client().ensure_connected()
    values = ib.accountSummary()

    tags = {
        "NetLiquidation": "net_liquidation",
        "BuyingPower": "buying_power",
        "TotalCashValue": "total_cash",
        "UnrealizedPnL": "unrealized_pnl",
        "RealizedPnL": "realized_pnl",
        "GrossPositionValue": "gross_position_value",
        "AvailableFunds": "available_funds",
        "MaintMarginReq": "margin_required",
    }

    result: dict[str, Any] = {"account": "", "currency": "USD"}
    for v in values:
        if v.currency not in ("USD", "BASE"):
            continue
        mapped = tags.get(v.tag)
        if mapped:
            result[mapped] = _safe_float(v.value)
            if not result["account"]:
                result["account"] = v.account

    return result


async def get_positions() -> list[dict[str, Any]]:
    """Fetch current portfolio positions from IBKR.

    Returns:
        List of position dicts with ticker, quantity, avg_cost, market_value,
        unrealized_pnl.
    """
    ib = await get_ibkr_client().ensure_connected()
    portfolio_items = ib.portfolio()

    positions: list[dict[str, Any]] = []
    for item in portfolio_items:
        positions.append(
            {
                "ticker": item.contract.symbol,
                "sec_type": item.contract.secType,
                "exchange": item.contract.exchange,
                "quantity": item.position,
                "avg_cost": item.averageCost,
                "market_price": item.marketPrice,
                "market_value": item.marketValue,
                "unrealized_pnl": item.unrealizedPNL,
                "realized_pnl": item.realizedPNL,
            }
        )
    return positions


async def get_open_orders() -> list[dict[str, Any]]:
    """Fetch open (pending) orders from IBKR.

    Returns:
        List of order dicts with order_id, ticker, action, quantity,
        order_type, limit_price, stop_price, status.
    """
    ib = await get_ibkr_client().ensure_connected()
    trades = ib.openTrades()

    orders: list[dict[str, Any]] = []
    for trade in trades:
        order = trade.order
        status = trade.orderStatus
        orders.append(
            {
                "order_id": order.orderId,
                "perm_id": order.permId,
                "parent_id": order.parentId,
                "ticker": trade.contract.symbol,
                "action": order.action,
                "quantity": order.totalQuantity,
                "order_type": order.orderType,
                "limit_price": order.lmtPrice,
                "stop_price": getattr(order, "auxPrice", None),
                "status": status.status,
                "filled": status.filled,
                "remaining": status.remaining,
                "avg_fill_price": status.avgFillPrice,
            }
        )
    return orders


def _safe_float(value: str) -> float:
    """Convert a string to float, returning 0.0 on failure.

    Args:
        value: String value from IBKR account data.

    Returns:
        Parsed float or 0.0 if parsing fails.
    """
    try:
        return float(value)
    except ValueError, TypeError:
        return 0.0
