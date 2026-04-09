"""Pipeline execution engine (v2 — parallel tracks).

Pipeline (parallel tracks):
  (FMP screening || Regime classification) →
  Re-score FMP with regime → Perplexity → pre_filter_tickers →
  (Numerical TA || Live Quotes) →
  (Gemini || Claude) →
  Risk post-filter → GPT synthesis → ML gate/shadow → Annotated charts.

Claude deliberately does NOT receive Gemini sentiment to avoid bias.
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
from pipeline.prompts.gemini_sentiment import get_prompt_hash as gemini_hash
from pipeline.prompts.gpt_debate import (
    get_bear_hash,
    get_bull_hash,
    get_judge_hash,
)
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
    RecommendationAction,
    RegimeOutput,
    ScreenerOverrides,
    ScreeningResult,
    SentimentAnalysis,
    StageError,
    StrategyConfig,
    TrackAgreement,
)
from pipeline.stages.claude import run_chart_analysis
from pipeline.stages.gemini import run_sentiment
from pipeline.stages.gpt import run_debate
from pipeline.stages.numerical_ta import run_numerical_ta
from pipeline.stages.perplexity import (
    run_analysis,
    run_bull_bear_discovery,
    run_discovery,
    run_prompted_discovery,
)
from pipeline.stages.regime import classify_regime
from pipeline.stages.risk_post_filter import pre_filter_tickers, risk_post_filter
from pipeline.stages.risk_validator import validate_risks
from services.chart_image import clear_run_symbol_cache, fetch_annotated_chart
from services.fmp_service import (
    FmpEnrichedStock,
    apply_regime_weight_adjustments,
    compute_composite_scores,
    fetch_quotes,
    fetch_sector_performance,
    fetch_vix_quote,
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
    "claude": 360.0,
    "gpt": 360.0,
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
    mode_override: str | None = None,
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

    _VALID_MODES = {"discovery", "analysis", "combined", "prompt"}
    if mode_override and mode_override in _VALID_MODES:
        logger.info("Mode override: %s → %s", mode, mode_override)
        mode = cast(Literal["discovery", "analysis", "combined", "prompt"], mode_override)

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

    effective_config = config or StrategyConfig(id="default", name="default", screening_prompt="")
    return await _run_pipeline(
        run_id=run_id,
        config=effective_config,
        mode=mode,
        manual_tickers=manual_tickers,
        user_prompt=user_prompt,
        user_id=user_id,
        result=result,
        start=start,
    )


async def _run_pipeline(
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
    """Execute the parallel-track pipeline.

    Maximises concurrency at three levels:
    1. FMP screening runs in parallel with regime classification.
    2. Numerical TA runs in parallel with live quote fetching.
    3. Gemini and Claude run in parallel as independent tracks.

    GPT is the convergence point that synthesises all track outputs.

    Args:
        run_id: Pipeline run UUID.
        config: Strategy configuration.
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

    # ── Stage 0 + 0.5: FMP Pre-Screening || Regime (CONCURRENT) ─────────
    # FMP screening and regime classification are independent — run in parallel
    # to save the latency of whichever is slower.

    fmp_enabled = (
        config.fmp_screener is not None and config.fmp_screener.enabled and mode != "analysis"
    )
    fmp_key = get_api_key("fmp")

    async def _fmp_screening() -> list[FmpEnrichedStock] | None:
        """FMP pre-screening (independent of regime)."""
        if not (fmp_enabled and config.fmp_screener and fmp_key):
            return None
        fmp_start = time.perf_counter()
        candidates = await asyncio.wait_for(
            screen_and_enrich(config.fmp_screener),
            timeout=STAGE_TIMEOUTS["fmp"],
        )
        fmp_elapsed_ms = int((time.perf_counter() - fmp_start) * 1000)
        logger.info(" FMP pre-screened %d candidates", len(candidates))
        await _save_stage_output(
            run_id,
            {
                "stage": "fmp",
                "status": "success",
                "model": "fmp-api",
                "duration_ms": fmp_elapsed_ms,
                "raw_response": json.dumps([c.model_dump(mode="json") for c in candidates]),
            },
        )
        return candidates

    async def _regime_classification() -> tuple[RegimeOutput | None, dict]:
        """Regime classification — uses cached heartbeat first, Perplexity fallback."""
        try:
            from services.market_heartbeat import get_heartbeat

            heartbeat = get_heartbeat()
            state = await heartbeat.get_current_state()
            if state.is_fresh():
                regime_dict = state.to_regime_output_dict()
                regime_out = RegimeOutput(**regime_dict)
                meta = {
                    "stage": "regime",
                    "status": "success",
                    "model": "heartbeat-cache",
                    "duration_ms": 0,
                    "raw_response": f"Cached regime: {regime_out.regime_type}",
                }
                await _save_stage_output(run_id, meta)
                logger.info(" Stage 0.5 using cached heartbeat: %s", regime_out.regime_type)
                return regime_out, meta
        except Exception as exc:
            logger.info(" Heartbeat unavailable, falling back to Perplexity: %s", exc)

        sector_data = None
        vix_value: float | None = None
        vix_label: str | None = None
        if fmp_key:
            try:
                sector_perf, (vix_value, vix_label) = await asyncio.gather(
                    fetch_sector_performance(),
                    fetch_vix_quote(),
                )
                sector_data = [sp.model_dump() for sp in sector_perf] if sector_perf else None
            except Exception as exc:
                logger.warning(" FMP regime ground truth fetch failed: %s", exc)

        regime_out, regime_meta = await asyncio.wait_for(
            classify_regime(
                run_id, sector_data=sector_data, vix_value=vix_value, vix_label=vix_label
            ),
            timeout=STAGE_TIMEOUTS.get("regime", 30),
        )
        if regime_meta:
            await _save_stage_output(run_id, regime_meta)
        return regime_out, regime_meta

    # Launch both concurrently
    fmp_task = asyncio.create_task(_fmp_screening())
    regime_task = asyncio.create_task(_regime_classification())

    fmp_candidates: list[FmpEnrichedStock] | None = None
    try:
        fmp_candidates = await fmp_task
    except Exception as exc:
        logger.warning("FMP screening failed, continuing without: %s", exc)
        result.stage_errors.append(StageError(stage="fmp", error=str(exc), type=type(exc).__name__))
        await _save_stage_output(
            run_id,
            {
                "stage": "fmp",
                "status": "error",
                "model": "fmp-api",
                "duration_ms": 0,
                "error": str(exc),
            },
        )

    if not fmp_candidates and not fmp_enabled:
        await _save_stage_output(
            run_id,
            {
                "stage": "fmp",
                "status": "skipped",
                "model": "fmp-api",
                "duration_ms": 0,
                "raw_response": "FMP pre-screening disabled for analysis mode",
            },
        )

    regime: RegimeOutput | None = None
    try:
        regime, _regime_meta = await regime_task
    except Exception as exc:
        result.stage_errors.append(
            StageError(stage="regime", error=str(exc), type=type(exc).__name__)
        )
        logger.warning(" Regime classifier failed: %s", exc)

    fmp_map: dict[str, FmpEnrichedStock] = {}
    if fmp_candidates:
        fmp_map = {s.symbol: s for s in fmp_candidates}

    regime_context = format_regime_header(regime) if regime else ""

    # Re-score FMP with regime-adjusted weights (sync point — needs both)
    if regime and fmp_candidates and config.fmp_screener:
        adjusted_config = apply_regime_weight_adjustments(config.fmp_screener, regime.regime_type)
        fmp_candidates = compute_composite_scores(fmp_candidates, adjusted_config)
        fmp_candidates.sort(key=lambda s: s.composite_score or 0, reverse=True)
        fmp_map = {s.symbol: s for s in fmp_candidates}

    # ── Stage 1: Perplexity (get ticker list) ─────────────────────────────
    screening: ScreeningResult | None = None
    try:

        async def _run_perplexity_stage() -> tuple:
            if mode == "prompt":
                return await run_prompted_discovery(
                    user_prompt or "", config, fmp_candidates=fmp_candidates
                )
            if mode == "discovery":
                if not config.screening_prompt:
                    default_prompt = "trending Canadian TSX stocks and top TSX market movers today"
                    return await run_prompted_discovery(
                        default_prompt, config, fmp_candidates=fmp_candidates
                    )
                if config.enable_debate:
                    return await run_bull_bear_discovery(config, fmp_candidates=fmp_candidates)
                return await run_discovery(config, fmp_candidates=fmp_candidates)
            if mode == "analysis":
                return await run_analysis(manual_tickers or [], config)
            if mode == "combined":
                if config.screening_prompt:
                    discovery_result, _disc_meta = await run_discovery(
                        config, fmp_candidates=fmp_candidates
                    )
                else:
                    default_prompt = "trending Canadian TSX stocks and top TSX market movers today"
                    discovery_result, _disc_meta = await run_prompted_discovery(
                        default_prompt, config, fmp_candidates=fmp_candidates
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
            StageError(stage="perplexity", error=str(exc), type=type(exc).__name__)
        )
        logger.exception(" Perplexity stage failed")
        stage_metadata = {
            "stage": "perplexity",
            "status": "error",
            "model": "perplexity-sonar",
            "duration_ms": 0,
            "error": str(exc),
        }

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

    await _save_stage_output(run_id, stage_metadata)

    # Build ticker list for parallel tracks
    ticker_symbols = (
        [t.ticker for t in screening.tickers]
        if screening and screening.tickers
        else list(manual_tickers or [])
    )

    # Merge scanner-confirmed tickers when available (pre-pipeline discovery)
    if not manual_tickers:
        try:
            from services.strategy_scanner import get_scanner

            scanner = get_scanner()
            strategy_type = config.strategy_type if hasattr(config, "strategy_type") else None
            scan_results = await scanner.get_latest_results(
                strategy_type=strategy_type,
                min_combined_score=0.45,
                max_age_minutes=90,
            )
            if scan_results:
                scanner_tickers = [r.ticker for r in scan_results]
                existing = set(ticker_symbols)
                added = [t for t in scanner_tickers if t not in existing]
                if added:
                    # Prepend so max_tickers keeps scanner hits; Perplexity tail is cut first.
                    ticker_symbols = added + ticker_symbols
                    result.meta["scanner_tickers_added"] = added
                    logger.info(
                        " Scanner added %d pre-confirmed tickers: %s",
                        len(added),
                        added[:10],
                    )
        except Exception as exc:
            logger.debug(" Scanner results unavailable: %s", exc)

    if not ticker_symbols:
        return await _finalize(run_id, result, start, client, regime_context)

    # ── Lightweight pre-filter (no LLM) ──────────────────────────────────
    ticker_symbols = pre_filter_tickers(ticker_symbols, fmp_map, config)

    # Enforce max_tickers cap from strategy config
    if config.max_tickers and len(ticker_symbols) > config.max_tickers:
        logger.info(
            " Capping ticker list from %d to %d (max_tickers=%d)",
            len(ticker_symbols),
            config.max_tickers,
            config.max_tickers,
        )
        ticker_symbols = ticker_symbols[: config.max_tickers]

    result.chart_indicators = config.chart_indicators

    # ── Numerical TA + Live Quotes (CONCURRENT) ─────────────────────────
    # Both need ticker_symbols but are independent of each other.
    ta_snapshots: list[MultiTimeframeTechnical] = []
    claude_live_quotes: dict = {}

    async def _numerical_ta() -> tuple[list[MultiTimeframeTechnical], list[dict]]:
        return await asyncio.wait_for(
            run_numerical_ta(ticker_symbols, config),
            timeout=STAGE_TIMEOUTS.get("numerical_ta", 90.0),
        )

    async def _claude_quotes() -> dict:
        quotes = await fetch_quotes(ticker_symbols)
        logger.info(" Fetched %d live quotes for Claude", len(quotes))
        return quotes

    ta_task = asyncio.create_task(_numerical_ta())
    quotes_task = asyncio.create_task(_claude_quotes())

    try:
        ta_snapshots, ta_metadata = await ta_task
        for tm in ta_metadata:
            await _save_stage_output(run_id, tm)
    except Exception as exc:
        result.stage_errors.append(
            StageError(stage="numerical_ta", error=str(exc), type=type(exc).__name__)
        )
        logger.warning(" Numerical TA stage failed: %s", exc)

    try:
        claude_live_quotes = await quotes_task
    except Exception as exc:
        logger.warning(" Live quote fetch for Claude failed (non-critical): %s", exc)

    # ── Three Independent Parallel Tracks ────────────────────────────────
    # Track A: Perplexity results already collected above (screening)
    # Track B: Gemini (FMP context + Perplexity highlights, no raw articles)
    # Track C: Claude (numerical TA + chart + live quotes — NO sentiment)

    ticker_highlights: dict[str, list[str]] | None = None
    if screening and screening.tickers:
        _hl = {t.ticker: t.key_highlights for t in screening.tickers if t.key_highlights}
        ticker_highlights = _hl or None

    async def _track_b_gemini() -> tuple[list[SentimentAnalysis], list[dict]]:
        """Track B: Gemini sentiment enriched with FMP + Perplexity highlights.

        Saves stage_outputs immediately so progress updates while Claude
        is still running.
        """
        sentiments_b, meta_b = await run_sentiment(
            ticker_symbols,
            config,
            ticker_news=None,
            fmp_context=fmp_map or None,
            ticker_highlights=ticker_highlights,
            regime_context=regime_context,
        )
        for gm in meta_b:
            await _save_stage_output(run_id, gm)
        return sentiments_b, meta_b

    async def _track_c_claude() -> tuple[list[ChartAnalysis], list[dict]]:
        """Track C: Technical analysis with numerical TA + live quotes (no sentiment).

        Saves stage_outputs immediately so progress updates while Gemini
        is still running.
        """
        charts_c, meta_c = await run_chart_analysis(
            ticker_symbols,
            config,
            ta_snapshots,
            run_id,
            user_id,
            regime_context=regime_context,
            live_quotes=claude_live_quotes or None,
            is_crypto=config.is_crypto,
        )
        for cm in meta_c:
            await _save_stage_output(run_id, cm)
        return charts_c, meta_c

    gemini_result: tuple[list[SentimentAnalysis], list[dict]] = ([], [])
    claude_result: tuple[list[ChartAnalysis], list[dict]] = ([], [])

    gather_results = await asyncio.gather(
        asyncio.wait_for(_track_b_gemini(), timeout=STAGE_TIMEOUTS["gemini"]),
        asyncio.wait_for(_track_c_claude(), timeout=STAGE_TIMEOUTS["claude"]),
        return_exceptions=True,
    )

    if isinstance(gather_results[0], BaseException):
        logger.error(" Gemini track failed: %s", gather_results[0])
        result.stage_errors.append(
            StageError(
                stage="gemini",
                error=str(gather_results[0]),
                type=type(gather_results[0]).__name__,
            )
        )
    else:
        gemini_result = gather_results[0]

    if isinstance(gather_results[1], BaseException):
        logger.error(" Claude track failed: %s", gather_results[1])
        result.stage_errors.append(
            StageError(
                stage="claude",
                error=str(gather_results[1]),
                type=type(gather_results[1]).__name__,
            )
        )
    else:
        claude_result = gather_results[1]

    sentiments, _gemini_meta = gemini_result
    charts, claude_metadata_list = claude_result

    result.sentiment_analyses = sentiments
    result.chart_analyses = charts

    for cm in claude_metadata_list:
        if cm.get("status") not in ("success", None):
            result.chart_errors.append(
                ChartError(
                    ticker=cm.get("ticker", "unknown"),
                    status=cm.get("status", "unknown"),
                    error=cm.get("error", ""),
                )
            )

    # ── Risk Post-Filter (enriches, doesn't remove) ──────────────────────
    risk_assessments: list = []
    try:
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
    except Exception as exc:
        logger.exception(" Risk post-filter failed")
        result.stage_errors.append(
            StageError(stage="risk_post_filter", error=str(exc), type=type(exc).__name__)
        )
        await _save_stage_output(
            run_id,
            {
                "stage": "risk_post_filter",
                "status": "error",
                "model": "deterministic",
                "duration_ms": 0,
                "error": str(exc),
            },
        )

    # ── Stage 4: GPT Synthesis (convergence point — track-aware) ─────────
    sector_consensus = _aggregate_sector_sentiment(sentiments, screening)
    live_quotes_v2: dict = {}
    if ticker_symbols:
        try:
            reflection_context = await load_reflection_context(user_id)
            # Fetch quotes immediately before GPT so entry prices anchor to the
            # freshest available price (Gemini+Claude may have taken several minutes).
            live_quotes: dict = {}
            try:
                live_quotes = await fetch_quotes(ticker_symbols)
                logger.info("Fetched %d live quotes before GPT stage", len(live_quotes))
            except Exception as exc:
                logger.warning("Live quote fetch failed: %s", exc)

            gpt_signal_time = datetime.now(tz=UTC)
            recommendations, gpt_metadata_list = await asyncio.wait_for(
                run_debate(
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
        except Exception as exc:
            result.stage_errors.append(
                StageError(stage="gpt", error=str(exc), type=type(exc).__name__)
            )
            logger.exception("GPT stage failed")

    # Track agreement (Gemini + Claude + GPT consensus)
    for rec in result.recommendations:
        try:
            rec.track_agreement = _compute_track_agreement(rec, sentiments, charts)
        except Exception as exc:
            logger.warning("Track agreement failed for %s: %s", rec.ticker, exc)

    # Risk validation
    if result.recommendations:
        try:
            result.recommendations = validate_risks(
                result.recommendations,
                config,
                charts,
                fmp_context=fmp_map or None,
                live_quotes=live_quotes or None,
            )
        except Exception as exc:
            logger.exception("Risk validation failed, using unvalidated recommendations")
            result.stage_errors.append(
                StageError(stage="risk_validation", error=str(exc), type=type(exc).__name__)
            )

    # Preserve raw GPT confidence before any calibration modifies it
    if result.recommendations:
        for rec in result.recommendations:
            if rec.raw_gpt_confidence is None:
                rec.raw_gpt_confidence = rec.confidence

    # Confidence calibration (Phase 7)
    if result.recommendations:
        use_ml_calibration = False
        try:
            from ml.inference import ml_model_available
            from ml.shadow_runner import get_shadow_stats

            if ml_model_available(config.strategy_type):
                stats = await get_shadow_stats(user_id)
                if (
                    stats.predictions_with_outcomes >= 50
                    and stats.ml_accuracy is not None
                    and stats.gpt_accuracy is not None
                    and stats.ml_accuracy >= stats.gpt_accuracy
                ):
                    use_ml_calibration = True
                    logger.info(
                        "ML calibration activated (ML=%.1f%% >= GPT=%.1f%%, n=%d)",
                        stats.ml_accuracy * 100,
                        stats.gpt_accuracy * 100,
                        stats.predictions_with_outcomes,
                    )
        except Exception:
            logger.warning("ML calibration check failed, using deterministic", exc_info=True)

        try:
            if use_ml_calibration:
                from services.ml_calibration import calibrate_with_ml

                ta_dict: dict[str, dict[str, Any]] = {}
                for snap in ta_snapshots:
                    if hasattr(snap, "ticker") and hasattr(snap, "primary"):
                        ta_dict[snap.ticker] = snap.primary.model_dump() if snap.primary else {}

                fmp_dict_cal: dict[str, dict[str, Any]] = {}
                if fmp_map:
                    for sym, stock in fmp_map.items():
                        fmp_dict_cal[sym] = (
                            stock.model_dump() if hasattr(stock, "model_dump") else {}
                        )

                regime_dict_cal: dict[str, Any] | None = None
                if regime:
                    regime_dict_cal = {
                        "regime_type": regime.regime_type,
                        "vix_estimate": regime.vix_estimate,
                        "breadth_estimate": regime.breadth_estimate,
                    }

                rec_dicts = [r.model_dump() for r in result.recommendations]
                calibrated = await calibrate_with_ml(
                    rec_dicts,
                    ta_snapshots=ta_dict or None,
                    fmp_data=fmp_dict_cal or None,
                    strategy_type=config.strategy_type,
                    regime_context=regime_dict_cal,
                )
                from pipeline.schemas import Recommendation

                result.recommendations = [Recommendation(**r) for r in calibrated]
            else:
                from services.confidence_calibration import calibrate_recommendations

                result.recommendations = calibrate_recommendations(
                    result.recommendations,
                    ta_snapshots=ta_snapshots or None,
                    config=config,
                    regime_context=regime_context,
                    risk_assessments=risk_assessments or None,
                )
        except Exception as exc:
            logger.exception(" Confidence calibration failed, using raw confidence")
            result.stage_errors.append(
                StageError(stage="calibration", error=str(exc), type=type(exc).__name__)
            )

    # ML gate + shadow predictions (Phase 7.5)
    if result.recommendations:
        ta_dict_ml: dict[str, dict[str, Any]] = {}
        for snap in ta_snapshots:
            if hasattr(snap, "ticker") and hasattr(snap, "primary"):
                ta_dict_ml[snap.ticker] = snap.primary.model_dump() if snap.primary else {}

        fmp_dict_ml: dict[str, dict[str, Any]] = {}
        if fmp_map:
            for sym, stock in fmp_map.items():
                fmp_dict_ml[sym] = stock.model_dump() if hasattr(stock, "model_dump") else {}

        regime_dict_ml: dict[str, Any] | None = None
        if regime:
            regime_dict_ml = {
                "regime_type": regime.regime_type,
                "vix_estimate": regime.vix_estimate,
                "breadth_estimate": regime.breadth_estimate,
            }

        # Capture raw GPT position sizing before gate modifies it
        for rec in result.recommendations:
            rec.raw_gpt_position_size_pct = rec.position_size_pct

        # 7.5a: ML gate — independent model adjusts sizing / blocks (parallelised)
        gate_start = datetime.now(tz=UTC)
        gate_results: list[dict[str, Any]] = []
        gate_status = "skipped"
        gate_model = ""
        try:
            from ml.gate import run_ml_gate
            from ml.inference import ml_model_available

            if ml_model_available(config.strategy_type, mode="independent"):
                gate_coros = [
                    run_ml_gate(
                        ticker=rec.ticker,
                        strategy_type=config.strategy_type,
                        ta_features=ta_dict_ml.get(rec.ticker, {}),
                        fmp_features=fmp_dict_ml.get(rec.ticker),
                        regime_context=regime_dict_ml,
                    )
                    for rec in result.recommendations
                ]
                gate_outputs = await asyncio.gather(*gate_coros, return_exceptions=True)
                for rec, gate_or_exc in zip(result.recommendations, gate_outputs, strict=True):
                    if isinstance(gate_or_exc, Exception):
                        logger.warning("ML gate failed for %s: %s", rec.ticker, gate_or_exc)
                        continue
                    gate = gate_or_exc
                    rec.ml_probability = gate.ml_probability
                    rec.ml_size_multiplier = gate.size_multiplier
                    rec.ml_blocked = gate.blocked
                    rec.ml_conformal_set = gate.conformal_set
                    rec.ml_model_version = gate.model_version
                    if gate.blocked:
                        rec.warnings.append(
                            f"ML gate blocked: probability {gate.ml_probability:.1%}"
                        )
                    elif gate.size_multiplier < 1.0:
                        rec.position_size_pct *= gate.size_multiplier
                    gate_results.append(gate.model_dump())
                    if gate.model_version:
                        gate_model = gate.model_version
                gate_status = "success"
                logger.info("ML gate complete (%d recs)", len(gate_coros))
        except Exception:
            gate_status = "error"
            logger.warning("ML gate skipped", exc_info=True)

        gate_ms = int((datetime.now(tz=UTC) - gate_start).total_seconds() * 1000)
        await _save_stage_output(
            run_id,
            {
                "stage": "ml_gate",
                "status": gate_status,
                "model": gate_model or "lightgbm",
                "duration_ms": gate_ms,
                "raw_response": json.dumps(gate_results) if gate_results else "",
            },
        )

        # 7.5b: ML shadow — full model comparison (non-blocking)
        try:
            from ml.inference import ml_model_available
            from ml.shadow_runner import run_ml_shadow

            if ml_model_available(config.strategy_type):
                rec_dicts = [r.model_dump() for r in result.recommendations]
                await run_ml_shadow(
                    run_id=run_id,
                    recommendations=rec_dicts,
                    ta_snapshots=ta_dict_ml or None,
                    fmp_data=fmp_dict_ml or None,
                    regime_context=regime_dict_ml,
                    strategy_type=config.strategy_type,
                    user_id=user_id,
                )
                logger.info(" ML shadow predictions complete")
        except Exception:
            logger.warning("ML shadow skipped", exc_info=True)

    # Save recommendations after all modifications (risk validation, ML gate)
    if result.recommendations:
        try:
            await _save_recommendations(run_id, result.recommendations, user_id)
        except Exception:
            logger.exception(" Failed to save recommendations for run %s", run_id)
            result.stage_errors.append(StageError(stage="save_recommendations", error="DB save failed"))

    # Annotated charts
    annotate_start = time.perf_counter()
    annotate_status = "skipped"
    annotate_count = 0
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
                    is_crypto=config.is_crypto,
                )
                result.chart_analyses[ca_index].annotated_chart_path = url
            except Exception as exc:
                logger.warning(" Annotated chart failed for %s: %s", ca.ticker, exc)

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *(_annotate(i) for i in range(len(result.chart_analyses))),
                    return_exceptions=True,
                ),
                timeout=STAGE_TIMEOUTS["annotate"],
            )
            annotate_count = sum(1 for ca in result.chart_analyses if ca.annotated_chart_path)
            annotate_status = "success" if annotate_count else "error"
        except TimeoutError:
            logger.error(" Annotate stage timed out")
            annotate_status = "error"

        await _update_annotated_paths(client, run_id, result.chart_analyses)

    annotate_ms = int((time.perf_counter() - annotate_start) * 1000)
    await _save_stage_output(
        run_id,
        {
            "stage": "annotate",
            "status": annotate_status,
            "model": "chart-img-v2",
            "duration_ms": annotate_ms,
            "raw_response": f"{annotate_count} charts annotated",
        },
    )

    return await _finalize(run_id, result, start, client, regime_context)


