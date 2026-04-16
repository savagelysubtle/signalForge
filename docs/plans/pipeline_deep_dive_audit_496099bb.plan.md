---
name: Pipeline Deep Dive Audit
overview:
  Comprehensive audit of the v2 pipeline revealing 3 critical bugs, 5 data flow
  gaps, and 4 calibration issues. The pipeline architecture is sound but Claude
  Vision is failing 77% of the time, confidence calibration is ignoring GPT
  entirely, and several data enrichment paths are disconnected in v2.
todos:
  - id: remove-v1-pipeline
    content:
      Remove all v1 pipeline code (~1500 lines) — orchestrator v1 body,
      risk_screener.py, v1 stage functions in claude.py/gpt.py, v1 prompts in
      gpt_debate.py/claude_chart.py, pipeline_version field. Rename v2 functions
      to drop _v2 suffix. Resolves 1C automatically.
    status: completed
  - id: claude-chart-fix
    content:
      Fix Claude Vision 77% failure rate — investigate Chart-Img ticker
      formatting for TSX symbols
    status: completed
  - id: gemini-enrichment
    content:
      Pass FMP context and Perplexity highlights to v2 Gemini (currently all
      None)
    status: completed
  - id: confidence-blend
    content:
      Blend GPT confidence with calibrated score instead of complete replacement
    status: completed
  - id: dedup-penalties
    content:
      De-duplicate ADX triple-penalty and risk disapproval double-penalty in
      calibration
    status: completed
  - id: meta-crash-fix
    content:
      Fix result.meta crash in scanner ticker merge (PipelineResult has no meta
      field)
    status: completed
  - id: gemini-confidence-fwd
    content: Forward Gemini confidence score to GPT formatter
    status: completed
  - id: scanner-ticker-order
    content:
      Fix scanner tickers being first cut by max_tickers (prepend instead of
      append)
    status: completed
  - id: track-agreement
    content: Wire up track agreement population in orchestrator
    status: completed
  - id: gpt-judge-temp
    content: Lower GPT judge temperature from 0.7 to 0.3-0.5
    status: completed
  - id: ml-gate-parallel
    content: Parallelize ML gate calls with asyncio.gather
    status: completed
isProject: false
---

# Pipeline Deep Dive Audit — Findings and Fixes

## Current Pipeline Health (Real Data, Last 7 Days)

- **139 recommendations** across 29 runs
- **Only 11 actionable** (7 BUY, 4 SHORT) = 7.9% actionable rate
- **Claude Vision: 23.2% success** (730 out of 950 calls failed with
  `chart_fetch_error`)
- **Gemini: 75% success** (37 API errors, 3 validation failures)
- **GPT: 100% success**, Perplexity: 95.8% success
- **Track agreement: not populated** in production
- **risk_screener: 100% failure** (13/13 errors, v1-only stage still being
  called)

## Priority 0 — V1 Pipeline Removal (~1,500 lines of dead code)

V1 is fully deprecated. Removing it first simplifies all subsequent changes and
resolves the risk_screener 100% failure (1C) automatically.

**Files to modify:**

- `[orchestrator.py](src/backend/pipeline/orchestrator.py)`: Remove lines
  229-968 (entire v1 body), v1 imports (lines 56, 58, 68), v1 dispatch branch
  (lines 211-214), v1 timeout entry (line 92), v1 prompt hash calls (lines
  939-941)
- `[stages/risk_screener.py](src/backend/pipeline/stages/risk_screener.py)`:
  DELETE entire file (182 lines, v1-only)
- `[stages/claude.py](src/backend/pipeline/stages/claude.py)`: Remove
  `_analyze_ticker` (L142-244) and `run_chart_analysis` (L247-366)
- `[stages/gpt.py](src/backend/pipeline/stages/gpt.py)`: Remove `run_debate`
  (L166-256), `_run_debate_phase` (L259-349), `_run_judge_phase` (L352-411)
- `[prompts/gpt_debate.py](src/backend/pipeline/prompts/gpt_debate.py)`: Remove
  v1 system prompts (L56-282), v1 builders (L793-1083), v1 hashes (L1400-1412)
