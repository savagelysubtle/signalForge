# SignalForge Pipeline Overhaul Plan

**Date:** April 1, 2026 **Last verified against codebase:** April 1, 2026
**Goal:** Fix wrong-direction signals by restructuring the pipeline around
numerical technical analysis, independent parallel analysis tracks, and a
conflict-resolution synthesis model.

**Root Causes Identified:**

1. Claude Vision reading chart images for TA is imprecise — pixel-based guessing
   instead of numerical computation
2. Forward bias injection — Gemini's sentiment score, bucket, and catalyst
   narrative are injected into Claude's chart prompt via a
   `--- RECENT NEWS CONTEXT ---` block, anchoring Claude's analysis before it
   reads the chart. Note: the Perplexity→Gemini link is **low-bias** (only
   `news_urls` and `key_highlights` pass forward — factual data, not directional
   conclusions). The real echo-chamber injection point is **Gemini→Claude**.
3. The existing reflection system (FinMem architecture,
   `services/reflection.py`) already does structured pattern analysis, but lacks
   failure-mode classification and per-signal numerical TA snapshots to target
   specific upstream issues
4. No "no trade" pathway — the pipeline always forces a directional call
   (`BUY`/`SHORT`/`HOLD`) even when the data is ambiguous or conflicting

---

## Codebase Reference (Current State)

> This section documents the actual codebase structure to prevent re-exploration
> during implementation.

### Key Files

| File                                       | Lines   | Role                                                                                                      |
| ------------------------------------------ | ------- | --------------------------------------------------------------------------------------------------------- |
| `pipeline/orchestrator.py`                 | ~650    | Sequential stage runner: FMP → Regime → Perplexity → Gemini → Risk Screen → Claude → GPT → Annotate       |
| `pipeline/schemas.py`                      | ~756    | **Single file** (NOT a directory) containing all Pydantic models                                          |
| `pipeline/prompts/claude_chart.py`         | —       | Claude prompt (v8), builds `--- RECENT NEWS CONTEXT ---` from Gemini                                      |
| `pipeline/prompts/gpt_debate.py`           | —       | Bull (v3) / Bear (v3) / Judge (v8) prompts, ~234 lines for judge                                          |
| `pipeline/prompts/gemini_sentiment.py`     | —       | Gemini prompt (v6)                                                                                        |
| `pipeline/prompts/perplexity_discovery.py` | —       | Perplexity discovery prompt (v16)                                                                         |
| `pipeline/prompts/perplexity_analysis.py`  | —       | Perplexity analysis prompt (v8)                                                                           |
| `pipeline/prompts/regime_classifier.py`    | —       | Regime classifier prompt (v2)                                                                             |
| `pipeline/stages/`                         | 7 files | `claude.py`, `gemini.py`, `gpt.py`, `perplexity.py`, `regime.py`, `risk_screener.py`, `risk_validator.py` |
| `services/fmp_service.py`                  | ~1867   | FMP API client — uses **v3 API** at `/api/v3/...` endpoints                                               |
| `services/chart_image.py`                  | —       | Chart-Img v2 client — **already 1920×1080 landscape**                                                     |
| `services/reflection.py`                   | ~759    | FinMem reflection engine (short-term 14d + long-term all-time memory)                                     |
| `api/questrade.py`                         | ~569    | Full Questrade OAuth + trade sync + auto-matching                                                         |
| `utils/hashing.py`                         | —       | `prompt_hash()` — 8-char SHA-256 hex digest for prompt content tracking                                   |

### Current Pipeline Flow (Actual)

```
FMP pre-screening (optional, data-only)
    ↓ [enriched stock data]
Regime Classifier (Perplexity web search + FMP VIX/sectors)
    ↓ [regime_context string]
Perplexity (screening/discovery)
    ↓ [ticker list + news_urls + key_highlights]     ← factual, NOT directional
Gemini (per-ticker, parallel within stage, semaphore=5)
    ↓ [SentimentAnalysis: score, bucket, catalysts]  ← DIRECTIONAL conclusions
Risk Screener (GPT nano, filters on sentiment + FMP)
    ↓ [passed/demoted ticker lists]
Claude (per-ticker per-timeframe, parallel within stage, semaphore=3)
    ↓ [ChartAnalysis: direction, key_levels, signals] ← sees Gemini's sentiment
GPT (judge, optionally with bull/bear debate in parallel)
    ↓ [Recommendations]                               ← sees EVERYTHING upstream
Annotated Charts (Chart-Img v2, post-processing)
```

### Current Data Flow Between Stages

| From → To           | What Actually Passes                                                                                                                                                      | Bias Level                                          |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| Perplexity → Gemini | `news_urls` (article links), `key_highlights` (factual bullets)                                                                                                           | **LOW** — facts only, no directional conclusions    |
| Gemini → Claude     | `SentimentAnalysis` object: `sentiment_score`, `sentiment_bucket`, `summary`, top 5 `key_catalysts` with impact ratings — injected as `--- RECENT NEWS CONTEXT ---` block | **HIGH** — directional anchor before chart analysis |
| Perplexity → GPT    | Full `ScreeningResult`                                                                                                                                                    | By design (synthesis)                               |
| Gemini → GPT        | Full `SentimentAnalysis` list                                                                                                                                             | By design (synthesis)                               |
| Claude → GPT        | Full `ChartAnalysis` list with multi-TF synthesis                                                                                                                         | By design (synthesis)                               |

**Within-stage parallelism already exists:** Gemini runs all tickers
concurrently (semaphore=5), Claude runs all tickers × timeframes concurrently
(semaphore=3), GPT runs bull+bear debate in parallel per ticker.

### Current Claude Inputs (claude_chart.py `build_chart_prompt()`)

| Input                   | Source                                                                             | Optional?                   |
| ----------------------- | ---------------------------------------------------------------------------------- | --------------------------- |
| Ticker symbol           | Direct param                                                                       | No                          |
| Strategy config         | `StrategyConfig` (timeframe, indicators, ta_focus, risk_params)                    | No                          |
| Chart image             | Base64-encoded PNG via Chart-Img v2, sent as `image` content block                 | Yes (graceful failure)      |
| Gemini sentiment        | `SentimentAnalysis` → `--- RECENT NEWS CONTEXT ---` block                          | Yes (None if Gemini failed) |
| FMP fundamental context | `format_fmp_for_claude()` → `--- FUNDAMENTAL CONTEXT ---` block                    | Yes (None if FMP skipped)   |
| Market regime context   | Pre-formatted string prepended at top                                              | Yes (empty if skipped)      |
| Live quote data         | `FmpQuote` → `--- LIVE MARKET DATA ---` block (price, change%, range, volume/RVOL) | Yes (None if unavailable)   |

### Current Claude Output Model (`ChartAnalysis` in `schemas.py`)

