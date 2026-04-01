"""Recommendations API — enriched with decision and outcome status for the trade journal."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from database.connection import get_db
from middleware.auth import CurrentUser
from pipeline.schemas import RecommendationWithStatus

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


def _build_status(
    r: dict,
    dec: dict | None,
    out: dict | None,
    strategy_name: str = "",
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
        strategy_name=strategy_name,
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
        outcome_source=out.get("source") or "manual" if out else "manual",
        outcome_commission=out.get("commission") if out else None,
        outcome_net_pnl=out.get("net_pnl") if out else None,
        outcome_gross_pnl=out.get("gross_pnl") if out else None,
        outcome_stop_loss=out.get("stop_loss") if out else None,
        outcome_take_profit=out.get("take_profit") if out else None,
        outcome_entry_timestamp=str(out["entry_timestamp"])
        if out and out.get("entry_timestamp")
        else None,
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
    action: list[str] | None = Query(None),
    confidence_min: float | None = Query(None, ge=0, le=1),
    confidence_max: float | None = Query(None, ge=0, le=1),
) -> list[RecommendationWithStatus]:
    """List user recommendations with joined decision and outcome status.

    Returns recommendations ordered by creation date (newest first),
    enriched with the user's follow/pass decision and trade outcome
    for each. Uses 3 batch queries to avoid N+1.

    Args:
        user_id: Authenticated user ID (injected).
        limit: Page size.
        offset: Page offset.
        action: Filter by action(s) — BUY, SHORT, HOLD. Repeatable query param.
        confidence_min: Minimum confidence (0.0-1.0 inclusive).
        confidence_max: Maximum confidence (0.0-1.0 inclusive).
    """
    client = await get_db()

    query = client.table("recommendations").select(_REC_SELECT).eq("user_id", user_id)

    if action:
        valid = [a.upper() for a in action if a.upper() in ("BUY", "SHORT", "HOLD")]
        if valid:
            query = query.in_("action", valid)

    if confidence_min is not None:
        query = query.gte("confidence", confidence_min)
    if confidence_max is not None:
        query = query.lte("confidence", confidence_max)

    rec_resp = (
        await query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    )
    recs = rec_resp.data
    if not recs:
        return []

    rec_ids = [r["id"] for r in recs]
    run_ids = list({r["run_id"] for r in recs})

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
                "id, recommendation_id, entry_price, exit_price, shares, pnl_dollars, pnl_percent, holding_days, exit_reason, notes, logged_at, source, commission, net_pnl, gross_pnl, stop_loss, take_profit, entry_timestamp"
            )
            .eq("user_id", user_id)
            .in_("recommendation_id", rec_ids)
            .execute()
        )
        out_map = {o["recommendation_id"]: o for o in out_resp.data}

    # Resolve strategy names: run_id → strategy_id → strategy name
    strategy_name_map: dict[str, str] = {}
    if run_ids:
        runs_resp = (
            await client.table("pipeline_runs")
            .select("id, strategy_id")
            .in_("id", run_ids)
            .execute()
        )
        strat_ids = list({
            pr["strategy_id"] for pr in runs_resp.data if pr.get("strategy_id")
        })
        strat_name_lookup: dict[str, str] = {}
        if strat_ids:
            strats_resp = (
                await client.table("strategies")
                .select("id, name")
                .in_("id", strat_ids)
                .execute()
            )
            strat_name_lookup = {s["id"]: s["name"] for s in strats_resp.data}

        for pr in runs_resp.data:
            sid = pr.get("strategy_id")
            strategy_name_map[pr["id"]] = strat_name_lookup.get(sid, "") if sid else ""

    return [
        _build_status(
            r,
            dec_map.get(r["id"]),
            out_map.get(r["id"]),
            strategy_name=strategy_name_map.get(r["run_id"], ""),
        )
        for r in recs
    ]


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
                "id, recommendation_id, entry_price, exit_price, shares, pnl_dollars, pnl_percent, holding_days, exit_reason, notes, logged_at, source, commission, net_pnl, gross_pnl, stop_loss, take_profit, entry_timestamp"
            )
            .eq("recommendation_id", recommendation_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        out = out_resp.data if out_resp else None

    # Resolve strategy name
    strategy_name = ""
    run_resp = (
        await client.table("pipeline_runs")
        .select("strategy_id")
        .eq("id", r["run_id"])
        .maybe_single()
        .execute()
    )
    if run_resp and run_resp.data and run_resp.data.get("strategy_id"):
        strat_resp = (
            await client.table("strategies")
            .select("name")
            .eq("id", run_resp.data["strategy_id"])
            .maybe_single()
            .execute()
        )
        if strat_resp and strat_resp.data:
            strategy_name = strat_resp.data["name"]

    return _build_status(r, dec, out, strategy_name=strategy_name)
