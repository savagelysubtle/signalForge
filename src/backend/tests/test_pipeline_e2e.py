"""End-to-end pipeline stage test.

Calls each LLM stage in sequence with a real ticker to verify
API keys, model names, and response parsing all work. Requires
live API keys in .env — skips automatically if keys are missing.

Usage:
    cd src/backend
    uv run --python 3.14 pytest tests/test_pipeline_e2e.py -v -s

    # Run a single stage:
    uv run --python 3.14 pytest tests/test_pipeline_e2e.py -v -s -k perplexity
"""

from __future__ import annotations

import time
import uuid

import pytest

from config import settings  # noqa: F401  — triggers .env load
from services.keyring_service import get_api_key, load_env

load_env()

TICKER = "AAPL"

_has_key = {
    "perplexity": bool(get_api_key("perplexity")),
    "google": bool(get_api_key("google")),
    "anthropic": bool(get_api_key("anthropic")),
    "openai": bool(get_api_key("openai")),
    "chartimg": bool(get_api_key("chartimg")),
}

needs_perplexity = pytest.mark.skipif(not _has_key["perplexity"], reason="PERPLEXITY_API_KEY unset")
needs_google = pytest.mark.skipif(not _has_key["google"], reason="GOOGLE_API_KEY unset")
needs_anthropic = pytest.mark.skipif(not _has_key["anthropic"], reason="ANTHROPIC_API_KEY unset")
needs_openai = pytest.mark.skipif(not _has_key["openai"], reason="OPENAI_API_KEY unset")
needs_chartimg = pytest.mark.skipif(not _has_key["chartimg"], reason="CHARTIMG_API_KEY unset")

# Cross-stage state so later stages can consume earlier output.
_stage_results: dict = {}


# ---------------------------------------------------------------------------
# Stage 1 — Perplexity
# ---------------------------------------------------------------------------


@needs_perplexity
@pytest.mark.asyncio
async def test_stage1_perplexity_analysis():
    """Perplexity analysis mode: research a known ticker."""
    from pipeline.stages.perplexity import run_analysis

    t0 = time.perf_counter()
    result, meta = await run_analysis([TICKER])
    elapsed = time.perf_counter() - t0

    assert meta["status"] == "success", f"Perplexity failed: {meta.get('error')}"
    assert result is not None
    assert len(result.tickers) >= 1
    assert any(TICKER in t.ticker for t in result.tickers)
    assert elapsed < 120, f"Perplexity took {elapsed:.0f}s (>120s timeout)"

    _stage_results["screening"] = result
    print(f"\n  Perplexity OK: {[t.ticker for t in result.tickers]} in {elapsed:.1f}s")


# ---------------------------------------------------------------------------
# Stage 2 — Gemini
# ---------------------------------------------------------------------------


@needs_google
@pytest.mark.asyncio
async def test_stage2_gemini_sentiment():
    """Gemini sentiment analysis for a single ticker."""
    from pipeline.schemas import StrategyConfig
    from pipeline.stages.gemini import run_sentiment

    config = StrategyConfig(id="e2e", name="E2E Test", screening_prompt="")
    t0 = time.perf_counter()
    results, meta_list = await run_sentiment([TICKER], config=config)
    elapsed = time.perf_counter() - t0

    assert results is not None and len(results) >= 1, (
        f"Gemini returned no results. Meta: {[m.get('status') for m in meta_list]}"
    )
    sa = results[0]
    assert sa.ticker == TICKER
    assert sa.sentiment_label in ("bullish", "bearish", "neutral", "mixed")
    assert elapsed < 120, f"Gemini took {elapsed:.0f}s (>120s timeout)"

    _stage_results["sentiments"] = results
    print(f"\n  Gemini OK: {sa.ticker} sentiment={sa.sentiment_label} in {elapsed:.1f}s")


# ---------------------------------------------------------------------------
# Stage 3 — Claude
# ---------------------------------------------------------------------------


@needs_anthropic
@needs_chartimg
@pytest.mark.asyncio
async def test_stage3_claude_chart_analysis():
    """Claude chart analysis with real chart image fetch."""
    from pipeline.schemas import StrategyConfig
    from pipeline.stages.claude import run_chart_analysis

    config = StrategyConfig(id="e2e", name="E2E Test", screening_prompt="")
    run_id = uuid.uuid4().hex

    t0 = time.perf_counter()
    results, meta_list = await run_chart_analysis(
        [TICKER],
        config=config,
        ta_snapshots=[],
        run_id=run_id,
    )
    elapsed = time.perf_counter() - t0

    assert results is not None and len(results) >= 1, (
        f"Claude returned no results. Meta: {[m.get('status') for m in meta_list]}"
    )
    ca = results[0]
    assert ca.ticker == TICKER
    assert ca.trend_direction in ("bullish", "bearish", "neutral", "transitioning")
    assert elapsed < 180, f"Claude took {elapsed:.0f}s (>180s timeout)"

    _stage_results["charts"] = results
    print(f"\n  Claude OK: {ca.ticker} trend={ca.trend_direction} in {elapsed:.1f}s")


# ---------------------------------------------------------------------------
# Stage 4 — GPT
# ---------------------------------------------------------------------------


@needs_openai
@pytest.mark.asyncio
async def test_stage4_gpt_debate():
    """GPT bull/bear/judge debate producing a recommendation."""
    from pipeline.schemas import StrategyConfig
    from pipeline.stages.gpt import run_debate

    config = StrategyConfig(
        id="e2e",
        name="E2E Test",
        screening_prompt="",
        enable_debate=True,
    )

    screening = _stage_results.get("screening")
    sentiments = _stage_results.get("sentiments", [])
    charts = _stage_results.get("charts", [])
    run_id = uuid.uuid4().hex

    t0 = time.perf_counter()
    recs, meta_list = await run_debate(
        [TICKER],
        screening,
        charts,
        sentiments,
        config,
        "",
        run_id,
    )
    elapsed = time.perf_counter() - t0

    assert recs is not None and len(recs) >= 1, (
        f"GPT returned no recs. Meta: {[m.get('status') for m in meta_list]}"
    )
    rec = recs[0]
    assert rec.ticker == TICKER
    valid_actions = ("BUY", "SHORT", "HOLD", "NO_TRADE", "WATCH")
    assert rec.action in valid_actions, f"Unexpected action: {rec.action}"
    assert 0 <= rec.confidence <= 100
    assert elapsed < 120, f"GPT took {elapsed:.0f}s (>120s timeout)"

    entry = f"${rec.entry_price:.2f}" if rec.entry_price else "N/A"
    rr = rec.risk_reward_ratio or "N/A"
    print(
        f"\n  GPT OK: {rec.ticker} {rec.action} @ {entry} "
        f"conf={rec.confidence}% R:R={rr} in {elapsed:.1f}s"
    )
