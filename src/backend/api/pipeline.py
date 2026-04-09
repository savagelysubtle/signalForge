"""Pipeline API endpoints for triggering and monitoring analysis runs."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid

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
    ChartError,
    DebateCase,
    FundamentalData,
    PipelineResult,
    Recommendation,
    ScreenerOverrides,
    ScreeningResult,
    SentimentAnalysis,
)
from utils.ticker import normalize_tickers

logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/pipeline", tags=["pipeline"])

# Keeps strong references to background tasks so the GC doesn't cancel them
_background_tasks: set[asyncio.Task] = set()


class PipelineRunRequest(BaseModel):
    strategy_id: str | None = None
    manual_tickers: list[str] = Field(default_factory=list)
    user_prompt: str | None = None
    screener_overrides: ScreenerOverrides | None = None
    mode_override: str | None = None


class PipelineRunResponse(BaseModel):
    run_id: str
    status: str


@router.post("/run", response_model=PipelineRunResponse)
@limiter.limit("5/minute")
async def trigger_pipeline_run(
    request: Request,
    body: PipelineRunRequest,
    user_id: CurrentUser,
) -> PipelineRunResponse:
    """Trigger a new pipeline analysis run.

    Returns immediately with a run_id while the pipeline executes in the
    background. Poll GET /pipeline/progress/{run_id} for live stage updates
    and GET /pipeline/status/{run_id} once the run completes.
    """
    tickers = normalize_tickers(body.manual_tickers) if body.manual_tickers else None
    user_prompt = body.user_prompt.strip() if body.user_prompt else None
    run_id = uuid.uuid4().hex

    async def _run_background() -> None:
        try:
            await run_pipeline(
                run_id=run_id,
                strategy_id=body.strategy_id,
                manual_tickers=tickers,
                user_prompt=user_prompt,
                user_id=user_id,
                screener_overrides=body.screener_overrides,
                mode_override=body.mode_override,
            )
        except Exception as exc:
            logger.error("Background pipeline run %s failed: %s", run_id, exc, exc_info=True)
            # Mark the run as failed in the DB so the frontend stops polling
            with contextlib.suppress(Exception):
                db = await get_db()
                await (
                    db.table("pipeline_runs")
                    .update(
                        {
                            "status": "failed",
                            "stage_errors": json.dumps(
                                [
                                    {
                                        "stage": "pipeline",
                                        "error": str(exc),
                                        "type": type(exc).__name__,
                                    }
                                ]
                            ),
                        }
                    )
                    .eq("id", run_id)
                    .execute()
                )

    task = asyncio.create_task(_run_background())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return PipelineRunResponse(run_id=run_id, status="running")


@router.get("/status/{run_id}", response_model=PipelineResult | None)
async def get_pipeline_status(run_id: str, user_id: CurrentUser) -> PipelineResult | None:
    """Get the status and full result of a pipeline run."""
    client = await get_db()
    resp = (
        await client.table("pipeline_runs")
        .select("*")
        .eq("id", run_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = resp.data if resp else []
    row = rows[0] if rows else None
    if not row:
        raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found")

    recs, screening, sentiments, charts, chart_errors = await asyncio.gather(
        _load_recommendations(client, run_id),
        _load_screening(client, run_id),
        _load_sentiment_analyses(client, run_id),
        _load_chart_analyses(client, run_id),
        _load_chart_errors(client, run_id),
    )

    return PipelineResult(
        run_id=row["id"],
        strategy_name=None,
        mode=row["mode"],
        input_tickers=json.loads(row["manual_tickers"]) if row["manual_tickers"] else [],
        screening=screening,
        sentiment_analyses=sentiments,
        chart_analyses=charts,
        chart_errors=chart_errors,
        recommendations=recs,
        stage_errors=json.loads(row["stage_errors"]) if row["stage_errors"] else [],
        total_duration_seconds=row["duration_seconds"] or 0.0,
        prompt_versions=json.loads(row["prompt_versions"]) if row["prompt_versions"] else {},
    )


class PipelineRunSummary(BaseModel):
    id: str
    strategy_id: str | None
    strategy_name: str | None = None
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

    strategy_ids = list({r["strategy_id"] for r in rows if r["strategy_id"]})
    strategy_names: dict[str, str] = {}
    if strategy_ids:
        strat_resp = (
            await client.table("strategies").select("id, name").in_("id", strategy_ids).execute()
        )
        strategy_names = {s["id"]: s["name"] for s in strat_resp.data}

    run_ids = [r["id"] for r in rows]
    rec_map: dict[str, list[str]] = {}
    if run_ids:
        rec_resp = (
            await client.table("recommendations")
            .select("run_id, ticker")
            .in_("run_id", run_ids)
            .execute()
        )
        for rr in rec_resp.data:
            rec_map.setdefault(rr["run_id"], []).append(rr["ticker"])

    summaries: list[PipelineRunSummary] = []
    for r in rows:
        manual = json.loads(r["manual_tickers"]) if r["manual_tickers"] else []
        discovered = list(dict.fromkeys(rec_map.get(r["id"], [])))

        all_tickers = list(dict.fromkeys(manual + discovered))

        summaries.append(
            PipelineRunSummary(
                id=r["id"],
                strategy_id=r["strategy_id"],
                strategy_name=strategy_names.get(r["strategy_id"]) if r["strategy_id"] else None,
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


class StageProgress(BaseModel):
    """Progress state for a single pipeline stage."""

    stage: str
    label: str
    status: str  # "pending" | "running" | "done" | "error" | "skipped"
    count: int = 0


class PipelineProgress(BaseModel):
    """Live progress snapshot for a pipeline run."""

    run_id: str
    run_status: str
    elapsed_seconds: float | None
    stages: list[StageProgress]


_STAGE_LABELS: dict[str, str] = {
    "fmp": "FMP Pre-Screening",
    "perplexity": "Perplexity Screening",
    "gemini": "Gemini Sentiment",
    "claude": "Claude Chart Analysis",
    "gpt": "GPT Synthesis",
    "annotate": "Annotated Charts",
}

_STAGE_ORDER = ["fmp", "perplexity", "gemini", "claude", "gpt", "annotate"]


@router.get("/progress/{run_id}", response_model=PipelineProgress)
async def get_pipeline_progress(run_id: str, user_id: CurrentUser) -> PipelineProgress:
    """Return live stage-by-stage progress for a pipeline run.

    Queries stage_outputs to infer which stages have started/completed.
    Safe to poll frequently — all queries are lightweight counts.
    """
    client = await get_db()

    run_resp = (
        await client.table("pipeline_runs")
        .select("status, started_at, duration_seconds")
        .eq("id", run_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not run_resp.data:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    run_row = run_resp.data[0]
    run_status: str = run_row["status"]

    outputs_resp = (
        await client.table("stage_outputs").select("stage, status").eq("run_id", run_id).execute()
    )
    rows = outputs_resp.data or []

    stage_counts: dict[str, dict[str, int]] = {}
    for row in rows:
        s = row.get("stage") or "perplexity"
        if s.startswith("gpt_"):
            s = "gpt"
        st = row.get("status") or "unknown"
        if s not in stage_counts:
            stage_counts[s] = {}
        stage_counts[s][st] = stage_counts[s].get(st, 0) + 1

    def _stage_status(stage_name: str) -> tuple[str, int]:
        if stage_name not in stage_counts:
            return "pending", 0
        counts = stage_counts[stage_name]
        total = sum(counts.values())
        skipped = counts.get("skipped", 0)
        if skipped > 0 and total == skipped:
            return "skipped", 0
        success = counts.get("success", 0)
        terminal = success + sum(
            v for k, v in counts.items() if k not in ("success", "skipped", "running")
        )
        if terminal > 0:
            return "done", total
        return "running", total

    stages: list[StageProgress] = []
    for stage_name in _STAGE_ORDER:
        st, cnt = _stage_status(stage_name)
        stages.append(
            StageProgress(
                stage=stage_name,
                label=_STAGE_LABELS[stage_name],
                status=st,
                count=cnt,
            )
        )

    return PipelineProgress(
        run_id=run_id,
        run_status=run_status,
        elapsed_seconds=run_row.get("duration_seconds"),
        stages=stages,
    )


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
                id=r["id"],
                ticker=r["ticker"],
                action="SHORT" if r["action"] == "SELL" else r["action"],
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
                signal_generated_at=r.get("signal_generated_at"),
                price_at_signal=r.get("price_at_signal"),
                entry_valid_window=r.get("entry_valid_window"),
                raw_gpt_position_size_pct=r.get("raw_gpt_position_size_pct"),
                ml_probability=r.get("ml_probability"),
                ml_size_multiplier=r.get("ml_size_multiplier"),
                ml_blocked=r.get("ml_blocked", False),
                ml_model_version=r.get("ml_model_version"),
                ml_conformal_set=json.loads(r["ml_conformal_set"])
                if r.get("ml_conformal_set")
                else [],
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
        .execute()
    )
    rows = resp.data if resp else []
    row = rows[0] if rows else None
    if row and row["raw_response"]:
        try:
            return ScreeningResult.model_validate_json(row["raw_response"])
        except Exception:
            pass

    rec_resp = await client.table("recommendations").select("ticker").eq("run_id", run_id).execute()
    rec_rows = rec_resp.data
    if not rec_rows:
        return None

    tickers = [FundamentalData(ticker=t) for t in dict.fromkeys(r["ticker"] for r in rec_rows)]
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


async def _load_chart_errors(
    client: AsyncClient,
    run_id: str,
) -> list[ChartError]:
    """Load per-ticker chart analysis errors for a pipeline run."""
    resp = (
        await client.table("stage_outputs")
        .select("ticker, status, parsed_output")
        .eq("run_id", run_id)
        .eq("stage", "claude")
        .neq("status", "success")
        .execute()
    )
    rows = resp.data
    errors: list[ChartError] = []
    for r in rows:
        errors.append(
            ChartError(
                ticker=r.get("ticker", "unknown"),
                status=r.get("status", "unknown"),
                error=r.get("parsed_output") or "",
            )
        )
    return errors