```python
class ChartAnalysis(BaseModel):
    ticker: str
    timeframe: str
    current_price: float | None = None
    trend_direction: Literal["bullish", "bearish", "neutral", "transitioning"]
    trend_strength: Literal["strong", "moderate", "weak"]
    key_levels: list[TechnicalLevel]       # (price, level_type, strength)
    patterns_detected: list[str]
    indicator_readings: list[IndicatorReading]  # (indicator, value, signal, notes)
    volume_analysis: str
    overall_bias: Literal["strongly_bullish", "bullish", "neutral", "bearish", "strongly_bearish"]
    confidence: Literal["high", "medium", "low"]
    summary: str
    chart_image_path: str
    annotated_chart_path: str
```

### Current GPT Judge Capabilities (Already Implemented)

The judge prompt (v8, ~234 lines in `gpt_debate.py`) already does **active
conflict resolution**, not passive summarization:

- Decision framework with explicit BUY/SHORT/HOLD criteria
- ATR-based stop loss placement (1.0–2.0× ATR by strategy style)
- Weighted bias score interpretation with conviction thresholds (+/−1.2 to fire,
  +/−0.8 for caution)
- Multi-timeframe synthesis with convergence/divergence analysis
- Historical performance memory reconciliation (short-term vs long-term conflict
  resolution)
- Entry price rules anchored to live market prices
- Risk management and position sizing based on confidence

GPT receives: `ScreeningResult` (Perplexity), `ChartAnalysis[]` (Claude),
`SentimentAnalysis[]` (Gemini), `FmpEnrichedStock[]`, live quotes, risk
parameters, regime context, sector consensus, reflection context, and (if debate
enabled) bull/bear case arguments.

### Current Recommendation Model (`schemas.py`)

```python
class Recommendation(BaseModel):
    id: str
    ticker: str
    action: Literal["BUY", "SHORT", "HOLD"]   # inline Literal, NOT an enum
    confidence: float                           # 0.0–1.0
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size_pct: float
    risk_reward_ratio: float
    holding_period: str
    bull_case: str
    bear_case: str
    judge_reasoning: str
    key_factors: list[str]
    warnings: list[str]
    risk_violations: list[str]
    risk_approved: bool
```

### Existing Feedback/Reflection System (`services/reflection.py`)

The reflection system is **already mature** (759 lines, FinMem architecture):

- Two-layer memory: short-term (14 days) + long-term (all-time)
- Pattern accuracy tracking per signal type
- Sector win rates
- Timeframe alignment analysis
- Suppression logic for repeated bad patterns
- Confidence calibration: buckets into high (>0.75), medium (0.55–0.75), low
  (<0.55) with win rate per bucket
- Calls GPT for strategic self-advice

**Trade journal models already exist:** `DecisionCreate`, `DecisionResponse`,
`OutcomeCreate`, `OutcomeResponse`, `ReflectionResponse`, `PerformanceOverview`,
`RecommendationWithStatus`, `TradeHistoryEntry`

### Existing Questrade Integration (`api/questrade.py`)

Fully implemented (569 lines): OAuth flow, account selection, trade sync,
auto-matching executions to recommendations, pending match
confirmation/rejection.

### Database Migrations (001–016)

```
001_initial.sql              — Core schema (strategies, pipeline_runs, stage_outputs,
                               chart_images, recommendations, decisions, outcomes, reflections)
002_enable_rls.sql           — RLS policies
003_add_secondary_timeframe  — Strategy TF config
004_additional_timeframes    — Multi-TF support
005_short_timeframes         — Short TF config
006_add_fmp_screener         — FMP screener config
007_add_user_prompt          — User prompt field
008_add_reflection_user_id   — Multi-tenant reflections
009_add_atr_to_chart_indicators
010_rename_sell_to_short     — Action CHECK: SELL→SHORT
011_questrade_tokens         — Brokerage OAuth storage
012_pending_matches          — Trade match staging
013_outcome_brokerage_fields — Brokerage outcome fields
014_add_recommended_and_strategy_type
015_outcome_trade_levels     — Outcome stop/take-profit
016_auto_journal_fields      — Auto-follow/confirm flags
```

**Next available migration number: 017**

### Current Prompt Versions

| Stage                | File                      | Version |
| -------------------- | ------------------------- | ------- |
| Regime Classifier    | `regime_classifier.py`    | v2      |
| Perplexity Discovery | `perplexity_discovery.py` | v16     |
| Perplexity Analysis  | `perplexity_analysis.py`  | v8      |
| Gemini Sentiment     | `gemini_sentiment.py`     | v6      |
| Claude Chart         | `claude_chart.py`         | v8      |
| GPT Bull             | `gpt_debate.py`           | v3      |
| GPT Bear             | `gpt_debate.py`           | v3      |
| GPT Judge            | `gpt_debate.py`           | v8      |

Versioning: human-readable `PROMPT_VERSION = "vN"` + content-based
`prompt_hash()` (8-char SHA-256 hex digest stored in `stage_outputs.prompt_hash`
and `pipeline_runs.prompt_versions`).

### FMP API (Current Usage in `fmp_service.py`)

Current endpoint format (v3 API):

```
GET /api/v3/technical_indicator/{timeframe}/{symbol}?type={indicator_type}&period={period}
```

Currently only used for RSI (single indicator). No multi-indicator TA support
exists.

---

## Phase 1: Numerical TA Layer (Foundation)

**Priority:** CRITICAL — this is the single highest-impact change **Estimated
effort:** 2-3 days **Risk:** Low — additive, doesn't break existing pipeline

### What

Build a new service that pulls pre-computed technical indicators from FMP's
Technical Indicators API and structures them into a rich numerical snapshot per
ticker per timeframe.

### FMP Endpoints to Use

> **NOTE:** Verify these endpoints against current FMP API docs before
> implementation. The existing codebase uses the **v3 API** format:
> `/api/v3/technical_indicator/{timeframe}/{symbol}?type={indicator_type}&period={period}`
> (see `fmp_service.py` line ~779). FMP may also offer newer `/stable/`
> endpoints — check docs.

```
# Current v3 format (confirmed working in codebase):
GET /api/v3/technical_indicator/{timeframe}/{symbol}?type=ema&period={period}
GET /api/v3/technical_indicator/{timeframe}/{symbol}?type=rsi&period=14
GET /api/v3/technical_indicator/{timeframe}/{symbol}?type=macd
GET /api/v3/technical_indicator/{timeframe}/{symbol}?type=adx&period=14
GET /api/v3/technical_indicator/{timeframe}/{symbol}?type=williams&period=14
GET /api/v3/technical_indicator/{timeframe}/{symbol}?type=standardDeviation&period=20

# Historical price data for volume analysis
GET /api/v3/historical-price-full/{symbol}
```

