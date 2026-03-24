# SignalForge — Pipeline Deep Dive

> **Version:** 1.0.0
> **Last Updated:** March 24, 2026

This document explains how the SignalForge analysis pipeline works end-to-end,
from strategy configuration through each AI stage to final recommendations.

---

## 1. Strategy System — Where It All Starts

Every pipeline run is driven by a **strategy**. A strategy is a configuration
object (`StrategyConfig`) that tells each AI stage what to do — what stocks to
look for, which indicators to chart, how aggressively to filter, and what risk
parameters to apply.

### 1.1 Strategy Templates

Pre-built strategies ship in [`templates/strategies.json`](../templates/strategies.json).
This file is a JSON array of strategy objects, each with `"is_template": true`.
Templates cover common trading styles:

| Template | Purpose | Key Trait |
|----------|---------|-----------|
| Momentum Breakout | High-volume stocks near 52-week highs | `constraint_style: "tight"`, `max_tickers: 8` |
| Value Accumulation | Undervalued names with insider buying | `constraint_style: "loose"`, `max_tickers: 10` |
| Mean Reversion | Oversold stocks near support levels | `constraint_style: "tight"`, `max_tickers: 6` |
| Earnings Play | Stocks reporting earnings within 2 weeks | `constraint_style: "tight"`, `max_tickers: 5` |
| Crypto Swing | Crypto with strong momentum and on-chain metrics | `constraint_style: "loose"`, `max_tickers: 8` |
| Crypto Intraday Scalp | Short-term crypto scalps on 15m charts | `constraint_style: "tight"`, `max_tickers: 5` |
| Intraday Scalp | Short-term stock momentum scalps on 15m charts | `constraint_style: "tight"`, `max_tickers: 5` |

### 1.2 Template Seeding

Templates are not read from disk at runtime. They are a **seed file**: the
`ensure_defaults()` function in [`services/strategy.py`](../src/backend/services/strategy.py)
loads them into the `strategies` database table the first time the app starts
with an empty table.

```
Application starts
       │
       ▼
ensure_defaults()
       │
       ├── Is strategies table empty?
       │    ├── YES → Read templates/strategies.json
       │    │         Parse each entry → StrategyConfig
       │    │         INSERT INTO strategies (user_id="system")
       │    │
       │    └── NO  → Do nothing (templates already loaded)
```

After seeding, all strategy operations go through the database. Users can
create their own strategies (from scratch or by cloning a template) via the
Strategy Manager in the frontend.

### 1.3 StrategyConfig Fields

The `StrategyConfig` Pydantic model ([`pipeline/schemas.py`](../src/backend/pipeline/schemas.py))
groups fields by which pipeline stage consumes them:

| Field | Type | Used By | Purpose |
|-------|------|---------|---------|
| `screening_prompt` | `str` | Perplexity | Natural language instruction for stock screening |
| `constraint_style` | `"tight" \| "loose"` | Perplexity | How strictly screening filters must match |
| `max_tickers` | `int` | Perplexity | Cap on how many tickers to return |
| `chart_indicators` | `list[str]` | Claude | Which indicators to render on charts (RSI, MACD, etc.) |
| `chart_timeframe` | `str` | Claude | Primary chart timeframe (`"D"`, `"4H"`, `"W"`) |
| `additional_timeframes` | `list[str]` | Claude | Extra timeframes for multi-TF analysis |
| `short_timeframes` | `list[str]` | Claude | Intraday timeframes (`"15m"`, `"1H"`) |
| `short_tf_indicators` | `list[str]` | Claude | Indicators for short timeframe charts |
| `ta_focus` | `str` | Claude | What the chart analysis should emphasize |
| `news_recency` | `"today" \| "week" \| "month"` | Gemini | How recent the news should be |
| `news_scope` | `"company" \| "sector" \| "macro"` | Gemini | How broad the news scope should be |
| `trading_style` | `str` | GPT | Describes the trading approach for the judge |
| `risk_params` | `RiskParams` | GPT | Max position %, min risk/reward, max portfolio risk |
| `enable_debate` | `bool` | GPT | Whether to run bull/bear/judge (3 calls) or single synthesis |

