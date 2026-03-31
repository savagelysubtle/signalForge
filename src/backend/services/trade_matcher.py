"""Trade matching engine for linking Questrade executions to SignalForge recommendations.

Groups raw executions by order ID, aggregates fill data, maps symbols to
TradingView format, then scores each order against open recommendations
using ticker match, direction alignment, and time proximity.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from database.connection import get_db
from services.questrade_service import QuestradeService

logger = logging.getLogger(__name__)

MATCH_WINDOW_DAYS = 7
MIN_MATCH_SCORE = 10.0

# Questrade side → SignalForge action for entries
_ENTRY_SIDES: dict[str, str] = {"Buy": "BUY", "Short": "SHORT"}
# Questrade exit side → original recommendation action
_EXIT_SIDES: dict[str, str] = {"Sell": "BUY", "Cov": "SHORT"}

# Options order sides to skip
_OPTIONS_SIDES = frozenset({"BTO", "STC", "STO", "BTC"})


async def find_matches(
    user_id: str,
    executions: list[dict[str, Any]],
    qt_service: QuestradeService,
) -> list[dict[str, Any]]:
    """Match Questrade executions against open SignalForge recommendations.

    Steps:
      1. Group executions by ``orderId`` and aggregate fill data.
      2. Filter out options (side is BTO/STC/STO/BTC).
      3. Map Questrade symbols to TradingView format.
      4. Load recommendations the user is following (no outcome yet).
      5. Score each order against each recommendation.
      6. Persist matches that meet ``MIN_MATCH_SCORE``.

    Args:
        user_id: Authenticated user ID.
        executions: Raw execution dicts from the Questrade API.
        qt_service: QuestradeService instance for symbol mapping.

    Returns:
        List of pending match dicts that were created.
    """
    if not executions:
        return []

    aggregated = _aggregate_orders(executions)
    aggregated = [o for o in aggregated if o["side"] not in _OPTIONS_SIDES]

    if not aggregated:
        return []

    for order in aggregated:
        order["tv_ticker"] = qt_service.map_symbol_to_tradingview(
            order["symbol"], order.get("listing_exchange", "")
        )

    open_recs = await _load_open_recommendations(user_id)
    if not open_recs:
        logger.info("No open recommendations for user %s — nothing to match", user_id)
        return []

    existing_order_ids = await _load_existing_match_order_ids(user_id)

    client = await get_db()
    created: list[dict[str, Any]] = []

    for order in aggregated:
        order_id_str = str(order["order_id"])
        if order_id_str in existing_order_ids:
            continue

        best_rec = None
        best_score = 0.0
        best_reasons: list[str] = []

        for rec in open_recs:
            score, reasons = _score_match(order, rec)
            if score > best_score:
                best_score = score
                best_rec = rec
                best_reasons = reasons

        if best_score < MIN_MATCH_SCORE or best_rec is None:
            continue

        match_row: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "user_id": user_id,
            "recommendation_id": best_rec["id"],
            "questrade_order_id": order_id_str,
            "ticker": order["tv_ticker"],
            "side": order["side"],
            "avg_price": order["avg_price"],
            "total_shares": order["total_shares"],
            "total_commission": order["total_commission"],
            "currency": order.get("currency", "CAD"),
            "executed_at": order["executed_at"],
            "match_score": round(best_score, 2),
            "match_reason": "; ".join(best_reasons),
            "status": "pending",
        }
        await client.table("pending_matches").insert(match_row).execute()
        created.append(match_row)
        logger.info(
            "Created pending match: order %s → rec %s (score %.1f)",
            order_id_str,
            best_rec["id"],
            best_score,
        )

    return created


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _aggregate_orders(
    executions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group raw executions by ``orderId`` and compute aggregated fill data.

    Computes VWAP, total shares, total commission, and picks the earliest
    timestamp per order.

    Args:
        executions: Raw execution list from the Questrade API.

    Returns:
        List of aggregated order dicts.
    """
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for ex in executions:
        groups[ex["orderId"]].append(ex)

    orders: list[dict[str, Any]] = []
    for order_id, fills in groups.items():
        total_qty = 0
        cost_basis = 0.0
        total_commission = 0.0
        earliest_ts = ""

        for fill in fills:
            qty = fill.get("quantity", 0)
            price = fill.get("price", 0.0)
            total_qty += qty
            cost_basis += price * qty
            total_commission += sum(
                fill.get(fee, 0.0) or 0.0
                for fee in (
                    "commission",
                    "executionFee",
                    "secFee",
                    "canadianExecutionFee",
                )
            )
            ts = fill.get("timestamp", "")
            if not earliest_ts or (ts and ts < earliest_ts):
                earliest_ts = ts

        first = fills[0]
        avg_price = cost_basis / total_qty if total_qty > 0 else 0.0

        orders.append(
            {
                "order_id": order_id,
                "symbol": first.get("symbol", ""),
                "side": first.get("side", ""),
                "listing_exchange": first.get("venue", ""),
                "avg_price": round(avg_price, 4),
                "total_shares": total_qty,
                "total_commission": round(total_commission, 4),
                "currency": first.get("currency", "CAD"),
                "executed_at": earliest_ts,
            }
        )

    return orders


