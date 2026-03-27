"""Outcome API endpoints for logging trade results."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from database.connection import get_db
from middleware.auth import CurrentUser
from pipeline.schemas import OutcomeCreate, OutcomeResponse

router = APIRouter(prefix="/outcomes", tags=["outcomes"])


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

    dec = dec_resp.data
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
    ticker = rec_resp.data["ticker"] if rec_resp and rec_resp.data else ""

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
    }
    await client.table("outcomes").insert(row).execute()

    inserted = await client.table("outcomes").select("*").eq("id", outcome_id).single().execute()
    o = inserted.data

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
    )


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
    }
    await client.table("outcomes").update(updates).eq("id", outcome_id).execute()

    updated = await client.table("outcomes").select("*").eq("id", outcome_id).single().execute()
    o = updated.data

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
    )


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

    return [
        OutcomeResponse(
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
        )
        for o in resp.data
    ]
