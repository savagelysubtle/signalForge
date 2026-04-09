"""Outcome API endpoints for logging trade results."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from database.connection import get_db
from middleware.auth import CurrentUser
from pipeline.schemas import (
    BrokerageOpenRequest,
    DailyOutcomeSummary,
    OutcomeCreate,
    OutcomeResponse,
)

router = APIRouter(prefix="/outcomes", tags=["outcomes"])

_ET = ZoneInfo("America/New_York")


def _build_outcome_response(o: dict[str, Any]) -> OutcomeResponse:
    """Build an OutcomeResponse from a raw database row dict."""
    return OutcomeResponse(
        id=o["id"],
        user_id=o["user_id"],
        decision_id=o["decision_id"],
        recommendation_id=o["recommendation_id"],
        ticker=o["ticker"],
        entry_price=o.get("entry_price"),
        exit_price=o.get("exit_price"),
        shares=o.get("shares"),
        pnl_dollars=o.get("pnl_dollars"),
        pnl_percent=o.get("pnl_percent"),
        holding_days=o.get("holding_days"),
        exit_reason=o.get("exit_reason") or "",
        notes=o.get("notes") or "",
        logged_at=str(o["logged_at"]),
        source=o.get("source") or "manual",
        brokerage_order_id=o.get("brokerage_order_id"),
        commission=o.get("commission"),
        fees=o.get("fees"),
        currency=o.get("currency"),
        gross_pnl=o.get("gross_pnl"),
        net_pnl=o.get("net_pnl"),
        entry_timestamp=str(o["entry_timestamp"]) if o.get("entry_timestamp") else None,
        exit_timestamp=str(o["exit_timestamp"]) if o.get("exit_timestamp") else None,
        stop_loss=o.get("stop_loss"),
        take_profit=o.get("take_profit"),
    )


@router.post("/brokerage-open", response_model=OutcomeResponse, status_code=201)
async def create_brokerage_open_outcome(
    body: BrokerageOpenRequest,
    user_id: CurrentUser,
) -> OutcomeResponse:
    """Create or reuse a *following* decision and log an open IBKR position."""
    client = await get_db()

    rec_resp = (
        await client.table("recommendations")
        .select("id, ticker, user_id")
        .eq("id", body.recommendation_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not rec_resp or not rec_resp.data:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    rec = cast(dict[str, Any], rec_resp.data)
    ticker = str(rec["ticker"])

    dec_resp = (
        await client.table("decisions")
        .select("id, decision")
        .eq("recommendation_id", body.recommendation_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )

    decision_id: str
    if dec_resp and dec_resp.data:
        prior = cast(dict[str, Any], dec_resp.data)
        if prior["decision"] != "following":
            raise HTTPException(
                status_code=409,
                detail="Recommendation was passed — cannot attach brokerage outcome",
            )
        decision_id = str(prior["id"])
    else:
        decision_id = uuid.uuid4().hex
        await (
            client.table("decisions")
            .insert(
                {
                    "id": decision_id,
                    "user_id": user_id,
                    "recommendation_id": body.recommendation_id,
                    "decision": "following",
                    "reason": "Auto-recorded from IBKR execution (MCP)",
                    "reason_category": "brokerage",
                }
            )
            .execute()
        )

    existing_o = (
        await client.table("outcomes")
        .select("id")
        .eq("decision_id", decision_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if existing_o and existing_o.data:
        raise HTTPException(status_code=409, detail="Outcome already recorded for this decision")

    entry_ts = body.entry_timestamp or datetime.now(UTC).isoformat()

    outcome_id = uuid.uuid4().hex
    row = {
        "id": outcome_id,
        "user_id": user_id,
        "decision_id": decision_id,
        "recommendation_id": body.recommendation_id,
        "ticker": ticker,
        "entry_price": body.entry_price,
        "exit_price": None,
        "shares": body.shares,
        "pnl_dollars": None,
        "pnl_percent": None,
        "holding_days": None,
        "exit_reason": "",
        "notes": body.notes,
        "source": "ibkr",
        "brokerage_order_id": body.brokerage_order_id,
        "commission": None,
        "fees": None,
        "currency": body.currency,
        "gross_pnl": None,
        "net_pnl": None,
        "entry_timestamp": entry_ts,
        "exit_timestamp": None,
        "stop_loss": body.stop_loss,
        "take_profit": body.take_profit,
    }
    await client.table("outcomes").insert(row).execute()

    inserted = await client.table("outcomes").select("*").eq("id", outcome_id).single().execute()
    return _build_outcome_response(cast(dict[str, Any], inserted.data))


@router.get("/daily-summary", response_model=DailyOutcomeSummary)
async def daily_outcome_summary(user_id: CurrentUser) -> DailyOutcomeSummary:
    """Aggregate logged outcomes for the current US Eastern calendar day."""
    client = await get_db()
    now_et = datetime.now(tz=_ET)
    day_start_et = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_et = day_start_et + timedelta(days=1)

    day_start_utc = day_start_et.astimezone(UTC).isoformat()
    day_end_utc = day_end_et.astimezone(UTC).isoformat()

    closed_resp = (
        await client.table("outcomes")
        .select("*")
        .eq("user_id", user_id)
        .gte("exit_timestamp", day_start_utc)
        .lt("exit_timestamp", day_end_utc)
        .execute()
    )
    closed_today = cast(list[dict[str, Any]], closed_resp.data or [])

    wins = losses = be = 0
    realized = 0.0
    for o in closed_today:
        pnl = o.get("net_pnl")
        if pnl is None:
            pnl = o.get("pnl_dollars")
        pnl_f = float(pnl) if pnl is not None else 0.0
        realized += pnl_f
        if pnl_f > 0:
            wins += 1
        elif pnl_f < 0:
            losses += 1
        else:
            be += 1

    opened_resp = (
        await client.table("outcomes")
        .select("id")
        .eq("user_id", user_id)
        .gte("entry_timestamp", day_start_utc)
        .lt("entry_timestamp", day_end_utc)
        .execute()
    )
    opened_today = len(opened_resp.data or [])

    open_resp = (
        await client.table("outcomes")
        .select("id")
        .eq("user_id", user_id)
        .not_("entry_price", "is", "null")
        .is_("exit_price", "null")
        .is_("exit_timestamp", "null")
        .execute()
    )
    open_tracked = len(open_resp.data or [])

    return DailyOutcomeSummary(
        trading_date_et=day_start_et.strftime("%Y-%m-%d"),
        closed_trades=len(closed_today),
        winning_trades=wins,
        losing_trades=losses,
        breakeven_trades=be,
        realized_pnl_dollars=round(realized, 2),
        opened_trades=opened_today,
        open_tracked_positions=open_tracked,
    )


@router.post(
    "/decisions/{decision_id}/outcome",
    response_model=OutcomeResponse,
    status_code=201,
)
async def create_outcome(
    decision_id: str,
    body: OutcomeCreate,
    user_id: CurrentUser,
) -> OutcomeResponse:
    """Log a trade outcome for a decision the user is following."""
    client = await get_db()

    dec_resp = (
        await client.table("decisions")
        .select("id, user_id, decision, recommendation_id")
        .eq("id", decision_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not dec_resp or not dec_resp.data:
        raise HTTPException(status_code=404, detail="Decision not found")

    dec = cast(dict[str, Any], dec_resp.data)
    if dec["decision"] != "following":
        raise HTTPException(
            status_code=400,
            detail="Cannot log an outcome for a passed recommendation",
        )

    existing = (
        await client.table("outcomes")
        .select("id")
        .eq("decision_id", decision_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if existing and existing.data:
        raise HTTPException(status_code=409, detail="Outcome already recorded for this decision")

    rec_resp = (
        await client.table("recommendations")
        .select("ticker")
        .eq("id", dec["recommendation_id"])
        .maybe_single()
        .execute()
    )
    rec_row = cast(dict[str, Any], rec_resp.data) if rec_resp and rec_resp.data else {}
    ticker = str(rec_row.get("ticker", ""))

    outcome_id = uuid.uuid4().hex
    row = {
        "id": outcome_id,
        "user_id": user_id,
        "decision_id": decision_id,
        "recommendation_id": dec["recommendation_id"],
        "ticker": ticker,
        "entry_price": body.entry_price,
        "exit_price": body.exit_price,
        "shares": body.shares,
        "pnl_dollars": body.pnl_dollars,
        "pnl_percent": body.pnl_percent,
        "holding_days": body.holding_days,
        "exit_reason": body.exit_reason,
        "notes": body.notes,
        "source": body.source,
        "brokerage_order_id": body.brokerage_order_id,
        "commission": body.commission,
        "fees": body.fees,
        "currency": body.currency,
        "gross_pnl": body.gross_pnl,
        "net_pnl": body.net_pnl,
        "entry_timestamp": body.entry_timestamp,
        "exit_timestamp": body.exit_timestamp,
        "stop_loss": body.stop_loss,
        "take_profit": body.take_profit,
    }
    await client.table("outcomes").insert(row).execute()

    inserted = await client.table("outcomes").select("*").eq("id", outcome_id).single().execute()
    return _build_outcome_response(cast(dict[str, Any], inserted.data))


@router.put("/{outcome_id}", response_model=OutcomeResponse)
async def update_outcome(
    outcome_id: str,
    body: OutcomeCreate,
    user_id: CurrentUser,
) -> OutcomeResponse:
    """Update an existing trade outcome."""
    client = await get_db()

    existing = (
        await client.table("outcomes")
        .select("id, decision_id, recommendation_id, ticker")
        .eq("id", outcome_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not existing or not existing.data:
        raise HTTPException(status_code=404, detail="Outcome not found")

    updates: dict = {
        "entry_price": body.entry_price,
        "exit_price": body.exit_price,
        "shares": body.shares,
        "pnl_dollars": body.pnl_dollars,
        "pnl_percent": body.pnl_percent,
        "holding_days": body.holding_days,
        "exit_reason": body.exit_reason,
        "notes": body.notes,
        "source": body.source,
        "brokerage_order_id": body.brokerage_order_id,
        "commission": body.commission,
        "fees": body.fees,
        "currency": body.currency,
        "gross_pnl": body.gross_pnl,
        "net_pnl": body.net_pnl,
        "entry_timestamp": body.entry_timestamp,
        "exit_timestamp": body.exit_timestamp,
        "stop_loss": body.stop_loss,
        "take_profit": body.take_profit,
    }
    await client.table("outcomes").update(updates).eq("id", outcome_id).execute()

    updated = await client.table("outcomes").select("*").eq("id", outcome_id).single().execute()
    return _build_outcome_response(cast(dict[str, Any], updated.data))


@router.get("", response_model=list[OutcomeResponse])
async def list_outcomes(
    user_id: CurrentUser,
    limit: int = 50,
    offset: int = 0,
) -> list[OutcomeResponse]:
    """List user trade outcomes."""
    client = await get_db()

    resp = (
        await client.table("outcomes")
        .select("*")
        .eq("user_id", user_id)
        .order("logged_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    raw_rows = resp.data or []
    return [_build_outcome_response(cast(dict[str, Any], o)) for o in raw_rows]