---

## 2. Pipeline Execution Flow

The pipeline orchestrator ([`pipeline/orchestrator.py`](../src/backend/pipeline/orchestrator.py))
runs all stages sequentially. A pipeline run is triggered via the
`POST /api/pipeline/run` endpoint with a strategy ID, manual tickers, and/or a
free-form prompt.

```
                    ┌────────────────────────────┐
                    │   User triggers pipeline   │
                    │  (strategy_id / tickers /   │
                    │    free-form prompt)        │
                    └─────────────┬──────────────┘
                                  │
                                  ▼
                    ┌────────────────────────────┐
                    │  1. Determine mode          │
                    │  (discovery / analysis /    │
                    │   combined / prompt)        │
                    └─────────────┬──────────────┘
                                  │
                                  ▼
         ┌─────────────────────────────────────────────┐
         │  Stage 1: Perplexity (Sonar Pro)             │
         │  Screen the market or research given tickers │
         │  Output: ScreeningResult + news URLs         │
         └─────────────────┬───────────────────────────┘
                           │
                           ▼
         ┌─────────────────────────────────────────────┐
         │  Stage 2: Gemini (News Sentiment)            │
         │  Analyze news articles from Perplexity URLs  │
         │  Output: SentimentAnalysis per ticker        │
         └─────────────────┬───────────────────────────┘
                           │
                           ▼
         ┌─────────────────────────────────────────────┐
         │  Stage 3: Claude Vision (Chart Analysis)     │
         │  Read chart images with news context         │
         │  Output: ChartAnalysis per ticker/timeframe  │
         └─────────────────┬───────────────────────────┘
                           │
                           ▼
         ┌─────────────────────────────────────────────┐
         │  Stage 4: GPT (Bull/Bear/Judge Debate)       │
         │  Synthesize all data into recommendations    │
         │  Output: Recommendation per ticker           │
         └─────────────────┬───────────────────────────┘
                           │
                           ▼
         ┌─────────────────────────────────────────────┐
         │  Stage 4.5: Annotated Charts                 │
         │  Overlay key levels on chart images           │
         │  Output: annotated chart URLs                │
         └─────────────────┬───────────────────────────┘
                           │
                           ▼
                    ┌────────────────────────────┐
                    │   PipelineResult returned   │
                    │   Dashboard displays it     │
                    └────────────────────────────┘
```

### 2.1 Pipeline Modes

The orchestrator chooses a mode based on what inputs are provided:

| Mode | Inputs | What Happens |
|------|--------|-------------|
| **discovery** | `strategy_id` only | Perplexity screens the market using the strategy's `screening_prompt` |
| **analysis** | `manual_tickers` only | Perplexity researches the given tickers (no screening) |
| **combined** | `strategy_id` + `manual_tickers` | Discovery runs first, then analysis combines both ticker lists |
| **prompt** | `user_prompt` (± strategy) | User's free-form text drives the screening |

---

## 3. Stage 1 — Perplexity (Stock Screening)

**Model:** Sonar Pro (via OpenAI-compatible API)
**Files:** [`pipeline/stages/perplexity.py`](../src/backend/pipeline/stages/perplexity.py),
[`pipeline/prompts/perplexity_discovery.py`](../src/backend/pipeline/prompts/perplexity_discovery.py),
[`pipeline/prompts/perplexity_analysis.py`](../src/backend/pipeline/prompts/perplexity_analysis.py)

Perplexity is the entry point of the pipeline. It uses real-time web search to
find or research stocks. Unlike the other stages, Perplexity's LLM has access
to current market data because Sonar Pro performs live web searches before
generating a response.

### 3.1 How the Strategy Drives Perplexity

In **discovery mode**, `build_discovery_prompt()` constructs the user prompt
from three strategy fields:

