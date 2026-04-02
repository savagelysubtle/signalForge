"""Pipeline execution engine.

Runs the full pipeline sequentially:
FMP pre-screening (optional) → Perplexity (screening/research) →
Gemini (news sentiment) → Risk screener (lightweight pre-filter) →
Claude (charts with news context) → GPT (bull/bear/judge debate).
Gemini runs before Claude so that chart analysis is informed by
recent news catalysts. The risk screener demotes structurally
ineligible tickers before expensive Claude analysis.
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
from pipeline.prompts.gpt_debate import (
    get_bear_hash,
    get_bear_hash_v2,
    get_bull_hash,
    get_bull_hash_v2,
    get_judge_hash,
    get_judge_hash_v2,
)
from pipeline.prompts.perplexity_analysis import get_prompt_hash as analysis_hash
from pipeline.prompts.perplexity_discovery import get_prompt_hash as discovery_hash
from pipeline.prompts.regime_classifier import format_regime_header
from pipeline.prompts.regime_classifier import get_prompt_hash as regime_hash
from pipeline.schemas import (
    ChartAnalysis,
    ChartError,
    FmpScreenerConfig,
    MultiTimeframeTechnical,
    PipelineResult,
    Recommendation,
    RegimeOutput,
    ScreenerOverrides,
    ScreeningResult,
    SentimentAnalysis,
    StrategyConfig,
)
from pipeline.stages.claude import run_chart_analysis, run_chart_analysis_v2
from pipeline.stages.gemini import run_sentiment
from pipeline.stages.gpt import run_debate, run_debate_v2
from pipeline.stages.numerical_ta import run_numerical_ta
from pipeline.stages.perplexity import (
    run_analysis,
    run_bull_bear_discovery,
    run_discovery,
    run_prompted_discovery,
)
from pipeline.stages.regime import classify_regime
from pipeline.stages.risk_post_filter import pre_filter_tickers, risk_post_filter
from pipeline.stages.risk_screener import screen_risks
from pipeline.stages.risk_validator import validate_risks
from services.chart_image import fetch_annotated_chart
from services.fmp_service import (
    FmpEnrichedStock,
    apply_regime_weight_adjustments,
    compute_composite_scores,
    fetch_quotes,
    fetch_sector_performance,
    fetch_vix_quote,
    filter_by_rsi,
    screen_and_enrich,
)
from services.keyring_service import get_api_key
from services.reflection import load_reflection_context
from services.strategy import get_strategy
from utils.ticker import normalize_ticker, normalize_tickers

logger = logging.getLogger(__name__)

STAGE_TIMEOUTS: dict[str, float] = {
    "fmp": 90.0,
    "perplexity": 180.0,
    "gemini": 120.0,
    "risk_screener": 20.0,
    "claude": 360.0,
    "gpt": 180.0,
    "annotate": 60.0,
}


async def run_pipeline(
    *,
    run_id: str | None = None,
    strategy_id: str | None = None,
    manual_tickers: list[str] | None = None,
    user_prompt: str | None = None,
    user_id: str,
    screener_overrides: ScreenerOverrides | None = None,
) -> PipelineResult:
    """Execute the analysis pipeline.

    Runs Perplexity screening then Gemini news sentiment. The mode is
    determined by inputs:
    - strategy_id only → discovery mode
    - manual_tickers only → analysis mode
    - both → combined mode
    - user_prompt (with or without strategy) → prompt mode

    Args:
        run_id: Optional pre-generated run ID. If omitted, a new UUID is created.
            Provide this when the caller needs to return the ID to a client before
            the pipeline starts (fire-and-forget pattern).
        strategy_id: Optional strategy UUID for discovery screening.
        manual_tickers: Optional list of ticker symbols.
        user_prompt: Optional free-form prompt for Perplexity screening.
        user_id: User UUID for multi-tenant data isolation.

    Returns:
        Completed PipelineResult with screening and sentiment data.
    """
    run_id = run_id or uuid.uuid4().hex
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

    # Apply screener overrides to FMP config (dashboard dropdowns)
    if screener_overrides and screener_overrides.has_any():
        if config and config.fmp_screener:
            config.fmp_screener = screener_overrides.apply_to(config.fmp_screener)
            logger.info(
                "Applied screener overrides to strategy '%s': %s",
                config.name,
                screener_overrides.model_dump(exclude_none=True),
            )
        elif config:
            config.fmp_screener = screener_overrides.apply_to(
                FmpScreenerConfig(enabled=True, country="CA")
            )
            logger.info(
                "Created FMP config on strategy '%s' from overrides: %s",
                config.name,
                screener_overrides.model_dump(exclude_none=True),
            )
        else:
            fmp_config = screener_overrides.apply_to(
                FmpScreenerConfig(enabled=True, country="CA", enrich_with_ratios=True, limit=50)
            )
            config = StrategyConfig(
                id="overrides",
                name="Custom Filters",
                description="Pipeline run with dashboard screener filters",
                screening_prompt=_build_override_screening_prompt(screener_overrides),
                fmp_screener=fmp_config,
            )
            logger.info(
                "Created synthetic strategy from screener overrides: %s",
                screener_overrides.model_dump(exclude_none=True),
            )

    # Pipeline v2 dispatch: if strategy has pipeline_version="v2", use parallel tracks
    if config and config.pipeline_version == "v2":
        return await _run_pipeline_v2(
            run_id=run_id,
            config=config,
            mode=mode,
            manual_tickers=manual_tickers,
            user_prompt=user_prompt,
            user_id=user_id,
            result=result,
            start=start,
        )

    # --- v1 pipeline (existing code, untouched below this line) ---

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
                fmp_start = time.perf_counter()
                fmp_candidates = await asyncio.wait_for(
                    screen_and_enrich(config.fmp_screener),
                    timeout=STAGE_TIMEOUTS["fmp"],
                )
                fmp_elapsed_ms = int((time.perf_counter() - fmp_start) * 1000)
                logger.info(
                    "FMP pre-screened %d candidates for strategy '%s'",
                    len(fmp_candidates),
                    config.name,
                )
                await _save_stage_output(
                    run_id,
                    {
                        "stage": "fmp",
                        "status": "success",
                        "model": "fmp-api",
                        "duration_ms": fmp_elapsed_ms,
                        "raw_response": json.dumps(
                            [c.model_dump(mode="json") for c in fmp_candidates]
                        ),
                    },
                )
            except TimeoutError:
                logger.error("FMP stage timed out after %ss", STAGE_TIMEOUTS["fmp"])
                result.stage_errors.append(
                    {"stage": "fmp", "error": "Stage timed out", "type": "TimeoutError"}
                )
                await _save_stage_output(
                    run_id,
                    {
                        "stage": "fmp",
                        "status": "error",
                        "model": "fmp-api",
                        "duration_ms": 0,
                        "raw_response": "",
                        "error": "Stage timed out",
                    },
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
                await _save_stage_output(
                    run_id,
                    {
                        "stage": "fmp",
                        "status": "error",
                        "model": "fmp-api",
                        "duration_ms": 0,
                        "raw_response": "",
                        "error": str(exc),
                    },
                )
        else:
            logger.info("FMP_API_KEY not set, skipping FMP pre-screening")
            await _save_stage_output(
                run_id,
                {
                    "stage": "fmp",
                    "status": "skipped",
                    "model": "fmp-api",
                    "duration_ms": 0,
                    "raw_response": "FMP_API_KEY not configured",
                },
            )
    else:
        await _save_stage_output(
            run_id,
            {
                "stage": "fmp",
                "status": "skipped",
                "model": "fmp-api",
                "duration_ms": 0,
                "raw_response": "FMP pre-screening disabled or not applicable",
            },
        )

    fmp_map: dict[str, FmpEnrichedStock] = {}
    if fmp_candidates:
        fmp_map = {s.symbol: s for s in fmp_candidates}

    # Stage 0.5: Regime classification (Perplexity web search + FMP ground truth)
    regime: RegimeOutput | None = None
    sector_data: list[dict] | None = None
    vix_value: float | None = None
    vix_label: str | None = None

    fmp_key = get_api_key("fmp")
    if fmp_key:
        try:
            sector_perf, (vix_value, vix_label) = await asyncio.gather(
                fetch_sector_performance(),
                fetch_vix_quote(),
            )
            sector_data = [sp.model_dump() for sp in sector_perf] if sector_perf else None
            logger.info(
                "FMP regime ground truth: VIX=%.2f (%s), %d sectors",
                vix_value or 0,
                vix_label,
                len(sector_perf) if sector_perf else 0,
            )
        except Exception as exc:
            logger.warning("FMP regime ground truth fetch failed, proceeding without: %s", exc)

    try:
        regime, regime_metadata = await asyncio.wait_for(
            classify_regime(
                run_id,
                sector_data=sector_data,
                vix_value=vix_value,
                vix_label=vix_label,
            ),
            timeout=STAGE_TIMEOUTS.get("regime", 30),
        )
        if regime_metadata:
            await _save_stage_output(run_id, regime_metadata)
    except TimeoutError:
        result.stage_errors.append(
            {"stage": "regime", "error": "Stage timed out", "type": "TimeoutError"}
        )
        logger.error("Regime classifier timed out")
    except Exception as exc:
        result.stage_errors.append(
            {"stage": "regime", "error": str(exc), "type": type(exc).__name__}
        )
        logger.warning("Regime classifier failed, continuing without: %s", exc)

    regime_context = format_regime_header(regime) if regime else ""

    # Re-score FMP candidates with regime-adjusted weights if applicable
    if regime and fmp_candidates and config and config.fmp_screener:
        adjusted_config = apply_regime_weight_adjustments(config.fmp_screener, regime.regime_type)
        fmp_candidates = compute_composite_scores(fmp_candidates, adjusted_config)
        fmp_candidates.sort(key=lambda s: s.composite_score or 0, reverse=True)
        fmp_map = {s.symbol: s for s in fmp_candidates}
        logger.info(
            "Re-scored FMP candidates with regime-adjusted weights (regime=%s)",
            regime.regime_type,
        )

    # RSI pre-filter: reject technically invalid candidates before LLM stages
    if fmp_candidates and config:
        strategy_type = config.strategy_type
        if strategy_type in ("momentum", "mean_reversion"):
            try:
                fmp_candidates = await filter_by_rsi(fmp_candidates, strategy_type, max_check=20)
                fmp_map = {s.symbol: s for s in fmp_candidates}
            except Exception as exc:
                logger.warning("RSI pre-filter failed, continuing without: %s", exc)

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
                if config.enable_debate:
                    return await run_bull_bear_discovery(config, fmp_candidates=fmp_candidates)
                return await run_discovery(config, fmp_candidates=fmp_candidates)
            if mode == "discovery" and not config:
                default_prompt = "trending Canadian TSX stocks and top TSX market movers today"
                return await run_prompted_discovery(
                    default_prompt, None, fmp_candidates=fmp_candidates
                )
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
        # Deduplicate tickers by symbol, keeping the first occurrence
        seen: set[str] = set()
        unique_tickers = []
        for td in screening.tickers:
            if td.ticker not in seen:
                seen.add(td.ticker)
                unique_tickers.append(td)
        screening.tickers = unique_tickers
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

        ticker_highlights: dict[str, list[str]] = {
            t.ticker: t.key_highlights for t in screening.tickers if t.key_highlights
        }

        try:
            sentiments, gemini_metadata_list = await asyncio.wait_for(
                run_sentiment(
                    ticker_symbols,
                    effective_config,
                    ticker_news=ticker_news or None,
                    fmp_context=fmp_map or None,
                    ticker_highlights=ticker_highlights or None,
                    regime_context=regime_context,
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

    # URL hit rate monitoring (Gap 14): compare Gemini catalyst URLs against provided URLs
    if result.sentiment_analyses and screening and screening.tickers:
        ticker_news_map: dict[str, list[str]] = {
            t.ticker: t.news_urls for t in screening.tickers if t.news_urls
        }
        for sa in result.sentiment_analyses:
            provided = set(ticker_news_map.get(sa.ticker, []))
            if not provided:
                continue
            catalyst_urls = {c.url for c in sa.key_catalysts if c.url}
            hits = len(provided & catalyst_urls)
            hit_rate = (hits / len(provided)) * 100 if provided else 0
            logger.info(
                "Gemini URL hit rate for %s: %.0f%% (%d/%d provided URLs used)",
                sa.ticker,
                hit_rate,
                hits,
                len(provided),
            )

    # Stage 2.5: Risk screening micro-agent — pre-filter before expensive Claude analysis
    demoted_tickers: list[str] = []
    if (
        screening
        and screening.tickers
        and result.sentiment_analyses
        and effective_config.risk_params
    ):
        try:
            all_syms = [t.ticker for t in screening.tickers]
            passed, demoted_tickers, risk_meta = await asyncio.wait_for(
                screen_risks(
                    all_syms,
                    result.sentiment_analyses,
                    effective_config,
                    fmp_context=fmp_map or None,
                ),
                timeout=STAGE_TIMEOUTS["risk_screener"],
            )
            await _save_stage_output(run_id, risk_meta)
            if demoted_tickers:
                logger.info(
                    "Risk screener demoted %d tickers: %s",
                    len(demoted_tickers),
                    demoted_tickers,
                )
        except TimeoutError:
            result.stage_errors.append(
                {"stage": "risk_screener", "error": "Stage timed out", "type": "TimeoutError"}
            )
            logger.error("Risk screener timed out, passing all tickers")
            passed = [t.ticker for t in screening.tickers]
        except Exception as exc:
            result.stage_errors.append(
                {"stage": "risk_screener", "error": str(exc), "type": type(exc).__name__}
            )
            logger.warning("Risk screener failed, passing all tickers: %s", exc)
            passed = [t.ticker for t in screening.tickers]
    else:
        passed = [t.ticker for t in screening.tickers] if screening and screening.tickers else []

    # Fetch real-time quotes for all pipeline tickers (runs fast, no stage timeout needed)
    all_tickers_for_quotes = passed or (
        [t.ticker for t in screening.tickers] if screening and screening.tickers else []
    )
    live_quotes: dict = {}
    if all_tickers_for_quotes:
        try:
            live_quotes = await fetch_quotes(all_tickers_for_quotes)
            logger.info("Fetched %d live quotes for pipeline tickers", len(live_quotes))
        except Exception as exc:
            logger.warning("Live quote fetch failed (non-critical): %s", exc)

    # Stage 3: Claude chart analysis (only for tickers that passed risk screening)
    if screening and screening.tickers and passed:
        try:
            charts, claude_metadata_list = await asyncio.wait_for(
                run_chart_analysis(
                    passed,
                    effective_config,
                    result.sentiment_analyses,
                    run_id,
                    user_id,
                    fmp_context=fmp_map or None,
                    regime_context=regime_context,
                    live_quotes=live_quotes or None,
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
    sector_consensus = _aggregate_sector_sentiment(result.sentiment_analyses, screening)

    # Re-fetch quotes immediately before GPT so entry prices are anchored to
    # the freshest available price, not the price captured before Claude ran.
    if ticker_symbols:
        try:
            live_quotes = await fetch_quotes(ticker_symbols)
            logger.info("Re-fetched %d live quotes before GPT stage", len(live_quotes))
        except Exception as exc:
            logger.warning("Pre-GPT live quote refresh failed (using prior quotes): %s", exc)

    logger.info("Stage 4 GPT: ticker_symbols=%s", ticker_symbols)
    if ticker_symbols:
        try:
            reflection_context = await load_reflection_context(user_id)
            gpt_signal_time = datetime.now(tz=UTC)
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
                    regime_context=regime_context,
                    sector_consensus=sector_consensus,
                    live_quotes=live_quotes or None,
                ),
                timeout=STAGE_TIMEOUTS["gpt"],
            )
            # Stamp freshness metadata onto each recommendation
            signal_ts = gpt_signal_time.isoformat()
            for rec in recommendations:
                rec.signal_generated_at = signal_ts
                if live_quotes and rec.ticker in live_quotes:
                    rec.price_at_signal = live_quotes[rec.ticker].price
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

    # Stage 4.7: Deterministic risk validation
    if result.recommendations:
        result.recommendations = validate_risks(
            result.recommendations,
            effective_config,
            result.chart_analyses,
            fmp_context=fmp_map or None,
        )
        logger.info("Stage 4.7 risk validation complete")

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

        annotated_count = sum(1 for ca in result.chart_analyses if ca.annotated_chart_path)
        await _save_stage_output(
            run_id,
            {
                "stage": "annotate",
                "status": "success" if annotated_count > 0 else "error",
                "model": "chart-img-v2",
                "duration_ms": 0,
                "raw_response": f"Annotated {annotated_count}/{len(result.chart_analyses)} charts",
            },
        )

        # Persist annotated_chart_path back into stage_outputs so it survives reload
        await _update_annotated_paths(client, run_id, result.chart_analyses)

    elapsed = time.perf_counter() - start
    result.total_duration_seconds = round(elapsed, 2)
    result.prompt_versions = {
        "regime": regime_hash(),
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


async def _run_pipeline_v2(
    *,
    run_id: str,
    config: StrategyConfig,
    mode: Literal["discovery", "analysis", "combined", "prompt"],
    manual_tickers: list[str] | None,
    user_prompt: str | None,
    user_id: str,
    result: PipelineResult,
    start: float,
) -> PipelineResult:
    """Execute the v2 parallel-track pipeline.

    Three independent analysis tracks (Perplexity, Gemini, Claude) run
    concurrently after shared FMP + Regime + Numerical TA stages. GPT is
    the first and only convergence point.

    This function is called from ``run_pipeline()`` when the strategy has
    ``pipeline_version="v2"``. The v1 code path is untouched.

    Args:
        run_id: Pipeline run UUID.
        config: Strategy configuration (guaranteed non-None with v2).
        mode: Pipeline mode (discovery/analysis/combined/prompt).
        manual_tickers: Optional manual ticker list.
        user_prompt: Optional free-form prompt.
        user_id: User UUID.
        result: Pre-initialized PipelineResult.
        start: ``time.perf_counter()`` value from pipeline start.

    Returns:
        Completed PipelineResult.
    """
    client = await get_db()

    # ── Stage 0: FMP Pre-Screening (shared with v1) ─────────────────────
    fmp_candidates: list[FmpEnrichedStock] | None = None
    fmp_enabled = (
        config.fmp_screener is not None and config.fmp_screener.enabled and mode != "analysis"
    )

    if fmp_enabled and config.fmp_screener:
        fmp_key = get_api_key("fmp")
        if fmp_key:
            try:
                fmp_start = time.perf_counter()
                fmp_candidates = await asyncio.wait_for(
                    screen_and_enrich(config.fmp_screener),
                    timeout=STAGE_TIMEOUTS["fmp"],
                )
                fmp_elapsed_ms = int((time.perf_counter() - fmp_start) * 1000)
                logger.info("v2: FMP pre-screened %d candidates", len(fmp_candidates))
                await _save_stage_output(
                    run_id,
                    {
                        "stage": "fmp",
                        "status": "success",
                        "model": "fmp-api",
                        "duration_ms": fmp_elapsed_ms,
                        "raw_response": json.dumps(
                            [c.model_dump(mode="json") for c in fmp_candidates]
                        ),
                    },
                )
            except Exception as exc:
                logger.warning("v2: FMP screening failed, continuing without: %s", exc)
                result.stage_errors.append(
                    {"stage": "fmp", "error": str(exc), "type": type(exc).__name__}
                )

    fmp_map: dict[str, FmpEnrichedStock] = {}
    if fmp_candidates:
        fmp_map = {s.symbol: s for s in fmp_candidates}

    # ── Stage 0.5: Regime Classification (shared with v1) ────────────────
    regime: RegimeOutput | None = None
    fmp_key = get_api_key("fmp")
    if fmp_key:
        try:
            sector_perf, (vix_value, vix_label) = await asyncio.gather(
                fetch_sector_performance(),
                fetch_vix_quote(),
            )
            sector_data = [sp.model_dump() for sp in sector_perf] if sector_perf else None
        except Exception as exc:
            logger.warning("v2: FMP regime ground truth fetch failed: %s", exc)
            sector_data = None
            vix_value = None
            vix_label = None
    else:
        sector_data = None
        vix_value = None
        vix_label = None

    try:
        regime, regime_metadata = await asyncio.wait_for(
            classify_regime(
                run_id, sector_data=sector_data, vix_value=vix_value, vix_label=vix_label
            ),
            timeout=STAGE_TIMEOUTS.get("regime", 30),
        )
        if regime_metadata:
            await _save_stage_output(run_id, regime_metadata)
    except Exception as exc:
        result.stage_errors.append(
            {"stage": "regime", "error": str(exc), "type": type(exc).__name__}
        )
        logger.warning("v2: Regime classifier failed: %s", exc)

    regime_context = format_regime_header(regime) if regime else ""

    # Re-score FMP with regime-adjusted weights
    if regime and fmp_candidates and config.fmp_screener:
        adjusted_config = apply_regime_weight_adjustments(config.fmp_screener, regime.regime_type)
        fmp_candidates = compute_composite_scores(fmp_candidates, adjusted_config)
        fmp_candidates.sort(key=lambda s: s.composite_score or 0, reverse=True)
        fmp_map = {s.symbol: s for s in fmp_candidates}

    # ── Stage 1: Perplexity (get ticker list — same as v1) ───────────────
    screening: ScreeningResult | None = None
    try:

        async def _run_perplexity_stage() -> tuple:
            if mode == "prompt":
                return await run_prompted_discovery(
                    user_prompt or "", config, fmp_candidates=fmp_candidates
                )
            if mode == "discovery":
                if config.enable_debate:
                    return await run_bull_bear_discovery(config, fmp_candidates=fmp_candidates)
                return await run_discovery(config, fmp_candidates=fmp_candidates)
            if mode == "analysis":
                return await run_analysis(manual_tickers or [], config)
            if mode == "combined":
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
    except Exception as exc:
        result.stage_errors.append(
            {"stage": "perplexity", "error": str(exc), "type": type(exc).__name__}
        )
        logger.exception("v2: Perplexity stage failed")

    if screening:
        for td in screening.tickers:
            td.ticker = normalize_ticker(td.ticker)
        seen: set[str] = set()
        unique_tickers = []
        for td in screening.tickers:
            if td.ticker not in seen:
                seen.add(td.ticker)
                unique_tickers.append(td)
        screening.tickers = unique_tickers
        result.screening = screening

    await _save_stage_output(run_id, stage_metadata if screening else {})

    # Build ticker list for parallel tracks
    ticker_symbols = (
        [t.ticker for t in screening.tickers]
        if screening and screening.tickers
        else list(manual_tickers or [])
    )

    if not ticker_symbols:
        return await _finalize_v2(run_id, result, start, client, regime_context)

    # ── Lightweight pre-filter (no LLM) ──────────────────────────────────
    ticker_symbols = pre_filter_tickers(ticker_symbols, fmp_map, config)
    result.chart_indicators = config.chart_indicators

    # ── Numerical TA (Phase 1) — before parallel tracks ──────────────────
    ta_snapshots: list[MultiTimeframeTechnical] = []
    try:
        ta_snapshots, ta_metadata = await asyncio.wait_for(
            run_numerical_ta(ticker_symbols, config),
            timeout=STAGE_TIMEOUTS.get("numerical_ta", 90.0),
        )
        for tm in ta_metadata:
            await _save_stage_output(run_id, tm)
    except Exception as exc:
        result.stage_errors.append(
            {"stage": "numerical_ta", "error": str(exc), "type": type(exc).__name__}
        )
        logger.warning("v2: Numerical TA stage failed: %s", exc)

    # ── Live Quotes — fetch once for Claude, GPT re-fetches its own later ─
    claude_live_quotes: dict = {}
    try:
        claude_live_quotes = await fetch_quotes(ticker_symbols)
        logger.info("v2: Fetched %d live quotes for Claude", len(claude_live_quotes))
    except Exception as exc:
        logger.warning("v2: Live quote fetch for Claude failed (non-critical): %s", exc)

    # ── Three Independent Parallel Tracks ────────────────────────────────
    # Track A: Perplexity results already collected above (screening)
    # Track B: Gemini (independent — NO Perplexity data injected)
    # Track C: Claude (numerical TA + chart + live quotes — NO sentiment)

    async def _track_b_gemini() -> tuple[list[SentimentAnalysis], list[dict]]:
        """Track B: Independent sentiment via Gemini (no Perplexity data)."""
        return await run_sentiment(
            ticker_symbols,
            config,
            ticker_news=None,
            fmp_context=None,
            ticker_highlights=None,
            regime_context=regime_context,
        )

    async def _track_c_claude() -> tuple[list[ChartAnalysis], list[dict]]:
        """Track C: Technical analysis with numerical TA + live quotes (no sentiment)."""
        return await run_chart_analysis_v2(
            ticker_symbols,
            config,
            ta_snapshots,
            run_id,
            user_id,
            regime_context=regime_context,
            live_quotes=claude_live_quotes or None,
        )

    gemini_result: tuple[list[SentimentAnalysis], list[dict]] = ([], [])
    claude_result: tuple[list[ChartAnalysis], list[dict]] = ([], [])

    try:
        gemini_result, claude_result = await asyncio.gather(
            asyncio.wait_for(_track_b_gemini(), timeout=STAGE_TIMEOUTS["gemini"]),
            asyncio.wait_for(_track_c_claude(), timeout=STAGE_TIMEOUTS["claude"]),
        )
    except Exception as exc:
        logger.error("v2: Parallel track gather failed: %s", exc)
        result.stage_errors.append(
            {"stage": "parallel_tracks", "error": str(exc), "type": type(exc).__name__}
        )

        # Try to salvage individual track results
        if not gemini_result[0]:
            try:
                gemini_result = await asyncio.wait_for(
                    _track_b_gemini(), timeout=STAGE_TIMEOUTS["gemini"]
                )
            except Exception as g_exc:
                logger.error("v2: Gemini fallback also failed: %s", g_exc)

        if not claude_result[0]:
            try:
                claude_result = await asyncio.wait_for(
                    _track_c_claude(), timeout=STAGE_TIMEOUTS["claude"]
                )
            except Exception as c_exc:
                logger.error("v2: Claude fallback also failed: %s", c_exc)

    sentiments, gemini_metadata_list = gemini_result
    charts, claude_metadata_list = claude_result

    result.sentiment_analyses = sentiments
    result.chart_analyses = charts

    for gm in gemini_metadata_list:
        await _save_stage_output(run_id, gm)
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

    # ── Risk Post-Filter (enriches, doesn't remove) ──────────────────────
    risk_assessments = risk_post_filter(
        ticker_symbols,
        sentiments,
        charts,
        ta_snapshots,
        config,
        fmp_map=fmp_map or None,
    )
    await _save_stage_output(
        run_id,
        {
            "stage": "risk_post_filter",
            "status": "success",
            "model": "deterministic",
            "duration_ms": 0,
            "raw_response": json.dumps([r.model_dump() for r in risk_assessments]),
        },
    )

    # ── Stage 4: GPT Synthesis (convergence point — track-aware v2) ──────
    sector_consensus = _aggregate_sector_sentiment(sentiments, screening)
    if ticker_symbols:
        try:
            reflection_context = await load_reflection_context(user_id)
            # Fetch quotes immediately before GPT so entry prices anchor to the
            # freshest available price (Gemini+Claude may have taken several minutes).
            live_quotes_v2: dict = {}
            try:
                live_quotes_v2 = await fetch_quotes(ticker_symbols)
                logger.info("v2: Fetched %d live quotes before GPT stage", len(live_quotes_v2))
            except Exception as exc:
                logger.warning("v2: Live quote fetch failed: %s", exc)

            gpt_signal_time_v2 = datetime.now(tz=UTC)
            recommendations, gpt_metadata_list = await asyncio.wait_for(
                run_debate_v2(
                    ticker_symbols,
                    screening,
                    charts,
                    sentiments,
                    config,
                    reflection_context,
                    run_id,
                    ta_snapshots=ta_snapshots or None,
                    risk_assessments=risk_assessments or None,
                    fmp_context=fmp_map or None,
                    regime_context=regime_context,
                    sector_consensus=sector_consensus,
                    live_quotes=live_quotes_v2 or None,
                ),
                timeout=STAGE_TIMEOUTS["gpt"],
            )
            # Stamp freshness metadata onto each recommendation
            signal_ts_v2 = gpt_signal_time_v2.isoformat()
            for rec in recommendations:
                rec.signal_generated_at = signal_ts_v2
                if live_quotes_v2 and rec.ticker in live_quotes_v2:
                    rec.price_at_signal = live_quotes_v2[rec.ticker].price
            result.recommendations = recommendations
            for gm in gpt_metadata_list:
                await _save_stage_output(run_id, gm)
            await _save_recommendations(run_id, recommendations, user_id)
        except Exception as exc:
            result.stage_errors.append(
                {"stage": "gpt", "error": str(exc), "type": type(exc).__name__}
            )
            logger.exception("v2: GPT stage failed")

    # Risk validation
    if result.recommendations:
        result.recommendations = validate_risks(
            result.recommendations, config, charts, fmp_context=fmp_map or None
        )

    # Confidence calibration (Phase 7)
    if result.recommendations:
        from services.confidence_calibration import calibrate_recommendations

        result.recommendations = calibrate_recommendations(
            result.recommendations,
            ta_snapshots=ta_snapshots or None,
            config=config,
            regime_context=regime_context,
            risk_assessments=risk_assessments or None,
        )

    # Annotated charts
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
                logger.warning("v2: Annotated chart failed for %s: %s", ca.ticker, exc)

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *(_annotate(i) for i in range(len(result.chart_analyses))),
                    return_exceptions=True,
                ),
                timeout=STAGE_TIMEOUTS["annotate"],
            )
        except TimeoutError:
            logger.error("v2: Annotate stage timed out")

        await _update_annotated_paths(client, run_id, result.chart_analyses)

    return await _finalize_v2(run_id, result, start, client, regime_context)


async def _finalize_v2(
    run_id: str,
    result: PipelineResult,
    start: float,
    client: Any,
    regime_context: str,
) -> PipelineResult:
    """Finalize a v2 pipeline run: timing, prompt versions, DB update.

    Args:
        run_id: Pipeline run UUID.
        result: The PipelineResult being built.
        start: perf_counter value from pipeline start.
        client: Supabase client.
        regime_context: Unused, kept for signature consistency.

    Returns:
        Completed PipelineResult.
    """
    from pipeline.prompts.claude_chart import get_prompt_hash_v2 as claude_v2_hash

    elapsed = time.perf_counter() - start
    result.total_duration_seconds = round(elapsed, 2)
    result.prompt_versions = {
        "regime": regime_hash(),
        "perplexity": discovery_hash(),
        "gemini": gemini_hash(),
        "claude": claude_v2_hash(),
        "gpt_bull": get_bull_hash_v2(),
        "gpt_bear": get_bear_hash_v2(),
        "gpt_judge": get_judge_hash_v2(),
        "pipeline_version": "v2",
    }

    has_data = (
        result.screening
        or result.sentiment_analyses
        or result.chart_analyses
        or result.recommendations
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
    elif metadata.get("raw_response"):
        row["parsed_output"] = metadata["raw_response"]
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
            "signal_generated_at": rec.signal_generated_at,
            "price_at_signal": rec.price_at_signal,
            "entry_valid_window": rec.entry_valid_window,
        }
        for rec in recommendations
    ]
    await client.table("recommendations").insert(rows).execute()
    logger.info("Saved %d recommendations for run %s", len(recommendations), run_id)


def _build_override_screening_prompt(overrides: ScreenerOverrides) -> str:
    """Build a screening prompt from dashboard filter overrides.

    Constructs a search-query-style prompt that reflects the user's
    chosen country, exchange, sector, and market cap filters.

    Args:
        overrides: The screener overrides from the dashboard.

    Returns:
        A screening prompt string for Perplexity.
    """
    parts: list[str] = []

    country_names = {"CA": "Canadian", "US": "US", "GB": "UK", "DE": "German", "AU": "Australian"}
    if overrides.country:
        parts.append(country_names.get(overrides.country, overrides.country))

    if overrides.exchange:
        parts.append(f"{overrides.exchange} listed")

    parts.append("stocks")

    if overrides.sector:
        parts.append(f"in the {overrides.sector} sector")

    cap_labels = {
        (None, 300_000_000): "micro-cap",
        (300_000_000, 2_000_000_000): "small-cap",
        (2_000_000_000, 10_000_000_000): "mid-cap",
        (10_000_000_000, 100_000_000_000): "large-cap",
        (100_000_000_000, None): "mega-cap",
    }
    for (lo, hi), label in cap_labels.items():
        if overrides.market_cap_min == lo and overrides.market_cap_max == hi:
            parts.insert(-1 if "sector" not in " ".join(parts) else len(parts), label)
            break

    parts.append("strong fundamentals momentum analyst upgrades")
    return " ".join(parts)


def _aggregate_sector_sentiment(
    sentiments: list[SentimentAnalysis],
    screening: ScreeningResult | None,
) -> str:
    """Aggregate sector-level sentiment across tickers into a consensus block.

    Groups sentiment scores by sector (from screening data), computes
    the median score and most common key_driver per sector, and returns
    a formatted text block for GPT.

    Args:
        sentiments: List of SentimentAnalysis objects.
        screening: ScreeningResult (or None).

    Returns:
        Formatted sector consensus text, or empty string if insufficient data.
    """
    from collections import Counter
    from statistics import median

    if not sentiments:
        return ""

    ticker_sector: dict[str, str] = {}
    if screening and hasattr(screening, "tickers"):
        for td in screening.tickers:
            if td.sector:
                ticker_sector[td.ticker] = td.sector

    sector_scores: dict[str, list[float]] = {}
    sector_drivers: dict[str, list[str]] = {}
    for sa in sentiments:
        sector = ticker_sector.get(sa.ticker, "Unknown")
        if sa.sector_sentiment:
            sector_scores.setdefault(sector, []).append(sa.sector_sentiment.score)
            if sa.sector_sentiment.key_driver:
                sector_drivers.setdefault(sector, []).append(sa.sector_sentiment.key_driver)

    if not sector_scores:
        return ""

    lines = []
    for sector in sorted(sector_scores.keys()):
        scores = sector_scores[sector]
        med = median(scores)
        drivers = sector_drivers.get(sector, [])
        top_driver = Counter(drivers).most_common(1)[0][0] if drivers else "N/A"
        label = (
            "strongly_bearish"
            if med <= -0.6
            else "bearish"
            if med <= -0.2
            else "neutral"
            if med <= 0.2
            else "bullish"
            if med <= 0.6
            else "strongly_bullish"
        )
        lines.append(f"- {sector}: {label} (median {med:+.2f}, n={len(scores)}) — {top_driver}")

    return "\n".join(lines)


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
