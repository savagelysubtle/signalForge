"""MCP tools for risk monitoring."""

from __future__ import annotations

import json

from mcp_server.config import settings
from mcp_server.ibkr import portfolio as ibkr_portfolio


async def get_daily_pnl() -> str:
    """Get today's profit and loss from IBKR.

    Shows realized P&L, unrealized P&L, and total for the day.
    """
    account = await ibkr_portfolio.get_account_summary()
    unrealized = account.get("unrealized_pnl", 0.0)
    realized = account.get("realized_pnl", 0.0)
    equity = account.get("net_liquidation", 0.0)

    total = unrealized + realized
    pnl_pct = (total / equity * 100) if equity > 0 else 0.0

    return json.dumps(
        {
            "unrealized_pnl": unrealized,
            "realized_pnl": realized,
            "total_pnl": round(total, 2),
            "pnl_percent": round(pnl_pct, 2),
            "net_liquidation": equity,
            "daily_loss_limit_pct": settings.daily_loss_limit_pct,
            "loss_limit_remaining_pct": round(
                settings.daily_loss_limit_pct - abs(pnl_pct)
                if total < 0
                else settings.daily_loss_limit_pct,
                2,
            ),
        },
        indent=2,
    )


async def get_risk_status() -> str:
    """Get current risk status including all safety limits.

    Shows daily loss limit usage, portfolio exposure, order rate,
    and all configured risk parameters.
    """
    account = await ibkr_portfolio.get_account_summary()
    positions = await ibkr_portfolio.get_positions()
    equity = account.get("net_liquidation", 0.0)

    unrealized = account.get("unrealized_pnl", 0.0)
    realized = account.get("realized_pnl", 0.0)
    total_pnl = unrealized + realized
    loss_pct = abs(total_pnl / equity * 100) if total_pnl < 0 and equity > 0 else 0.0

    total_exposure = sum(abs(p.get("market_value", 0.0)) for p in positions)
    exposure_pct = (total_exposure / equity * 100) if equity > 0 else 0.0

    return json.dumps(
        {
            "account_equity": round(equity, 2),
            "daily_pnl": round(total_pnl, 2),
            "daily_loss_pct": round(loss_pct, 2),
            "daily_loss_limit_pct": settings.daily_loss_limit_pct,
            "portfolio_exposure": round(total_exposure, 2),
            "portfolio_exposure_pct": round(exposure_pct, 1),
            "max_exposure_pct": settings.max_portfolio_exposure_pct,
            "open_positions": len(positions),
            "max_position_size_pct": settings.max_position_size_pct,
            "min_confidence": settings.min_confidence,
            "max_orders_per_hour": settings.max_orders_per_hour,
            "require_market_hours": settings.require_market_hours,
            "paper_account": settings.ibkr_paper,
        },
        indent=2,
    )