Timeframes confirmed in codebase: `daily`, `1hour`, `4hour`. Minute-level
granularity (`1min`, `5min`, `15min`, `30min`) needs FMP docs verification and
may depend on subscription tier.

### New Files

```
src/backend/
├── services/
│   └── technical_analysis.py    # FMP TA API client + computation
├── pipeline/
│   ├── schemas.py               # ADD new TA models to existing single file
│   │                            # (schemas is a SINGLE FILE, not a directory)
│   └── stages/
│       └── numerical_ta.py      # Pipeline stage wrapper (alongside existing 7 stages)
```

> **Decision required:** Whether to split `schemas.py` (~756 lines) into a
> `schemas/` package before adding more models. If splitting, create
> `schemas/__init__.py` that re-exports everything for backward compatibility,
> then put TA models in `schemas/technical.py`. If not splitting, add models
> directly to the existing `schemas.py` file.

### Pydantic Schema (draft)

These models go into `schemas.py` (or `schemas/technical.py` if the package
split is done first):

```python
class EMASnapshot(BaseModel):
    """EMA values at current candle for multiple periods."""
    period: int
    current_value: float
    previous_value: float  # 1 candle ago
    slope: float           # current - previous (positive = rising)

class EMACross(BaseModel):
    """Detected EMA crossover event."""
    fast_period: int
    slow_period: int
    cross_type: Literal["bullish", "bearish"]
    candles_ago: int          # how many candles since the cross
    spread_pct: float         # current distance between EMAs as %
    spread_direction: Literal["widening", "narrowing"]

class MACDSnapshot(BaseModel):
    macd_line: float
    signal_line: float
    histogram: float
    histogram_slope: Literal["expanding", "contracting"]
    signal_cross: Literal["above", "below"]

class RSISnapshot(BaseModel):
    current: float
    previous: float
    trend: Literal["rising", "falling", "flat"]
    zone: Literal["overbought", "neutral", "oversold"]
    divergence: Literal["bullish_divergence", "bearish_divergence", "none"]

class VolumeSnapshot(BaseModel):
    current: int
    avg_20: float
    ratio: float  # current / avg_20 — above 1.5 = notable
    trend: Literal["increasing", "decreasing", "stable"]

class TechnicalSnapshot(BaseModel):
    """Complete numerical TA for one ticker at one timeframe."""
    ticker: str
    timeframe: str
    timestamp: datetime
    price_current: float
    price_open: float
    price_high: float
    price_low: float

    emas: list[EMASnapshot]        # 9, 21, 50, 200
    ema_crosses: list[EMACross]    # all detected crosses
    macd: MACDSnapshot
    rsi: RSISnapshot
    adx: float                     # trend strength (>25 = trending)
    atr: float                     # average true range
    atr_pct: float                 # ATR as % of price
    volume: VolumeSnapshot

    # Derived signals
    trend_alignment: Literal["all_bullish", "all_bearish", "mixed"]
    momentum_score: float          # -1.0 to 1.0 composite

class MultiTimeframeTechnical(BaseModel):
    """TA across all strategy timeframes for one ticker."""
    ticker: str
    primary: TechnicalSnapshot
    additional: list[TechnicalSnapshot]
    short: list[TechnicalSnapshot]
    timeframe_alignment: Literal["aligned_bullish", "aligned_bearish", "divergent"]
```

### Computation Logic

The service doesn't just return raw API values — it computes derived signals:

- **EMA crosses:** Compare fast vs slow EMA across last N candles to find cross
  point and measure spread
- **Trend alignment:** Are all EMAs stacked in order? (9 > 21 > 50 > 200 =
  bullish alignment)
- **Timeframe alignment:** Do primary and additional timeframes agree on
  direction?

**Momentum score formula** (explicit starting weights — Phase 6 feedback loop
tunes these over time):

```python
def compute_momentum_score(rsi: RSISnapshot, macd: MACDSnapshot,
                           emas: list[EMASnapshot], adx: float) -> float:
    """Weighted composite momentum score, range -1.0 to +1.0."""
    # RSI component: -1 (oversold) to +1 (overbought), centered at 50
    rsi_component = (rsi.current - 50) / 50  # maps 0-100 to -1.0 to +1.0

    # MACD component: histogram direction and magnitude
    macd_component = 1.0 if macd.histogram > 0 else -1.0
    if macd.histogram_slope == "contracting":
        macd_component *= 0.5  # weaken if momentum fading

    # EMA spread component: alignment and stack order
    # +1.0 if all bullish aligned (9>21>50>200), -1.0 if bearish, 0 if mixed
    bullish_pairs = sum(1 for i in range(len(emas)-1)
                        if emas[i].current_value > emas[i+1].current_value)
    ema_spread_component = (bullish_pairs / max(len(emas)-1, 1)) * 2 - 1

    # ADX component: 0.0 to 1.0 trend strength (>25 = trending)
    adx_component = min(adx / 50, 1.0)  # cap at 50 for normalization

    return (
        rsi_component * 0.25 +
        macd_component * 0.25 +
        ema_spread_component * 0.30 +
        adx_component * 0.20
    )
```

> **Note:** These weights (RSI 0.25, MACD 0.25, EMA 0.30, ADX 0.20) are starting
> values. Track which components correlate most with winning trades in Phase 6
> and adjust.

**RSI divergence detection — deferred to Phase 1.5:**

