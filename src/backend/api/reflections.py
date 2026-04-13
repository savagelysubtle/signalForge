"""Reflection and insights API endpoints."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from database.connection import get_db
from middleware.auth import CurrentUser
from pipeline.schemas import PerformanceOverview, ReflectionResponse, TradeHistoryEntry
from services.calibration_curve import compute_calibration_curve
from services.paper_tracker import get_paper_performance, process_pending_checks
from services.reflection import generate_reflection

router = APIRouter(prefix="/insights", tags=["insights"])


@router.post("/reflect", response_model=ReflectionResponse)
async def trigger_reflection(
    user_id: CurrentUser,
    strategy_id: str | None = None,
) -> ReflectionResponse:
    """Generate a new reflection from the user's trade history.

    Requires at least 5 logged outcomes to produce meaningful stats.
    Optionally scoped to a single strategy via ``strategy_id`` query param.
    """
    client = await get_db()

    count_resp = (
        await client.table("outcomes").select("id", count="exact").eq("user_id", user_id).execute()
    )
    outcome_count = count_resp.count or 0
    if outcome_count < 5:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least 5 logged outcomes to generate a reflection (have {outcome_count})",
        )

    reflection = await generate_reflection(user_id, strategy_id=strategy_id)
    return reflection


@router.get("/reflections/latest", response_model=ReflectionResponse)
async def get_latest_reflection(user_id: CurrentUser) -> ReflectionResponse:
    """Get the most recent reflection for the user."""
    client = await get_db()

    resp = (
        await client.table("reflections")
        .select("*")
        .eq("user_id", user_id)
        .order("generated_at", desc=True)
        .limit(1)
        .maybe_single()
        .execute()
    )
    if not resp or not resp.data:
        raise HTTPException(status_code=404, detail="No reflections found")

    r = resp.data
    return ReflectionResponse(
        id=r["id"],
        generated_at=str(r["generated_at"]),
        recommendations_analyzed=r["recommendations_analyzed"],
        decisions_analyzed=r["decisions_analyzed"],
        outcomes_analyzed=r["outcomes_analyzed"],
        date_range_start=str(r["date_range_start"]) if r.get("date_range_start") else None,
        date_range_end=str(r["date_range_end"]) if r.get("date_range_end") else None,
        summary_text=r["summary_text"],
        injection_prompt=r["injection_prompt"],
        metrics=json.loads(r["metrics"]) if isinstance(r["metrics"], str) else r["metrics"],
    )


@router.delete("/reflections/{reflection_id}")
async def delete_reflection(reflection_id: str, user_id: CurrentUser) -> dict[str, str]:
    """Delete a specific reflection by ID (must belong to the authenticated user)."""
    client = await get_db()

    existing = (
        await client.table("reflections")
        .select("id")
        .eq("id", reflection_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not existing or not existing.data:
        raise HTTPException(status_code=404, detail="Reflection not found")

    await client.table("reflections").delete().eq("id", reflection_id).eq(
        "user_id", user_id
    ).execute()
    return {"status": "deleted"}


@router.get("/trade-history", response_model=list[TradeHistoryEntry])
async def get_trade_history(user_id: CurrentUser) -> list[TradeHistoryEntry]:
    """Return resolved outcomes as a time-series with cumulative PnL.

    Used by the equity curve chart and P&L calendar heatmap. Includes any
    outcome that has either a recorded exit_price or a non-null pnl_dollars,
    sorted by logged_at ascending.
    """
    client = await get_db()

    out_resp = (
        await client.table("outcomes")
        .select("ticker, pnl_dollars, pnl_percent, logged_at, recommendation_id")
        .eq("user_id", user_id)
        .or_("exit_price.not.is.null,pnl_dollars.not.is.null")
        .order("logged_at", desc=False)
        .execute()
    )
    outcomes = out_resp.data if out_resp and out_resp.data else []

    if not outcomes:
        return []

    rec_ids = list({o["recommendation_id"] for o in outcomes if o.get("recommendation_id")})
    conf_map: dict[str, tuple[str, float]] = {}
    if rec_ids:
        rec_resp = (
            await client.table("recommendations")
            .select("id, action, confidence")
            .in_("id", rec_ids)
            .execute()
        )
        for r in rec_resp.data:
            conf_map[r["id"]] = (r.get("action", ""), r.get("confidence", 0.5))

    result: list[TradeHistoryEntry] = []
    cumulative = 0.0
    for o in outcomes:
        pnl = o.get("pnl_dollars") or 0.0
        cumulative += pnl
        rec_id = o.get("recommendation_id", "")
        action, confidence = conf_map.get(rec_id, ("", 0.5))
        logged_at = str(o.get("logged_at", ""))
        date_str = logged_at[:10] if len(logged_at) >= 10 else logged_at

        result.append(
            TradeHistoryEntry(
                date=date_str,
                ticker=o.get("ticker", ""),
                pnl_dollars=pnl,
                pnl_percent=o.get("pnl_percent"),
                cumulative_pnl=round(cumulative, 2),
                action=action,
                confidence=confidence,
            )
        )

    return result


@router.get("/overview", response_model=PerformanceOverview)
async def get_performance_overview(user_id: CurrentUser) -> PerformanceOverview:
    """Get aggregated performance metrics for the insights dashboard."""
    client = await get_db()

    rec_resp = (
        await client.table("recommendations")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .execute()
    )
    total_recs = rec_resp.count or 0

    dec_resp = (
        await client.table("decisions").select("id, decision").eq("user_id", user_id).execute()
    )
    decisions = dec_resp.data
    total_decisions = len(decisions)
    total_following = sum(1 for d in decisions if d["decision"] == "following")
    total_passing = sum(1 for d in decisions if d["decision"] == "passing")

    out_resp = await client.table("outcomes").select("*").eq("user_id", user_id).execute()
    outcomes = out_resp.data
    total_outcomes = len(outcomes)

    wins = 0
    losses = 0
    breakeven = 0
    total_pnl = 0.0
    pnl_percents: list[float] = []
    holding_days_list: list[int] = []
    best_trade: dict | None = None
    worst_trade: dict | None = None

    for o in outcomes:
        pnl = o.get("pnl_dollars") or 0.0
        total_pnl += pnl

        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1
        else:
            breakeven += 1

        if o.get("pnl_percent") is not None:
            pnl_percents.append(o["pnl_percent"])
        if o.get("holding_days") is not None:
            holding_days_list.append(o["holding_days"])

        trade_summary = {
            "ticker": o["ticker"],
            "pnl_dollars": pnl,
            "pnl_percent": o.get("pnl_percent"),
        }
        if best_trade is None or pnl > (best_trade.get("pnl_dollars") or 0.0):
            best_trade = trade_summary
        if worst_trade is None or pnl < (worst_trade.get("pnl_dollars") or 0.0):
            worst_trade = trade_summary

    win_rate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else None
    avg_pnl_pct = sum(pnl_percents) / len(pnl_percents) if pnl_percents else None
    avg_holding = sum(holding_days_list) / len(holding_days_list) if holding_days_list else None

    confidence_calibration = await _compute_confidence_calibration(client, user_id, outcomes)

    return PerformanceOverview(
        total_recommendations=total_recs,
        total_decisions=total_decisions,
        total_following=total_following,
        total_passing=total_passing,
        total_outcomes=total_outcomes,
        wins=wins,
        losses=losses,
        breakeven=breakeven,
        win_rate=win_rate,
        total_pnl_dollars=total_pnl,
        avg_pnl_percent=avg_pnl_pct,
        avg_holding_days=avg_holding,
        best_trade=best_trade,
        worst_trade=worst_trade,
        confidence_calibration=confidence_calibration,
    )


async def _compute_confidence_calibration(
    client: object,
    user_id: str,
    outcomes: list[dict],
) -> list[dict]:
    """Bucket outcomes by recommendation confidence and compute actual win rates."""
    if not outcomes:
        return []

    from supabase import AsyncClient as SupabaseClient

    sb = client  # type: ignore[assignment]
    assert isinstance(sb, SupabaseClient)

    rec_ids = list({o["recommendation_id"] for o in outcomes})
    rec_resp = (
        await sb.table("recommendations").select("id, confidence").in_("id", rec_ids).execute()
    )
    conf_map = {r["id"]: r["confidence"] for r in rec_resp.data}

    buckets: dict[str, list[float]] = {"high": [], "medium": [], "low": []}
    for o in outcomes:
        conf = conf_map.get(o["recommendation_id"], 0.5)
        pnl = o.get("pnl_dollars") or 0.0
        if conf > 0.75:
            buckets["high"].append(pnl)
        elif conf >= 0.55:
            buckets["medium"].append(pnl)
        else:
            buckets["low"].append(pnl)

    calibration: list[dict] = []
    for label, trades in buckets.items():
        if not trades:
            continue
        bucket_wins = sum(1 for p in trades if p > 0)
        calibration.append(
            {
                "bucket": label,
                "count": len(trades),
                "win_rate": round((bucket_wins / len(trades)) * 100, 1),
            }
        )

    return calibration


@router.post("/paper-trades/process")
async def trigger_paper_trade_processing(user_id: CurrentUser) -> dict[str, Any]:
    """Run due paper-trade price checks (FMP quotes) and update stored P&L."""
    _ = user_id
    return await process_pending_checks()


@router.get("/paper-performance")
async def read_paper_performance(user_id: CurrentUser) -> dict[str, Any]:
    """Aggregate paper trading stats for the authenticated user."""
    return await get_paper_performance(user_id)


@router.get("/calibration-curve")
async def get_calibration_curve(user_id: CurrentUser) -> dict:
    """Return the empirical calibration curve from historical outcomes.

    Bins raw GPT confidence vs actual win rate. When sufficient data
    exists (50+ outcomes), also provides isotonic regression mapping.
    """
    result = await compute_calibration_curve(user_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Not enough outcome data to build a calibration curve (need 50+).",
        )
    return result