async def _finalize(
    run_id: str,
    result: PipelineResult,
    start: float,
    client: Any,
    regime_context: str,
) -> PipelineResult:
    """Finalize pipeline run: timing, prompt versions, DB update.

    Args:
        run_id: Pipeline run UUID.
        result: The PipelineResult being built.
        start: perf_counter value from pipeline start.
        client: Supabase client.
        regime_context: Unused, kept for signature consistency.

    Returns:
        Completed PipelineResult.
    """
    elapsed = time.perf_counter() - start
    result.total_duration_seconds = round(elapsed, 2)
    result.prompt_versions = {
        "regime": regime_hash(),
        "perplexity": discovery_hash(),
        "gemini": gemini_hash(),
        "claude": claude_hash(),
        "gpt_bull": get_bull_hash(),
        "gpt_bear": get_bear_hash(),
        "gpt_judge": get_judge_hash(),
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
                "stage_errors": (
                    json.dumps([e.model_dump() for e in result.stage_errors])
                    if result.stage_errors
                    else None
                ),
            }
        )
        .eq("id", run_id)
        .execute()
    )

    clear_run_symbol_cache(run_id)
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
            "raw_gpt_confidence": rec.raw_gpt_confidence,
            "raw_gpt_position_size_pct": rec.raw_gpt_position_size_pct,
            "ml_probability": rec.ml_probability,
            "ml_size_multiplier": rec.ml_size_multiplier,
            "ml_blocked": rec.ml_blocked,
            "ml_model_version": rec.ml_model_version,
            "ml_conformal_set": json.dumps(rec.ml_conformal_set) if rec.ml_conformal_set else None,
            "track_agreement": rec.track_agreement.model_dump_json()
            if rec.track_agreement
            else None,
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