RSI divergence (`bullish_divergence` / `bearish_divergence` / `none`) requires
identifying swing highs/lows in both price and RSI, then comparing them. FMP
gives raw RSI values but swing detection is custom code with edge cases (how
many candles define a swing? what's the lookback window?). To avoid scope creep
on the most critical phase:

- **Phase 1:** Ship `RSISnapshot.divergence` as `"none"` always (field exists
  but not computed)
- **Phase 1.5:** Implement swing high/low detection and divergence
  classification as a follow-up
- This keeps Phase 1 focused on the indicators FMP gives us directly (EMA, RSI
  value, MACD, ADX, volume)

### Concurrency

Pull all indicators for a ticker concurrently with `asyncio.gather`. Pull all
tickers concurrently with semaphore (match FMP's rate limits — existing FMP
service uses `Semaphore(5)` as precedent).

### Integration Point

This stage runs BEFORE the three parallel LLM tracks. Its output is passed to
Claude (Track C) as structured text. Perplexity and Gemini do NOT receive this
data — they analyze independently.

### Validation

- Unit test: mock FMP responses, verify cross detection, divergence detection,
  alignment scoring
- Sanity check: run against 10 known tickers and manually verify EMA cross
  timing against TradingView

---

## Phase 2: Decouple the Pipeline (Kill the Echo Chamber)

**Priority:** CRITICAL — addresses root cause of directional bias **Estimated
effort:** 2-3 days **Risk:** Medium — requires restructuring orchestrator and
all stage prompts

### What

Restructure the pipeline so Perplexity, Gemini, and Claude run as independent
parallel analysis tracks. Their directional conclusions do NOT flow to each
other. GPT becomes the first and only convergence point.

### Current Flow (Problem)

```
Perplexity → [news_urls, highlights] → Gemini → [sentiment_score, catalysts] → Claude → GPT
              (low bias: facts only)             (HIGH bias: directional anchor)   (sees all)
```

The **primary bias injection** is Gemini→Claude. Claude's prompt
(`claude_chart.py` `build_chart_prompt()`) injects Gemini's sentiment score,
bucket label, summary, and top 5 key catalysts as a
`--- RECENT NEWS CONTEXT ---` block before the chart image. This anchors
Claude's chart reading with a directional lean.

The Perplexity→Gemini link is **low-risk** — Gemini receives only article URLs
and factual highlights, and performs its own independent news discovery via
Google Search grounding. However, even these URLs subtly pre-select which news
Gemini prioritizes.

### New Flow

```
                              ┌→ Perplexity (fundamentals + news)  ──┐
FMP + Regime + Numerical TA ──┼→ Gemini (sentiment grounding)       ──┼→ Risk Post-Filter → GPT
                              └→ Claude (numerical TA + chart conf.) ─┘
```

### Risk Screener Placement (Design Decision)

**Problem:** In the current pipeline, the risk screener sits between Gemini and
Claude — it uses sentiment + FMP data to filter tickers _before_ Claude burns
expensive Vision API calls. In the new parallel architecture, the risk screener
can't run until all three tracks complete, meaning Claude runs on tickers that
might get filtered out.

**Cost impact:** If screening 20 tickers and the risk screener typically cuts to
12, that's 8 extra Claude Vision calls per run (each with Chart-Img fetch +
Anthropic API).

**Decision: Lightweight pre-filter + post-filter.**

1. **Pre-filter (before parallel tracks):** Run a fast, cheap check using only
   FMP fundamentals (no LLM call). Filter out tickers with obvious
   disqualifiers: market cap below strategy minimum, average volume below
   threshold, price outside strategy range. This is data the FMP pre-screening
   stage already has.

2. **Post-filter (after parallel tracks):** The risk screener becomes a
   post-filter that enriches GPT's input rather than removing tickers. It adds a
   `risk_flags: list[str]` and `risk_approved: bool` to each ticker's data
   package. GPT sees all three track analyses plus the risk assessment, and can
   factor risk flags into its NO_TRADE/WATCH decision.

This keeps Claude's call count reasonable (pre-filter catches the obvious ones)
while letting GPT make the final risk-adjusted call with full information.

### Changes to Orchestrator

File: `src/backend/pipeline/orchestrator.py`

```python
async def _run_pipeline(self, config: StrategyConfig, ...):
    """Dispatch to v1 (sequential) or v2 (parallel) based on strategy config."""
    if getattr(config, "pipeline_version", "v1") == "v2":
        return await self._run_pipeline_v2(config, ...)
    return await self._run_pipeline_v1(config, ...)  # existing code, untouched

async def _run_pipeline_v2(self, config: StrategyConfig, ...):
    # FMP pre-screening + regime (same as v1)
    fmp_data = await run_fmp_screening(config)
    regime = await run_regime_classifier(config)

    # Lightweight pre-filter: drop tickers with obvious disqualifiers
    tickers = pre_filter_tickers(fmp_data, config)  # fast, no LLM

    # Numerical TA (Phase 1) — runs before parallel tracks
    numerical_ta = await run_numerical_ta(tickers, regime)

    # Three independent parallel tracks
    perplexity_result, gemini_result, claude_result = await asyncio.gather(
        run_perplexity(tickers, regime),
        run_gemini(tickers, regime),
        run_claude(tickers, regime, numerical_ta),
    )

    # Risk post-filter: enrich with risk flags, don't remove tickers
    risk_assessments = await run_risk_post_filter(
        tickers, perplexity_result, gemini_result, claude_result, fmp_data
    )

    gpt_result = await run_gpt(
        perplexity_result,
        gemini_result,
        claude_result,
        numerical_ta,
        risk_assessments,
        journal_context,
    )
```

> **Key principle:** `_run_pipeline_v1()` is the existing working code,
> completely untouched. This means the A/B test is safe — you're adding a new
> code path, not modifying the old one.

### Prompt Changes Required

**Perplexity prompt (currently v16 discovery / v8 analysis):**

- Already independent — receives only ticker, regime, strategy params, FMP tool
  access
- Add: explicit instruction — "Provide your independent fundamental assessment.
  Do not assume any directional bias."

**Gemini prompt (currently v6):**

- Remove: `ticker_news` (news URLs from Perplexity) and `ticker_highlights`
  parameters from `run_gemini_sentiment()`
- Keep: ticker, date range, Google Search grounding (Gemini already does
  independent search)
- Change: Gemini does its OWN news discovery via Google grounding, not
  Perplexity's curated list
- Add: "Provide your independent sentiment assessment based on your own
  research."

**Claude prompt (currently v8 — MAJOR REWRITE):**

- Remove: `--- RECENT NEWS CONTEXT ---` section (Gemini's `SentimentAnalysis`
  injection in `build_chart_prompt()`)
- Remove: `--- FUNDAMENTAL CONTEXT ---` section (FMP data via
  `format_fmp_for_claude()`)
- Remove: `--- LIVE MARKET DATA ---` section (live quotes — these are in the
  numerical TA now)
- Add: Full `TechnicalSnapshot` as structured text (numerical data from Phase 1)
- Keep: chart image (base64 PNG), but reframe its purpose
- Keep: regime context, strategy config
- New role: "You are a technical analyst. You have been given precise numerical
  indicator data. Your job is to interpret these numbers and confirm or flag
  discrepancies against the chart image. The chart is a visual sanity check, not
  your primary data source."
- Add: "Report if the chart image contradicts the numerical data — this is a
  data quality flag."

**GPT synthesis prompt (currently v8 judge — ENHANCEMENT, not full rewrite):**
The judge already does active conflict resolution with decision frameworks,
ATR-based stops, weighted bias scoring, and historical memory reconciliation.
The changes are:

- Receives three independent analyses clearly labeled as TRACK A / TRACK B /
  TRACK C
- New instruction: "These three analyses were produced independently. They may
  agree or disagree. Your job is to identify and resolve conflicts, not to find
  consensus."
- Add: agreement/disagreement scoring — "Note where tracks agree and where they
  conflict. Conflicts should LOWER confidence, not be ignored."
- Add: "If fewer than 2 of 3 tracks agree on direction, the default
  recommendation is NO TRADE unless there is an exceptional edge case you can
  articulate."

### Degraded Mode Updates

Current degraded mode handles stage failures. Update it for the parallel model:

