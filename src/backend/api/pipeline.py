"""Pipeline API endpoints for triggering and monitoring analysis runs."""

from __future__ import annotations

import json

import asyncpg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class PipelineRunRequest(BaseModel):
    """Request body for triggering a pipeline run."""

    strategy_id: str | None = None
    manual_tickers: list[str] = Field(default_factory=list)
    user_prompt: str | None = None


class PipelineRunResponse(BaseModel):
    """Immediate response when a pipeline run is triggered."""

    run_id: str
    status: str


@router.post("/run", response_model=PipelineRunResponse)
async def trigger_pipeline_run(
    request: PipelineRunRequest,
    user_id: CurrentUser,
) -> PipelineRunResponse:
    """Trigger a new pipeline analysis run.

    Runs asynchronously in the background. Poll ``/pipeline/status/{id}``
    for progress.
    """
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
    """Get the status and full result of a pipeline run.

    Fetches from the database. Returns 404 if not found or not owned by user.
    """
    pool = await get_db()
    row = await pool.fetchrow(
        "SELECT * FROM pipeline_runs WHERE id = $1 AND user_id = $2",
        run_id,
        user_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found")

    recs = await _load_recommendations(pool, run_id)
    screening = await _load_screening(pool, run_id)
    sentiments = await _load_sentiment_analyses(pool, run_id)
    charts = await _load_chart_analyses(pool, run_id)

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
    """Compact summary of a pipeline run for listing."""

    id: str
    strategy_id: str | None
    mode: str
    status: str
    started_at: str
    duration_seconds: float | None
    tickers: list[str] = Field(default_factory=list)


@router.get("/runs", response_model=list[PipelineRunSummary])
async def list_pipeline_runs(user_id: CurrentUser) -> list[PipelineRunSummary]:
    """List all past pipeline runs, most recent first."""
    pool = await get_db()
    rows = await pool.fetch(
        "SELECT id, strategy_id, mode, status, started_at, duration_seconds, manual_tickers "
        "FROM pipeline_runs WHERE user_id = $1 ORDER BY started_at DESC LIMIT 100",
        user_id,
    )

    summaries: list[PipelineRunSummary] = []
    for r in rows:
        manual = json.loads(r["manual_tickers"]) if r["manual_tickers"] else []

        rec_rows = await pool.fetch(
            "SELECT DISTINCT ticker FROM recommendations WHERE run_id = $1",
            r["id"],
        )
        discovered = [rr["ticker"] for rr in rec_rows]

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
    """Get full pipeline result for a specific run."""
    return await get_pipeline_status(run_id, user_id)


async def _load_recommendations(
    pool: asyncpg.Pool,
    run_id: str,
) -> list[Recommendation]:
    """Load saved recommendations for a pipeline run from the database."""
    rows = await pool.fetch(
        "SELECT * FROM recommendations WHERE run_id = $1 ORDER BY confidence DESC",
        run_id,
    )
    recs: list[Recommendation] = []
    for r in rows:
        bull = None
        bear = None
        if r["bull_case"] and r["bull_case"] != "{}":
            try:
                bull = DebateCase.model_validate_json(r["bull_case"])
            except Exception:
                pass
        if r["bear_case"] and r["bear_case"] != "{}":
            try:
                bear = DebateCase.model_validate_json(r["bear_case"])
            except Exception:
                pass

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
    pool: asyncpg.Pool,
    run_id: str,
) -> ScreeningResult | None:
    """Reconstruct a ScreeningResult from saved stage output and recommendations."""
    row = await pool.fetchrow(
        "SELECT raw_response FROM stage_outputs WHERE run_id = $1 AND stage = 'perplexity' LIMIT 1",
        run_id,
    )
    if row and row["raw_response"]:
        try:
            return ScreeningResult.model_validate_json(row["raw_response"])
        except Exception:
            pass

    rec_rows = await pool.fetch(
        "SELECT DISTINCT ticker FROM recommendations WHERE run_id = $1",
        run_id,
    )
    if not rec_rows:
        return None

    tickers = [FundamentalData(ticker=r["ticker"]) for r in rec_rows]
    return ScreeningResult(
        mode="discovery",
        tickers=tickers,
        screening_summary="Reconstructed from saved recommendations.",
    )


async def _load_sentiment_analyses(
    pool: asyncpg.Pool,
    run_id: str,
) -> list[SentimentAnalysis]:
    """Load saved Gemini sentiment analyses for a pipeline run."""
    rows = await pool.fetch(
        "SELECT raw_response FROM stage_outputs "
        "WHERE run_id = $1 AND stage = 'gemini' AND status = 'success'",
        run_id,
    )
    sentiments: list[SentimentAnalysis] = []
    for r in rows:
        if r["raw_response"]:
            try:
                sentiments.append(SentimentAnalysis.model_validate_json(r["raw_response"]))
            except Exception:
                pass
    return sentiments


async def _load_chart_analyses(
    pool: asyncpg.Pool,
    run_id: str,
) -> list[ChartAnalysis]:
    """Load saved Claude chart analyses for a pipeline run."""
    rows = await pool.fetch(
        "SELECT raw_response FROM stage_outputs "
        "WHERE run_id = $1 AND stage = 'claude' AND status = 'success'",
        run_id,
    )
    charts: list[ChartAnalysis] = []
    for r in rows:
        if r["raw_response"]:
            try:
                charts.append(ChartAnalysis.model_validate_json(r["raw_response"]))
            except Exception:
                pass
    return charts
