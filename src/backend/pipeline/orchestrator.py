"""Pipeline execution engine.

Phase 1: Runs only the Perplexity screening stage.
Future phases add Claude, Gemini, and GPT stages with parallel execution.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Literal

from database.connection import get_db
from pipeline.prompts.perplexity_analysis import get_prompt_hash as analysis_hash
from pipeline.prompts.perplexity_discovery import get_prompt_hash as discovery_hash
from pipeline.schemas import PipelineResult, StrategyConfig
from pipeline.stages.perplexity import run_analysis, run_discovery
from services.strategy import get_strategy

logger = logging.getLogger(__name__)

_active_runs: dict[str, PipelineResult] = {}


def get_run_status(run_id: str) -> PipelineResult | None:
    """Return the current state of an in-progress or completed pipeline run.

    Args:
        run_id: The pipeline run UUID.

    Returns:
        The PipelineResult if found, else None.
    """
    return _active_runs.get(run_id)


async def run_pipeline(
    *,
    strategy_id: str | None = None,
    manual_tickers: list[str] | None = None,
) -> PipelineResult:
    """Execute the analysis pipeline.

    Phase 1 only runs Perplexity. The mode is determined by inputs:
    - strategy_id only → discovery mode
    - manual_tickers only → analysis mode
    - both → combined mode

    Args:
        strategy_id: Optional strategy UUID for discovery screening.
        manual_tickers: Optional list of ticker symbols.

    Returns:
        Completed PipelineResult with screening data and metadata.
    """
    run_id = uuid.uuid4().hex
    start = time.perf_counter()

    mode: Literal["discovery", "analysis", "combined"] = _determine_mode(
        strategy_id, manual_tickers
    )

    config: StrategyConfig | None = None
    if strategy_id:
        config = await get_strategy(strategy_id)
        if not config:
            raise ValueError(f"Strategy '{strategy_id}' not found")

    result = PipelineResult(
        run_id=run_id,
        timestamp=datetime.now(tz=UTC),
        strategy_name=config.name if config else None,
        mode=mode,
        input_tickers=manual_tickers or [],
    )
    _active_runs[run_id] = result

    db = await get_db()
    await db.execute(
        """
        INSERT INTO pipeline_runs (id, strategy_id, mode, manual_tickers, status, started_at)
        VALUES (?, ?, ?, ?, 'running', ?)
        """,
        (run_id, strategy_id, mode, json.dumps(manual_tickers or []), result.timestamp.isoformat()),
    )
    await db.commit()

    screening = None
    stage_metadata: dict = {}

    try:
        if mode == "discovery" and config:
            screening, stage_metadata = await run_discovery(config)
        elif mode == "analysis":
            screening, stage_metadata = await run_analysis(manual_tickers or [], config)
        elif mode == "combined" and config:
            discovery_result, _disc_meta = await run_discovery(config)
            all_tickers = list(manual_tickers or [])
            if discovery_result:
                all_tickers.extend(t.ticker for t in discovery_result.tickers)
            all_tickers = list(dict.fromkeys(all_tickers))
            screening, stage_metadata = await run_analysis(all_tickers, config)
            if not screening and discovery_result:
                screening = discovery_result
    except Exception as exc:
        result.stage_errors.append(
            {
                "stage": "perplexity",
                "error": str(exc),
                "type": type(exc).__name__,
            }
        )
        logger.exception("Pipeline Perplexity stage failed")

    if screening:
        result.screening = screening
    elif not result.stage_errors:
        result.stage_errors.append(
            {
                "stage": "perplexity",
                "error": "Screening returned no results after retries",
                "type": "validation_failed",
            }
        )

    await _save_stage_output(run_id, stage_metadata)

    elapsed = time.perf_counter() - start
    result.total_duration_seconds = round(elapsed, 2)
    result.prompt_versions = {
        "perplexity": discovery_hash() if mode == "discovery" else analysis_hash()
    }

    status = "completed" if screening else ("partial" if result.stage_errors else "failed")
    await db.execute(
        """
        UPDATE pipeline_runs
        SET status = ?, completed_at = ?, duration_seconds = ?,
            prompt_versions = ?, stage_errors = ?
        WHERE id = ?
        """,
        (
            status,
            datetime.now(tz=UTC).isoformat(),
            result.total_duration_seconds,
            json.dumps(result.prompt_versions),
            json.dumps(result.stage_errors) if result.stage_errors else None,
            run_id,
        ),
    )
    await db.commit()

    return result


async def _save_stage_output(run_id: str, metadata: dict) -> None:
    """Persist raw stage output to the stage_outputs table."""
    if not metadata:
        return

    db = await get_db()
    await db.execute(
        """
        INSERT INTO stage_outputs (
            id, run_id, stage, prompt_text, raw_response, model_used,
            duration_ms, status, retry_count, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (
            uuid.uuid4().hex,
            run_id,
            metadata.get("stage", "perplexity"),
            metadata.get("prompt_text", ""),
            metadata.get("raw_response", ""),
            metadata.get("model", ""),
            metadata.get("duration_ms", 0),
            metadata.get("status", "unknown"),
            datetime.now(tz=UTC).isoformat(),
        ),
    )
    await db.commit()


def _determine_mode(
    strategy_id: str | None,
    manual_tickers: list[str] | None,
) -> Literal["discovery", "analysis", "combined"]:
    """Determine pipeline mode from inputs."""
    has_strategy = strategy_id is not None
    has_tickers = bool(manual_tickers)

    if has_strategy and has_tickers:
        return "combined"
    if has_strategy:
        return "discovery"
    if has_tickers:
        return "analysis"
    raise ValueError("Either strategy_id or manual_tickers (or both) must be provided")