- If 1 of 3 tracks fails: GPT synthesizes with 2. Flag reduced confidence.
- If 2 of 3 tracks fail: GPT synthesizes with 1 + numerical TA. Flag as low
  confidence.
- If all 3 fail: numerical TA only → GPT produces a "data only, no
  recommendation" output.

### What Data Flows Forward (New Architecture)

| Data                   | Perplexity | Gemini | Claude | GPT |
| ---------------------- | ---------- | ------ | ------ | --- |
| Ticker list            | ✅         | ✅     | ✅     | ✅  |
| Regime context         | ✅         | ✅     | ✅     | ✅  |
| Strategy params        | ✅         | ✅     | ✅     | ✅  |
| FMP screening data     | ✅         | ❌     | ❌     | ✅  |
| Numerical TA           | ❌         | ❌     | ✅     | ✅  |
| Perplexity conclusions | —          | ❌     | ❌     | ✅  |
| Gemini conclusions     | ❌         | —      | ❌     | ✅  |
| Claude conclusions     | ❌         | ❌     | —      | ✅  |
| Chart images           | ❌         | ❌     | ✅     | ❌  |
| Journal context        | ❌         | ❌     | ❌     | ✅  |

---

## Phase 3: First-Class "No Trade" Signal

**Priority:** HIGH — prevents forced bad calls **Estimated effort:** 1 day
**Risk:** Low — schema addition + prompt update

### What

Add `NO_TRADE` and `WATCH` actions to the recommendation schema and update GPT's
synthesis to use them when tracks disagree or confidence is low.

### Current State

- `Recommendation.action` is `Literal["BUY", "SHORT", "HOLD"]` (inline literal,
  not an enum)
- DB CHECK constraint on `recommendations.action` was updated from `SELL→SHORT`
  in migration 010
- No `RecommendationAction` enum exists
- No `TrackAgreement` model exists

### Schema Changes

Add to `schemas.py` (single file):

```python
class RecommendationAction(str, Enum):
    BUY = "BUY"
    SHORT = "SHORT"
    HOLD = "HOLD"            # EXISTING — keep for backward compat
    NO_TRADE = "NO_TRADE"    # NEW
    WATCH = "WATCH"          # NEW — interesting but not actionable yet

class TrackAgreement(BaseModel):
    """How the three independent tracks aligned."""
    perplexity_direction: Literal["bullish", "bearish", "neutral"]
    gemini_direction: Literal["bullish", "bearish", "neutral"]
    claude_direction: Literal["bullish", "bearish", "neutral"]
    agreement_score: float    # 0.0 (full disagreement) to 1.0 (unanimous)
    conflicts: list[str]      # human-readable conflict descriptions
```

Update `Recommendation`:

```python
class Recommendation(BaseModel):
    # ... existing fields (id, ticker, entry_price, stop_loss, etc.) ...
    action: RecommendationAction          # was Literal["BUY", "SHORT", "HOLD"]
    track_agreement: TrackAgreement       # NEW
    confidence_adjustment: str            # NEW — why confidence was raised/lowered
```

### Database Migration

Create migration **`017_pipeline_v2.sql`** (NOT 011 — that's taken by
`questrade_tokens`):

- ALTER `recommendations` CHECK constraint to allow `NO_TRADE`, `WATCH`
- ADD `track_agreement` JSONB column to `recommendations`
- ADD `confidence_adjustment` TEXT column to `recommendations`

### GPT Prompt Rules

Add explicit decision rules to the GPT synthesis prompt:

```
DECISION RULES:
- 3/3 tracks agree on direction → proceed with signal, confidence based on strength
- 2/3 tracks agree, 1 dissents → proceed with LOWER confidence, note the dissent
- All 3 tracks disagree → NO_TRADE. Do not force a direction.
- 2/3 agree but numerical TA contradicts → WATCH. Flag the discrepancy.
- Any signal where ADX < 20 and strategy requires trending market → NO_TRADE
- Momentum score near zero (-0.2 to 0.2) → WATCH unless other signals are strong
```

### Frontend Changes

- Add `NO_TRADE` and `WATCH` rendering to `RecommendationsView`
- Display `TrackAgreement` breakdown in the Synthesis tab
- Color-code: green (3/3 agree), yellow (2/3), red (disagreement/no trade)
- Update `types/index.ts` to mirror new `RecommendationAction` and
  `TrackAgreement` (schema-sync skill)

---

## Phase 4: Claude Prompt Rewrite (Vision → Analyst)

**Priority:** HIGH — transforms Claude's role from "chart reader" to "technical
analyst" **Estimated effort:** 1-2 days **Risk:** Medium — prompt engineering
iteration required

### What

Rewrite Claude's prompt and input structure. Claude becomes a technical analyst
who receives precise numerical data and uses the chart as visual confirmation,
not the primary analytical input.

### Current State

- Claude prompt is at **v8** in `claude_chart.py`
- System prompt: "expert technical analyst reviewing a TradingView chart
  screenshot"
- Claude currently receives: chart image (base64), Gemini sentiment, FMP
  fundamentals, live quotes, regime context, strategy config
- Output model: `ChartAnalysis` (NOT `TechnicalAssessment` — that model doesn't
  exist yet)
- Chart images are **already 1920×1080 landscape** (Phase 8 is already done)

### New Claude Input Structure

```
TECHNICAL DATA (PRIMARY — analyze these numbers):
Ticker: AAPL
Timeframe: Daily
Current Price: $187.42
Today's Range: $185.90 - $188.15

EMA Stack:
  9 EMA:   $186.78 (rising, slope +0.34)
  21 EMA:  $185.21 (rising, slope +0.18)
  50 EMA:  $182.45 (rising, slope +0.09)
  200 EMA: $176.33 (rising, slope +0.04)
  Stack Order: 9 > 21 > 50 > 200 (BULLISH ALIGNMENT)

EMA Crosses:
  9/21 EMA: Bullish cross 4 candles ago, spread 0.85% and WIDENING

RSI (14): 64.2 (neutral zone, rising from 58.1)
  Divergence: None detected

MACD:
  Line: 1.23, Signal: 0.89, Histogram: +0.34 (EXPANDING)
  Signal: MACD above signal line

ADX: 28.4 (trending)
ATR: $2.87 (1.53% of price)
Volume: 1.3x 20-day average (elevated)

Composite Momentum Score: +0.62 (moderately bullish)

REGIME CONTEXT:
Market regime: Trending bullish
Strategy: Swing EMA Crossover

CHART IMAGE (CONFIRMATION — verify the above data visually):
[attached chart image]

YOUR TASK:
1. Interpret the numerical data above. What is the technical picture telling you?
2. Look at the chart image. Does it visually confirm what the numbers say?
3. If the chart contradicts the numbers, flag this as a DATA QUALITY CONCERN.
4. Provide your independent technical assessment: direction, confidence, key levels.
5. Identify the nearest support and resistance from the EMA structure.
6. Do NOT consider fundamentals or sentiment — other analysts handle that.
```