```python
def build_discovery_prompt(config: StrategyConfig) -> str:
    constraint_instruction = (
        "Apply strict filtering — only return tickers that strongly match ALL criteria."
        if config.constraint_style == "tight"
        else "Apply loose filtering — return tickers that match most criteria, even partially."
    )

    return (
        f"Strategy: {config.name}\n\n"
        f"Screening criteria:\n{config.screening_prompt}\n\n"
        f"{constraint_instruction}\n\n"
        f"Return up to {config.max_tickers} tickers as JSON. "
        f"Include both traditional securities and crypto if the criteria apply."
    )
```

For a "Momentum Breakout" strategy, the assembled prompt looks like:

```
Strategy: Momentum Breakout

Screening criteria:
Find Canadian stocks (TSX, TSX-V listed) with high relative volume (>2x average),
trading near 52-week highs, with bullish technical breakout patterns. Focus on
mid-to-large cap Canadian companies with strong earnings growth. Only include
stocks trading on Canadian exchanges.

Apply strict filtering — only return tickers that strongly match ALL criteria.

Return up to 8 tickers as JSON. Include both traditional securities and crypto
if the criteria apply.
```

The **system prompt** (`DISCOVERY_SYSTEM_PROMPT`) defines the JSON output
schema, ticker formatting rules (TradingView format like `TSX:ENB` not `.TO`),
and requires `news_urls` for each ticker. These URLs feed into Gemini in
Stage 2.

### 3.2 Discovery vs. Analysis vs. Prompt Modes

| Mode | Prompt Builder | What It Asks Perplexity |
|------|---------------|------------------------|
| Discovery | `build_discovery_prompt(config)` | "Screen the market for stocks matching these criteria" |
| Analysis | `build_analysis_prompt(tickers, config)` | "Research these specific tickers and return fundamentals" |
| Prompt | `build_prompted_discovery_prompt(user_prompt, config)` | User's free-form text, optionally constrained by strategy |

### 3.3 Validation and Retry

The `_call_perplexity()` function is decorated with `@with_validation_retry`:

1. Perplexity returns raw text (may include markdown fences).
2. `extract_json()` strips fences and finds the JSON object.
3. `ScreeningResult.model_validate()` validates against the Pydantic schema.
4. On validation failure: retries up to 2 times, appending the error to the
   prompt so Perplexity can self-correct.
5. On final failure: returns `None` and the pipeline records a stage error.

### 3.4 Output Schema

Perplexity returns a `ScreeningResult` containing a list of `FundamentalData`:

```python
class FundamentalData(BaseModel):
    ticker: str                              # e.g. "TSX:CNQ"
    company_name: str                        # e.g. "Canadian Natural Resources"
    asset_type: Literal["stock", "etf", "crypto"]
    sector: str                              # e.g. "Energy"
    market_cap: str | None                   # e.g. "$85B"
    pe_ratio: float | None
    revenue_growth: str | None               # e.g. "+15% YoY"
    free_cash_flow: str | None               # e.g. "$2.3B"
    key_highlights: list[str]
    risk_factors: list[str]
    sources: list[str]
    news_urls: list[str]                     # ← fed into Gemini Stage 2

class ScreeningResult(BaseModel):
    mode: Literal["discovery", "analysis", "prompt"]
    strategy_name: str | None
    tickers: list[FundamentalData]
    screening_summary: str
```

### 3.5 Concurrency

A `Semaphore(3)` limits concurrent Perplexity API calls to avoid rate limiting.

---

## 4. Stage 2 — Gemini (News Sentiment)

**Model:** Gemini
**Input:** Ticker list + `news_urls` from Perplexity's output
**Output:** `SentimentAnalysis` per ticker

Gemini receives the article URLs that Perplexity discovered and performs
grounded sentiment analysis. The strategy's `news_recency` and `news_scope`
fields control how Gemini scopes its analysis.

Gemini runs **before** Claude so that chart analysis in Stage 3 has news
context — Claude's prompt includes sentiment data when available.

### 4.1 Degraded Mode

If Gemini fails, the pipeline continues without sentiment data. Claude proceeds
without the "Recent News Context" section in its prompt, and the GPT judge is
informed that sentiment data is unavailable.

