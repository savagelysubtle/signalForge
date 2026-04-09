"""MCP tools for IBKR account and portfolio data."""

from __future__ import annotations

import json

from mcp_server.config import settings
from mcp_server.ibkr import portfolio as ibkr_portfolio


async def get_account_summary() -> str:
    """Get your Interactive Brokers account summary.

    Returns buying power, net liquidation value, cash, unrealized/realized P&L,
    and margin information. Requires IBKR TWS or Gateway to be running.
    """
    summary = await ibkr_portfolio.get_account_summary()
    summary["paper_account"] = settings.ibkr_paper
    return json.dumps(summary, indent=2)


async def get_positions() -> str:
    """Get your current IBKR portfolio positions.

    Shows all open positions with ticker, quantity, average cost, market value,
    and unrealized P&L.
    """
    positions = await ibkr_portfolio.get_positions()
    if not positions:
        return json.dumps({"positions": [], "message": "No open positions"})
    return json.dumps({"positions": positions, "count": len(positions)}, indent=2)


async def get_open_orders() -> str:
    """Get your pending IBKR orders.

    Shows all open (unfilled) orders with order type, price, status,
    and fill information.
    """
    orders = await ibkr_portfolio.get_open_orders()
    if not orders:
        return json.dumps({"orders": [], "message": "No open orders"})
    return json.dumps({"orders": orders, "count": len(orders)}, indent=2)