### New Claude Output Model

**Strategy: Keep `ChartAnalysis` as a backward-compat alias.** Old pipeline v1
runs stored `ChartAnalysis` objects in `stage_outputs`. If we delete the class,
the history view breaks when deserializing old data. Instead:

1. Create `TechnicalAssessment` as the new primary model with the new fields
2. Make `ChartAnalysis` a type alias or thin subclass that maps to
   `TechnicalAssessment`
3. Old v1 pipeline runs continue to deserialize via `ChartAnalysis`
4. New v2 pipeline runs produce `TechnicalAssessment` objects

```python
class TechnicalAssessment(BaseModel):
    """Claude's independent technical analysis (v2 pipeline output)."""
    ticker: str
    timeframe: str
    direction: Literal["bullish", "bearish", "neutral", "transitioning"]
    confidence: float  # 0.0 to 1.0 (change from Literal["high","medium","low"])

    # Key findings from numerical data
    ema_assessment: str      # "Bullish alignment, 9/21 cross confirmed and widening"
    momentum_assessment: str # "RSI healthy, MACD expanding, no divergence"
    volume_assessment: str   # "Elevated volume confirms move"
    trend_strength: str      # "ADX 28 confirms trending conditions"

    # Chart confirmation
    chart_confirms_data: bool
    chart_discrepancies: list[str]  # any visual vs numerical mismatches

    # Key levels from EMA structure
    nearest_support: float
    nearest_resistance: float
    suggested_stop_zone: str  # "Below 21 EMA at $185.21"

    # Multi-timeframe note (if additional TFs provided)
    timeframe_alignment_note: str

    # Preserved from ChartAnalysis for backward compat
    chart_image_path: str = ""
    annotated_chart_path: str = ""

# Backward compat: old pipeline runs can still deserialize
ChartAnalysis = TechnicalAssessment  # alias — keeps old imports working
```

**Full surface area for this rename** (all must handle both old and new):

| File                               | What references `ChartAnalysis`                         |
| ---------------------------------- | ------------------------------------------------------- |
| `pipeline/schemas.py`              | Model definition                                        |
| `pipeline/stages/claude.py`        | Return type, Pydantic validation                        |
| `pipeline/stages/gpt.py`           | Input type, data formatting                             |
| `pipeline/prompts/gpt_debate.py`   | `_format_chart_data()`, `_synthesize_timeframes()`      |
| `pipeline/prompts/claude_chart.py` | Output schema in prompt text                            |
| `pipeline/stages/annotated_charts` | Stage 4.5 reads chart analysis for annotation overlays  |
| `services/reflection.py`           | May reference chart analysis fields in pattern analysis |
| `frontend/src/types/index.ts`      | TypeScript interface (schema-sync)                      |
| `frontend/src/views/`              | Chart tab in detail panel, history view rendering       |

### Chart Image Notes

- **Already landscape 1920×1080** — no change needed (was switched in commit
  `f1e5791`)
- No candle count configuration exists — Chart-Img uses server-side defaults per
  interval. If specific candle counts are needed, check Chart-Img v2 API docs
  for range/bars parameters.
- Chart images remain supplementary — if Chart-Img is down, Claude works from
  numbers alone

---

## Phase 5: GPT Synthesis Enhancement (Track-Aware Conflict Resolution)

**Priority:** HIGH — adds track independence awareness to existing conflict
resolution **Estimated effort:** 1-2 days **Risk:** Medium — prompt engineering
iteration required

### What

Enhance GPT's synthesis stage to be explicitly aware of track independence. The
judge **already does** active conflict resolution (decision frameworks, ATR
stops, weighted bias scoring, historical memory). The main changes are: (1)
framing inputs as independent tracks, (2) adding explicit agreement scoring, and
(3) supporting NO_TRADE/WATCH outputs.

### New GPT Input Structure

Build on the existing `build_judge_prompt()` format:

```
You are a senior trading analyst receiving three independent research reports
on the same ticker. These analysts did NOT communicate with each other.
Your job is to synthesize their findings, identify agreements and conflicts,
and produce a final recommendation.

IMPORTANT: Disagreement between analysts should LOWER your confidence.
If the technical picture contradicts the fundamental or sentiment picture,
this is a warning sign, not something to gloss over.

=== TRACK A: FUNDAMENTAL ANALYSIS (Perplexity) ===
[Perplexity output — fundamentals, catalysts, news]

=== TRACK B: SENTIMENT ANALYSIS (Gemini) ===
[Gemini output — sentiment score, momentum, themes]

=== TRACK C: TECHNICAL ANALYSIS (Claude) ===
[Claude output — technical assessment, key levels, confidence]

=== RAW NUMERICAL DATA (for your verification) ===
[TechnicalSnapshot — so GPT can sanity-check Claude's interpretation]

=== HISTORICAL CONTEXT (from trade journal) ===
[Already available via reflection system — enhance with pattern matching]

=== DECISION RULES ===
[The rules from Phase 3 — agreement scoring, no-trade thresholds]
```

### Bull/Bear Debate Changes

The existing `enable_debate` flag stays (8 strategies enabled, 5 disabled —
mainly scalp/intraday). The debate structure changes:

**Current:** Bull and Bear both receive ALL upstream data (Perplexity, Gemini,
Claude, FMP, quotes) and argue from the same pile. Bull+Bear run in parallel via
`asyncio.gather()`, then Judge runs sequentially.

**New:** Bull argues using the most optimistic reading across all three tracks.
Bear argues using the most pessimistic reading. The Judge must explain which
track(s) they weighted most and WHY, citing specific numbers.

The Judge prompt enhancement:

```
Your verdict must explicitly state:
1. Which tracks you weighted most heavily and why
2. What the key disagreement was and how you resolved it
3. Your confidence level and what would change your mind
4. If confidence is below 0.5, recommend NO_TRADE or WATCH
```

---

## Phase 6: Feedback Loop Enhancement

**Priority:** MEDIUM — builds on Phases 1-5 being in place **Estimated effort:**
1-2 days (reduced from 2-3 — foundation already exists) **Risk:** Low — extends
existing mature reflection system

### What

Extend the existing FinMem reflection system with failure-mode classification
and per-signal numerical TA snapshots, enabling targeted pattern learning.

### Current State (Already Implemented)

The reflection system (`services/reflection.py`, 759 lines) already provides:

- **Two-layer memory:** short-term (14 days) + long-term (all-time)
- **Pattern accuracy tracking** per signal type
- **Sector win rates** and timeframe alignment analysis
- **Confidence calibration:** buckets into high (>0.75), medium (0.55–0.75), low
  (<0.55) with win rates per bucket