def _compute_track_agreement(
    rec: Recommendation,
    sentiments: list[SentimentAnalysis],
    charts: list[ChartAnalysis],
) -> TrackAgreement:
    """Compute multi-track agreement between GPT, Gemini, and Claude for one ticker.

    Compares the independent Gemini sentiment and Claude chart bias against
    GPT's final action to measure consensus across the pipeline tracks.

    Args:
        rec: The GPT recommendation for a single ticker.
        sentiments: All Gemini sentiment analyses from the pipeline run.
        charts: All Claude chart analyses from the pipeline run.

    Returns:
        Populated TrackAgreement with directions, score, and conflict details.
    """
    gpt_dir: Literal["bullish", "bearish", "neutral"]
    if rec.action == RecommendationAction.BUY:
        gpt_dir = "bullish"
    elif rec.action == RecommendationAction.SHORT:
        gpt_dir = "bearish"
    else:
        gpt_dir = "neutral"

    gemini_dir: Literal["bullish", "bearish", "neutral"] = "neutral"
    for sa in sentiments:
        if sa.ticker == rec.ticker:
            if sa.sentiment_label in ("bullish", "strongly_bullish"):
                gemini_dir = "bullish"
            elif sa.sentiment_label in ("bearish", "strongly_bearish"):
                gemini_dir = "bearish"
            break

    claude_dir: Literal["bullish", "bearish", "neutral"] = "neutral"
    for ca in charts:
        if ca.ticker == rec.ticker:
            bias = ca.overall_bias.lower()
            if "bullish" in bias:
                claude_dir = "bullish"
            elif "bearish" in bias:
                claude_dir = "bearish"
            break

    if gpt_dir == "neutral":
        return TrackAgreement(
            gemini_direction=gemini_dir,
            claude_direction=claude_dir,
            agreement_score=0.5,
        )

    aligned: list[str] = []
    dissenting: list[str] = []
    track_dirs = {"gemini": gemini_dir, "claude": claude_dir}
    for name, direction in track_dirs.items():
        if direction == "neutral":
            continue
        if direction == gpt_dir:
            aligned.append(name)
        else:
            dissenting.append(name)

    total = len(aligned) + len(dissenting)
    score = len(aligned) / total if total > 0 else 0.5
    conflicts = [f"{name} ({track_dirs[name]}) vs GPT ({gpt_dir})" for name in dissenting]

    return TrackAgreement(
        gemini_direction=gemini_dir,
        claude_direction=claude_dir,
        agreement_score=score,
        conflicts=conflicts,
    )


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
