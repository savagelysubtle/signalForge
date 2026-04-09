"""Automated paper trading tracker for signal quality measurement.

After each pipeline run, schedules deferred price lookups at T+1d,
T+3d, and T+5d for every BUY/SHORT recommendation. Results are
stored in the ``paper_trades`` table for empirical calibration.

This module does NOT execute trades — it only observes prices.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from database.connection import get_db
from services.keyring_service import get_api_key

logger = logging.getLogger(__name__)

TRACK_DAYS: list[int] = [1, 3, 5]


def _action_str(action: Any) -> str:
    """Normalize recommendation action to a string for comparisons and storage."""
    if isinstance(action, str):
        return action
    return str(getattr(action, "value", action))


async def _fetch_quote_price(ticker: str) -> float | None:
    """Fetch current price for a ticker via FMP quote API.

    Args:
        ticker: Stock/crypto ticker symbol.

    Returns:
        Current price or None if unavailable.
    """
    import httpx

    api_key = get_api_key("fmp")
    if not api_key:
        logger.warning("FMP API key not configured for paper tracker")
        return None

    url = f"https://financialmodelingprep.com/api/v3/quote-short/{ticker}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params={"apikey": api_key})
            resp.raise_for_status()
            data = resp.json()
            if data and isinstance(data, list) and len(data) > 0:
                raw = data[0].get("price", 0)
                price = float(raw) if raw is not None else None
                return price if price and price > 0 else None
    except Exception:
        logger.exception("Failed to fetch quote for %s", ticker)
    return None


async def schedule_paper_tracking(
    run_id: str,
    recommendations: list[dict[str, Any]],
    user_id: str = "",
) -> None:
    """Schedule paper trade tracking for actionable recommendations.

    Creates ``paper_trades`` rows for each BUY/SHORT recommendation
    with deferred price lookup timestamps. A background loop later
    fills in the actual prices.

    Args:
        run_id: Pipeline run UUID.
        recommendations: List of recommendation dicts from the pipeline.
        user_id: User UUID for row-level security.
    """
    actionable = [
        r
        for r in recommendations
        if _action_str(r.get("action")) in ("BUY", "SHORT") and r.get("entry_price") is not None
    ]
    if not actionable:
        return

    client = await get_db()
    now = datetime.now(tz=UTC)

    rows = []
    for rec in actionable:
        for days in TRACK_DAYS:
            rows.append(
                {
                    "id": uuid.uuid4().hex,
                    "run_id": run_id,
                    "user_id": user_id,
                    "ticker": rec["ticker"],
                    "action": _action_str(rec["action"]),
                    "entry_price": rec["entry_price"],
                    "confidence": float(rec.get("confidence") or 0.0),
                    "strategy_name": rec.get("strategy_name") or "",
                    "check_day": days,
                    "check_at": (now + timedelta(days=days)).isoformat(),
                    "status": "pending",
                }
            )

    if rows:
        try:
            await client.table("paper_trades").insert(rows).execute()
            logger.info(
                "Scheduled %d paper trade checks for run %s (%d recs x %d intervals)",
                len(rows),
                run_id,
                len(actionable),
                len(TRACK_DAYS),
            )
        except Exception:
            logger.exception("Failed to schedule paper trades for run %s", run_id)


async def process_pending_checks() -> dict[str, Any]:
    """Process all paper trade checks that are due.

    Fetches current prices for pending checks whose ``check_at``
    timestamp has passed, computes P&L, and updates the rows.

    Returns:
        Summary dict with counts of processed/failed checks.
    """
    client = await get_db()
    now = datetime.now(tz=UTC).isoformat()

    try:
        result = await (
            client.table("paper_trades")
            .select("*")
            .eq("status", "pending")
            .lte("check_at", now)
            .limit(100)
            .execute()
        )
    except Exception:
        logger.exception("Failed to fetch pending paper trades")
        return {"processed": 0, "failed": 0, "error": "db_fetch_failed"}

    pending = result.data or []
    if not pending:
        return {"processed": 0, "failed": 0}

    processed = 0
    failed = 0

    tickers = list({row["ticker"] for row in pending})
    prices: dict[str, float | None] = {}
    for ticker in tickers:
        prices[ticker] = await _fetch_quote_price(ticker)

    for row in pending:
        ticker = row["ticker"]
        current_price = prices.get(ticker)

        if current_price is None:
            failed += 1
            continue

        entry = row["entry_price"]
        action = row["action"]

        if action == "BUY":
            pnl_pct = ((current_price - entry) / entry) * 100
        else:
            pnl_pct = ((entry - current_price) / entry) * 100

        try:
            await (
                client.table("paper_trades")
                .update(
                    {
                        "actual_price": current_price,
                        "pnl_pct": round(pnl_pct, 2),
                        "status": "completed",
                        "completed_at": datetime.now(tz=UTC).isoformat(),
                    }
                )
                .eq("id", row["id"])
                .execute()
            )
            processed += 1
        except Exception:
            logger.exception("Failed to update paper trade %s", row["id"])
            failed += 1

    logger.info("Paper trade processing: %d completed, %d failed", processed, failed)
    return {"processed": processed, "failed": failed}


async def get_paper_performance(user_id: str = "") -> dict[str, Any]:
    """Compute aggregate paper trading performance statistics.

    Args:
        user_id: Filter by user (empty string = all users).

    Returns:
        Performance summary with per-day and per-confidence-bucket stats.
    """
    client = await get_db()

    query = client.table("paper_trades").select("*").eq("status", "completed")
    if user_id:
        query = query.eq("user_id", user_id)

    try:
        result = await query.limit(1000).execute()
    except Exception:
        logger.exception("Failed to fetch paper trade performance")
        return {"error": "db_fetch_failed"}

    trades = result.data or []
    if not trades:
        return {
            "total_trades": 0,
            "message": "No completed paper trades yet",
        }

    by_day: dict[int, list[float]] = {1: [], 3: [], 5: []}
    by_confidence: dict[str, list[float]] = {}
    wins = 0
    total = len(trades)

    for t in trades:
        pnl = t.get("pnl_pct", 0.0)
        day = t.get("check_day", 0)
        conf = t.get("confidence", 0.0)

        if day in by_day:
            by_day[day].append(pnl)

        bucket = f"{int(conf * 10) / 10:.1f}-{int(conf * 10) / 10 + 0.1:.1f}"
        by_confidence.setdefault(bucket, []).append(pnl)

        if pnl > 0:
            wins += 1

    def _stats(values: list[float]) -> dict[str, float]:
        if not values:
            return {"count": 0, "avg_pnl": 0.0, "win_rate": 0.0}
        w = sum(1 for v in values if v > 0)
        return {
            "count": len(values),
            "avg_pnl": round(sum(values) / len(values), 2),
            "win_rate": round(w / len(values), 2),
        }

    return {
        "total_trades": total,
        "overall_win_rate": round(wins / total, 2) if total else 0.0,
        "by_check_day": {f"T+{d}d": _stats(vals) for d, vals in by_day.items()},
        "by_confidence_bucket": {k: _stats(v) for k, v in sorted(by_confidence.items())},
    }