---

## 5. Stage 3 — Claude Vision (Chart Analysis)

**Model:** Claude (Anthropic)
**Input:** Chart images + strategy indicators + sentiment context
**Output:** `ChartAnalysis` per ticker per timeframe

Claude analyzes chart images generated by the Chart-Img v2 API. The strategy's
`chart_indicators`, `chart_timeframe`, `additional_timeframes`,
`short_timeframes`, and `ta_focus` fields control what charts are generated and
what Claude looks for.

Claude runs **two or more timeframes** per ticker concurrently (e.g., Daily +
4H + Weekly). Each timeframe produces a separate `ChartAnalysis` with trend
direction, key levels, indicator readings, and overall bias.

### 5.1 Degraded Mode

If Claude fails, GPT proceeds with Perplexity fundamentals and Gemini
sentiment only (no chart data). The GPT judge prompt notes that chart analysis
is unavailable.

---

## 6. Stage 4 — GPT (Bull/Bear/Judge Debate)

**Model:** GPT (OpenAI)
**Input:** All upstream data (screening, sentiment, charts) + strategy config
**Output:** `Recommendation` per ticker

When `enable_debate` is true, GPT makes three calls per ticker:

1. **Bull case** — argues for buying
2. **Bear case** — argues for selling
3. **Judge** — weighs both cases and renders a final `BUY`, `SELL`, or `HOLD`
   recommendation with entry price, stop loss, take profit, and confidence

Bull and Bear run **concurrently**. The Judge runs after both complete.

The strategy's `trading_style` and `risk_params` shape how the judge sizes
positions and sets risk/reward targets.

When `enable_debate` is false (e.g., Intraday Scalp strategies), GPT makes a
single synthesis call instead of the 3-call debate.

### 6.1 Self-Learning Injection

Before the judge prompt, the orchestrator loads `reflection_context` — a
text blob generated by the reflection engine from past outcomes. This is
prepended to the judge system prompt, giving GPT concrete performance stats
(win rates, confidence calibration, sector patterns) so it improves over time.

---

## 7. Stage 4.5 — Annotated Charts

**Input:** `ChartAnalysis` key levels + `Recommendation` trade parameters
**Output:** Annotated chart image URLs (stored in Supabase Storage)

After GPT produces recommendations, the pipeline overlays key levels (support,
resistance) and trade parameters (entry, stop loss, take profit) onto chart
images as horizontal lines via the Chart-Img v2 drawings API.

Annotated charts are persisted to Supabase Storage and their URLs are written
back into both the in-memory `ChartAnalysis` objects and the `stage_outputs`
database table.

---

## 8. Pipeline Result

The final `PipelineResult` bundles everything:

```python
class PipelineResult(BaseModel):
    run_id: str
    timestamp: datetime
    strategy_name: str | None
    mode: Literal["discovery", "analysis", "combined", "prompt"]
    input_tickers: list[str]
    screening: ScreeningResult | None           # Stage 1
    sentiment_analyses: list[SentimentAnalysis]  # Stage 2
    chart_analyses: list[ChartAnalysis]          # Stage 3
    chart_errors: list[ChartError]               # Stage 3 errors
    recommendations: list[Recommendation]        # Stage 4
    stage_errors: list[dict]                     # Any stage failures
    total_duration_seconds: float
    prompt_versions: dict[str, str]              # Hash of each prompt
    chart_indicators: list[str]
```

The orchestrator saves everything to the database:
- `pipeline_runs` — run metadata, status, timing, prompt versions
- `stage_outputs` — raw prompt/response for each stage call (audit trail)
- `recommendations` — validated trade recommendations

---

## 9. Degraded Pipeline Behavior

The pipeline is designed to survive partial failures. If a non-critical stage
fails, downstream stages adapt:

| Failed Stage | Impact | Downstream Behavior |
|-------------|--------|---------------------|
| Perplexity | No tickers found | Pipeline ends early with error |
| Gemini | No sentiment data | Claude skips news context; GPT notes "sentiment unavailable" |
| Claude | No chart analysis | GPT synthesizes from fundamentals + sentiment only |
| GPT | No recommendations | Pipeline returns partial result with screening + charts |

