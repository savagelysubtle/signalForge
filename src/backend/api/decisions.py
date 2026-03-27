"""Decision API endpoints for recording user decisions on recommendations."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from database.connection import get_db
from middleware.auth import CurrentUser
from pipeline.schemas import DecisionCreate, DecisionResponse

router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.post(
    "/recommendations/{recommendation_id}/decision",
    response_model=DecisionResponse,
    status_code=201,
)
async def create_decision(
    recommendation_id: str,
    body: DecisionCreate,
    user_id: CurrentUser,
) -> DecisionResponse:
    """Record a follow/pass decision on a recommendation."""
    client = await get_db()

    rec_resp = (
        await client.table("recommendations")
        .select("id, ticker, action, confidence, user_id")
        .eq("id", recommendation_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not rec_resp.data:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    rec = rec_resp.data

    existing = (
        await client.table("decisions")
        .select("id")
        .eq("recommendation_id", recommendation_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if existing.data:
        raise HTTPException(
            status_code=409, detail="Decision already recorded for this recommendation"
        )

    decision_id = uuid.uuid4().hex
    row = {
        "id": decision_id,
        "user_id": user_id,
        "recommendation_id": recommendation_id,
        "decision": body.decision,
        "reason": body.reason,
        "reason_category": body.reason_category,
    }
    await client.table("decisions").insert(row).execute()

    inserted = await client.table("decisions").select("*").eq("id", decision_id).single().execute()
    d = inserted.data

    return DecisionResponse(
        id=d["id"],
        user_id=d["user_id"],
        recommendation_id=d["recommendation_id"],
        decision=d["decision"],
        reason=d.get("reason") or "",
        reason_category=d.get("reason_category") or "",
        decided_at=str(d["decided_at"]),
        ticker=rec["ticker"],
        action=rec["action"],
        confidence=rec["confidence"],
    )


@router.get("", response_model=list[DecisionResponse])
async def list_decisions(
    user_id: CurrentUser,
    limit: int = 50,
    offset: int = 0,
    decision_filter: str | None = None,
) -> list[DecisionResponse]:
    """List user decisions with optional follow/pass filter."""
    client = await get_db()

    query = (
        client.table("decisions")
        .select("*")
        .eq("user_id", user_id)
        .order("decided_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if decision_filter in ("following", "passing"):
        query = query.eq("decision", decision_filter)

    resp = await query.execute()
    rows = resp.data

    rec_ids = list({r["recommendation_id"] for r in rows})
    rec_map: dict[str, dict] = {}
    if rec_ids:
        rec_resp = (
            await client.table("recommendations")
            .select("id, ticker, action, confidence")
            .in_("id", rec_ids)
            .execute()
        )
        rec_map = {r["id"]: r for r in rec_resp.data}

    results: list[DecisionResponse] = []
    for d in rows:
        rec = rec_map.get(d["recommendation_id"], {})
        results.append(
            DecisionResponse(
                id=d["id"],
                user_id=d["user_id"],
                recommendation_id=d["recommendation_id"],
                decision=d["decision"],
                reason=d.get("reason") or "",
                reason_category=d.get("reason_category") or "",
                decided_at=str(d["decided_at"]),
                ticker=rec.get("ticker", ""),
                action=rec.get("action", ""),
                confidence=rec.get("confidence", 0.0),
            )
        )
    return results


@router.get("/{decision_id}", response_model=DecisionResponse)
async def get_decision(
    decision_id: str,
    user_id: CurrentUser,
) -> DecisionResponse:
    """Get a single decision by ID."""
    client = await get_db()

    resp = (
        await client.table("decisions")
        .select("*")
        .eq("id", decision_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Decision not found")
    d = resp.data

    rec_resp = (
        await client.table("recommendations")
        .select("ticker, action, confidence")
        .eq("id", d["recommendation_id"])
        .maybe_single()
        .execute()
    )
    rec = rec_resp.data or {}

    return DecisionResponse(
        id=d["id"],
        user_id=d["user_id"],
        recommendation_id=d["recommendation_id"],
        decision=d["decision"],
        reason=d.get("reason") or "",
        reason_category=d.get("reason_category") or "",
        decided_at=str(d["decided_at"]),
        ticker=rec.get("ticker", ""),
        action=rec.get("action", ""),
        confidence=rec.get("confidence", 0.0),
    )
