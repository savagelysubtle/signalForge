"""Pipeline API endpoints for triggering and monitoring analysis runs."""

from __future__ import annotations

import contextlib
import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from supabase import AsyncClient

from database.connection import get_db
from middleware.auth import CurrentUser
from pipeline.orchestrator import run_pipeline
from pipeline.schemas import (
    ChartAnalysis,
    DebateCase,
    FundamentalData,
    PipelineResult,
    Recommendation,
    ScreeningResult,
    SentimentAnalysis,
)

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class PipelineRunRequest(BaseModel):
    strategy_id: str | None = None
    manual_tickers: list[str] = Field(default_factory=list)
    user_prompt: str | None = None


class PipelineRunResponse(BaseModel):
    run_id: str
    status: str


@router.post("/run", response_model=PipelineRunResponse)
@limiter.limit("5/minute")
async def trigger_pipeline_run(
    request: PipelineRunRequest,
    user_id: CurrentUser,
    _rate_limit_request: Request = None,
) -> PipelineRunResponse:
    """Trigger a new pipeline analysis run."""
    if not request.strategy_id and not request.manual_tickers and not request.user_prompt:
        raise HTTPException(
            status_code=400,
            detail="Provide a strategy, tickers, or a prompt",
        )

    tickers = request.manual_tickers if request.manual_tickers else None
    user_prompt = request.user_prompt.strip() if request.user_prompt else None

    result = await run_pipeline(
        strategy_id=request.strategy_id,
        manual_tickers=tickers,
        user_prompt=user_prompt,
        user_id=user_id,
    )
    return PipelineRunResponse(run_id=result.run_id, status="completed")


