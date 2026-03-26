---
name:
  Pipeline Improvements v2 — Data Flow, Multi-TF Synthesis, Reliability, and Gap
  Fixes
overview: |
  Rich FMP data (insider activity, Piotroski, analyst targets, earnings dates, composite scores)
  currently dies after Perplexity. This plan threads it through all downstream stages (Gemini,
  Claude, GPT), adds a multi-timeframe synthesis step to Claude, hardens the orchestrator with
  per-stage timeouts and retry tracking, and closes miscellaneous gaps (FMP tool definition,
  strategy CRUD, user_prompt persistence, annotated chart error tracking).
todos:
  - id: fmp-data-threading
    content:
      Thread FMP candidates through orchestrator to Gemini, Claude, and GPT
      prompts
    status: pending
  - id: gemini-fmp-context
    content:
      Inject company name, sector, earnings date, and insider data into Gemini
      prompts
    status: pending
  - id: claude-fmp-context
    content:
      Inject earnings date, insider activity, and analyst targets into Claude
      chart prompts
    status: pending
  - id: gpt-fmp-context
    content:
      Add structured FMP data section to bull/bear/judge prompts (not just
      Perplexity echo)
    status: pending
  - id: multi-tf-synthesis
    content:
      Add multi-timeframe synthesis step after Claude completes all timeframes
      per ticker
    status: pending
  - id: stage-timeouts
    content:
      Wrap each orchestrator stage in asyncio.wait_for with configurable
      timeouts
    status: pending
  - id: retry-tracking
    content:
      Propagate actual retry count from validation decorator to stage metadata
    status: pending
  - id: annotated-chart-errors
    content: Track annotated chart failures in PipelineResult.stage_errors
    status: pending
  - id: gpt-semaphore
    content: Add concurrency semaphore to GPT stage
    status: pending
  - id: fmp-tool-expansion
    content:
      Expand FMP tool definition to expose new screening fields to Perplexity
    status: pending
  - id: strategy-crud
    content: Add update_strategy and delete_strategy to service + API routes
    status: pending
  - id: user-prompt-persistence
    content: Persist user_prompt in pipeline_runs DB row for prompt-mode runs
    status: pending
  - id: prompt-version-bumps
    content: Bump all prompt versions after content changes
    status: pending
  - id: frontend-sync
    content:
      Sync any new StrategyConfig fields or schema changes to TypeScript types
    status: pending
isProject: true
---

# Pipeline Improvements v2

## Problem

The FMP pre-screening stage (Stage 0) now produces rich per-stock data: insider
activity, Piotroski quality scores, analyst consensus and price target upside,
price momentum (1D/1M/3M), relative volume, earnings dates, beat rates, and a
multi-factor composite score. However, this data is formatted into a text blob
for Perplexity only — Gemini, Claude, and GPT never see it directly. GPT
receives only what Perplexity echoes back in `ScreeningResult.FundamentalData`,
which has ~15 fields vs FMP's 30+. This is the biggest data leak in the
pipeline.

Additionally, Claude analyzes each timeframe independently with no
cross-timeframe awareness, the orchestrator has no per-stage timeouts, retry
counts are always written as 0, and several smaller gaps (strategy CRUD, FMP
tool definition, error tracking) reduce operational quality.

## Solution

1. **Thread FMP data everywhere** — Store `fmp_candidates` on the orchestrator
   scope and pass it to all downstream stages via new helper functions that
   format the relevant subset for each stage's prompt.
2. **Multi-timeframe synthesis** — After Claude completes all timeframe analyses
   for a ticker, group them and add a synthesis section to the GPT prompt that
   explicitly cross-references timeframes (rather than a separate Claude call,
   which would add cost without visual context).
3. **Operational hardening** — Per-stage timeouts, retry tracking, GPT
   semaphore, annotated chart error tracking.
4. **Gap closure** — Expand FMP tool, add strategy update/delete, persist
   user_prompt.

## Implementation Steps

### Step 1: fmp-data-threading

Thread FMP candidates through the orchestrator so all stages can access them.

**Files:**
`[src/backend/pipeline/orchestrator.py](src/backend/pipeline/orchestrator.py)`

