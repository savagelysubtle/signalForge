"""IBKR execution fills for reconciliation with SignalForge outcomes."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from mcp_server.ibkr.client import get_ibkr_client

logger = logging.getLogger(__name__)


def _bare_symbol(ticker: str) -> str:
    t = ticker.strip().upper()
    return t.split(":", 1)[-1] if ":" in t else t


async def get_fills_snapshot() -> list[Any]:
    """Return a snapshot list of IB ``Fill`` objects (may be empty until trades occur)."""
    ib = await get_ibkr_client().ensure_connected()

    def _read() -> list[Any]:
        return list(ib.fills())

    return await asyncio.to_thread(_read)


def parse_fill_time(ex_time: Any) -> datetime | None:
    """Best-effort parse of IB execution time to UTC."""
    if ex_time is None:
        return None
    if isinstance(ex_time, datetime):
        if ex_time.tzinfo is None:
            return ex_time.replace(tzinfo=UTC)
        return ex_time.astimezone(UTC)
    if isinstance(ex_time, str):
        try:
            raw = ex_time.replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            return None
    return None


def aggregate_exit_leg(
    fills: list[Any],
    symbol: str,
    entry_time: datetime | None,
    target_shares: int,
) -> tuple[float | None, float, datetime | None]:
    """Aggregate SLD fills after ``entry_time`` up to ``target_shares``.

    Returns:
        Tuple of (VWAP exit price, total commission, latest fill time).
    """
    sym = _bare_symbol(symbol)
    rows: list[tuple[datetime, float, int, float]] = []
    for fl in fills:
        ex = fl.execution
        ct = getattr(ex, "contract", None)
        if ct is None or getattr(ct, "symbol", "") != sym:
            continue
        side = getattr(ex, "side", "")
        if side != "SLD":
            continue
        t = parse_fill_time(getattr(ex, "time", None))
        if t is None:
            continue
        if entry_time is not None and t < entry_time:
            continue
        price = float(getattr(ex, "price", 0.0) or 0.0)
        sh = int(getattr(ex, "shares", 0) or 0)
        cr = getattr(fl, "commissionReport", None)
        comm = float(getattr(cr, "commission", 0.0) or 0.0) if cr is not None else 0.0
        if sh <= 0:
            continue
        rows.append((t, price, sh, comm))

    rows.sort(key=lambda r: r[0])
    total_sh = 0
    notional = 0.0
    commission = 0.0
    last_t: datetime | None = None
    for t, price, sh, comm in rows:
        need = target_shares - total_sh
        if need <= 0:
            break
        take = min(sh, need)
        notional += price * take
        commission += comm * (take / sh)
        total_sh += take
        last_t = t
        if total_sh >= target_shares:
            break

    if total_sh == 0:
        return None, 0.0, None
    return notional / total_sh, commission, last_t