@router.get("/status/{run_id}", response_model=PipelineResult | None)
async def get_pipeline_status(run_id: str, user_id: CurrentUser) -> PipelineResult | None:
    """Get the status and full result of a pipeline run."""
    client = await get_db()
    resp = (
        await client.table("pipeline_runs")
        .select("*")
        .eq("id", run_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    row = resp.data
    if not row:
        raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found")

    recs = await _load_recommendations(client, run_id)
    screening = await _load_screening(client, run_id)
    sentiments = await _load_sentiment_analyses(client, run_id)
    charts = await _load_chart_analyses(client, run_id)

    return PipelineResult(
        run_id=row["id"],
        strategy_name=None,
        mode=row["mode"],
        input_tickers=json.loads(row["manual_tickers"]) if row["manual_tickers"] else [],
        screening=screening,
        sentiment_analyses=sentiments,
        chart_analyses=charts,
        recommendations=recs,
        stage_errors=json.loads(row["stage_errors"]) if row["stage_errors"] else [],
        total_duration_seconds=row["duration_seconds"] or 0.0,
        prompt_versions=json.loads(row["prompt_versions"]) if row["prompt_versions"] else {},
    )


class PipelineRunSummary(BaseModel):
    id: str
    strategy_id: str | None
    mode: str
    status: str
    started_at: str
    duration_seconds: float | None
    tickers: list[str] = Field(default_factory=list)


@router.get("/runs", response_model=list[PipelineRunSummary])
async def list_pipeline_runs(user_id: CurrentUser) -> list[PipelineRunSummary]:
    """List recent pipeline runs for the current user."""
    client = await get_db()
    resp = (
        await client.table("pipeline_runs")
        .select("id, strategy_id, mode, status, started_at, duration_seconds, manual_tickers")
        .eq("user_id", user_id)
        .order("started_at", desc=True)
        .limit(100)
        .execute()
    )
    rows = resp.data

    summaries: list[PipelineRunSummary] = []
    for r in rows:
        manual = json.loads(r["manual_tickers"]) if r["manual_tickers"] else []

        rec_resp = (
            await client.table("recommendations")
            .select("ticker")
            .eq("run_id", r["id"])
            .execute()
        )
        rec_rows = rec_resp.data
        discovered = list(dict.fromkeys(rr["ticker"] for rr in rec_rows))

        all_tickers = list(dict.fromkeys(manual + discovered))

        summaries.append(
            PipelineRunSummary(
                id=r["id"],
                strategy_id=r["strategy_id"],
                mode=r["mode"],
                status=r["status"],
                started_at=str(r["started_at"]),
                duration_seconds=r["duration_seconds"],
                tickers=all_tickers,
            )
        )
    return summaries


@router.get("/runs/{run_id}", response_model=PipelineResult | None)
async def get_pipeline_run(run_id: str, user_id: CurrentUser) -> PipelineResult | None:
    """Get a single pipeline run by ID."""
    return await get_pipeline_status(run_id, user_id)


async def _load_recommendations(
    client: AsyncClient,
    run_id: str,
) -> list[Recommendation]:
    """Load recommendations for a pipeline run."""
    resp = (
        await client.table("recommendations")
        .select("*")
        .eq("run_id", run_id)
        .order("confidence", desc=True)
        .execute()
    )
    rows = resp.data
    recs: list[Recommendation] = []
    for r in rows:
        bull = None
        bear = None
        if r["bull_case"] and r["bull_case"] != "{}":
            with contextlib.suppress(Exception):
                bull = DebateCase.model_validate_json(r["bull_case"])
        if r["bear_case"] and r["bear_case"] != "{}":
            with contextlib.suppress(Exception):
                bear = DebateCase.model_validate_json(r["bear_case"])

        recs.append(
            Recommendation(
                ticker=r["ticker"],
                action=r["action"],
                confidence=r["confidence"],
                entry_price=r["entry_price"],
                stop_loss=r["stop_loss"],
                take_profit=r["take_profit"],
                position_size_pct=r["position_size_pct"] or 0.0,
                risk_reward_ratio=r["risk_reward_ratio"],
                holding_period=r["holding_period"] or "",
                bull_case=bull,
                bear_case=bear,
                judge_reasoning=r["judge_reasoning"] or "",
                key_factors=json.loads(r["key_factors"]) if r["key_factors"] else [],
                warnings=json.loads(r["warnings"]) if r["warnings"] else [],
            )
        )
    return recs


async def _load_screening(
    client: AsyncClient,
    run_id: str,
) -> ScreeningResult | None:
    """Load screening result for a pipeline run."""
    resp = (
        await client.table("stage_outputs")
        .select("raw_response")
        .eq("run_id", run_id)
        .eq("stage", "perplexity")
        .limit(1)
        .maybe_single()
        .execute()
    )
    row = resp.data
    if row and row["raw_response"]:
        try:
            return ScreeningResult.model_validate_json(row["raw_response"])
        except Exception:
            pass

    rec_resp = (
        await client.table("recommendations")
        .select("ticker")
        .eq("run_id", run_id)
        .execute()
    )
    rec_rows = rec_resp.data
    if not rec_rows:
        return None

    tickers = [
        FundamentalData(ticker=t)
        for t in dict.fromkeys(r["ticker"] for r in rec_rows)
    ]
    return ScreeningResult(
        mode="discovery",
        tickers=tickers,
        screening_summary="Reconstructed from saved recommendations.",
    )


async def _load_sentiment_analyses(
    client: AsyncClient,
    run_id: str,
) -> list[SentimentAnalysis]:
    """Load sentiment analyses for a pipeline run."""
    resp = (
        await client.table("stage_outputs")
        .select("raw_response")
        .eq("run_id", run_id)
        .eq("stage", "gemini")
        .eq("status", "success")
        .execute()
    )
    rows = resp.data
    sentiments: list[SentimentAnalysis] = []
    for r in rows:
        if r["raw_response"]:
            with contextlib.suppress(Exception):
                sentiments.append(SentimentAnalysis.model_validate_json(r["raw_response"]))
    return sentiments


async def _load_chart_analyses(
    client: AsyncClient,
    run_id: str,
) -> list[ChartAnalysis]:
    """Load chart analyses for a pipeline run."""
    resp = (
        await client.table("stage_outputs")
        .select("raw_response")
        .eq("run_id", run_id)
        .eq("stage", "claude")
        .eq("status", "success")
        .execute()
    )
    rows = resp.data
    charts: list[ChartAnalysis] = []
    for r in rows:
        if r["raw_response"]:
            with contextlib.suppress(Exception):
                charts.append(ChartAnalysis.model_validate_json(r["raw_response"]))
    return charts