- `[prompts/claude_chart.py](src/backend/pipeline/prompts/claude_chart.py)`:
  Remove v1 system prompt (L17-108), v1 builder (L111-216), v1 hash (L219-221)
- `[schemas.py](src/backend/pipeline/schemas.py)`: Remove `pipeline_version`
  field (L719-720)

**Post-removal rename** (drop `_v2` suffix since v2 is now the only version):

- `run_chart_analysis_v2` -> `run_chart_analysis`
- `run_debate_v2` -> `run_debate`
- `build_bull_prompt_v2` -> `build_bull_prompt` (and bear, judge, chart
  variants)
- `CHART_SYSTEM_PROMPT_V2` -> `CHART_SYSTEM_PROMPT` (and bull, bear, judge)
- All `_v2` hash functions -> drop suffix

**Keep** the `ChartAnalysis._coerce_string_confidence` validator for backward
compat with old DB records that stored v1 string confidences.

## Priority 1 — Critical Bugs (Highest Impact)

### 1A. Claude Vision 77% Failure Rate

The biggest quality issue. Claude is failing to analyze charts for most TSX
tickers due to Chart-Img fetch errors. This means GPT is making recommendations
**without chart analysis** for the majority of tickers.

**Root cause:** Likely TSX ticker formatting for Chart-Img v2 API. Need to
investigate `[services/chart_image.py](src/backend/services/chart_image.py)` for
symbol translation issues (e.g., `BTE.TO` vs `TSX:BTE`).

**Impact:** Fixing this alone recovers ~730 chart analyses and would
dramatically improve recommendation quality.

### 1B. `result.meta` Crash (Scanner Ticker Merge)

Line 1235 of `[orchestrator.py](src/backend/pipeline/orchestrator.py)`:

```python
result.meta["scanner_tickers_added"] = added
```

`PipelineResult` has no `meta` field. This crashes whenever the scanner tries to
add tickers to a pipeline run, meaning the scanner-merge feature is broken in
production.

**Fix:** Add `meta: dict[str, Any] = {}` to `PipelineResult` in
`[schemas.py](src/backend/pipeline/schemas.py)`, or use `result.stage_errors` to
log this info.

### ~~1C. risk_screener 100% Failure~~ — Resolved by P0 (v1 removal)

## Priority 2 — Data Flow Gaps (Signal Quality)

### 2A. v2 Gemini Gets No FMP Context or Perplexity Highlights

In v1, Gemini receives company identity, earnings dates, insider data, and
Perplexity's key highlights. In v2, ALL of this is set to `None`:

```python
# orchestrator.py line 1308-1313
sentiments_b, meta_b = await run_sentiment(
    ticker_symbols, config,
    ticker_news=None,       # Lost: Perplexity article URLs
    fmp_context=None,       # Lost: earnings, insider, company data
    ticker_highlights=None, # Lost: Perplexity catalyst highlights
    regime_context=regime_context,
)
```

Gemini's Google Search is untargeted without these inputs. The v2 "independent
tracks" philosophy went too far here — FMP data is factual grounding, not bias.

**Fix:** Pass `fmp_context=fmp_map` and `ticker_highlights` from Perplexity to
v2 Gemini. Keep `ticker_news=None` to preserve independence from Perplexity's
specific article choices.

### 2B. Gemini Confidence Not Forwarded to GPT

Gemini produces a `confidence` score (0.0-1.0) for its sentiment, but the GPT
prompt formatter (`_format_sentiment_data`) drops it. GPT cannot distinguish
between high-confidence and low-confidence sentiment signals.

### 2C. FMP Candidates Not Used as Fallback Ticker Source

When Perplexity fails in discovery mode and there are no manual tickers, the
pipeline returns empty — even if FMP successfully screened 50 candidates. The
`fmp_map` is used for enrichment only, never as a fallback ticker source.

### 2D. Scanner Tickers First to Be Cut

Scanner-discovered tickers are appended at the END of the ticker list (line
1233), then `max_tickers` caps from the FRONT. Scanner tickers (pre-confirmed by
rule scoring + ML) are the first to be dropped.

**Fix:** Prepend scanner tickers or interleave them with Perplexity tickers.