- **Suppression logic** for repeated bad patterns
- **GPT-generated strategic self-advice**

Questrade integration already provides actual entry/exit prices, timestamps,
position sizing, hold duration, and auto-matching to recommendations.

### What's New (Extend, Don't Replace)

Add to the existing reflection system:

```python
class StructuredOutcomeAnalysis(BaseModel):
    """Rich post-trade analysis — EXTENDS existing OutcomeResponse."""
    # Basic outcome (already tracked in OutcomeResponse)
    ticker: str
    signal_direction: str
    actual_outcome: Literal["win", "loss", "breakeven"]
    pnl_pct: float

    # NEW: Track agreement at time of signal
    track_agreement_score: float
    tracks_that_agreed_with_outcome: list[str]
    tracks_that_disagreed_with_outcome: list[str]

    # NEW: Numerical TA snapshot comparison
    ema_cross_age_at_signal: int
    rsi_at_signal: float
    rsi_at_outcome: float
    adx_at_signal: float
    momentum_score_at_signal: float
    momentum_score_at_outcome: float

    # NEW: Pattern classification
    failure_mode: Literal[
        "late_entry",
        "false_breakout",
        "sentiment_reversal",
        "regime_change",
        "correct_direction_bad_timing",
        "wrong_direction",
        "low_agreement_taken",
        "unknown",
    ]

    lesson: str
```

### Enhanced Feedback to GPT

Extend existing reflection context with track-agreement statistics:

```
HISTORICAL PATTERN ANALYSIS (from last 50 trades):

Signal accuracy by track agreement:
  3/3 agree: 62% win rate (13 trades)
  2/3 agree: 41% win rate (22 trades)
  Full disagree: 18% win rate (15 trades)

Signal accuracy by EMA cross age:
  Cross within last 2 candles: 58% win rate
  Cross 3-5 candles ago: 34% win rate
  Cross 6+ candles ago: 21% win rate

Most common failure mode: late_entry (38% of losses)
Second most common: low_agreement_taken (27% of losses)

SPECIFIC LESSON for current setup:
This signal matches the pattern "EMA cross + trending ADX + elevated volume."
Historical accuracy for this pattern: 55%
When this pattern had RSI > 65 at signal time: 38% (worse)
When this pattern had RSI < 60 at signal time: 67% (better)
```

### Questrade Cross-Reference (Already Available)

The existing Questrade integration already provides:

- Actual entry/exit prices and timestamps
- Auto-matching executions to recommendations
- Pending match confirmation/rejection

**Extend** with:

- Slippage calculation (signal price vs actual fill)
- Time-to-execution (signal generation → trade execution)
- Trader deviation tracking (followed signal exactly vs modified)
- Signal accuracy vs execution accuracy as separate metrics

### Database Changes

Add to migration **`017_pipeline_v2.sql`** (same migration as Phase 3):

- ADD `failure_mode` TEXT column to `outcomes`
- ADD `structured_analysis` JSONB column to `outcomes`
- ADD `pattern_statistics` JSONB column to `reflections`

---

## Phase 7: Confidence Calibration & Thresholds

**Priority:** MEDIUM — prevents overconfident bad signals **Estimated effort:**
1-2 days **Risk:** Low — tuning on top of new architecture

### What

Add structured confidence decomposition that breaks down the confidence score
into weighted sub-components, replacing the single float.

### Current State

- `Recommendation.confidence` is a single `float` (0.0–1.0)
- Reflection system already does retroactive calibration: buckets
  high/medium/low with win rates
- No forward-looking structured breakdown exists

### New Models

Add to `schemas.py`:

```python
class ConfidenceBreakdown(BaseModel):
    track_agreement: float      # 0.0-0.3 based on agreement score
    technical_strength: float   # 0.0-0.2 based on momentum score + ADX
    trend_alignment: float      # 0.0-0.2 based on multi-timeframe agreement
    historical_pattern: float   # 0.0-0.2 based on similar trade outcomes
    regime_fit: float           # 0.0-0.1 based on strategy-regime match
    total: float                # sum, 0.0 to 1.0

class SignalStrength(str, Enum):
    STRONG = "strong"     # confidence >= 0.7, full position
    MODERATE = "moderate" # confidence 0.5-0.7, half position
    WEAK = "weak"         # confidence 0.3-0.5, quarter position or WATCH
    NO_EDGE = "no_edge"   # confidence < 0.3, NO_TRADE
```

### Auto-Threshold Rules

Starting points — the feedback loop in Phase 6 should tune these over time:

- **EMA cross age > 5 candles on daily:** reduce confidence by 0.15
- **RSI > 70 on bullish signal:** reduce confidence by 0.10
- **RSI < 30 on bearish signal:** reduce confidence by 0.10
- **ADX < 20 (no trend):** reduce confidence by 0.20 for trend-following
  strategies
- **Volume < 0.8x average:** reduce confidence by 0.10
- **Tracks disagree:** reduce confidence by 0.15 per dissenting track
- **Historical pattern accuracy < 40%:** reduce confidence by 0.20

---

## ~~Phase 8: Chart Orientation + Landscape Mode~~ ✅ DONE

**Status: ALREADY IMPLEMENTED — no work needed**

Chart images are **already 1920×1080 landscape** in both `fetch_chart_image()`
and `fetch_annotated_chart()` (see `services/chart_image.py` lines 277-283,
446-452). They were switched from 800×600 to 1920×1080 in commit `f1e5791`.
Charts were **never** portrait (1080×1920) — that claim was incorrect.

Supabase Storage upload to `charts` bucket is confirmed working.

The only remaining chart improvement is adding candle count configuration per
timeframe (Chart-Img v2 uses server-side defaults currently). This is low
priority and can be done whenever.

---

## Implementation Order & Dependencies

```
Week 1:
  Phase 1 (Numerical TA)      ← no dependencies, can start immediately
                                 RSI divergence ships as "none" (deferred to 1.5)
                                 Momentum score uses explicit formula with defined weights
  Phase 3 (No Trade schema)   ← no dependencies, can start immediately
  Migration 017               ← combine Phase 3 + Phase 6 + feature flag DB changes

Week 2:
  Phase 2 (Decouple pipeline) ← depends on Phase 1 output schema
                                 Includes: _run_pipeline_v1/_v2 split, pre-filter,
                                 risk post-filter, pipeline_version dispatch
  Phase 4 (Claude rewrite)    ← depends on Phase 1 + Phase 2
                                 ChartAnalysis kept as alias for backward compat

Week 3:
  Phase 5 (GPT enhancement)   ← depends on Phase 2 + Phase 3 + Phase 4
  Phase 1.5 (RSI divergence)  ← depends on Phase 1 being stable
  Schema-sync skill            ← sync all new/changed models to frontend types

Week 4:
  Phase 6 (Feedback loop ext.) ← depends on Phase 5 + needs some trade data
  Phase 7 (Confidence cal.)    ← depends on Phase 5

Ongoing:
  Feedback loop tuning         ← needs 20+ trades on new pipeline
  Confidence threshold tuning  ← needs 50+ trades for statistical significance
  Momentum score weight tuning ← needs 30+ trades to identify strongest component correlations
```