Changes:

- Keep `fmp_candidates` in scope after Stage 0 (already done).
- Build a `fmp_map: dict[str, FmpEnrichedStock]` keyed by ticker symbol for O(1)
  lookups.
- Pass `fmp_map` to `run_sentiment()`, `run_chart_analysis()`, and
  `run_debate()`.
- No schema changes needed — `FmpEnrichedStock` is already importable.

```python
# After Stage 0 completes:
fmp_map: dict[str, FmpEnrichedStock] = {}
if fmp_candidates:
    fmp_map = {s.symbol: s for s in fmp_candidates}

# Stage 2: pass to Gemini
sentiments, gemini_metadata_list = await run_sentiment(
    ticker_symbols, effective_config, ticker_news=ticker_news or None,
    fmp_context=fmp_map or None,
)

# Stage 3: pass to Claude
charts, claude_metadata_list = await run_chart_analysis(
    ticker_symbols, effective_config, result.sentiment_analyses,
    run_id, user_id, fmp_context=fmp_map or None,
)

# Stage 4: pass to GPT
recommendations, gpt_metadata_list = await run_debate(
    ticker_symbols, screening, result.chart_analyses,
    result.sentiment_analyses, effective_config, reflection_context,
    run_id, fmp_context=fmp_map or None,
)
```

---

### Step 2: gemini-fmp-context

Inject company context from FMP into Gemini's sentiment prompt so it can assess
news impact with knowledge of the company's fundamentals, upcoming earnings, and
insider activity.

**Files:**

- `[src/backend/pipeline/prompts/gemini_sentiment.py](src/backend/pipeline/prompts/gemini_sentiment.py)`
- `[src/backend/pipeline/stages/gemini.py](src/backend/pipeline/stages/gemini.py)`

Changes to `build_sentiment_prompt()`:

- Add optional `fmp_context: str | None` parameter.
- When present, insert a `--- COMPANY CONTEXT ---` section before the JSON
  instructions.

```python
def build_sentiment_prompt(
    ticker: str,
    config: StrategyConfig,
    news_urls: list[str] | None = None,
    fmp_context: str | None = None,  # NEW
) -> str:
    # ... existing code ...
    if fmp_context:
        parts.append(f"--- COMPANY CONTEXT (from FMP) ---\n{fmp_context}\n--- END CONTEXT ---\n")
    # ...
```

New helper `format_fmp_for_gemini()` in `gemini_sentiment.py` (or a shared
`pipeline/fmp_context.py`):

```python
def format_fmp_for_gemini(stock: FmpEnrichedStock) -> str:
    """Format FMP data relevant to sentiment analysis."""
    parts = [f"Company: {stock.company_name} ({stock.symbol})"]
    if stock.sector:
        parts.append(f"Sector: {stock.sector}")
    if stock.earnings_date:
        parts.append(f"Upcoming earnings: {stock.earnings_date}")
    if stock.insider_net_buys is not None:
        direction = "NET BUYING" if stock.insider_net_buys > 0 else "NET SELLING"
        parts.append(f"Insider activity: {direction} ({stock.insider_net_buys:+d} transactions)")
    if stock.analyst_consensus:
        parts.append(f"Analyst consensus: {stock.analyst_consensus}")
    if stock.analyst_target_upside is not None:
        parts.append(f"Price target upside: {stock.analyst_target_upside:+.1f}%")
    if stock.market_cap:
        parts.append(f"Market cap: ${stock.market_cap:,.0f}")
    return "\n".join(parts)
```

Changes to `run_sentiment()` in `stages/gemini.py`:

- Add `fmp_context: dict[str, FmpEnrichedStock] | None = None` parameter.
- Look up each ticker in the map and format context for the prompt.

Bump `PROMPT_VERSION` in `gemini_sentiment.py`.

---

### Step 3: claude-fmp-context

Inject FMP context into Claude's chart analysis prompt so chart patterns are
interpreted with knowledge of fundamentals, upcoming earnings, and insider
activity.

**Files:**

- `[src/backend/pipeline/prompts/claude_chart.py](src/backend/pipeline/prompts/claude_chart.py)`
- `[src/backend/pipeline/stages/claude.py](src/backend/pipeline/stages/claude.py)`