### 2E. Sector Consensus Ignores FMP Data

Sector info for consensus building comes solely from Perplexity's
`screening.tickers[].sector`, which is often empty. FMP's `fmp_map` HAS sector
data but isn't used as a fallback.

## Priority 3 — Confidence Calibration Issues

### 3A. Calibration Completely Replaces GPT Confidence

The deterministic calibration engine in
`[services/confidence_calibration.py](src/backend/services/confidence_calibration.py)`
**ignores** GPT's confidence entirely. It builds a score from
TA/agreement/history sub-components and replaces the original. A GPT confidence
of 0.85 based on strong fundamental catalysts gets thrown away and replaced with
0.45 if the TA sub-components are middling.

**Real data confirms this:** `raw_gpt_confidence` is not being stored (all nulls
in DB), so the calibration's replacement is invisible.

**Fix:** Blend GPT and calibrated confidence (e.g.,
`0.4 * gpt_confidence + 0.6 * calibrated`) rather than complete replacement.
This preserves qualitative signal from GPT while still applying TA-based reality
checks.

### 3B. ADX Triple-Penalized

ADX < 20 triggers penalties in THREE places:

1. `risk_post_filter`: -0.15 to risk_score
2. `calibrate_recommendation._score_trend_alignment()`: -0.20
3. `calibrate_recommendation._score_technical_strength()`: lower base score

A ranging market ticker gets up to -0.50 from ADX alone across these three
systems.

### 3C. Risk Disapproval Double-Penalized

Risk flags are:

1. Shown to GPT (who already factors them into confidence)
2. Re-penalized by `calibrate_recommendation` (up to -0.15)

GPT has already lowered its confidence for risky tickers, then calibration
penalizes again.

### 3D. Track Agreement Not Populated

The schema has `track_agreement_score`, `tracks_aligned`, `tracks_dissenting`
fields, but they're all NULL in production. The multi-model consensus system
isn't being written.

## Priority 4 — Performance and Robustness

### 4A. ML Gate Sequential Bottleneck

ML gate runs in a sequential
`for rec in recommendations: await run_ml_gate(...)` loop. These calls are
independent and could be parallelized with `asyncio.gather`.

### 4B. Missing Timeouts

No timeout on: ML gate loop, confidence calibration, ML shadow,
`_save_stage_output` calls. Any of these can block indefinitely.

### 4C. GPT Judge Temperature Too High

GPT bull/bear/judge all use temperature 0.7. The judge (analytical, precise)
would benefit from 0.3-0.5. Bull/bear benefit from 0.7 for creative
argumentation.

### 4D. Annotated Charts Shared Timeout

All annotations share a single 60s timeout. One slow Chart-Img response kills
all concurrent annotations.

## What's Working Well (Don't Touch)

- Pipeline degradation pattern — recommendations still flow when stages fail
- Perplexity Agent API integration — 95.8% success, well-structured prompts
- GPT debate system — 100% success, excellent prompt engineering
- v2 Claude prompt design — numerical data as PRIMARY, chart as CONFIRMATION
- Risk validator — advisory-only, well-calibrated
- ML gate Kelly criterion approach — principled, conservative
- Regime classification — fast, reliable, properly injected into all stages

## Recommended Fix Order

Fixes are ordered by **impact on recommendation quality** per unit of effort:

1. **P0** — Remove v1 pipeline (~1,500 lines). Resolves 1C, simplifies all later
   changes.
2. **1A** — Fix Claude chart fetching (recovers 77% of lost chart analyses)
3. **2A** — Pass FMP context + Perplexity highlights to Gemini
4. **3A** — Blend GPT confidence instead of replacing it
5. **3B/3C** — De-duplicate ADX and risk penalties
6. **1B** — Fix `result.meta` crash
7. **2B** — Forward Gemini confidence to GPT
8. **2D** — Fix scanner ticker ordering
9. **3D** — Wire up track agreement population
10. **4C** — Lower GPT judge temperature
11. **4A** — Parallelize ML gate

Items 2C (FMP fallback), 2E (sector fallback), 4B (timeouts), 4D (annotate
timeout) are lower priority but worth addressing.
