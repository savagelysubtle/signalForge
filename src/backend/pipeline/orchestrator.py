"""Pipeline execution engine.

Runs the full 4-stage analysis pipeline sequentially:
Perplexity (screening) → Gemini (news sentiment) →
Claude (charts with news context) → GPT (bull/bear/judge debate).
Gemini runs before Claude so that chart analysis is informed by
recent news catalysts.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Literal

from database.connection import get_db
from pipeline.prompts.claude_chart import get_prompt_hash as claude_hash
from pipeline.prompts.gemini_sentiment import get_prompt_hash as gemini_hash
from pipeline.prompts.gpt_debate import get_bear_hash, get_bull_hash, get_judge_hash
from pipeline.prompts.perplexity_analysis import get_prompt_hash as analysis_hash
from pipeline.prompts.perplexity_discovery import get_prompt_hash as discovery_hash
from pipeline.schemas import PipelineResult, Recommendation, StrategyConfig
from pipeline.stages.claude import run_chart_analysis
from pipeline.stages.gemini import run_sentiment
from pipeline.stages.gpt import run_debate
from pipeline.stages.perplexity import run_analysis, run_discovery, run_prompted_discovery
from services.reflection import load_reflection_context
from services.strategy import get_strategy

logger = logging.getLogger(__name__)


async def run_pipeline(
    *,
    strategy_id: str | None = None,
    manual_tickers: list[str] | None = None,
    user_prompt: str | None = None,
    user_id: str,
) -> PipelineResult:
    """Execute the analysis pipeline.

    Runs Perplexity screening then Gemini news sentiment. The mode is
    determined by inputs:
    - strategy_id only → discovery mode
    - manual_tickers only → analysis mode
    - both → combined mode
    - user_prompt (with or without strategy) → prompt mode

    Args:
        strategy_id: Optional strategy UUID for discovery screening.
        manual_tickers: Optional list of ticker symbols.
        user_prompt: Optional free-form prompt for Perplexity screening.
        user_id: User UUID for multi-tenant data isolation.

    Returns:
        Completed PipelineResult with screening and sentiment data.
    """
    run_id = uuid.uuid4().hex
    start = time.perf_counter()

    mode: Literal["discovery", "analysis", "combined", "prompt"] = _determine_mode(
        strategy_id, manual_tickers, user_prompt
    )

    config: StrategyConfig | None = None
    if strategy_id:
        config = await get_strategy(strategy_id, user_id)
        if not config:
            raise ValueError(f"Strategy '{strategy_id}' not found")

    result = PipelineResult(
        run_id=run_id,
        timestamp=datetime.now(tz=UTC),
        strategy_name=config.name if config else None,
        mode=mode,
        input_tickers=manual_tickers or [],
    )

    pool = await get_db()
    await pool.execute(
        """
        INSERT INTO pipeline_runs
        (id, user_id, strategy_id, mode, manual_tickers, status, started_at)
        VALUES ($1, $2, $3, $4, $5, 'running', $6)
        """,
        run_id,
        user_id,
        strategy_id,
        mode,
        json.dumps(manual_tickers or []),
        result.timestamp.isoformat(),
    )

    screening = None
    stage_metadata: dict = {}

    try:
        if mode == "prompt":
            screening, stage_metadata = await run_prompted_discovery(user_prompt or "", config)
        elif mode == "discovery" and config:
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

    # ------------------------------------------------------------------
    # Stage 2: Gemini news sentiment (runs after Perplexity)
    # ------------------------------------------------------------------
    effective_config = config or StrategyConfig(id="default", name="default", screening_prompt="")

    if screening and screening.tickers:
        ticker_symbols = [t.ticker for t in screening.tickers]
        try:
            sentiments, gemini_metadata_list = await run_sentiment(ticker_symbols, effective_config)
            result.sentiment_analyses = sentiments
            for gm in gemini_metadata_list:
                await _save_stage_output(run_id, gm)
        except Exception as exc:
            result.stage_errors.append(
                {
                    "stage": "gemini",
                    "error": str(exc),
                    "type": type(exc).__name__,
                }
            )
            logger.exception("Pipeline Gemini stage failed")

    # ------------------------------------------------------------------
    # Stage 3: Claude chart analysis (with news context from Gemini)
    # ------------------------------------------------------------------
    if screening and screening.tickers:
        ticker_symbols = [t.ticker for t in screening.tickers]
        try:
            charts, claude_metadata_list = await run_chart_analysis(
                ticker_symbols,
                effective_config,
                result.sentiment_analyses,
                run_id,
                user_id,
            )
            result.chart_analyses = charts
            for cm in claude_metadata_list:
                await _save_stage_output(run_id, cm)
        except Exception as exc:
            result.stage_errors.append(
                {
                    "stage": "claude",
                    "error": str(exc),
                    "type": type(exc).__name__,
                }
            )
            logger.exception("Pipeline Claude stage failed")

    # ------------------------------------------------------------------
    # Stage 4: GPT debate / synthesis
    # ------------------------------------------------------------------
    ticker_symbols = (
        [t.ticker for t in screening.tickers]
        if screening and screening.tickers
        else list(manual_tickers or [])
    )
    logger.info("Stage 4 GPT: ticker_symbols=%s", ticker_symbols)
    if ticker_symbols:
        try:
            reflection_context = await load_reflection_context()
            recommendations, gpt_metadata_list = await run_debate(
                ticker_symbols,
                screening,
                result.chart_analyses,
                result.sentiment_analyses,
                effective_config,
                reflection_context,
                run_id,
            )
            result.recommendations = recommendations
            for gm in gpt_metadata_list:
                await _save_stage_output(run_id, gm)
            await _save_recommendations(run_id, recommendations, user_id)
        except Exception as exc:
            result.stage_errors.append(
                {
                    "stage": "gpt",
                    "error": str(exc),
                    "type": type(exc).__name__,
                }
            )
            logger.exception("Pipeline GPT stage failed")

    logger.info("Stage 4 GPT complete: %d recommendations", len(result.recommendations))

    elapsed = time.perf_counter() - start
    result.total_duration_seconds = round(elapsed, 2)
    result.prompt_versions = {
        "perplexity": discovery_hash() if mode == "discovery" else analysis_hash(),
        "gemini": gemini_hash(),
        "claude": claude_hash(),
        "gpt_bull": get_bull_hash(),
        "gpt_bear": get_bear_hash(),
        "gpt_judge": get_judge_hash(),
    }

    has_data = (
        screening or result.sentiment_analyses or result.chart_analyses or result.recommendations
    )
    status = "completed" if has_data else ("partial" if result.stage_errors else "failed")
    await pool.execute(
        """
        UPDATE pipeline_runs
        SET status = $1, completed_at = $2, duration_seconds = $3,
            prompt_versions = $4, stage_errors = $5
        WHERE id = $6
        """,
        status,
        datetime.now(tz=UTC).isoformat(),
        result.total_duration_seconds,
        json.dumps(result.prompt_versions),
        json.dumps(result.stage_errors) if result.stage_errors else None,
        run_id,
    )

    return result


async def _save_stage_output(run_id: str, metadata: dict) -> None:
    """Persist raw stage output to the stage_outputs table."""
    if not metadata:
        return

    pool = await get_db()
    await pool.execute(
        """
        INSERT INTO stage_outputs (
            id, run_id, stage, prompt_text, raw_response, model_used,
            duration_ms, status, retry_count, created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 0, $9)
        """,
        uuid.uuid4().hex,
        run_id,
        metadata.get("stage", "perplexity"),
        metadata.get("prompt_text", ""),
        metadata.get("raw_response", ""),
        metadata.get("model", ""),
        metadata.get("duration_ms", 0),
        metadata.get("status", "unknown"),
        datetime.now(tz=UTC).isoformat(),
    )


async def _save_recommendations(
    run_id: str, recommendations: list[Recommendation], user_id: str
) -> None:
    """Persist validated recommendations to the recommendations table.

    Args:
        run_id: Pipeline run UUID.
        recommendations: List of validated recommendation objects.
        user_id: User UUID for multi-tenant data isolation.
    """
    if not recommendations:
        return

    pool = await get_db()
    for rec in recommendations:
        await pool.execute(
            """
            INSERT INTO recommendations (
                id, run_id, user_id, ticker, action, confidence, entry_price,
                stop_loss, take_profit, position_size_pct, risk_reward_ratio,
                holding_period, bull_case, bear_case, judge_reasoning,
                key_factors, warnings
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
            """,
            uuid.uuid4().hex,
            run_id,
            user_id,
            rec.ticker,
            rec.action,
            rec.confidence,
            rec.entry_price,
            rec.stop_loss,
            rec.take_profit,
            rec.position_size_pct,
            rec.risk_reward_ratio,
            rec.holding_period,
            rec.bull_case.model_dump_json() if rec.bull_case else "{}",
            rec.bear_case.model_dump_json() if rec.bear_case else "{}",
            rec.judge_reasoning,
            json.dumps(rec.key_factors),
            json.dumps(rec.warnings) if rec.warnings else None,
        )
    logger.info("Saved %d recommendations for run %s", len(recommendations), run_id)


def _determine_mode(
    strategy_id: str | None,
    manual_tickers: list[str] | None,
    user_prompt: str | None = None,
) -> Literal["discovery", "analysis", "combined", "prompt"]:
    """Determine pipeline mode from inputs.

    A user_prompt takes priority — when provided the pipeline uses
    Perplexity to find stocks based on the free-form prompt (optionally
    augmented by a selected strategy's configuration).
    """
    has_strategy = strategy_id is not None
    has_tickers = bool(manual_tickers)
    has_prompt = bool(user_prompt)

    if has_prompt:
        return "prompt"
    if has_strategy and has_tickers:
        return "combined"
    if has_strategy:
        return "discovery"
    if has_tickers:
        return "analysis"
    raise ValueError("Provide a strategy, tickers, or a prompt")