Errors are tracked in `PipelineResult.stage_errors` so the frontend can
display which stages succeeded and which degraded.

---

## 10. Validation Layer

Every LLM response passes through the same validation pipeline
([`pipeline/validation.py`](../src/backend/pipeline/validation.py)):

1. **Extract JSON** — strips markdown fences, finds `{...}` or `[...]`
2. **Parse** — `json.loads()` into a Python dict
3. **Validate** — `PydanticModel.model_validate(data)` against the stage schema
4. **Retry on failure** — re-calls the LLM with the validation error appended
   to the prompt (up to 2 retries)
5. **Return `None` on exhaustion** — logs the error, pipeline continues degraded

This ensures no raw JSON dicts flow through the system — every piece of data
is a typed, validated Pydantic model.

---

## 11. Prompt Versioning

Every prompt template has a `PROMPT_VERSION` constant and a `get_prompt_hash()`
function that returns a SHA-256 hash of the prompt text. When the pipeline
completes, all prompt hashes are stored in `pipeline_runs.prompt_versions`.

This enables tracking which prompt versions correlate with better or worse
recommendation outcomes over time, forming the foundation of the self-learning
loop.

---

## 12. Data Flow Summary

```
templates/strategies.json ──(seed on first boot)──▶ strategies table (Postgres)
                                                          │
                                                          ▼
                                          get_strategy(id) → StrategyConfig
                                                          │
              ┌───────────────────────────────────────────┤
              │                                           │
              ▼                                           ▼
     screening_prompt                            chart_indicators
     constraint_style                            chart_timeframe
     max_tickers                                 additional_timeframes
              │                                  ta_focus
              ▼                                           │
     ┌─────────────────┐                                  ▼
     │   Perplexity     │                       ┌─────────────────┐
     │   (Stage 1)      │─── tickers ──────────▶│   Claude Vision  │
     │   + news_urls    │    + news_urls        │   (Stage 3)      │
     └────────┬────────┘        │               └────────┬────────┘
              │                 ▼                        │
              │        ┌─────────────────┐               │
              │        │   Gemini         │               │
              │        │   (Stage 2)      │───sentiment──▶│
              │        └─────────────────┘               │
              │                                          │
              └────────── fundamentals ──────────────────┤
                                                         │
                                                         ▼
                                               ┌─────────────────┐
                                               │   GPT Judge      │
                                               │   (Stage 4)      │
                                               └────────┬────────┘
                                                        │
                                                        ▼
                                                 Recommendation
                                               (BUY / SELL / HOLD)
```

---

## 13. File Reference

| File | Purpose |
|------|---------|
| `templates/strategies.json` | Seed strategy templates |
| `services/strategy.py` | Strategy CRUD, template seeding |
| `pipeline/schemas.py` | All Pydantic models (StrategyConfig, ScreeningResult, etc.) |
| `pipeline/orchestrator.py` | Pipeline execution engine |
| `pipeline/validation.py` | JSON extraction, Pydantic validation, retry logic |
| `pipeline/stages/perplexity.py` | Perplexity Sonar API integration |
| `pipeline/stages/gemini.py` | Gemini sentiment analysis |
| `pipeline/stages/claude.py` | Claude Vision chart analysis |
| `pipeline/stages/gpt.py` | GPT bull/bear/judge debate |
| `pipeline/prompts/perplexity_discovery.py` | Discovery mode prompt template |
| `pipeline/prompts/perplexity_analysis.py` | Analysis mode prompt template |
| `pipeline/prompts/gemini_sentiment.py` | Gemini prompt template |
| `pipeline/prompts/claude_chart.py` | Claude prompt template |
| `pipeline/prompts/gpt_debate.py` | GPT debate prompt templates |
| `services/chart_image.py` | Chart-Img v2 API, annotated chart overlays |
| `services/reflection.py` | Self-learning reflection engine |
