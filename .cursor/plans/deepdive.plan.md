---
name: ''
overview: ''
todos: []
isProject: false
---

# SignalForge Pipeline: End-to-End Deep Dive Review

> Generated 2026-04-08 from a full codebase audit of every pipeline stage,
> service, prompt, schema, and frontend component. Five parallel exploration
> agents read every line of the orchestrator, all LLM stages, all prompts, all
> services/API routes, and all frontend consumers.

---

## Table of Contents

1. [How the Pipeline Actually Works](#how-the-pipeline-actually-works)
2. [Where We Do Well](#where-we-do-well)
3. [Where We Need Improvement](#where-we-need-improvement)
4. [Bugs Found](#bugs-found)
5. [Prompt System Assessment](#prompt-system-assessment)
6. [Frontend Gaps](#frontend-gaps)
7. [Stage-by-Stage Analysis](#stage-by-stage-analysis)
8. [Confidence Score Flow](#confidence-score-flow)
9. [Cross-Cutting Concerns](#cross-cutting-concerns)
10. [Top Improvements (Prioritized)](#top-improvements-prioritized)
11. [The Big Picture](#the-big-picture)

---

## How the Pipeline Actually Works

```
+-------------------------------------------------------------------------+
| Stage 0 + 0.5 (PARALLEL)                                               |
|   FMP Pre-Screening -----------+                                        |
|   Regime Classification -------+-> Re-score FMP with regime weights     |
+-------------------------------------------------------------------------+
| Stage 1: Perplexity -> ticker list + fundamentals + highlights          |
|   -> pre_filter_tickers() drops obvious duds (market cap, volume, price)|
+-------------------------------------------------------------------------+
| Stage 1.5 (PARALLEL): Numerical TA || Live Quotes                       |
+-------------------------------------------------------------------------+
| Stage 2+3 (PARALLEL TRACKS -- independent, no cross-contamination):     |
|   Track B: Gemini sentiment (FMP + Perplexity highlights, NO articles)  |
|   Track C: Claude vision (numerical TA + charts + live quotes, NO sent) |
+-------------------------------------------------------------------------+
| Risk Post-Filter: enriches with risk_flags + risk_score (no removal)    |
+-------------------------------------------------------------------------+
| Stage 4: GPT Bull/Bear/Judge debate (convergence -- sees everything)    |
|   -> Reflection context injected for self-learning                      |
|   -> Live quotes re-fetched for freshest price                          |
+-------------------------------------------------------------------------+
| Post-GPT Processing:                                                    |
|   1. Track agreement (Gemini vs Claude vs GPT consensus)                |
|   2. Risk validation                                                    |
|   3. Confidence calibration (40% GPT + 60% deterministic TA)            |
|   4. ML gate + shadow (optional, needs trained model)                   |
+-------------------------------------------------------------------------+
| Stage 4.5: Annotated charts (entry/stop/target lines on chart images)   |
+-------------------------------------------------------------------------+
```

### Pipeline Modes

| Mode        | Trigger                          | Behavior                             |
| ----------- | -------------------------------- | ------------------------------------ |
| `discovery` | strategy_id only, no tickers     | Screen market for new opportunities  |
| `analysis`  | manual_tickers only, no strategy | Research specific tickers            |
| `combined`  | strategy_id + manual_tickers     | Both screening and targeted research |
| `prompt`    | user_prompt free-form text       | Natural language drives screening    |

### Concurrency Model

All concurrency uses asyncio with module-level semaphores:

| Stage      | Semaphore | Model            |
| ---------- | --------- | ---------------- |
| Regime     | 3         | perplexity/sonar |
| Perplexity | 3         | openai/gpt-5.4   |
| Gemini     | 5         | gemini-2.5-pro   |
| Claude     | 3         | claude-opus-4-6  |
| GPT        | 3         | gpt-5.4          |

Semaphores are module-level globals shared across all concurrent pipeline runs.

### Stage Timeouts

| Stage      | Timeout |
| ---------- | ------- |
| FMP        | 90s     |
| Perplexity | 180s    |
| Gemini     | 120s    |
| Claude     | 360s    |
| GPT        | 360s    |
| Annotate   | 60s     |

---

## Where We Do Well

### 1. Parallel Architecture is Genuinely Smart

The v2 pipeline runs Gemini and Claude as **independent parallel tracks** that
never see each other's output. This is a real architectural win -- it means each
model forms its opinion independently, and disagreements between them are
signal, not noise. The `TrackAgreement` computation at the end is a meaningful
consensus metric. Claude deliberately does NOT receive Gemini sentiment to avoid
anchoring bias.

### 2. Degraded Pipeline is Production-Grade

Every stage has proper try/except, `StageError` tracking, and the pipeline
genuinely continues when individual stages fail. The GPT judge prompt explicitly
receives a `DATA AVAILABILITY` section so it knows what's missing. This is
better than most production ML pipelines.

### 3. Validation + Retry is Well-Designed

The `with_validation_retry` decorator is elegant -- it wraps any async LLM call
with JSON extraction, Pydantic validation, and retry with error context
injection (giving the LLM the full JSON schema to self-correct). The circuit
breaker integration prevents wasting API calls on down providers.

- `extract_json` handles real-world LLM quirks: strips `<think>` reasoning
  tokens, handles markdown code fences, finds JSON in surrounding prose
- `_strip_control_chars` removes ASCII control characters LLMs sometimes embed
- Retry count is tracked on validated objects for downstream observability

### 4. Confidence Calibration is Multi-Layered

Three layers of confidence adjustment:

- **Raw GPT confidence** (preserved for comparison)
- **Deterministic calibration** (40% GPT + 60% TA-based with specific penalty
  rules across 5 weighted sub-components)
- **ML gate** (independent model that can block or resize positions)

The confidence breakdown with explicit `penalties_applied` list is excellent for
explainability.

### 5. Strategy System is Comprehensive

Strategies control every stage -- FMP screening parameters, Perplexity prompt
style, chart timeframes/indicators, risk params, debate toggle. 14 richly
defined templates spanning swing, intraday, mean reversion, value, event, and
crypto categories. Each template has highly specific, well-differentiated
parameters.

### 6. Self-Learning Loop Exists End-to-End

Decisions -> outcomes -> reflections -> injection into future GPT judge prompts.
FinMem-style two-layer memory (short-term 14-day + long-term all-time) with
pattern accuracy, sector win rates, timeframe alignment, confidence calibration
buckets, failure mode classification, and GPT-4o-mini strategic advice.

### 7. Observability is Excellent

Every stage produces metadata persisted to `stage_outputs` table: stage name,
ticker, model, prompt_hash, prompt_text, raw_response, duration_ms, status,
retry_count, error. You can reconstruct exactly what happened in any pipeline
run. Prompt version hashes are stored per-run for audit.

### 8. Prompt Engineering Has Strong Foundations

- Anti-hallucination rules (Perplexity explicitly says "set that field to null")
- Confidence calibration bands in every prompt (0.85+ overwhelming, 0.70-0.85
  strong, etc.)
- Track independence framing ("independent research reports that did NOT
  communicate")
- Structured decision framework (3/3 agree -> proceed, all disagree -> NO_TRADE)
- Ground truth injection (regime classifier gets verified FMP VIX/sector data)
- ATR-based stop-loss methodology with structural level cross-check
- Entry validity window guidance per timeframe

### 9. Numerical TA as Claude's Primary Input

The `format_ta_for_prompt()` function (298 lines) converts structured technical
data into rich human-readable text. Claude receives this as PRIMARY input with
the chart image as CONFIRMATION. This avoids "pixel-guessing" and makes analysis
reproducible.

---

## Where We Need Improvement

### CRITICAL: Confidence Scores are Still Mostly Vibes

**The Problem:** The entire confidence system ultimately rests on GPT's
self-assessed confidence number (a float from 0-1), and then the calibration
adjusts it with heuristic penalties. Nobody has validated that these confidence
numbers actually predict outcomes.

**Specific issues:**

1. **The 40/60 blend is arbitrary.** `confidence_calibration.py:338` hardcodes
   `0.4 * gpt_confidence + 0.6 * calibrated`. Why 40/60? This should be learned
   from outcome data.
2. **Penalty magnitudes are guesses.** The penalties (-0.15 for stale EMA cross,
   -0.10 for RSI overbought, etc.) are starting points with no empirical
   validation. Line 11 says "Phase 6 feedback loop tunes over time" but there's
   no code that actually tunes them.
3. **No calibration curve.** You track `raw_gpt_confidence` vs `confidence` but
   there's no code that computes "when GPT says 70%, how often does the trade
   win?" This is the most basic calibration metric.
4. **The ConfidenceBreakdown components cap at arbitrary maximums**
   (track_agreement: 0.30, technical_strength: 0.20, trend_alignment: 0.20,
   historical_pattern: 0.20, regime_fit: 0.10).

**Fix:**

- Build a calibration curve from historical outcomes (data exists in
  `decisions` + `outcomes` tables)
- Use Platt scaling or isotonic regression on GPT confidence -> actual win rate
- Replace fixed blend weights and penalty magnitudes with learned values
- The ML training pipeline already has Venn-ABERS calibration -- bridge that to
  the live pipeline

### CRITICAL: Trade Recommendations Lack Temporal Precision

**The Problem:** The pipeline says "BUY AAPL at $190, stop at $185, target $200"
but doesn't tell you:

- **When** to enter (at market open? on a pullback to support? on a breakout?)
- **How long** the signal is valid (`entry_valid_window` exists but often empty)
- **Conditional entries** ("buy only if price holds above $188 for 30 minutes")
- **Scaling plan** ("enter 50% now, add 50% on pullback to $187")
- **Invalidation conditions** ("signal void if price drops below X before
  entry")

**Fix:**

- Add entry conditions to the GPT judge prompt (trigger type, scaling,
  invalidation)
- Make `entry_valid_window` mandatory with concrete time bounds
- Add invalidation conditions as a required field

### HIGH: Gemini and Claude Don't Challenge Each Other

**The Problem:** The parallel track design (good for independence) means
Gemini's bearish sentiment and Claude's bullish chart pattern never get directly
reconciled. GPT sees both, but the `TrackAgreement` is computed _after_ GPT's
recommendation, so it's diagnostic, not actionable -- GPT doesn't see its own
track agreement when making the decision.

**Fix:**

- Feed the track agreement computation (or raw directional disagreement) into
  GPT's judge prompt
- When tracks disagree strongly, flag it explicitly: "CONFLICT: Gemini sees
  bearish sentiment (-0.6) while Claude sees bullish chart (ascending triangle).
  The judge must explicitly resolve this conflict."

### HIGH: The Reflection System is Underutilized

**The Problem:**

1. Reflections are manual (user must click "Generate Reflection" with 5+
   outcomes)
2. No automated scheduling
3. The injection prompt is one-size-fits-all (not strategy-specific)
4. Pattern suppression is suggested but not enforced

**Fix:**

- Auto-generate reflections after every N outcomes
- Make reflections strategy-specific
- Implement pattern suppression -- if a pattern's win rate < threshold, Claude
  deprioritizes it
- Feed calibration bucket data back into confidence blend weights

### HIGH: No Backtesting or Paper Trading Mode

**The Problem:** No way to evaluate if the pipeline makes money. The only
feedback loop is manual.

**Fix:**

- Add paper trading mode (auto-track recommendation prices at T+1d, T+3d, T+5d)
- Build historical pipeline replay
- Add prompt version -> outcome correlation in Insights UI (data already stored)

### MEDIUM: Risk Management is Too Passive

The risk post-filter flags risks but doesn't adjust position sizing based on
them. The confidence calibration applies a tiny penalty
(`(1 - risk_score) * 0.07`), but a ticker with an Altman Z-score of 1.2
(distress zone) should probably get its position size halved.

**Fix:**

- Wire risk_score directly into position sizing
- Add hard blocks for extreme risk (Z-score < 1.0, Piotroski < 2)
- Scale position size inversely with risk: `position_pct *= risk_score`

### MEDIUM: No Token Budget Management

The GPT judge prompt can grow enormous with many tickers x full data from all
tracks. There's no token counting or truncation strategy. If the prompt exceeds
the model's context window, it fails silently or truncates.

### MEDIUM: No Cost Tracking

A single pipeline run can make 30+ LLM calls (multi-timeframe Claude x tickers,
plus bull/bear/judge per ticker). There's no per-run cost accounting.

### LOW-MEDIUM: Missing Tests Entirely

Zero test files across the entire codebase. For a pipeline that makes financial
recommendations, this is a significant risk. `validation.py` `extract_json` and
the confidence calibration logic are perfect candidates for unit tests.

---

## Bugs Found

### P0: Python 2 Exception Syntax (5 files)

```python
# WRONG (Python 2 syntax -- catches ValueError, binds it to name "TypeError"):
except json.JSONDecodeError, TypeError:

# CORRECT:
except (json.JSONDecodeError, TypeError):
```

**Affected files:**

- `services/reflection.py` lines 87, 655
- `services/trade_matcher.py` lines 374, 455
- `api/questrade.py` line 266
- `services/technical_analysis.py` line 845

Was noted in commit `b4fda13` but not fully resolved.

### P0: Analysis Mode Hardcoded Canadian Market Bias

`perplexity_analysis.py` line 18 hardcodes:

```python
ANALYSIS_SYSTEM_PROMPT = """\
You are a financial research analyst with a focus on the Canadian market
(TSX, TSXV). You will be given a list of ticker symbols...
```

Unlike discovery mode which dynamically adapts to the strategy's market
settings. Running analysis on US tickers still tells Perplexity to "prefer the
Canadian listing."

### P1: `config.is_crypto` Property Missing

`orchestrator.py` references `config.is_crypto` (lines 585, 962) but
`StrategyConfig` has no `is_crypto` field. The correct access is
`config.fmp_screener.is_crypto if config.fmp_screener else False`. This will
raise `AttributeError` for any pipeline run.

### P2: `live_quotes` Variable Scoping

At orchestrator line 740, `validate_risks` references `live_quotes`, but this
variable is only assigned inside the `try` block starting at line 679. If GPT
raises before `live_quotes` is assigned, `validate_risks` hits
`UnboundLocalError`.

### P2: `_update_annotated_paths` N+1 Updates

Issues individual UPDATE queries in a loop (one per chart analysis) instead of a
batch operation. Slow for large ticker lists.

---

## Prompt System Assessment

### Prompt Versioning

Each prompt module has two versioning layers:

1. **Manual `PROMPT_VERSION` string** (e.g., `"v16"`, `"v12"`) -- bumped by
   developers
2. **Automatic SHA-256 hash** via `prompt_hash()` -- computed from static system
   prompt, truncated to 8 hex chars, stored per-run in DB

**Note:** Hash only covers the static system prompt, NOT the dynamic user
prompt. Two runs with identical system prompts but different strategy configs
have the same hash.

### Strategy Parameter Usage Across Stages

| Parameter          | Perplexity Disc | Perplexity Anal | Gemini    | Claude    | GPT Bull/Bear | GPT Judge |
| ------------------ | --------------- | --------------- | --------- | --------- | ------------- | --------- |
| `screening_prompt` | YES             | no              | no        | no        | no            | no        |
| `ta_focus`         | YES             | no              | no        | YES       | no            | no        |
| `max_tickers`      | YES             | no              | no        | no        | no            | no        |
| `constraint_style` | YES             | no              | no        | no        | no            | no        |
| `fmp_screener.`    | YES             | no              | no        | no        | no            | no        |
| `news_recency`     | no              | no              | YES       | no        | no            | no        |
| `news_scope`       | no              | no              | YES       | no        | no            | no        |
| `chart_timeframe`  | no              | no              | no        | YES       | no            | no        |
| `chart_indicators` | no              | no              | no        | YES       | no            | no        |
| `trading_style`    | no              | YES             | no        | no        | YES           | YES       |
| `risk_params.`     | no              | no              | no        | YES       | no            | YES       |
| `enable_debate`    | no              | no              | no        | no        | controls run  | controls  |
| `**strategy_type`  | **NEVER**       | **NEVER**       | **NEVER** | **NEVER** | **NEVER**     | **NEVER** |
| `**description`    | **NEVER**       | **NEVER**       | **NEVER** | **NEVER** | **NEVER**     | **NEVER** |

### Prompt Weaknesses

1. `**description` field is never injected into any prompt. Every strategy
   template has a rich description that could provide valuable GPT context.
2. `**strategy_type` never influences any LLM prompt. It only affects the
   scanner and ML layers. The LLMs have no awareness of whether they're
   processing a "swing" vs "intraday" vs "mean_reversion" strategy.
3. **No few-shot examples in any prompt.** Gemini, Claude, and GPT would benefit
   from 1-2 examples of excellent outputs.
4. **Bull/Bear debate doesn't create structured disagreement.** Bull and Bear
   run independently -- they don't actually respond to each other's specific
   points.
5. **Duplicate JSON schema definitions.** Output schemas are defined as inline
   text in prompt strings AND as Pydantic models in `schemas.py`. No automated
   sync -- schema drift risk.
6. **Judge system prompt is ~270 lines.** Risk of cognitive overload for the
   LLM. Could be split into base + conditional sections.
7. **All model names hardcoded.** Prevents A/B testing models or using cheaper
   models for lower-priority strategies:

- `regime.py`: `"perplexity/sonar"`
- `perplexity.py`: `"openai/gpt-5.4"`
- `gemini.py`: `"gemini-2.5-pro"`
- `claude.py`: `"claude-opus-4-6"`
- `gpt.py`: `"gpt-5.4"`

---

## Frontend Gaps

### Data Available but Not Displayed

| Field                       | Where It Exists                    | Where It's Missing                             |
| --------------------------- | ---------------------------------- | ---------------------------------------------- |
| Current price               | `FundamentalData.price`            | OverviewTab never shows it                     |
| Gemini sentiment confidence | `SentimentAnalysis.confidence`     | SentimentTab never shows it                    |
| 52-week high/low            | `FundamentalData.week_52`          | Nowhere in UI                                  |
| Relative volume             | `FundamentalData.relative_volume`  | Nowhere in UI                                  |
| Stage errors (readable)     | `PipelineResult.stage_errors`      | Only in raw JSON tab                           |
| Screening summary           | `screening.screening_summary`      | Tooltip-only on mode badge                     |
| News URLs from Perplexity   | `FundamentalData.news_urls`        | Not rendered (sources shown but not clickable) |
| Daily price change %        | `FundamentalData.price_change_pct` | Nowhere in overview                            |
| FMP pre-screened list       | `screening.fmp_pre_screened`       | Only visible in raw JSON                       |
| Regime output               | `RegimeOutput` (backend)           | No TypeScript interface, no UI                 |

### UX Gaps

1. **No ticker prioritization on sidebar.** Cards show tickers in API return
   order with no confidence indicator, no sorting. Users must click through
   every ticker to find the best opportunities.
2. **No cross-ticker comparison view.** Results are strictly
   one-ticker-at-a-time. A summary table or comparison grid would speed
   decision-making.
3. **Chart analysis details collapsed by default.** Claude Vision's trend
   direction + bias hidden behind an accordion. Should default open or surface
   key fields outside the collapse.
4. **No "what changed since signal" indicator.** `price_at_signal` is shown but
   no current live price next to it for drift assessment.
5. **No alert system.** User must manually check for new recommendations.
6. **History view is minimal.** Shows run metadata but no outcome data. No link
   to Insights journal.
7. **Screening summary is tooltip-only.** Perplexity's reasoning about WHY these
   tickers were chosen deserves prominent display.

### State Management

`SearchScreen` and `ResultsScreen` each instantiate their own `usePipeline()`
hook independently. Progress state from search is lost during navigation. Known
issue.

### Type Alignment

Backend Pydantic models and frontend TypeScript interfaces are well-aligned. No
type mismatches detected. The `resolveConfidence()` helper in ChartTab correctly
handles both numeric and string ("high/medium/low") confidence formats.

---

## Stage-by-Stage Analysis

### Stage 0.5: Regime Classification (`regime.py`)

| Aspect          | Details                                                      |
| --------------- | ------------------------------------------------------------ |
| Model           | `perplexity/sonar`                                           |
| Output          | `RegimeOutput` (regime_type, vix_estimate, breadth, sectors) |
| Retries         | 1 (hardcoded)                                                |
| Circuit breaker | No (uses manual retry, not `with_validation_retry`)          |
| Semaphore       | 3                                                            |

**Strengths:** Ground truth injection, heartbeat cache fallback. **Weaknesses:**
No self-correction on retry (re-sends same prompt), validation diverges from
shared pattern.

### Stage 0.7: Numerical TA (`numerical_ta.py`)

| Aspect      | Details                              |
| ----------- | ------------------------------------ |
| Model       | None (pure Python)                   |
| Output      | `MultiTimeframeTechnical` per ticker |
| Data source | FMP OHLCV API                        |

**Strengths:** Deterministic, fast, rich computed features (EMA crosses with
candles-ago, RSI divergence, multi-timeframe alignment). **Weaknesses:**
Hardcoded thresholds (momentum 0.4, ADX 25), no OHLCV caching across runs.

### Stage 1: Perplexity Screening (`perplexity.py`)

| Aspect          | Details                                                |
| --------------- | ------------------------------------------------------ |
| Model           | `openai/gpt-5.4` via Perplexity Agent API              |
| Output          | `ScreeningResult` (tickers + fundamentals + citations) |
| Retries         | 2 (custom `_call_with_retry`)                          |
| Circuit breaker | No (divergent retry pattern)                           |
| Tools           | Web search + FMP function-calling (max 3 rounds)       |

**Strengths:** `_openai_strict_schema()` for constrained decoding, source
auditing tracks hallucination, domain filtering per market, FMP tool-calling
gives LLM agency. **Weaknesses:** Custom retry loop diverges from shared
`with_validation_retry`, no circuit breaker, `_CRYPTO_KEYWORDS` detection is
naive substring match.

### Stage 2: Gemini Sentiment (`gemini.py`)

| Aspect          | Details                                            |
| --------------- | -------------------------------------------------- |
| Model           | `gemini-2.5-pro`                                   |
| Output          | `SentimentAnalysis` per ticker                     |
| Retries         | 2 (validation) + 3 (transient HTTP) = 9 worst case |
| Circuit breaker | Yes (`provider="google"`)                          |
| Semaphore       | 5                                                  |

**Strengths:** Google Search grounding, 3-step protocol (read URLs, search,
synthesize), FMP company context injection, 7-level sentiment bucket.
**Weaknesses:** Transient error detection via string matching on exception
message (fragile), total worst case 9 API calls per ticker.

### Stage 3: Claude Vision (`claude.py`)

| Aspect          | Details                                    |
| --------------- | ------------------------------------------ |
| Model           | `claude-opus-4-6`                          |
| Output          | `TechnicalAssessment` per ticker/timeframe |
| Retries         | 2 (validation) + 2 (chart image fetch)     |
| Circuit breaker | Yes (`provider="anthropic"`)               |
| Semaphore       | 3                                          |

**Strengths:** Numerical-data-first approach, `chart_confirms_data` /
`chart_discrepancies` data integrity signal, multi-timeframe concurrent
analysis. **Weaknesses:** `max_tokens=4096` hardcoded, no transient HTTP retry
(unlike Gemini), N tickers x M timeframes generates many API calls with no
budget.

### Stage 4: GPT Debate (`gpt.py`)

| Aspect          | Details                            |
| --------------- | ---------------------------------- |
| Model           | `gpt-5.4`                          |
| Output          | `Recommendation` per ticker        |
| Retries         | 2 per sub-call (bull, bear, judge) |
| Circuit breaker | Yes (`provider="openai"`)          |
| Temperature     | 0.7 (bull/bear), 0.4 (judge)       |

**Strengths:** Track-aware framing, adversarial debate, raw TA alongside
Claude's interpretation for GPT cross-check, fresh quote re-fetch, explicit
decision framework. **Weaknesses:** Bull/bear prompts nearly identical (code
duplication), no transient HTTP retry, prompt can be very large with many
tickers, most expensive stage with no cost tracking.

### Risk Post-Filter + Validator

| Aspect | Details                                                 |
| ------ | ------------------------------------------------------- |
| Model  | None (pure Python)                                      |
| Output | `RiskAssessment` per ticker + `risk_violations` on recs |

**Rules:** Sentiment score, RSI extremes, ADX, volume, Altman Z-score,
Piotroski, price sanity vs live quotes, R:R ratio, ATR stop validation, earnings
proximity. **All thresholds hardcoded.** Advisory only -- doesn't remove
tickers.

### Stage 4.5: Annotated Charts

| Aspect | Details                                                      |
| ------ | ------------------------------------------------------------ |
| Model  | Chart-Img v2 API (not LLM)                                   |
| Output | Annotated chart URLs on `ChartAnalysis.annotated_chart_path` |

Overlays key_levels, entry, stop, take_profit from GPT. All charts annotated
concurrently. Non-blocking -- failures don't affect recommendations.

---

## Confidence Score Flow

```
Perplexity (Stage 1):
  - No explicit confidence score
  - Provides key_highlights and risk_factors per ticker

Gemini (Stage 2):
  - SentimentAnalysis.confidence: float [0.0, 1.0]
    "Self-assessed confidence based on source authority, count, recency"
  - SentimentAnalysis.sentiment_score: float [-1.0, 1.0]

Claude (Stage 3):
  - TechnicalAssessment.confidence: float [0.0, 1.0]
    Backward-compat converts v1 strings to floats

GPT (Stage 4):
  - Recommendation.confidence: float [0.0, 1.0]
  - DebateCase.confidence: float [0.0, 1.0] (per bull/bear case)

Post-GPT Calibration:
  1. raw_gpt_confidence preserved (orchestrator line 751-752)
  2. Confidence calibration (deterministic or ML-based):
     - ConfidenceBreakdown: 5 weighted components:
       * track_agreement:    max 0.30
       * technical_strength: max 0.20
       * trend_alignment:    max 0.20
       * historical_pattern: max 0.20
       * regime_fit:         max 0.10
     - Penalties: stale EMA cross (-0.15), RSI overbought (-0.10),
       low volume (-0.10), tracks disagree (-0.15 each),
       weak historical pattern (-0.20), risk disapproved (-0.07)
     - Blend: 40% GPT + 60% calibrated
     - SignalStrength: position-sizing hint enum
       (STRONG >= 0.7, MODERATE >= 0.5, WEAK >= 0.3, NO_EDGE < 0.3)
  3. ML gate (Stage 7.5):
     - ml_probability: independent model's assessment
     - ml_size_multiplier: position size adjustment
     - ml_blocked: hard veto if ML probability too low
     - ml_conformal_set: prediction interval
  4. TrackAgreement.agreement_score: [0.0, 1.0]
     Computed from Gemini/Claude direction alignment with GPT action
```

---

## Cross-Cutting Concerns

### Perplexity Validation Divergence

Perplexity uses a custom `_call_with_retry` loop instead of the shared
`with_validation_retry` decorator. This means it lacks circuit breaker
integration and has slightly different retry semantics. The two patterns should
be unified.

### Semaphore Sharing

Module-level semaphores are shared across concurrent pipeline runs. Two users
running pipelines simultaneously compete for the same rate-limit slots. This is
intentional for API rate limiting but reduces throughput.

### Prompt Schema Drift Risk

JSON output schemas are defined as inline text in prompt strings AND as Pydantic
models in `schemas.py`. No automated sync mechanism. If someone adds a field to
the Pydantic model but forgets to update the prompt text, the pipeline either
misses data or fails validation.

### No Exponential Backoff on Validation Retries

`with_validation_retry` retries happen immediately without delay. For
rate-limited providers this could burn through retries instantly. (Gemini has
its own transient retry with exponential backoff, but others don't.)

### Circuit Breaker Limitations

- Not thread-safe (fine for single async loop, risk if multi-worker)
- State lost on restart (provider that was down gets immediately retried)
- Fixed thresholds (3 failures, 120s cooldown) hardcoded for all providers

### Duplicated Code in Orchestrator

The same `ta_dict` / `fmp_dict` dictionary-building loop appears 3 times in the
orchestrator (for ML calibration, ML gate, and shadow runner). Should be
extracted.

---

## Top Improvements (Prioritized)

### P0 -- Bug Fixes (Do First)

| #   | Item                                                               | Files                                                                |
| --- | ------------------------------------------------------------------ | -------------------------------------------------------------------- |
| 1   | Fix Python 2 exception syntax (`except X, Y:` -> `except (X, Y):`) | reflection.py, trade_matcher.py, questrade.py, technical_analysis.py |
| 2   | Fix analysis mode hardcoded Canadian market bias                   | perplexity_analysis.py                                               |
| 3   | Fix `config.is_crypto` -> `config.fmp_screener.is_crypto`          | orchestrator.py                                                      |
| 4   | Fix `live_quotes` variable scoping                                 | orchestrator.py                                                      |

### P1 -- Accuracy & Actionability (Highest Impact)

| #   | Item                                                                             | Impact                                      | Effort |
| --- | -------------------------------------------------------------------------------- | ------------------------------------------- | ------ |
| 5   | **Empirical confidence calibration** -- learn blend weights from outcomes        | Confidence -> calibrated probability        | Medium |
| 6   | **Auto paper trading** -- track price at T+1/3/5d for every recommendation       | Enables data-driven improvement             | Medium |
| 7   | **Entry conditions** -- force GPT to specify trigger type, scaling, invalidation | Recommendations -> executable plans         | Low    |
| 8   | **Feed track disagreement INTO GPT** (not just compute it after)                 | Judge makes better conflict-aware calls     | Low    |
| 9   | **Auto-generate reflections** per strategy after every 5 outcomes                | Self-learning loop runs without user effort | Low    |

### P2 -- Quality & UX (High Impact)

| #   | Item                                                                      | Impact                                     | Effort |
| --- | ------------------------------------------------------------------------- | ------------------------------------------ | ------ |
| 10  | Surface missing frontend data (price, sentiment confidence, stage errors) | Trading decision context                   | Low    |
| 11  | Ticker sidebar sorting/filtering by confidence                            | Faster triage                              | Low    |
| 12  | Inject `strategy_type` and `description` into prompts                     | Better LLM outputs                         | Low    |
| 13  | Risk-adjusted position sizing (wire risk_score into position_size_pct)    | Risk management                            | Low    |
| 14  | Strategy-specific calibration profiles                                    | Different strategies need different tuning | Medium |
| 15  | Unify Perplexity retry with `with_validation_retry` + circuit breaker     | Consistency, resilience                    | Low    |

### P3 -- Polish & Infrastructure

| #   | Item                                                                  | Impact                         | Effort |
| --- | --------------------------------------------------------------------- | ------------------------------ | ------ |
| 16  | Structured bull/bear debate (Bear responds to Bull's specific points) | Better dialectic               | Medium |
| 17  | Few-shot examples in prompts                                          | Consistency, fewer retries     | Low    |
| 18  | Cross-ticker comparison view in frontend                              | Faster decision-making         | Medium |
| 19  | Confidence breakdown visualization in frontend                        | User understands WHY           | Low    |
| 20  | Test infrastructure (start with validation.py + calibration)          | Quality assurance              | Medium |
| 21  | Token budget management for GPT judge prompt                          | Prevents silent failures       | Medium |
| 22  | Per-run cost tracking                                                 | Cost awareness                 | Low    |
| 23  | Make model names strategy-configurable                                | A/B testing, cost optimization | Medium |
| 24  | Add exponential backoff to validation retries                         | Rate limit resilience          | Low    |
| 25  | Prompt schema auto-sync (generate prompt text from Pydantic models)   | Prevent schema drift           | Medium |

---

## The Big Picture

SignalForge's architecture is genuinely sophisticated -- the parallel tracks,
degraded pipeline, multi-layer calibration, and self-learning loop put it well
ahead of most AI trading tools. The pipeline does **a lot of things right** at
the infrastructure level.

The gap is in the **last mile**: turning a well-engineered pipeline into
**trades that actually make money and can prove it**. The confidence numbers
need empirical backing, the recommendations need entry precision, and the
feedback loop needs to close automatically.

The ML training pipeline (`src/ml_training/`) has all the right statistical
tools (Venn-ABERS, conformal prediction, calibration curves) -- bridging those
into the live pipeline would be transformative.

The highest-ROI work is items 5-9 above: calibrate confidence from real
outcomes, track prices automatically, add entry conditions to recommendations,
feed track disagreements into the judge, and auto-generate reflections. These
five changes would make every recommendation significantly more actionable
without any new infrastructure.
