"""Pipeline execution engine.

Runs the full pipeline sequentially:
FMP pre-screening (optional) → Perplexity (screening/research) →
Gemini (news sentiment) → Claude (charts with news context) →
GPT (bull/bear/judge debate).
Gemini runs before Claude so that chart analysis is informed by
recent news catalysts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

from supabase import AsyncClient

from database.connection import get_db
from pipeline.prompts.claude_chart import get_prompt_hash as claude_hash
from pipeline.prompts.gemini_sentiment import get_prompt_hash as gemini_hash
from pipeline.prompts.gpt_debate import get_bear_hash, get_bull_hash, get_judge_hash
from pipeline.prompts.perplexity_analysis import get_prompt_hash as analysis_hash
from pipeline.prompts.perplexity_discovery import get_prompt_hash as discovery_hash
from pipeline.schemas import (
    ChartAnalysis,
    ChartError,
    PipelineResult,
    Recommendation,
    StrategyConfig,
)
from pipeline.stages.claude import run_chart_analysis
from pipeline.stages.gemini import run_sentiment
from pipeline.stages.gpt import run_debate
from pipeline.stages.perplexity import run_analysis, run_discovery, run_prompted_discovery
from services.chart_image import fetch_annotated_chart
from services.fmp_service import FmpEnrichedStock, screen_and_enrich
from services.keyring_service import get_api_key
from services.reflection import load_reflection_context
from services.strategy import get_strategy
from utils.ticker import normalize_ticker, normalize_tickers

logger = logging.getLogger(__name__)

STAGE_TIMEOUTS: dict[str, float] = {
    "fmp": 90.0,
    "perplexity": 180.0,
    "gemini": 120.0,
    "claude": 360.0,
    "gpt": 180.0,
    "annotate": 60.0,
}


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

    if manual_tickers:
        manual_tickers = normalize_tickers(manual_tickers)

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
    await (
        client.table("pipeline_runs")
        .insert(
            {
                "id": run_id,
                "user_id": user_id,
                "strategy_id": strategy_id,
                "mode": mode,
                "manual_tickers": json.dumps(manual_tickers or []),
                "user_prompt": user_prompt,
                "status": "running",
                "started_at": result.timestamp.isoformat(),
            }
        )
        .execute()
    )

    # Stage 0: FMP Pre-Screening (if strategy has fmp_screener config)
    fmp_candidates: list[FmpEnrichedStock] | None = None
    fmp_enabled = (
        config is not None
        and config.fmp_screener is not None
        and config.fmp_screener.enabled
        and mode != "analysis"
    )

    if fmp_enabled and config and config.fmp_screener:
        fmp_key = get_api_key("fmp")
        if fmp_key:
            try:
                fmp_candidates = await asyncio.wait_for(
                    screen_and_enrich(config.fmp_screener),
                    timeout=STAGE_TIMEOUTS["fmp"],
                )
                logger.info(
                    "FMP pre-screened %d candidates for strategy '%s'",
                    len(fmp_candidates),
                    config.name,
                )
            except TimeoutError:
                logger.error("FMP stage timed out after %ss", STAGE_TIMEOUTS["fmp"])
                result.stage_errors.append(
                    {"stage": "fmp", "error": "Stage timed out", "type": "TimeoutError"}
                )
            except Exception as exc:
                logger.warning("FMP screening failed, continuing without: %s", exc)
                result.stage_errors.append(
                    {
                        "stage": "fmp",
                        "error": str(exc),
                        "type": type(exc).__name__,
                    }
                )
        else:
            logger.info("FMP_API_KEY not set, skipping FMP pre-screening")

    fmp_map: dict[str, FmpEnrichedStock] = {}
    if fmp_candidates:
        fmp_map = {s.symbol: s for s in fmp_candidates}

    # Stage 1: Perplexity (screening/research)
    screening = None
    stage_metadata: dict = {}

    try:

        async def _run_perplexity_stage() -> tuple:
            if mode == "prompt":
                return await run_prompted_discovery(
                    user_prompt or "", config, fmp_candidates=fmp_candidates
                )
            if mode == "discovery" and config:
                return await run_discovery(config, fmp_candidates=fmp_candidates)
            if mode == "discovery" and not config:
                default_prompt = "trending Canadian TSX stocks and top TSX market movers today"
                return await run_prompted_discovery(default_prompt, None)
            if mode == "analysis":
                return await run_analysis(manual_tickers or [], config)
            if mode == "combined" and config:
                discovery_result, _disc_meta = await run_discovery(
                    config, fmp_candidates=fmp_candidates
                )
                all_tickers = list(manual_tickers or [])
                if discovery_result:
                    all_tickers.extend(t.ticker for t in discovery_result.tickers)
                all_tickers = list(dict.fromkeys(all_tickers))
                _screening, _meta = await run_analysis(all_tickers, config)
                if not _screening and discovery_result:
                    _screening = discovery_result
                return _screening, _meta
            return None, {}

        screening, stage_metadata = await asyncio.wait_for(
            _run_perplexity_stage(),
            timeout=STAGE_TIMEOUTS["perplexity"],
        )
    except TimeoutError:
        result.stage_errors.append(
            {"stage": "perplexity", "error": "Stage timed out", "type": "TimeoutError"}
        )
        logger.error("Perplexity stage timed out after %ss", STAGE_TIMEOUTS["perplexity"])
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
        for td in screening.tickers:
            td.ticker = normalize_ticker(td.ticker)
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
    result.chart_indicators = effective_config.chart_indicators

    if screening and screening.tickers:
        ticker_symbols = [t.ticker for t in screening.tickers]

        # Per-ticker news_urls are populated by _distribute_citations() in the
        # Perplexity stage. Fall back to broadcasting screening.citations only
        # when per-ticker URLs are empty (shouldn't happen after the overhaul).
        ticker_news: dict[str, list[str]] = {
            t.ticker: t.news_urls for t in screening.tickers if t.news_urls
        }
        if not ticker_news and screening.citations:
            for t in screening.tickers:
                ticker_news[t.ticker] = screening.citations[:3]

        try:
            sentiments, gemini_metadata_list = await asyncio.wait_for(
                run_sentiment(
                    ticker_symbols,
                    effective_config,
                    ticker_news=ticker_news or None,
                    fmp_context=fmp_map or None,
                ),
                timeout=STAGE_TIMEOUTS["gemini"],
            )
            result.sentiment_analyses = sentiments
            for gm in gemini_metadata_list:
                await _save_stage_output(run_id, gm)
        except TimeoutError:
            result.stage_errors.append(
                {"stage": "gemini", "error": "Stage timed out", "type": "TimeoutError"}
            )
            logger.error("Gemini stage timed out after %ss", STAGE_TIMEOUTS["gemini"])
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
            charts, claude_metadata_list = await asyncio.wait_for(
                run_chart_analysis(
                    ticker_symbols,
                    effective_config,
                    result.sentiment_analyses,
                    run_id,
                    user_id,
                    fmp_context=fmp_map or None,
                ),
                timeout=STAGE_TIMEOUTS["claude"],
            )
            result.chart_analyses = charts
            for cm in claude_metadata_list:
                await _save_stage_output(run_id, cm)
                if cm.get("status") not in ("success", None):
                    result.chart_errors.append(
                        ChartError(
                            ticker=cm.get("ticker", "unknown"),
                            status=cm.get("status", "unknown"),
                            error=cm.get("error", ""),
                        )
                    )
        except TimeoutError:
            result.stage_errors.append(
                {"stage": "claude", "error": "Stage timed out", "type": "TimeoutError"}
            )
            logger.error("Claude stage timed out after %ss", STAGE_TIMEOUTS["claude"])
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
            recommendations, gpt_metadata_list = await asyncio.wait_for(
                run_debate(
                    ticker_symbols,
                    screening,
                    result.chart_analyses,
                    result.sentiment_analyses,
                    effective_config,
                    reflection_context,
                    run_id,
                    fmp_context=fmp_map or None,
                ),
                timeout=STAGE_TIMEOUTS["gpt"],
            )
            result.recommendations = recommendations
            for gm in gpt_metadata_list:
                await _save_stage_output(run_id, gm)
            await _save_recommendations(run_id, recommendations, user_id)
        except TimeoutError:
            result.stage_errors.append(
                {"stage": "gpt", "error": "Stage timed out", "type": "TimeoutError"}
            )
            logger.error("GPT stage timed out after %ss", STAGE_TIMEOUTS["gpt"])
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

    # Stage 4.5: Generate annotated charts with key-level overlays
    if result.chart_analyses:
        rec_map = {r.ticker: r for r in result.recommendations}

        async def _annotate(ca_index: int) -> None:
            ca = result.chart_analyses[ca_index]
            rec = rec_map.get(ca.ticker)
            try:
                url = await fetch_annotated_chart(
                    ticker=ca.ticker,
                    timeframe=ca.timeframe,
                    key_levels=ca.key_levels,
                    run_id=run_id,
                    user_id=user_id,
                    entry_price=rec.entry_price if rec else None,
                    stop_loss=rec.stop_loss if rec else None,
                    take_profit=rec.take_profit if rec else None,
                )
                result.chart_analyses[ca_index].annotated_chart_path = url
            except Exception as exc:
                logger.warning(
                    "Annotated chart failed for %s %s: %s",
                    ca.ticker,
                    ca.timeframe,
                    exc,
                )
                result.stage_errors.append(
                    {
                        "stage": "annotate",
                        "error": str(exc),
                        "type": type(exc).__name__,
                        "ticker": ca.ticker,
                    }
                )

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *(_annotate(i) for i in range(len(result.chart_analyses))),
                    return_exceptions=True,
                ),
                timeout=STAGE_TIMEOUTS["annotate"],
            )
        except TimeoutError:
            logger.error("Annotate stage timed out after %ss", STAGE_TIMEOUTS["annotate"])
        logger.info("Stage 4.5 annotated charts complete")

        # Persist annotated_chart_path back into stage_outputs so it survives reload
        await _update_annotated_paths(client, run_id, result.chart_analyses)

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
    await (
        client.table("pipeline_runs")
        .update(
            {
                "status": status,
                "completed_at": datetime.now(tz=UTC).isoformat(),
                "duration_seconds": result.total_duration_seconds,
                "prompt_versions": json.dumps(result.prompt_versions),
                "stage_errors": json.dumps(result.stage_errors) if result.stage_errors else None,
            }
        )
        .eq("id", run_id)
        .execute()
    )

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
        "retry_count": metadata.get("retry_count", 0),
        "created_at": datetime.now(tz=UTC).isoformat(),
    }
    if metadata.get("error"):
        row["parsed_output"] = metadata["error"]
    await client.table("stage_outputs").insert(row).execute()


async def _update_annotated_paths(
    client: AsyncClient,
    run_id: str,
    chart_analyses: list[ChartAnalysis],
) -> None:
    """Persist annotated_chart_path into existing stage_outputs rows.

    Stage 4.5 sets annotated_chart_path on in-memory ChartAnalysis objects
    after Stage 3 already saved raw_response. This function updates those
    rows so the annotated URL survives database reloads.
    """
    analyses_with_paths = [ca for ca in chart_analyses if ca.annotated_chart_path]
    if not analyses_with_paths:
        return

    resp = (
        await client.table("stage_outputs")
        .select("id, ticker, raw_response")
        .eq("run_id", run_id)
        .eq("stage", "claude")
        .eq("status", "success")
        .execute()
    )
    rows = cast(list[dict[str, Any]], resp.data or [])

    row_map: dict[tuple[str, str], str] = {}
    for row in rows:
        if not row["raw_response"]:
            continue
        try:
            data = json.loads(row["raw_response"])
            key = (data.get("ticker", ""), data.get("timeframe", ""))
            row_map[key] = row["id"]
        except (
            json.JSONDecodeError,
            KeyError,
        ):
            continue

    for ca in analyses_with_paths:
        row_id = row_map.get((ca.ticker, ca.timeframe))
        if row_id:
            await (
                client.table("stage_outputs")
                .update({"raw_response": ca.model_dump_json()})
                .eq("id", row_id)
                .execute()
            )
            logger.debug(
                "Updated annotated_chart_path for %s %s in stage_outputs",
                ca.ticker,
                ca.timeframe,
            )


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
    return "discovery"