---

## Validation Checkpoints

After each phase, run the pipeline against 10-20 known tickers and manually
verify:

### Phase 1 Checkpoint

- [ ] EMA values match TradingView within 0.1%
- [ ] EMA crosses detected at correct candle
- [ ] Momentum score formula produces directionally correct results on 10 test
      cases
- [ ] Momentum score weights (RSI 0.25, MACD 0.25, EMA 0.30, ADX 0.20) produce
      sensible outputs
- [ ] FMP endpoint format verified against current API docs
- [ ] RSI divergence field exists but returns `"none"` (deferred to Phase 1.5)

### Phase 1.5 Checkpoint (after Phase 1 ships)

- [ ] Swing high/low detection works on known examples
- [ ] RSI divergence detection correctly identifies bullish/bearish divergences
- [ ] False positive rate for divergence is acceptable (<20%)

### Phase 2 Checkpoint

- [ ] Perplexity output contains NO reference to sentiment or technicals
- [ ] Gemini output contains NO reference to fundamentals or technicals
- [ ] Claude output contains NO reference to fundamentals or sentiment
- [ ] All three tracks run concurrently (measure wall-clock time improvement)
- [ ] GPT receives all three clearly labeled independent analyses
- [ ] Gemini no longer receives `news_urls`/`key_highlights` from Perplexity
- [ ] Claude no longer receives `--- RECENT NEWS CONTEXT ---` from Gemini
- [ ] Lightweight pre-filter correctly drops obvious disqualifiers before
      parallel tracks
- [ ] Risk post-filter produces `risk_flags` and `risk_approved` for GPT input
- [ ] `_run_pipeline_v1()` still works identically to current behavior (A/B test
      safety)
- [ ] `_run_pipeline_v2()` dispatches correctly based on `pipeline_version`
      field

### Phase 3 Checkpoint

- [ ] Pipeline produces NO_TRADE when given intentionally conflicting signals
- [ ] Frontend renders NO_TRADE and WATCH correctly
- [ ] Track agreement breakdown visible in Synthesis tab
- [ ] DB CHECK constraint updated to allow new action values

### Phase 4 Checkpoint

- [ ] Claude cites specific numerical values in its analysis (not "appears to be
      crossing")
- [ ] Claude flags data quality concerns when chart contradicts numbers
- [ ] Claude's direction assessment matches numerical data in 90%+ of cases
- [ ] `TechnicalAssessment` model replaces `ChartAnalysis` throughout backend
      and frontend

### Phase 5 Checkpoint

- [ ] GPT's verdict references specific track disagreements
- [ ] GPT explains which tracks it weighted and why
- [ ] Low-agreement signals get lower confidence scores
- [ ] NO_TRADE signals produced when appropriate

### Phase 6 Checkpoint

- [ ] Failure modes correctly classified on historical trades
- [ ] Pattern statistics calculated correctly (extend existing reflection
      system)
- [ ] GPT references pattern statistics in synthesis
- [ ] Signal accuracy and execution accuracy tracked separately

---

## Migration Notes

### Prompt Versioning

Every prompt change in Phases 2, 4, 5 needs a version bump. Given the scale of
changes, reset to a new major version scheme:

```
Current versions (pre-overhaul):
  Regime: v2, Perplexity Discovery: v16, Perplexity Analysis: v8,
  Gemini: v6, Claude: v8, GPT Bull: v3, GPT Bear: v3, GPT Judge: v8

Post-overhaul: bump to next major for all changed prompts
  e.g., Claude v8 → v9, GPT Judge v8 → v9, Gemini v6 → v7
```

The `prompt_hash()` system (8-char SHA-256 in `utils/hashing.py`) automatically
detects content changes regardless of version string, so both tracking
mechanisms work.

### Database

Migration **`017_pipeline_v2.sql`** (combines Phase 3 + Phase 6 + feature flag
changes):

- ADD `pipeline_version` TEXT DEFAULT `'v1'` to `strategies` (feature flag for
  A/B test)
- ALTER `recommendations` CHECK constraint: add `NO_TRADE`, `WATCH` to allowed
  values
- ADD `track_agreement` JSONB to `recommendations` (nullable for backward
  compat)
- ADD `confidence_adjustment` TEXT to `recommendations` (nullable)
- ADD `failure_mode` TEXT to `outcomes` (nullable)
- ADD `structured_analysis` JSONB to `outcomes` (nullable)
- ADD `pattern_statistics` JSONB to `reflections` (nullable)

No new tables needed — all changes are additive columns on existing tables.

### Backward Compatibility

Old pipeline runs display correctly in History view. All new fields are nullable
— old runs show null, which the frontend handles gracefully (already the pattern
for optional fields).

### Feature Flags

Add a `pipeline_version` field to `StrategyConfig` and the `strategies` table:

- `v1` = legacy sequential pipeline (existing code, untouched)
- `v2` = new parallel independent pipeline

**Orchestrator branching strategy:**

```python
# In orchestrator.py — entry point dispatches based on strategy config
async def _run_pipeline(self, config: StrategyConfig, ...):
    if getattr(config, "pipeline_version", "v1") == "v2":
        return await self._run_pipeline_v2(config, ...)
    return await self._run_pipeline_v1(config, ...)
```

- `_run_pipeline_v1()` = rename of the current `_run_pipeline()` method, **zero
  changes to working code**
- `_run_pipeline_v2()` = new method implementing the parallel architecture
- This means the A/B test is safe — you're adding a new code path, not modifying
  the old one
- Migration `017_pipeline_v2.sql` adds `pipeline_version TEXT DEFAULT 'v1'` to
  `strategies` table
- All existing strategies default to `v1` and continue working exactly as before
- Switch individual strategies to `v2` to test, compare results in insights
  dashboard

---

## Success Metrics

After 50 trades on the new pipeline, measure:

1. **Directional accuracy:** % of trades where direction was correct
   (target: >55%)
2. **No-trade rate:** % of pipeline runs that produce NO_TRADE (target: 30-40% —
   if it's 0%, thresholds are too loose; if it's 80%, too tight)
3. **Win rate by agreement score:** 3/3 agree should win more than 2/3 agree
   should win more than disagree
4. **Track independence:** measure correlation between track outputs — they
   should NOT be >0.8 correlated
5. **EMA cross age at signal:** average should be <3 candles if timing is
   improved
6. **Feedback loop convergence:** pattern accuracy predictions should get closer
   to actual outcomes over time