Changes to `build_chart_prompt()`:

- Add optional `fmp_context: str | None` parameter.
- Insert a `--- FUNDAMENTAL CONTEXT ---` section after the news context section.

```python
def build_chart_prompt(
    ticker: str,
    config: StrategyConfig,
    sentiment: SentimentAnalysis | None = None,
    timeframe_override: str | None = None,
    indicators_override: list[str] | None = None,
    fmp_context: str | None = None,  # NEW
) -> str:
    # ... existing code ...
    if fmp_context:
        parts.append(
            f"\n--- FUNDAMENTAL CONTEXT (from FMP) ---"
            f"\n{fmp_context}"
            f"\nUse this context to weight your technical assessment. "
            f"A breakout in a stock with strong insider buying and high Piotroski "
            f"score is more meaningful than the same pattern in a low-quality stock."
            f"\n--- END FUNDAMENTAL CONTEXT ---"
        )
    # ...
```

New helper `format_fmp_for_claude()`:

```python
def format_fmp_for_claude(stock: FmpEnrichedStock) -> str:
    """Format FMP data relevant to chart analysis context."""
    parts = [f"Company: {stock.company_name} ({stock.symbol})"]
    if stock.sector:
        parts.append(f"Sector: {stock.sector}")
    if stock.earnings_date:
        parts.append(f"UPCOMING EARNINGS: {stock.earnings_date} — expect volatility")
    if stock.insider_net_buys is not None and stock.insider_net_buys > 0:
        parts.append(f"Insider buying: {stock.insider_net_buys:+d} net transactions (bullish signal)")
    if stock.piotroski_score is not None:
        quality = "strong" if stock.piotroski_score >= 7 else "moderate" if stock.piotroski_score >= 5 else "weak"
        parts.append(f"Piotroski score: {stock.piotroski_score}/9 ({quality} fundamentals)")
    if stock.analyst_target_upside is not None:
        parts.append(f"Analyst target upside: {stock.analyst_target_upside:+.1f}%")
    if stock.relative_volume is not None:
        parts.append(f"Relative volume: {stock.relative_volume:.1f}x average")
    if stock.composite_score is not None:
        parts.append(f"Composite quality score: {stock.composite_score:.0f}/100")
    return "\n".join(parts)
```

Changes to `_analyze_ticker()` and `run_chart_analysis()` in `stages/claude.py`:

- Thread `fmp_context` parameter through to `build_chart_prompt()`.

Bump `PROMPT_VERSION` in `claude_chart.py`.

---

### Step 4: gpt-fmp-context

Add a structured FMP data section to GPT prompts so bull/bear/judge have direct
access to quantitative FMP data — not just what Perplexity chose to echo back.

**Files:**

- `[src/backend/pipeline/prompts/gpt_debate.py](src/backend/pipeline/prompts/gpt_debate.py)`
- `[src/backend/pipeline/stages/gpt.py](src/backend/pipeline/stages/gpt.py)`

New helper `_format_fmp_data()` in `gpt_debate.py`:

```python
def _format_fmp_data(
    fmp_context: dict[str, FmpEnrichedStock] | None,
    tickers: list[str],
) -> str:
    """Format structured FMP data for GPT prompts."""
    if not fmp_context:
        return "No FMP pre-screening data available."
    parts: list[str] = []
    for ticker in tickers:
        stock = fmp_context.get(ticker)
        if not stock:
            parts.append(f"\n### {ticker}\nNo FMP data available.")
            continue
        lines = [f"\n### {stock.symbol} — {stock.company_name}"]
        if stock.composite_score is not None:
            lines.append(f"Composite Score: {stock.composite_score:.0f}/100 "
                         f"(F:{stock.score_fundamental:.0f} M:{stock.score_momentum:.0f} "
                         f"S:{stock.score_sentiment:.0f} Q:{stock.score_quality:.0f})")
        # ... insider, analyst, momentum, quality fields ...
        parts.append("\n".join(lines))
    return "\n".join(parts)
```

