# Services Layer

> **Source:** [`src/backend/services/`](../../src/backend/services/)

The services layer contains business logic that sits between the API routes
and the database/external APIs. Services are called by both API handlers and
the pipeline orchestrator.

---

## Strategy Service

**File:** [`services/strategy.py`](../../src/backend/services/strategy.py)

Manages the lifecycle of strategy configurations — the core unit that drives
every pipeline stage.

### Functions

| Function | Purpose |
|----------|---------|
| `list_strategies(user_id)` | List user's strategies (excludes templates) |
| `list_templates()` | List all system templates (`is_template=True`) |
| `get_strategy(strategy_id, user_id)` | Fetch a single strategy by ID |
| `create_strategy(config, user_id)` | Insert a new strategy |
| `ensure_defaults()` | Seed templates from `templates/strategies.json` if table is empty |

### Template Seeding

`ensure_defaults()` runs at application startup. It checks if the
`strategies` table is empty. If so, it reads `templates/strategies.json`,
parses each entry into a `StrategyConfig`, and inserts them with
`user_id="system"`.

The template file is a **one-time seed** — after initial load, strategies
are managed entirely through the database. Editing `strategies.json` has no
effect once templates exist in the database.

### Row-to-Config Conversion

`_row_to_config()` handles the messy reality of database rows: JSON strings
in `chart_indicators`, `risk_params`, `additional_timeframes`,
`short_timeframes`, and `short_tf_indicators` are parsed back into their
Python types. Falls back to sensible defaults if columns are missing
(backward compatibility with older schema versions).

---

## Chart Image Service

**File:** [`services/chart_image.py`](../../src/backend/services/chart_image.py)

Fetches chart images from the Chart-Img v2 API and stores them in Supabase
Storage.

### Key Functions

| Function | Purpose |
|----------|---------|
| `fetch_chart_image(ticker, timeframe, indicators, run_id, user_id)` | Fetch a chart PNG, upload to Supabase Storage, return `(bytes, url)` |
| `fetch_annotated_chart(ticker, timeframe, key_levels, run_id, user_id, entry_price, stop_loss, take_profit)` | Fetch a chart with horizontal line overlays for key levels and trade parameters |

### How It Works

1. **Symbol mapping** — converts TradingView format (`TSX:ENB`) to
   Chart-Img format with exchange suffixes
2. **Indicator mapping** — converts indicator names (`RSI`, `MACD`, etc.)
   to Chart-Img `studies[]` objects with correct parameters
3. **API call** — POST to `https://api.chart-img.com/v2/tradingview/advanced-chart`
4. **Upload** — stores the PNG in Supabase Storage under
   `{user_id}/{run_id}/{ticker}_{timeframe}.png`
5. **Return** — returns both the raw bytes (for Claude Vision) and the
   public CDN URL (for the frontend)

### Annotated Charts

`fetch_annotated_chart()` adds horizontal line `drawings[]` to the
Chart-Img request:

- **Support levels** — green dashed lines
- **Resistance levels** — red dashed lines
- **Entry price** — blue solid line
- **Stop loss** — red solid line
- **Take profit** — green solid line

These annotated charts are generated in Stage 4.5 (after GPT produces
recommendations) and stored under
`{user_id}/{run_id}/annotated/{ticker}_{timeframe}.png`.

### Maps

The service maintains three mapping dictionaries:

- **`INDICATOR_MAP`** — indicator name → Chart-Img study config
- **`TIMEFRAME_MAP`** — timeframe string → Chart-Img interval value
- **`EXCHANGE_SUFFIX_MAP`** — exchange prefix → Chart-Img exchange suffix

---

## Keyring Service

**File:** [`services/keyring_service.py`](../../src/backend/services/keyring_service.py)

Loads API keys from environment variables (`.env` in dev, Railway env vars
in production).

### Functions

| Function | Purpose |
|----------|---------|
| `load_env()` | Load `.env` file (called at startup) |
| `get_api_key(service)` | Get an API key by service name (e.g., `"perplexity"`) |
| `get_key_status()` | Return `dict[str, bool]` showing which keys are configured |

Keys are **never** stored in the database, logged, or returned to the
frontend. The settings endpoint only returns boolean presence.

---

## Reflection Service

**File:** [`services/reflection.py`](../../src/backend/services/reflection.py)

Powers the self-learning loop. Queries past outcomes, decisions, and stage outputs to compute performance metrics and generate a memory injection that gets embedded in the GPT judge prompt on every run.

### Functions

| Function | Purpose |
|----------|---------|
| `generate_reflection(user_id)` | Full generation: fetch decisions + outcomes + recommendations + stage_outputs, compute FinMem two-layer metrics, optionally call GPT-4o-mini for strategic advice, store new row in `reflections` table. Requires ≥5 logged outcomes. |
| `load_reflection_context(user_id)` | Load the most recent reflection's `injection_prompt` text for GPT judge injection |
| `_compute_metrics(...)` | Compute win/loss, P&L, pattern accuracy, sector win rates, TF alignment, confidence calibration, streak |
| `_format_short_term_memory(...)` | 14-day window: current streak, pattern/sector suppression alerts |
| `_format_long_term_memory(...)` | All-time: durable pattern accuracy, sector rates, TF alignment stats, calibration buckets |
| `build_memory_injection(...)` | Assemble two-layer injection from short-term + long-term formatted strings |

### FinMem Architecture

The reflection engine implements a two-layer memory system:

**Short-term (14 days):**
- Recent trade streak (last 5 trades)
- Pattern suppression alerts (e.g., "double bottom 0/2 — reduce confidence by 40%")
- Sector suppression flags

**Long-term (all-time):**
- Pattern accuracy with minimum 3-sample threshold
- Sector win rates
- Timeframe alignment categories (`all_agree`, `partial`, `single_tf`) with confidence annotations
- Confidence calibration by bucket (high >0.75 / medium 0.55–0.75 / low <0.55)

The `injection_prompt` is prepended to the GPT judge system prompt as `## HISTORICAL PERFORMANCE CONTEXT` on every subsequent pipeline run. The GPT judge prompt includes explicit instructions to apply suppression multipliers and prioritize short-term signals over long-term when they conflict.

**Trigger:** Manual only. The user clicks "Generate Reflection" in `InsightsView` which calls `POST /api/insights/reflect`.

---

## FMP Service

**File:** [`services/fmp_service.py`](../../src/backend/services/fmp_service.py)

Optional Stage 0 pre-screener using the Financial Modeling Prep API. Only active when `FMP_API_KEY` is set and `fmp_screener.enabled = true` on the strategy.

### Key Functions

| Function | Purpose |
|----------|---------|
| `run_stock_screener(config, user_id)` | Call FMP `/stable/company-screener`, enrich results with `ratios-ttm` + `key-metrics-ttm` (concurrent), apply post-filters (P/E, ROE, debt/equity) |
| `run_crypto_screener(config)` | Fetch `/stable/batch-crypto-quotes`, filter by market cap / volume / price range, sort by market cap |

### How It Works

1. **Stock path:** Company screener → concurrent ratios-ttm enrichment (Semaphore(5)) → client-side P/E, ROE, debt/equity filtering → truncate to `limit`
2. **Crypto path:** Batch quotes → market cap/volume/price filter → top-N by market cap

The FMP service also exposes a **Perplexity function-calling tool** via `pipeline/tools/fmp_tool.py` so the Perplexity Agent API can invoke FMP dynamically during its tool-calling rounds (max 3 rounds per run).
