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

    client = await get_db()
    await client.table("pipeline_runs").insert(
        {
            "id": run_id,
            "user_id": user_id,
            "strategy_id": strategy_id,
            "mode": mode,
            "manual_tickers": json.dumps(manual_tickers or []),
            "status": "running",
            "started_at": result.timestamp.isoformat(),
        }
    ).execute()

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

    # Stage 2: Gemini news sentiment
    effective_config = config or StrategyConfig(id="default", name="default", screening_prompt="")

    if screening and screening.tickers:
        ticker_symbols = [t.ticker for t in screening.tickers]
        ticker_news = {
            t.ticker: t.news_urls
            for t in screening.tickers
            if t.news_urls
        }
        try:
            sentiments, gemini_metadata_list = await run_sentiment(
                ticker_symbols, effective_config, ticker_news=ticker_news or None
            )
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

    # Stage 3: Claude chart analysis
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

    # Stage 4: GPT debate / synthesis
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
    await client.table("pipeline_runs").update(
        {
            "status": status,
            "completed_at": datetime.now(tz=UTC).isoformat(),
            "duration_seconds": result.total_duration_seconds,
            "prompt_versions": json.dumps(result.prompt_versions),
            "stage_errors": json.dumps(result.stage_errors) if result.stage_errors else None,
        }
    ).eq("id", run_id).execute()

    return result


async def _save_stage_output(run_id: str, metadata: dict) -> None:
    """Persist raw stage output to the stage_outputs table."""
    if not metadata:
        return

    client = await get_db()
    row: dict = {
        "id": uuid.uuid4().hex,
        "run_id": run_id,
        "stage": metadata.get("stage", "perplexity"),
        "ticker": metadata.get("ticker"),
        "prompt_text": metadata.get("prompt_text", ""),
        "raw_response": metadata.get("raw_response", ""),
        "model_used": metadata.get("model", ""),
        "duration_ms": metadata.get("duration_ms", 0),
        "status": metadata.get("status", "unknown"),
        "retry_count": 0,
        "created_at": datetime.now(tz=UTC).isoformat(),
    }
    if metadata.get("error"):
        row["parsed_output"] = metadata["error"]
    await client.table("stage_outputs").insert(row).execute()


async def _save_recommendations(
    run_id: str, recommendations: list[Recommendation], user_id: str
) -> None:
    """Persist validated recommendations to the recommendations table."""
    if not recommendations:
        return

    client = await get_db()
    rows = [
        {
            "id": uuid.uuid4().hex,
            "run_id": run_id,
            "user_id": user_id,
            "ticker": rec.ticker,
            "action": rec.action,
            "confidence": rec.confidence,
            "entry_price": rec.entry_price,
            "stop_loss": rec.stop_loss,
            "take_profit": rec.take_profit,
            "position_size_pct": rec.position_size_pct,
            "risk_reward_ratio": rec.risk_reward_ratio,
            "holding_period": rec.holding_period,
            "bull_case": rec.bull_case.model_dump_json() if rec.bull_case else "{}",
            "bear_case": rec.bear_case.model_dump_json() if rec.bear_case else "{}",
            "judge_reasoning": rec.judge_reasoning,
            "key_factors": json.dumps(rec.key_factors),
            "warnings": json.dumps(rec.warnings) if rec.warnings else None,
        }
        for rec in recommendations
    ]
    await client.table("recommendations").insert(rows).execute()
    logger.info("Saved %d recommendations for run %s", len(recommendations), run_id)


def _determine_mode(
    strategy_id: str | None,
    manual_tickers: list[str] | None,
    user_prompt: str | None = None,
) -> Literal["discovery", "analysis", "combined", "prompt"]:
    """Determine pipeline mode from inputs."""
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