Changes to `build_bull_prompt()`, `build_bear_prompt()`, `build_judge_prompt()`:

- Add `fmp_context: dict[str, FmpEnrichedStock] | None = None` parameter.
- Insert `## QUANTITATIVE DATA (FMP)\n{_format_fmp_data(fmp_context, tickers)}`
  section between FUNDAMENTALS and TECHNICAL ANALYSIS.

Changes to `run_debate()` and `_run_debate_phase()` / `_run_judge_phase()` in
`stages/gpt.py`:

- Thread `fmp_context` parameter through.

Bump `BULL_PROMPT_VERSION`, `BEAR_PROMPT_VERSION`, `JUDGE_PROMPT_VERSION`.

---

### Step 5: multi-tf-synthesis

Add a multi-timeframe synthesis section to the GPT prompt that explicitly
cross-references Claude's analyses across timeframes for the same ticker, rather
than leaving GPT to reconcile a flat list.

**Files:**

- `[src/backend/pipeline/prompts/gpt_debate.py](src/backend/pipeline/prompts/gpt_debate.py)`

Changes to `_format_chart_data()`:

- After listing all timeframes for a ticker, add a synthesis subsection that
  highlights:
  - Whether timeframes **agree** (convergence = higher confidence) or
    **conflict**
  - The dominant trend across timeframes
  - Any timeframe-specific signals (e.g., "4H shows reversal within Daily
    downtrend")

```python
def _format_chart_data(charts: list[ChartAnalysis], tickers: list[str]) -> str:
    # ... existing grouping code ...
    for ticker in tickers:
        ticker_charts = chart_map.get(ticker)
        if not ticker_charts:
            parts.append(f"\n### {ticker}\nNo chart analysis available.")
            continue

        parts.append(f"\n### {ticker}")
        for ca in ticker_charts:
            parts.append(_format_single_chart(ca))

        # NEW: multi-timeframe synthesis
        if len(ticker_charts) > 1:
            parts.append(_synthesize_timeframes(ticker, ticker_charts))
    return "\n".join(parts)


def _synthesize_timeframes(ticker: str, charts: list[ChartAnalysis]) -> str:
    """Generate a cross-timeframe synthesis for GPT."""
    biases = {ca.timeframe: ca.overall_bias for ca in charts}
    trends = {ca.timeframe: ca.trend_direction for ca in charts}

    # Check alignment
    unique_biases = set(biases.values())
    all_bullish = all("bullish" in b for b in unique_biases)
    all_bearish = all("bearish" in b for b in unique_biases)
    mixed = not all_bullish and not all_bearish

    lines = [f"\n#### Multi-Timeframe Synthesis for {ticker}"]
    lines.append(f"Timeframes analyzed: {', '.join(biases.keys())}")
    lines.append(f"Bias alignment: {', '.join(f'{tf}={b}' for tf, b in biases.items())}")

    if all_bullish:
        lines.append("CONVERGENCE: All timeframes bullish — HIGH confidence signal.")
    elif all_bearish:
        lines.append("CONVERGENCE: All timeframes bearish — HIGH confidence signal.")
    elif mixed:
        lines.append("DIVERGENCE: Timeframes show mixed signals — assess carefully.")
        # Identify conflicts
        for tf, bias in biases.items():
            if "bullish" in bias and any("bearish" in b for b in biases.values()):
                lines.append(f"  - {tf} is {bias} while other timeframes are bearish")
            elif "bearish" in bias and any("bullish" in b for b in biases.values()):
                lines.append(f"  - {tf} is {bias} while other timeframes are bullish")

    return "\n".join(lines)
```

No version bump needed for this — it's part of the same prompt changes in
step 4.

---

### Step 6: stage-timeouts

Wrap each orchestrator stage in `asyncio.wait_for` with configurable timeouts.

**Files:**
`[src/backend/pipeline/orchestrator.py](src/backend/pipeline/orchestrator.py)`

Add timeout constants at module level:

```python
STAGE_TIMEOUTS: dict[str, float] = {
    "fmp": 90.0,
    "perplexity": 180.0,
    "gemini": 120.0,
    "claude": 180.0,
    "gpt": 180.0,
    "annotate": 60.0,
}
```

Wrap each stage call:

```python
# Stage 0 example:
try:
    fmp_candidates = await asyncio.wait_for(
        screen_and_enrich(config.fmp_screener),
        timeout=STAGE_TIMEOUTS["fmp"],
    )
except asyncio.TimeoutError:
    logger.error("FMP stage timed out after %ss", STAGE_TIMEOUTS["fmp"])
    result.stage_errors.append({
        "stage": "fmp", "error": "Stage timed out", "type": "TimeoutError"
    })
```

Apply the same pattern to all stage calls in the orchestrator.

---

### Step 7: retry-tracking

Propagate actual retry count from the validation decorator to stage metadata.

**Files:**

- `[src/backend/pipeline/validation.py](src/backend/pipeline/validation.py)`
- `[src/backend/pipeline/orchestrator.py](src/backend/pipeline/orchestrator.py)`

The `with_validation_retry` decorator currently returns `T | None`. Change the
wrapper to attach the retry count to the returned model instance via a dunder
attribute:

```python
# In validation.py wrapper:
for attempt in range(1 + max_retries):
    # ... existing logic ...
    try:
        raw_text = await fn(*args, **kwargs)
        validated = validate_llm_json(raw_text, schema)
        validated.__dict__["_retry_count"] = attempt  # attach retry count
        return validated
    except ...
```

Then in each stage, read it back:

```python
# In stages, after getting result:
retry_count = getattr(result, "_retry_count", 0) if result else 0
metadata["retry_count"] = retry_count
```

Update `_save_stage_output()` in orchestrator to use the actual `retry_count`
from metadata instead of hardcoded `0`.

---

### Step 8: annotated-chart-errors

Track annotated chart failures in `PipelineResult.stage_errors` instead of only
logging.

**Files:**
`[src/backend/pipeline/orchestrator.py](src/backend/pipeline/orchestrator.py)`

Change the `_annotate()` inner function:

```python
async def _annotate(ca_index: int) -> None:
    ca = result.chart_analyses[ca_index]
    rec = rec_map.get(ca.ticker)
    try:
        url = await fetch_annotated_chart(...)
        result.chart_analyses[ca_index].annotated_chart_path = url
    except Exception as exc:
        logger.warning("Annotated chart failed for %s %s: %s", ca.ticker, ca.timeframe, exc)
        result.stage_errors.append({
            "stage": "annotate",
            "error": str(exc),
            "type": type(exc).__name__,
            "ticker": ca.ticker,
        })
```

---

### Step 9: gpt-semaphore

Add a concurrency semaphore to the GPT stage to prevent rate limit issues.

**Files:**
`[src/backend/pipeline/stages/gpt.py](src/backend/pipeline/stages/gpt.py)`

```python
_semaphore = asyncio.Semaphore(3)

async def _call_gpt(...) -> str:
    # ...
    async with _semaphore:
        response = await client.chat.completions.create(...)
    return response.choices[0].message.content or ""
```

---

### Step 10: fmp-tool-expansion

Expand the FMP tool definition so Perplexity can use the new screening fields
when making dynamic tool calls.

**Files:**
`[src/backend/pipeline/tools/fmp_tool.py](src/backend/pipeline/tools/fmp_tool.py)`

Add these properties to `FMP_TOOL_DEFINITION["parameters"]["properties"]`:

```python
"pe_max": {"type": "number", "description": "Maximum P/E ratio filter"},
"roe_min": {"type": "number", "description": "Minimum return on equity (%)"},
"debt_equity_max": {"type": "number", "description": "Maximum debt-to-equity ratio"},
"piotroski_min": {"type": "integer", "description": "Minimum Piotroski score (0-9)"},
"require_insider_buying": {"type": "boolean", "description": "Only include stocks with net insider buying"},
"rvol_min": {"type": "number", "description": "Minimum relative volume (volume/avgVolume)"},
"earnings_within_days": {"type": "integer", "description": "Only include stocks reporting earnings within N days"},
```

Update `execute_fmp_tool()` and `screen_stocks_from_params()` to pass through
the new fields. Enable `enrich_with_ratios=True` when any ratio-dependent filter
is provided, so the tool call results include scoring data.

---

### Step 11: strategy-crud

Add update and delete operations to the strategy service and API.

**Files:**

- `[src/backend/services/strategy.py](src/backend/services/strategy.py)`
- `[src/backend/api/strategies.py](src/backend/api/strategies.py)`

New functions in `services/strategy.py`:

```python
async def update_strategy(strategy_id: str, config: StrategyConfig, user_id: str) -> StrategyConfig:
    """Update an existing strategy owned by the user."""
    # Verify ownership, build payload (same as create), use .update().eq("id", strategy_id)
    ...

async def delete_strategy(strategy_id: str, user_id: str) -> None:
    """Delete a strategy owned by the user. Templates cannot be deleted."""
    # Verify ownership + not a template, then .delete().eq("id", strategy_id)
    ...
```

New API endpoints in `api/strategies.py`:

```python
@router.put("/{strategy_id}", response_model=StrategyConfig)
async def update_existing_strategy(strategy_id: str, config: StrategyConfig, user_id: CurrentUser):
    ...

@router.delete("/{strategy_id}", status_code=204)
async def delete_existing_strategy(strategy_id: str, user_id: CurrentUser):
    ...
```

---

### Step 12: user-prompt-persistence

Save the user's free-form prompt in the `pipeline_runs` database row.

**Files:**
`[src/backend/pipeline/orchestrator.py](src/backend/pipeline/orchestrator.py)`

Add `user_prompt` to the initial INSERT:

```python
await (
    client.table("pipeline_runs")
    .insert({
        "id": run_id,
        "user_id": user_id,
        "strategy_id": strategy_id,
        "mode": mode,
        "manual_tickers": json.dumps(manual_tickers or []),
        "user_prompt": user_prompt,  # NEW
        "status": "running",
        "started_at": result.timestamp.isoformat(),
    })
    .execute()
)
```

May require a migration if `user_prompt` column doesn't exist on the table.

---

### Step 13: prompt-version-bumps

After all prompt content changes, bump version constants:

**Files:**

- `[src/backend/pipeline/prompts/gemini_sentiment.py](src/backend/pipeline/prompts/gemini_sentiment.py)`:
  `v2` -> `v3`
- `[src/backend/pipeline/prompts/claude_chart.py](src/backend/pipeline/prompts/claude_chart.py)`:
  `v4` -> `v5`
- `[src/backend/pipeline/prompts/gpt_debate.py](src/backend/pipeline/prompts/gpt_debate.py)`:
  Bull `v1` -> `v2`, Bear `v1` -> `v2`, Judge `v3` -> `v4`

---

### Step 14: frontend-sync

Sync any new TypeScript types if schema changes were made.

**Files:** `[src/frontend/src/types/index.ts](src/frontend/src/types/index.ts)`

No new Pydantic schema fields are being added (FMP data flows through existing
models). The only frontend change needed is adding the strategy update/delete
API calls in the frontend client if they don't already exist.

---

## Risks / Open Questions

- **Prompt token budget**: Adding FMP context to Gemini, Claude, and GPT prompts
  increases token usage. The FMP context helpers should be kept concise (5-10
  lines per ticker). Monitor token counts after deployment.
- **Timeout values**: The proposed stage timeouts (90-180s) are initial guesses.
  Should be tuned based on observed latency in production. Consider making them
  env vars.
- **Multi-TF synthesis in GPT vs Claude**: This plan puts the synthesis in the
  GPT prompt (text-based, no extra API call). An alternative is a separate
  Claude synthesis call, but that adds cost and Claude wouldn't have visual
  context for the synthesis. GPT handling it is simpler and arguably better
  since GPT already sees all the data.
- **FMP tool enrichment cost**: Enabling `enrich_with_ratios=True` on tool calls
  means each Perplexity tool invocation triggers bulk API calls. This is
  acceptable with the 750 calls/min tier but should be monitored.
- **Migration for user_prompt column**: Need to check if `pipeline_runs` table
  already has a `user_prompt` column. If not, a new Alembic migration is
  required.

## Branch

`feature/pipeline-improvements-v2` off `dev`
