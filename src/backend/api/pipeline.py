"""Pipeline API endpoints for triggering and monitoring analysis runs."""

from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from database.connection import get_db
from pipeline.orchestrator import get_run_status, run_pipeline
from pipeline.schemas import PipelineResult

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class PipelineRunRequest(BaseModel):
    """Request body for triggering a pipeline run."""

    strategy_id: str | None = None
    manual_tickers: list[str] = Field(default_factory=list)


class PipelineRunResponse(BaseModel):
    """Immediate response when a pipeline run is triggered."""

    run_id: str
    status: str


@router.post("/run", response_model=PipelineRunResponse)
async def trigger_pipeline_run(
    request: PipelineRunRequest,
    background_tasks: BackgroundTasks,
) -> PipelineRunResponse:
    """Trigger a new pipeline analysis run.

    Runs asynchronously in the background. Poll ``/pipeline/status/{id}``
    for progress.
    """
    if not request.strategy_id and not request.manual_tickers:
        raise HTTPException(
            status_code=400,
            detail="Either strategy_id or manual_tickers (or both) must be provided",
        )

    tickers = request.manual_tickers if request.manual_tickers else None

    result_holder: dict[str, str] = {}

    async def _run() -> None:
        try:
            result = await run_pipeline(
                strategy_id=request.strategy_id,
                manual_tickers=tickers,
            )
            result_holder["run_id"] = result.run_id
        except Exception:
            pass

    result = await run_pipeline(
        strategy_id=request.strategy_id,
        manual_tickers=tickers,
    )
    return PipelineRunResponse(run_id=result.run_id, status="completed")


@router.get("/status/{run_id}", response_model=PipelineResult | None)
async def get_pipeline_status(run_id: str) -> PipelineResult | None:
    """Poll the status of a pipeline run.

    Returns the current PipelineResult if the run is in memory,
    otherwise fetches from the database.
    """
    result = get_run_status(run_id)
    if result:
        return result

    db = await get_db()
    cursor = await db.execute("SELECT * FROM pipeline_runs WHERE id = ?", (run_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found")

    return PipelineResult(
        run_id=row["id"],
        strategy_name=None,
        mode=row["mode"],
        input_tickers=json.loads(row["manual_tickers"]) if row["manual_tickers"] else [],
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


@router.get("/runs", response_model=list[PipelineRunSummary])
async def list_pipeline_runs() -> list[PipelineRunSummary]:
    """List all past pipeline runs, most recent first."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, strategy_id, mode, status, started_at, duration_seconds "
        "FROM pipeline_runs ORDER BY started_at DESC LIMIT 100"
    )
    rows = await cursor.fetchall()
    return [
        PipelineRunSummary(
            id=r["id"],
            strategy_id=r["strategy_id"],
            mode=r["mode"],
            status=r["status"],
            started_at=r["started_at"],
            duration_seconds=r["duration_seconds"],
        )
        for r in rows
    ]


@router.get("/runs/{run_id}", response_model=PipelineResult | None)
async def get_pipeline_run(run_id: str) -> PipelineResult | None:
    """Get full pipeline result for a specific run."""
    return await get_pipeline_status(run_id)
