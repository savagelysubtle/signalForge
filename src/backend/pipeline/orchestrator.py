"""Pipeline execution engine (v2 — parallel tracks).

Pipeline (parallel tracks):
  (FMP screening || Regime classification) →
  Re-score FMP with regime → Perplexity → pre_filter_tickers →
  (Numerical TA || Live Quotes) →
  (Gemini || Claude) →
  Risk post-filter → Pre-GPT ML prior (prompts + optional debate escalation) →
  GPT synthesis → calibration → ML gate/shadow → ML confidence blend → Annotated charts.

Claude deliberately does NOT receive Gemini sentiment to avoid bias.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

from postgrest.exceptions import APIError
from supabase import AsyncClient

from database.connection import get_db
from pipeline.cost_tracker import PipelineCostTracker, should_estimate_cost_from_metadata
from pipeline.prompts.claude_chart import get_prompt_hash as claude_hash
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
from services.ml_confidence_blend import blend_confidence_with_ml
from services.paper_tracker import schedule_paper_tracking
from services.reflection import load_reflection_context, load_reflection_metrics
from services.strategy import get_strategy
from utils.ticker import (
    canonical_ticker_match_key,
    dedupe_ticker_symbols_preserve_order,
    normalize_ticker,
    normalize_tickers,
)

logger = logging.getLogger(__name__)

STAGE_TIMEOUTS: dict[str, float] = {
    "fmp": float(os.getenv("SF_TIMEOUT_FMP", "90")),
    "perplexity": float(os.getenv("SF_TIMEOUT_PERPLEXITY", "180")),
    "gemini": float(os.getenv("SF_TIMEOUT_GEMINI", "300")),
    "claude": float(os.getenv("SF_TIMEOUT_CLAUDE", "600")),
    "gpt": float(os.getenv("SF_TIMEOUT_GPT", "900")),
    "annotate": float(os.getenv("SF_TIMEOUT_ANNOTATE", "60")),
}


def _build_ml_dicts(
    ta_snapshots: list[MultiTimeframeTechnical],
    fmp_map: dict[str, FmpEnrichedStock],
    regime: RegimeOutput | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any] | None]:
    """Build the TA/FMP/regime dictionaries needed by ML calibration and gate.

    Extracts the repeated dict-building pattern used by both the ML
    calibration path and the ML gate/shadow runner.

    Args:
        ta_snapshots: Multi-timeframe TA snapshots keyed by ticker in the returned dict.
        fmp_map: Mapping of symbol to enriched FMP stock (may be empty).
        regime: Market regime output (may be None).

    Returns:
        Tuple of (ta_dict, fmp_dict, regime_dict).
    """
    from ml.feature_mapper import map_fmp_to_features, map_multi_tf_to_features

    ta_dict: dict[str, dict[str, Any]] = {}
    for snap in ta_snapshots:
        if hasattr(snap, "ticker"):
            ta_dict[snap.ticker] = map_multi_tf_to_features(snap.model_dump())

    fmp_dict: dict[str, dict[str, Any]] = {}
    if fmp_map:
        for sym, stock in fmp_map.items():
            raw = stock.model_dump() if hasattr(stock, "model_dump") else {}
            fmp_dict[sym] = map_fmp_to_features(raw)

    regime_dict: dict[str, Any] | None = None
    if regime:
        regime_dict = {
            "regime_type": regime.regime_type,
            "vix_estimate": regime.vix_estimate,
            "breadth_estimate": regime.breadth_estimate,
        }

    return ta_dict, fmp_dict, regime_dict


def _enrich_screening_fundamentals(
    screening: ScreeningResult,
    fmp_map: dict[str, FmpEnrichedStock],
    live_quotes: dict,
) -> None:
    """Back-patch FundamentalData fields from FMP and live quotes.

    Perplexity's anti-hallucination rule forces null for any unverified
    metric, leaving market_cap, pe_ratio, price, etc. blank.  This fills
    them from deterministic sources (FMP enrichment, live quotes) so the
    frontend overview cards actually show data.

    Mutates ``screening.tickers`` in place; only overwrites fields that
    are still ``None``.
    """
    if not screening or not screening.tickers:
        return

    for td in screening.tickers:
        key = canonical_ticker_match_key(td.ticker)

        fmp = next(
            (s for sym, s in fmp_map.items() if canonical_ticker_match_key(sym) == key),
            None,
        )
        if fmp:
            if td.market_cap is None and fmp.market_cap is not None:
                if fmp.market_cap >= 1_000_000_000:
                    td.market_cap = f"${fmp.market_cap / 1_000_000_000:.1f}B"
                else:
                    td.market_cap = f"${fmp.market_cap / 1_000_000:.0f}M"
            if td.pe_ratio is None and fmp.pe_ratio is not None:
                td.pe_ratio = round(fmp.pe_ratio, 2)
            if td.sector in ("", None) and fmp.sector:
                td.sector = fmp.sector
            if td.price is None and fmp.price is not None:
                td.price = fmp.price
            if td.relative_volume is None and fmp.relative_volume is not None:
                td.relative_volume = round(fmp.relative_volume, 2)
            if td.free_cash_flow is None and fmp.fcf_per_share is not None:
                td.free_cash_flow = f"${fmp.fcf_per_share:.2f}/sh"
            if td.company_name in ("", None) and fmp.company_name:
                td.company_name = fmp.company_name

        quote = next(
            (q for sym, q in live_quotes.items() if canonical_ticker_match_key(sym) == key),
            None,
        )
        if quote:
            if td.price is None and quote.price is not None:
                td.price = quote.price
            if td.price_change_pct is None and quote.changesPercentage is not None:
                td.price_change_pct = round(quote.changesPercentage, 2)


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

    # Load regime-aware priors if not already loaded
    from services.prior_service import is_loaded as priors_loaded
    from services.prior_service import load_prior_table

    if not priors_loaded():
        load_prior_table()

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
    cost_tracker = PipelineCostTracker()

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
            cost_tracker,
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
                await _save_stage_output(run_id, meta, cost_tracker)
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
            await _save_stage_output(run_id, regime_meta, cost_tracker)
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
            cost_tracker,
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
            cost_tracker,
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

    await _save_stage_output(run_id, stage_metadata, cost_tracker)

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
                scanner_tickers = [normalize_ticker(r.ticker) for r in scan_results]
                existing_keys = {canonical_ticker_match_key(t) for t in ticker_symbols}
                added: list[str] = []
                for t in scanner_tickers:
                    k = canonical_ticker_match_key(t)
                    if k in existing_keys:
                        continue
                    existing_keys.add(k)
                    added.append(t)
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

    if not ticker_symbols and fmp_candidates:
        cap = config.max_tickers if config.max_tickers else 20
        ticker_symbols = [normalize_ticker(s.symbol) for s in fmp_candidates[:cap]]
        result.meta["ticker_source"] = "fmp_fallback"
        logger.info(
            " No tickers from discovery/screening; using top %d FMP pre-screened symbols",
            len(ticker_symbols),
        )

    ticker_symbols = dedupe_ticker_symbols_preserve_order(ticker_symbols)

    if not ticker_symbols:
        result.stage_errors.append(
            StageError(
                stage="pipeline",
                error=(
                    "No symbols to analyze: Perplexity returned no tickers, FMP pre-screen "
                    "was empty or disabled, and no manual tickers were provided. "
                    "Enter tickers (e.g. AAPL, MSFT), check API keys (Perplexity, FMP), "
                    "or relax strategy screener filters."
                ),
                type="NoTickers",
            )
        )
        result.meta["halt_reason"] = "no_tickers"
        return await _finalize(run_id, result, start, client, regime_context, cost_tracker)

    # ── Lightweight pre-filter (no LLM) ──────────────────────────────────
    _tickers_before_pre_filter = list(ticker_symbols)
    ticker_symbols = pre_filter_tickers(ticker_symbols, fmp_map, config)
    if not ticker_symbols and _tickers_before_pre_filter:
        logger.warning(
            " FMP pre-filter removed all %d tickers; continuing with unfiltered list",
            len(_tickers_before_pre_filter),
        )
        ticker_symbols = _tickers_before_pre_filter

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
            await _save_stage_output(run_id, tm, cost_tracker)
    except Exception as exc:
        result.stage_errors.append(
            StageError(stage="numerical_ta", error=str(exc), type=type(exc).__name__)
        )
        logger.warning(" Numerical TA stage failed: %s", exc)

    try:
        claude_live_quotes = await quotes_task
    except Exception as exc:
        logger.warning(" Live quote fetch for Claude failed (non-critical): %s", exc)

    # ── Enrich screening fundamentals with FMP + live quotes ─────────────
    if screening:
        _enrich_screening_fundamentals(screening, fmp_map, claude_live_quotes)
        try:
            client = await get_db()
            await (
                client.table("stage_outputs")
                .update({"raw_response": screening.model_dump_json()})
                .eq("run_id", run_id)
                .eq("stage", "perplexity")
                .execute()
            )
        except Exception as exc:
            logger.warning("Failed to update enriched screening: %s", exc)

    # ── Three Independent Parallel Tracks ────────────────────────────────
    # Track A: Perplexity results already collected above (screening)
    # Track B: Gemini (FMP context + Perplexity article URLs/highlights)
    # Track C: Claude (numerical TA + chart + live quotes — NO sentiment)

    ticker_news: dict[str, list[str]] | None = None
    ticker_highlights: dict[str, list[str]] | None = None
    if screening and screening.tickers:
        _news = {t.ticker: t.news_urls for t in screening.tickers if t.news_urls}
        _hl = {t.ticker: t.key_highlights for t in screening.tickers if t.key_highlights}
        ticker_news = _news or None
        ticker_highlights = _hl or None

    async def _track_b_gemini() -> tuple[list[SentimentAnalysis], list[dict]]:
        """Track B: Gemini sentiment enriched with Perplexity links/highlights + FMP."""
        sentiments_b, meta_b = await run_sentiment(
            ticker_symbols,
            config,
            ticker_news=ticker_news,
            fmp_context=fmp_map or None,
            ticker_highlights=ticker_highlights,
            regime_context=regime_context,
        )
        for gm in meta_b:
            await _save_stage_output(run_id, gm, cost_tracker)
        return sentiments_b, meta_b

    async def _track_c_claude() -> tuple[list[ChartAnalysis], list[dict]]:
        """Track C: Technical analysis with numerical TA + live quotes (no sentiment)."""
        charts_c, meta_c = await run_chart_analysis(
            ticker_symbols,
            config,
            ta_snapshots,
            run_id,
            user_id,
            regime_context=regime_context,
            live_quotes=claude_live_quotes or None,
            is_crypto=config.fmp_screener.is_crypto if config.fmp_screener else False,
        )
        for cm in meta_c:
            await _save_stage_output(run_id, cm, cost_tracker)
        return charts_c, meta_c

    gemini_result: tuple[list[SentimentAnalysis], list[dict]] = ([], [])
    claude_result: tuple[list[ChartAnalysis], list[dict]] = ([], [])

    gather_results = await asyncio.gather(
        asyncio.wait_for(_track_b_gemini(), timeout=STAGE_TIMEOUTS["gemini"]),
        asyncio.wait_for(_track_c_claude(), timeout=STAGE_TIMEOUTS["claude"]),
        return_exceptions=True,
    )

    if isinstance(gather_results[0], BaseException):
        gemini_exc = gather_results[0]
        logger.error(
            "Gemini track failed (%s): %s",
            type(gemini_exc).__name__,
            gemini_exc or "(no message)",
        )
        result.stage_errors.append(
            StageError(
                stage="gemini",
                error=str(gemini_exc) or type(gemini_exc).__name__,
                type=type(gemini_exc).__name__,
            )
        )
    else:
        gemini_result = gather_results[0]

    if isinstance(gather_results[1], BaseException):
        claude_exc = gather_results[1]
        logger.error(
            "Claude track failed (%s): %s",
            type(claude_exc).__name__,
            claude_exc or "(no message)",
        )
        result.stage_errors.append(
            StageError(
                stage="claude",
                error=str(claude_exc) or type(claude_exc).__name__,
                type=type(claude_exc).__name__,
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
            cost_tracker,
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
            cost_tracker,
        )

    # ── Stage 3.5: Pre-GPT ML prior (prompt injection + debate escalation) ──
    pre_gpt_hints: dict[str, Any] = {}
    ml_escalation_flag = False
    force_ml_debate_flag = False
    if ticker_symbols:
        try:
            from ml.pre_gpt import (
                build_ml_feature_dicts,
                ml_uncertainty_escalates_debate,
                pre_gpt_hints_to_json,
                run_pre_gpt_gates,
            )

            ta_pre, fmp_pre, regime_pre = build_ml_feature_dicts(
                ta_snapshots or None, fmp_map or None, regime
            )
            mg_start = time.perf_counter()
            pre_gpt_hints = await run_pre_gpt_gates(
                ticker_symbols,
                config.strategy_type,
                ta_pre,
                fmp_pre,
                regime_pre,
            )
            mg_ms = int((time.perf_counter() - mg_start) * 1000)
            ml_escalation_flag = ml_uncertainty_escalates_debate(pre_gpt_hints)
            force_ml_debate_flag = ml_escalation_flag and not config.enable_debate
            mv_hint = next(
                (h.model_version for h in pre_gpt_hints.values() if h.model_version),
                "",
            )
            await _save_stage_output(
                run_id,
                {
                    "stage": "ml_pre_gpt",
                    "status": "success",
                    "model": mv_hint or "lightgbm",
                    "duration_ms": mg_ms,
                    "raw_response": pre_gpt_hints_to_json(pre_gpt_hints),
                },
                cost_tracker,
            )
            if ml_escalation_flag:
                result.meta["pre_gpt_ml_escalation"] = True
        except Exception as exc:
            logger.warning("Pre-GPT ML stage failed: %s", exc)
            result.stage_errors.append(
                StageError(stage="ml_pre_gpt", error=str(exc), type=type(exc).__name__)
            )
            await _save_stage_output(
                run_id,
                {
                    "stage": "ml_pre_gpt",
                    "status": "error",
                    "model": "lightgbm",
                    "duration_ms": 0,
                    "error": str(exc),
                },
                cost_tracker,
            )

    # ── Stage 4: GPT Synthesis (convergence point — track-aware) ─────────
    sector_consensus = _aggregate_sector_sentiment(sentiments, screening)
    live_quotes: dict = {}
    reflection_metrics: dict | None = None
    if ticker_symbols:
        try:
            reflection_context = await load_reflection_context(user_id)
            reflection_metrics = await load_reflection_metrics(user_id)
            try:
                live_quotes = await fetch_quotes(ticker_symbols)
                logger.info("Fetched %d live quotes before GPT stage", len(live_quotes))
            except Exception as exc:
                logger.warning("Live quote fetch failed: %s", exc)

            track_conflicts = _build_track_conflicts(sentiments, charts, ticker_symbols)

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
                    track_conflicts=track_conflicts,
                    force_ml_debate=force_ml_debate_flag,
                    pre_gpt_ml=pre_gpt_hints or None,
                    ml_escalation=ml_escalation_flag,
                ),
                timeout=STAGE_TIMEOUTS["gpt"],
            )
            # Stamp freshness metadata onto each recommendation
            signal_ts = gpt_signal_time.isoformat()
            for rec in recommendations:
                rec.signal_generated_at = signal_ts
                if live_quotes and rec.ticker in live_quotes:
                    rec.price_at_signal = live_quotes[rec.ticker].price
                hint = pre_gpt_hints.get(rec.ticker)
                if hint and hint.reason not in ("no_independent_model", "prediction_failed"):
                    rec.pre_gpt_ml_probability = hint.ml_probability
                    rec.pre_gpt_ml_direction = hint.predicted_direction
            result.recommendations = recommendations
            for gm in gpt_metadata_list:
                await _save_stage_output(run_id, gm, cost_tracker)
        except Exception as exc:
            result.stage_errors.append(
                StageError(stage="gpt", error=str(exc), type=type(exc).__name__)
            )
            logger.exception("GPT stage failed")

    # Track agreement (Perplexity + Gemini + Claude — true 3-track consensus)
    for rec in result.recommendations:
        try:
            rec.track_agreement = _compute_track_agreement(
                rec, sentiments, charts, screening=result.screening
            )
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
                risk_assessments=risk_assessments or None,
                ta_snapshots=ta_snapshots or None,
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

        # Clamp confidence by action — GPT often interprets confidence as
        # "certainty in its verdict" rather than "directional trade conviction."
        # NO_TRADE should be low (no edge), WATCH moderate (developing setup).
        _ACTION_CONFIDENCE_CAPS: dict[str, float] = {
            "NO_TRADE": 0.25,
            "HOLD": 0.35,
            "WATCH": 0.55,
        }
        for rec in result.recommendations:
            cap = _ACTION_CONFIDENCE_CAPS.get(rec.action)
            if cap is not None and rec.confidence > cap:
                logger.info(
                    "Clamped %s %s confidence %.2f -> %.2f",
                    rec.ticker,
                    rec.action,
                    rec.confidence,
                    cap,
                )
                rec.confidence = cap

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

                ta_dict, fmp_dict_cal, regime_dict_cal = _build_ml_dicts(
                    ta_snapshots, fmp_map, regime
                )

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
                    reflection_metrics=reflection_metrics,
                )
        except Exception as exc:
            logger.exception(" Confidence calibration failed, using raw confidence")
            result.stage_errors.append(
                StageError(stage="calibration", error=str(exc), type=type(exc).__name__)
            )

    # ML gate + shadow predictions (Phase 7.5)
    if result.recommendations:
        ta_dict_ml, fmp_dict_ml, regime_dict_ml = _build_ml_dicts(ta_snapshots, fmp_map, regime)

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
            cost_tracker,
        )

        for rec in result.recommendations:
            blend_confidence_with_ml(rec)

        # Re-apply confidence floor after ML blend — track consensus overrides ML crush
        for rec in result.recommendations:
            if rec.action in ("BUY", "SHORT", "WATCH"):
                ag = rec.track_agreement.agreement_score if rec.track_agreement else 0.0
                if ag >= 0.8 and rec.confidence < 0.55:
                    logger.info(
                        "Post-ML floor 0.55 for %s (agreement=%.2f, was %.2f)",
                        rec.ticker,
                        ag,
                        rec.confidence,
                    )
                    rec.confidence = 0.55
                elif ag >= 0.5 and rec.confidence < 0.45:
                    logger.info(
                        "Post-ML floor 0.45 for %s (agreement=%.2f, was %.2f)",
                        rec.ticker,
                        ag,
                        rec.confidence,
                    )
                    rec.confidence = 0.45

        # Re-apply regime-aware signal strength after all confidence modifications
        from services.confidence_calibration import _classify_signal_strength

        for rec in result.recommendations:
            rec.signal_strength = _classify_signal_strength(rec.confidence, regime_context)

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

    # Stamp entry_valid_window from strategy half-life if GPT left it empty
    half_life = config.signal_half_life_hours
    for rec in result.recommendations:
        if not rec.entry_valid_window and rec.action in ("BUY", "SHORT", "WATCH"):
            if half_life <= 4:
                rec.entry_valid_window = f"{half_life} hours"
            elif half_life <= 48:
                days = half_life / 24
                rec.entry_valid_window = f"{days:.0f}-{days + 1:.0f} trading days"
            else:
                days = half_life / 24
                rec.entry_valid_window = f"{days:.0f} trading days"

    # Expected value calculation — uses win_probability when available, falls back to confidence
    for rec in result.recommendations:
        if (
            rec.action in ("BUY", "SHORT")
            and rec.risk_reward_ratio is not None
            and rec.risk_reward_ratio > 0
        ):
            prob = rec.win_probability if rec.win_probability is not None else rec.confidence
            ev = prob * rec.risk_reward_ratio - (1.0 - prob)
            rec.expected_value = round(ev, 4)
            if ev > 0.3:
                rec.key_factors.append(f"Positive expected value: {ev:.2f}")
            elif ev < 0:
                rec.warnings.append(f"Negative expected value: {ev:.2f}")

    # Save recommendations after all modifications (risk validation, ML gate)
    if result.recommendations:
        try:
            await _save_recommendations(run_id, result.recommendations, user_id)
        except Exception:
            logger.exception(" Failed to save recommendations for run %s", run_id)
            result.stage_errors.append(
                StageError(stage="save_recommendations", error="DB save failed")
            )

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
                    is_crypto=config.fmp_screener.is_crypto if config.fmp_screener else False,
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
        cost_tracker,
    )

    # Schedule paper tracking (fire-and-forget)
    if result.recommendations:
        rec_dicts = [r.model_dump(mode="json") for r in result.recommendations]
        _paper_task = asyncio.create_task(schedule_paper_tracking(run_id, rec_dicts, user_id))  # noqa: RUF006 — fire-and-forget; ref stored to prevent GC

    return await _finalize(run_id, result, start, client, regime_context, cost_tracker)


async def _finalize(
    run_id: str,
    result: PipelineResult,
    start: float,
    client: Any,
    regime_context: str,
    cost_tracker: PipelineCostTracker | None = None,
) -> PipelineResult:
    """Finalize pipeline run: timing, prompt versions, cost, DB update.

    Args:
        run_id: Pipeline run UUID.
        result: The PipelineResult being built.
        start: perf_counter value from pipeline start.
        client: Supabase client.
        regime_context: Unused, kept for signature consistency.
        cost_tracker: Accumulated LLM cost data for this run.

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

    if cost_tracker and cost_tracker.entries:
        result.meta["cost"] = cost_tracker.summary()

    has_data = (
        result.screening
        or result.sentiment_analyses
        or result.chart_analyses
        or result.recommendations
    )
    status = "completed" if has_data else ("partial" if result.stage_errors else "failed")

    update_fields: dict[str, Any] = {
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
    if result.meta:
        update_fields["meta"] = json.dumps(result.meta)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            await client.table("pipeline_runs").update(update_fields).eq("id", run_id).execute()
            break
        except APIError as exc:
            if (
                exc.code in ("PGRST204", "42703")
                and exc.message
                and "meta" in exc.message
                and "meta" in update_fields
            ):
                logger.warning(
                    "pipeline_runs.meta column missing; apply "
                    "database/migrations/023_pipeline_runs_meta.sql. Finalizing without meta."
                )
                update_fields.pop("meta", None)
                continue
            is_transient = str(exc.code) in ("504", "502", "503") or (
                exc.message and "timeout" in exc.message.lower()
            )
            if is_transient and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                logger.warning(
                    "Transient DB error finalizing run %s (attempt %d/%d), retrying in %ds: %s",
                    run_id,
                    attempt + 1,
                    max_retries,
                    wait,
                    exc,
                )
                await asyncio.sleep(wait)
                continue
            raise

    clear_run_symbol_cache(run_id)
    return result


_STAGE_OUTPUT_INSERT_CHUNK = 75


def _stage_output_row(run_id: str, metadata: dict) -> dict:
    """Build a ``stage_outputs`` row dict from stage metadata."""
    row: dict = {
        "id": uuid.uuid4().hex,
        "run_id": run_id,
        "stage": metadata.get("stage", "perplexity"),
        "ticker": metadata.get("ticker"),
        "prompt_text": metadata.get("prompt_text", ""),
        "raw_response": metadata.get("raw_response", ""),
        "model_used": metadata.get("model") or metadata.get("model_used", ""),
        "duration_ms": metadata.get("duration_ms", 0),
        "status": metadata.get("status", "unknown"),
        "retry_count": metadata.get("retry_count", 0),
        "created_at": datetime.now(tz=UTC).isoformat(),
    }
    if metadata.get("error"):
        row["parsed_output"] = metadata["error"]
    elif metadata.get("raw_response"):
        row["parsed_output"] = metadata["raw_response"]
    return row


async def _save_stage_outputs_batch(run_id: str, metadatas: list[dict]) -> None:
    """Persist multiple stage output rows in chunked inserts."""
    if not metadatas:
        return

    client = await get_db()
    rows = [_stage_output_row(run_id, m) for m in metadatas]
    for i in range(0, len(rows), _STAGE_OUTPUT_INSERT_CHUNK):
        chunk = rows[i : i + _STAGE_OUTPUT_INSERT_CHUNK]
        await client.table("stage_outputs").insert(chunk).execute()


async def _save_stage_output(
    run_id: str,
    metadata: dict,
    cost_tracker: PipelineCostTracker | None = None,
) -> None:
    """Persist raw stage output to the stage_outputs table."""
    if not metadata:
        return

    if cost_tracker and should_estimate_cost_from_metadata(metadata):
        from pipeline.token_budget import count_tokens

        model = (metadata.get("model") or metadata.get("model_used") or "").strip()
        input_tokens = count_tokens(metadata.get("prompt_text", ""))
        output_tokens = count_tokens(metadata.get("raw_response", ""))
        cost_tracker.record(
            stage=metadata.get("stage", "unknown"),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    await _save_stage_outputs_batch(run_id, [metadata])


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

    async def _update_one(ca: ChartAnalysis, row_id: str) -> None:
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

    tasks = [
        _update_one(ca, row_map[key])
        for ca in analyses_with_paths
        if (key := (ca.ticker, ca.timeframe)) in row_map
    ]
    if tasks:
        await asyncio.gather(*tasks)


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
            "confidence_label": rec.confidence_label,
            "raw_gpt_confidence": rec.raw_gpt_confidence,
            "raw_gpt_position_size_pct": rec.raw_gpt_position_size_pct,
            "ml_probability": rec.ml_probability,
            "ml_size_multiplier": rec.ml_size_multiplier,
            "ml_blocked": rec.ml_blocked,
            "ml_model_version": rec.ml_model_version,
            "ml_conformal_set": json.dumps(rec.ml_conformal_set) if rec.ml_conformal_set else None,
            "pre_gpt_ml_probability": rec.pre_gpt_ml_probability,
            "pre_gpt_ml_direction": rec.pre_gpt_ml_direction,
            "confidence_adjustment": rec.confidence_adjustment or "",
            "track_agreement": rec.track_agreement.model_dump_json()
            if rec.track_agreement
            else None,
            "expected_value": rec.expected_value,
            "win_probability": rec.win_probability,
            "setup_quality_score": rec.setup_quality_score,
            "llm_conviction": rec.llm_conviction,
            "prior_base_rate": rec.prior_base_rate,
            "confidence_v2": rec.confidence_v2,
            "setup_type": rec.setup_type,
            "confidence_drivers": json.dumps(rec.confidence_drivers)
            if rec.confidence_drivers
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


def _build_track_conflicts(
    sentiments: list[SentimentAnalysis],
    charts: list[ChartAnalysis],
    tickers: list[str],
) -> str:
    """Build a per-ticker directional conflict summary between Gemini and Claude.

    Compares Gemini's sentiment direction to Claude's technical direction for
    each ticker. Only flags meaningful disagreements (one bullish, other bearish).

    Args:
        sentiments: Gemini sentiment analyses.
        charts: Claude chart analyses.
        tickers: Tickers to check for conflicts.

    Returns:
        Formatted conflict summary text, or empty string if no conflicts.
    """
    sent_map = {s.ticker: s for s in sentiments}
    chart_map: dict[str, ChartAnalysis] = {}
    for c in charts:
        if c.ticker not in chart_map:
            chart_map[c.ticker] = c

    _BEARISH = frozenset({"bearish", "strongly_bearish"})
    _BULLISH = frozenset({"bullish", "strongly_bullish"})

    conflicts: list[str] = []
    for ticker in tickers:
        sa = sent_map.get(ticker)
        ca = chart_map.get(ticker)
        if not sa or not ca:
            continue

        sent_dir = sa.sentiment_label
        tech_dir = ca.trend_direction

        gemini_bearish = sent_dir in _BEARISH
        gemini_bullish = sent_dir in _BULLISH
        claude_bearish = tech_dir == "bearish"
        claude_bullish = tech_dir == "bullish"

        if gemini_bearish and claude_bullish:
            patterns = ", ".join(ca.patterns_detected[:3]) if ca.patterns_detected else ca.summary
            conflicts.append(
                f"- CONFLICT {ticker}: Gemini sentiment is {sent_dir} "
                f"(score {sa.sentiment_score:+.2f}) while Claude chart is bullish "
                f"({patterns}). The judge must explicitly resolve this conflict."
            )
        elif gemini_bullish and claude_bearish:
            patterns = ", ".join(ca.patterns_detected[:3]) if ca.patterns_detected else ca.summary
            conflicts.append(
                f"- CONFLICT {ticker}: Gemini sentiment is {sent_dir} "
                f"(score {sa.sentiment_score:+.2f}) while Claude chart is bearish "
                f"({patterns}). The judge must explicitly resolve this conflict."
            )

    return "\n".join(conflicts)


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


def _derive_perplexity_direction(
    screening: ScreeningResult | None,
    ticker: str,
) -> Literal["bullish", "bearish", "neutral"]:
    """Derive Perplexity's directional lean from fundamental data heuristics.

    Uses key_highlights vs risk_factors count and revenue growth sign.
    """
    if not screening:
        return "neutral"

    fd = None
    for t in screening.tickers:
        if t.ticker == ticker:
            fd = t
            break
    if fd is None:
        return "neutral"

    highlights = len(fd.key_highlights)
    risks = len(fd.risk_factors)

    revenue_positive = False
    if fd.revenue_growth:
        try:
            cleaned = fd.revenue_growth.replace("%", "").replace("+", "").strip()
            revenue_positive = float(cleaned) > 0
        except ValueError, AttributeError:
            pass

    if highlights > risks and revenue_positive:
        return "bullish"
    if risks > highlights:
        return "bearish"
    if highlights > risks:
        return "bullish"

    return "neutral"


def _compute_track_agreement(
    rec: Recommendation,
    sentiments: list[SentimentAnalysis],
    charts: list[ChartAnalysis],
    screening: ScreeningResult | None = None,
) -> TrackAgreement:
    """Compute true 3-track agreement: Perplexity + Gemini + Claude.

    All three directions are derived deterministically from upstream data.
    GPT's action is NOT one of the tracks — it is the consumer of agreement.

    Args:
        rec: The GPT recommendation for a single ticker.
        sentiments: All Gemini sentiment analyses from the pipeline run.
        charts: All Claude chart analyses from the pipeline run.
        screening: Perplexity screening result (may be None).

    Returns:
        Populated TrackAgreement with directions, score, and conflict details.
    """
    perplexity_dir = _derive_perplexity_direction(screening, rec.ticker)

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

    gpt_dir: Literal["bullish", "bearish", "neutral"]
    if rec.action == RecommendationAction.BUY:
        gpt_dir = "bullish"
    elif rec.action == RecommendationAction.SHORT:
        gpt_dir = "bearish"
    else:
        gpt_dir = "neutral"

    if gpt_dir == "neutral":
        return TrackAgreement(
            perplexity_direction=perplexity_dir,
            gemini_direction=gemini_dir,
            claude_direction=claude_dir,
            agreement_score=0.5,
        )

    aligned: list[str] = []
    dissenting: list[str] = []
    track_dirs = {
        "perplexity": perplexity_dir,
        "gemini": gemini_dir,
        "claude": claude_dir,
    }
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
        perplexity_direction=perplexity_dir,
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
