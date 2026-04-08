"""IBKR order construction from SignalForge recommendations."""

from __future__ import annotations

import math

from ib_async import Contract, LimitOrder, MarketOrder, Order, Stock, StopOrder


def build_contract(ticker: str) -> Contract:
    """Build an IB Contract from a TradingView-style ticker.

    Only US exchanges are supported. Canadian and other non-US exchanges are
    rejected to comply with CIRO regulations (DMR 3200 A.1.(b)(i)) that prohibit
    Canadian residents from programmatic trading of Canadian-listed products.

    Args:
        ticker: TradingView-format ticker (e.g. "NASDAQ:AAPL" or "AAPL").

    Returns:
        An IB Stock contract ready for order submission.

    Raises:
        ValueError: If the ticker references a blocked (non-US) exchange.
    """
    if ":" in ticker:
        exchange_prefix, symbol = ticker.split(":", 1)
    else:
        exchange_prefix = ""
        symbol = ticker

    symbol = symbol.strip().upper()
    exchange_prefix = exchange_prefix.strip().upper()

    if exchange_prefix in _BLOCKED_EXCHANGES:
        raise ValueError(
            f"Exchange '{exchange_prefix}' is blocked — only US exchanges are supported. "
            f"Canadian products cannot be traded programmatically (CIRO DMR 3200)."
        )

    if exchange_prefix and exchange_prefix not in _TV_TO_IB_PRIMARY:
        raise ValueError(
            f"Unrecognized exchange '{exchange_prefix}' — only US exchanges are supported: "
            f"{', '.join(sorted(_TV_TO_IB_PRIMARY.keys()))}"
        )

    # US stock via SMART routing
    primary = _TV_TO_IB_PRIMARY.get(exchange_prefix, "")
    contract = Stock(symbol, "SMART", "USD")
    if primary:
        contract.primaryExchange = primary
    return contract


def calculate_quantity(
    equity: float,
    position_size_pct: float,
    entry_price: float,
    max_position_size_pct: float,
) -> int:
    """Calculate share quantity from position sizing.

    Args:
        equity: Account net liquidation value.
        position_size_pct: Desired position size as percent of equity.
        entry_price: Target entry price per share.
        max_position_size_pct: Hard cap on position size percent.

    Returns:
        Number of shares to buy (always >= 0, rounded down).
    """
    if entry_price <= 0 or equity <= 0:
        return 0
    capped_pct = min(position_size_pct, max_position_size_pct)
    dollar_amount = equity * capped_pct / 100.0
    return max(0, math.floor(dollar_amount / entry_price))


def build_bracket_order(
    action: str,
    quantity: int,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
) -> list[Order]:
    """Build an IB bracket order (entry + stop loss + take profit).

    Constructs three linked orders: a parent LimitOrder at entry_price,
    a child LimitOrder at take_profit, and a child StopOrder at stop_loss.
    The last child has transmit=True which triggers submission of all three.

    Args:
        action: "BUY" for long entry, "SELL" for short entry.
        quantity: Number of shares.
        entry_price: Limit price for entry order.
        stop_loss: Stop loss trigger price.
        take_profit: Take profit limit price.

    Returns:
        List of three Order objects [parent, take_profit, stop_loss].
    """
    reverse_action = "SELL" if action == "BUY" else "BUY"

    parent = LimitOrder(
        action=action,
        totalQuantity=quantity,
        lmtPrice=entry_price,
        transmit=False,
    )

    tp_order = LimitOrder(
        action=reverse_action,
        totalQuantity=quantity,
        lmtPrice=take_profit,
        parentId=parent.orderId,
        transmit=False,
    )

    sl_order = StopOrder(
        action=reverse_action,
        totalQuantity=quantity,
        stopPrice=stop_loss,
        parentId=parent.orderId,
        transmit=True,
    )

    return [parent, tp_order, sl_order]


def build_close_order(action: str, quantity: int) -> MarketOrder:
    """Build a market order to close a position.

    Args:
        action: "SELL" to close a long, "BUY" to close a short (cover).
        quantity: Number of shares to close.

    Returns:
        A MarketOrder for immediate execution.
    """
    return MarketOrder(action=action, totalQuantity=abs(quantity))


def map_action_to_ib(rec_action: str) -> str | None:
    """Map a SignalForge recommendation action to an IB order action.

    Args:
        rec_action: Recommendation action (BUY, SHORT, HOLD, NO_TRADE, WATCH).

    Returns:
        IB action string ("BUY" or "SELL") or None if not tradeable.
    """
    if rec_action == "BUY":
        return "BUY"
    if rec_action == "SHORT":
        return "SELL"
    return None


def close_action_for_position(quantity: float) -> str | None:
    """Determine the close action for an existing position.

    Args:
        quantity: Signed position quantity (positive = long, negative = short).

    Returns:
        "SELL" for long positions, "BUY" for short positions, None if flat.
    """
    if quantity > 0:
        return "SELL"
    if quantity < 0:
        return "BUY"
    return None


# Non-US exchanges that must be rejected
_BLOCKED_EXCHANGES: set[str] = {"TSX", "TSXV", "CSE", "NEO", "CNSX", "LSE", "HKEX", "ASX"}

# TradingView exchange prefix → IB primaryExchange (US only)
_TV_TO_IB_PRIMARY: dict[str, str] = {
    "NASDAQ": "NASDAQ",
    "NYSE": "NYSE",
    "AMEX": "AMEX",
    "ARCA": "ARCA",
    "BATS": "BATS",
}
