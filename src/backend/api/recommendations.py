"""Recommendations API — enriched with decision and outcome status for the trade journal."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from database.connection import get_db
from middleware.auth import CurrentUser
from pipeline.schemas import RecommendationWithStatus

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


def _build_status(
    r: dict,
    dec: dict | None,
    out: dict | None,
) -> RecommendationWithStatus:
    """Build a RecommendationWithStatus from raw DB rows."""
    return RecommendationWithStatus(
        id=r["id"],
        run_id=r["run_id"],
        ticker=r["ticker"],
        action=r["action"],
        confidence=r["confidence"],
        entry_price=r.get("entry_price"),
        stop_loss=r.get("stop_loss"),
        take_profit=r.get("take_profit"),
        risk_reward_ratio=r.get("risk_reward_ratio"),
        holding_period=r.get("holding_period") or "",
        judge_reasoning=r.get("judge_reasoning") or "",
        created_at=str(r["created_at"]),
        decision=dec["decision"] if dec else None,
        decision_id=dec["id"] if dec else None,
        decision_reason=dec.get("reason") or "" if dec else "",
        decided_at=str(dec["decided_at"]) if dec else None,
        outcome_id=out["id"] if out else None,
        outcome_entry_price=out.get("entry_price") if out else None,
        outcome_exit_price=out.get("exit_price") if out else None,
        outcome_shares=out.get("shares") if out else None,
        outcome_pnl_dollars=out.get("pnl_dollars") if out else None,
        outcome_pnl_percent=out.get("pnl_percent") if out else None,
        outcome_holding_days=out.get("holding_days") if out else None,
        outcome_exit_reason=out.get("exit_reason") or "" if out else "",
        outcome_notes=out.get("notes") or "" if out else "",
        outcome_logged_at=str(out["logged_at"]) if out else None,
    )


_REC_SELECT = (
    "id, run_id, ticker, action, confidence, entry_price, stop_loss, "
    "take_profit, risk_reward_ratio, holding_period, judge_reasoning, created_at"
)


@router.get("", response_model=list[RecommendationWithStatus])
async def list_recommendations(
    user_id: CurrentUser,
    limit: int = 50,
    offset: int = 0,
) -> list[RecommendationWithStatus]:
    """List user recommendations with joined decision and outcome status.

    Returns recommendations ordered by creation date (newest first),
    enriched with the user's follow/pass decision and trade outcome
    for each. Uses 3 batch queries to avoid N+1.
    """
    client = await get_db()

    rec_resp = (
        await client.table("recommendations")
        .select(_REC_SELECT)
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    recs = rec_resp.data
    if not recs:
        return []

    rec_ids = [r["id"] for r in recs]

    dec_resp = (
        await client.table("decisions")
        .select("id, recommendation_id, decision, reason, decided_at")
        .eq("user_id", user_id)
        .in_("recommendation_id", rec_ids)
        .execute()
    )
    dec_map: dict[str, dict] = {d["recommendation_id"]: d for d in dec_resp.data}

    decision_ids = [d["id"] for d in dec_resp.data]
    out_map: dict[str, dict] = {}
    if decision_ids:
        out_resp = (
            await client.table("outcomes")
            .select(
                "id, recommendation_id, entry_price, exit_price, shares, pnl_dollars, pnl_percent, holding_days, exit_reason, notes, logged_at"
            )
            .eq("user_id", user_id)
            .in_("recommendation_id", rec_ids)
            .execute()
        )
        out_map = {o["recommendation_id"]: o for o in out_resp.data}

    return [_build_status(r, dec_map.get(r["id"]), out_map.get(r["id"])) for r in recs]


@router.get("/{recommendation_id}", response_model=RecommendationWithStatus)
async def get_recommendation_status(
    recommendation_id: str,
    user_id: CurrentUser,
) -> RecommendationWithStatus:
    """Get a single recommendation with its decision and outcome status."""
    client = await get_db()

    rec_resp = (
        await client.table("recommendations")
        .select(_REC_SELECT)
        .eq("id", recommendation_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not rec_resp or not rec_resp.data:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    r = rec_resp.data

    dec_resp = (
        await client.table("decisions")
        .select("id, recommendation_id, decision, reason, decided_at")
        .eq("recommendation_id", recommendation_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    dec = dec_resp.data if dec_resp else None

    out: dict | None = None
    if dec:
        out_resp = (
            await client.table("outcomes")
            .select(
                "id, recommendation_id, entry_price, exit_price, shares, pnl_dollars, pnl_percent, holding_days, exit_reason, notes, logged_at"
            )
            .eq("recommendation_id", recommendation_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        out = out_resp.data if out_resp else None

    return _build_status(r, dec, out)