async def _load_open_recommendations(user_id: str) -> list[dict[str, Any]]:
    """Load recommendations the user is following that are still open.

    A recommendation is "open" if:
      - It has no outcome at all, OR
      - It has an outcome with no ``exit_price`` (trade entered but not closed).

    Args:
        user_id: Authenticated user ID.

    Returns:
        List of recommendation dicts with joined decision data.
    """
    client = await get_db()

    dec_resp = (
        await client.table("decisions")
        .select("id, recommendation_id")
        .eq("user_id", user_id)
        .eq("decision", "following")
        .execute()
    )
    if not dec_resp or not dec_resp.data:
        return []

    following = dec_resp.data

    outcome_resp = (
        await client.table("outcomes")
        .select("decision_id, exit_price")
        .eq("user_id", user_id)
        .execute()
    )

    closed_decision_ids: set[str] = set()
    if outcome_resp and outcome_resp.data:
        for o in outcome_resp.data:
            if o.get("exit_price") is not None:
                closed_decision_ids.add(o["decision_id"])

    open_decision_map: dict[str, str] = {}
    for d in following:
        if d["id"] not in closed_decision_ids:
            open_decision_map[d["recommendation_id"]] = d["id"]

    if not open_decision_map:
        return []

    rec_ids = list(open_decision_map.keys())
    rec_resp = (
        await client.table("recommendations")
        .select("id, ticker, action, confidence, entry_price, created_at")
        .in_("id", rec_ids)
        .execute()
    )
    if not rec_resp or not rec_resp.data:
        return []

    for rec in rec_resp.data:
        rec["decision_id"] = open_decision_map[rec["id"]]

    return rec_resp.data


async def _load_existing_match_order_ids(user_id: str) -> set[str]:
    """Load Questrade order IDs that already have pending matches.

    Args:
        user_id: Authenticated user ID.

    Returns:
        Set of order ID strings.
    """
    client = await get_db()
    resp = (
        await client.table("pending_matches")
        .select("questrade_order_id")
        .eq("user_id", user_id)
        .in_("status", ["pending", "confirmed"])
        .execute()
    )
    if not resp or not resp.data:
        return set()
    return {row["questrade_order_id"] for row in resp.data}


def _score_match(order: dict[str, Any], rec: dict[str, Any]) -> tuple[float, list[str]]:
    """Score how well a Questrade order matches a SignalForge recommendation.

    Scoring:
      - Ticker exact match: +10
      - Direction match: +5
      - Time proximity: up to +5 (linear decay over ``MATCH_WINDOW_DAYS``)

    Args:
        order: Aggregated order dict with ``tv_ticker``, ``side``, ``executed_at``.
        rec: Recommendation dict with ``ticker``, ``action``, ``created_at``.

    Returns:
        Tuple of (score, list of reason strings).
    """
    score = 0.0
    reasons: list[str] = []

    if order["tv_ticker"].upper() == rec["ticker"].upper():
        score += 10.0
        reasons.append("ticker_match")

    side = order["side"]
    rec_action = rec.get("action", "")

    is_entry = side in _ENTRY_SIDES and _ENTRY_SIDES[side] == rec_action
    is_exit = side in _EXIT_SIDES and _EXIT_SIDES[side] == rec_action

    if is_entry or is_exit:
        score += 5.0
        label = "entry" if is_entry else "exit"
        reasons.append(f"direction_match ({label})")

    days_diff = _days_between(order.get("executed_at", ""), rec.get("created_at", ""))
    if days_diff is not None and days_diff <= MATCH_WINDOW_DAYS:
        proximity = 5.0 * max(0.0, 1.0 - days_diff / MATCH_WINDOW_DAYS)
        score += proximity
        reasons.append(f"time_proximity ({days_diff:.1f}d)")

    return score, reasons


def _days_between(ts1: str, ts2: str) -> float | None:
    """Compute the absolute number of days between two ISO timestamps.

    Args:
        ts1: First ISO timestamp string.
        ts2: Second ISO timestamp string.

    Returns:
        Days as a float, or ``None`` if parsing fails.
    """
    try:
        dt1 = datetime.fromisoformat(ts1)
        dt2 = datetime.fromisoformat(ts2)
        if dt1.tzinfo is None:
            dt1 = dt1.replace(tzinfo=UTC)
        if dt2.tzinfo is None:
            dt2 = dt2.replace(tzinfo=UTC)
        return abs((dt1 - dt2).total_seconds()) / 86400.0
    except ValueError, TypeError:
        return None
