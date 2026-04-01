# CLAUDE2.md — SignalForge Detailed Reference

> This file contains detailed architectural, configuration, and reference
> documentation for AI coding assistants. It supplements the lightweight
> `CLAUDE.md` and should be consulted when working on specific subsystems.
>
> **Read `CLAUDE.md` first.** Only consult sections here when you need the
> full details for a particular area.

---

## Python Code Style — Full Example

```python
from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import BaseModel


class ChartAnalysis(BaseModel):
    """Complete output from Claude Vision chart analysis.

    Attributes:
        ticker: Stock ticker symbol.
        timeframe: Chart timeframe (e.g., "D" for daily).
        trend_direction: Overall trend assessment.
    """

    ticker: str
    timeframe: str
    trend_direction: Literal["bullish", "bearish", "neutral", "transitioning"]


async def analyze_chart(
    ticker: str,
    timeframe: str,
    indicators: list[str],
) -> ChartAnalysis:
    """Analyze a stock chart using Claude Vision.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL").
        timeframe: Chart timeframe. One of "4H", "D", "W".
        indicators: List of technical indicators to include.

    Returns:
        Validated chart analysis result.

    Raises:
        ValidationError: If Claude's response fails schema validation.
        httpx.HTTPError: If the API call fails.
    """
    chart_image = await fetch_chart_image(ticker, timeframe, indicators)
    raw_response = await call_claude_vision(chart_image, ticker, indicators)
    return ChartAnalysis.model_validate_json(raw_response)
```

---

## Ruff Configuration (`pyproject.toml`)

```toml
[tool.ruff]
line-length = 100
target-version = "py314"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort (import sorting)
    "B",   # flake8-bugbear (common bugs)
    "C4",  # flake8-comprehensions
    "UP",  # pyupgrade (modern syntax)
    "SIM", # flake8-simplify
    "RUF", # Ruff-specific rules
]
ignore = ["E501", "B008", "C901", "B905"]
fixable = ["ALL"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
skip-magic-trailing-comma = false
line-ending = "auto"

[tool.ruff.lint.isort]
known-first-party = ["database", "pipeline", "services", "api", "utils", "middleware", "config"]
```

### ty Configuration (`pyproject.toml`)

```toml
[tool.ty.environment]
root = ["."]
python-version = "3.14"

[tool.ty.terminal]
output-format = "full"
error-on-warning = false
```

---

## Pipeline Architecture

### Pipeline Stage Contract

Every LLM stage follows this pattern:

1. Build prompt from strategy config + upstream data
2. Call LLM API
3. Parse response as JSON
4. Validate against Pydantic schema
5. On validation failure: retry with error context (max 2 retries)
6. On success: return validated model
7. On final failure: return `None`, log error, mark stage as degraded

```python
@with_validation_retry(schema=ChartAnalysis, max_retries=2)
async def call_claude_chart_analysis(prompt: str, image: bytes) -> ChartAnalysis:
    ...
```

The `validation.py` module also handles JSON extraction from LLM responses —
stripping markdown fences, `<think>` tags, and other wrapper text before parsing.

### Full Pipeline Flow (5 Stages)

```
Stage 0 (Optional): FMP Pre-Screening
    │  Stock screener + ratios-ttm enrichment, OR crypto batch quotes
    │  Output: enriched stock/crypto list passed as context to Perplexity
    ↓
Stage 1: Perplexity (Agent API with web_search + optional FMP tool)
    │  Discovery mode: screen market for opportunities
    │  Analysis mode: research given tickers
    │  Output: ScreeningResult with tickers, fundamentals, news_urls
    ↓
Stage 2: Gemini (Google Search grounding, per-ticker)
    │  Uses Perplexity-provided news URLs for grounded sentiment
    │  Output: SentimentAnalysis per ticker
    ↓
Stage 3: Claude (Vision API, per-ticker × per-timeframe)
    │  Receives chart images + news context from Gemini
    │  Runs ALL timeframes concurrently (primary + additional + short)
    │  Output: ChartAnalysis per ticker per timeframe
    ↓
Stage 4: GPT (Bull/Bear/Judge debate)
    │  Bull + Bear run in parallel, Judge runs sequentially
    │  Debate is optional per strategy (enable_debate flag)
    │  Output: Recommendation per ticker
    ↓
Stage 4.5: Annotated Charts (Chart-Img v2 with horizontal line drawings)
    │  Runs after GPT so trade params (entry/stop/target) are available
    │  Max 5 drawings per chart (PRO plan limit)
    │  Output: annotated chart images uploaded to Supabase Storage
```

### Pipeline Modes

| Mode        | Trigger                          | Behavior                             |
| ----------- | -------------------------------- | ------------------------------------ |
| `discovery` | strategy_id only, no tickers     | Screen market for new opportunities  |
| `analysis`  | manual_tickers only, no strategy | Research specific tickers            |
| `combined`  | strategy_id + manual_tickers     | Both screening and targeted research |
| `prompt`    | user_prompt free-form text       | Natural language drives screening    |

### LLM Models

Each stage's model is configured in its stage file under `pipeline/stages/`.

| Stage      | Provider   | API Style                                        |
| ---------- | ---------- | ------------------------------------------------ |
| Perplexity | Perplexity | Agent API (`responses.create`) with tool calling |
| Gemini     | Google     | Google GenAI SDK with Search grounding           |
| Claude     | Anthropic  | Vision API with base64 chart images              |
| GPT        | OpenAI     | Chat completions (bull/bear/judge roles)         |

### Concurrency Control

Per-stage semaphores prevent API rate limit issues:

- Perplexity: `Semaphore(3)`
- Gemini: `Semaphore(5)`
- Claude: `Semaphore(3)`
- FMP: `Semaphore(5)`

Bull + Bear GPT calls run in `asyncio.gather`. Judge is sequential after both
complete.

### Degraded Pipeline

If a non-critical stage fails, the pipeline continues. The
`PipelineResult.stage_errors` list tracks all failures.

- If **FMP** fails or is not configured, Perplexity proceeds without
  pre-screened data.
- If **Gemini** fails, Claude proceeds without news context (the prompt omits
  the "Recent News Context" section). GPT judge is told sentiment data is
  unavailable.
- If **Claude** fails after receiving news, GPT proceeds with Perplexity
  fundamentals + Gemini sentiment only (no chart analysis).
- The GPT judge prompt explicitly notes which data is missing via a
  `DATA AVAILABILITY` section so it can adjust confidence accordingly.

### Prompt Versioning

Every prompt is stored as a Python constant with a version hash. When a prompt
changes, the hash changes. The hash is stored in `pipeline_runs.prompt_versions`
so you can correlate prompt iterations with outcome performance.

```python
JUDGE_PROMPT_VERSION = "v7"  # bump when the judge prompt changes

def get_judge_hash() -> str:
    return prompt_hash(JUDGE_SYSTEM_PROMPT)
```

Prompt versions are `*_PROMPT_VERSION` / `PROMPT_VERSION` constants per file under
`pipeline/prompts/`. The orchestrator stores per-stage hashes in
`pipeline_runs.prompt_versions` (regime, perplexity, gemini, claude, gpt_bull,
gpt_bear, gpt_judge). Correlating those hashes with outcomes is possible via
`recommendations.run_id` but not yet surfaced in the Insights UI.

---

## FMP Integration (Financial Modeling Prep)

FMP provides Stage 0 pre-screening and is also available as a Perplexity
tool-calling function.

### Stock Screening Flow

1. `/stable/company-screener` — filter by country, exchange, sector, industry,
   market cap, price, volume, beta, ETF toggle
2. Concurrent `ratios-ttm` + `key-metrics-ttm` enrichment per result
3. Client-side post-filtering: P/E range, min ROE, max debt/equity
4. Results passed as context to Perplexity prompt

### Crypto Screening Flow

1. `/stable/batch-crypto-quotes` — fetch all crypto quotes
2. Client-side filtering by market cap, volume, price range
3. Sort by market cap, limit results

### Strategy-Level Config

Every strategy has an optional `fmp_screener` JSON field (`FmpScreenerConfig`
model) controlling:

- `enabled`, `is_crypto`, `country`, `exchange`, `sector`, `industry`
- `market_cap_min/max`, `price_min/max`, `volume_min`, `beta_min/max`
- `is_actively_trading`, `is_etf`, `limit`
- `pe_max`, `pe_min`, `roe_min`, `debt_equity_max`, `enrich_with_ratios`

### Perplexity Tool Calling

FMP is exposed as a function tool (`pipeline/tools/fmp_tool.py`) so Perplexity
can dynamically invoke the screener with different parameters during its Agent
API conversation. Max 3 tool-calling rounds per run.

### Key Files

- `services/fmp_service.py` — FMP API client, screening, enrichment
- `pipeline/tools/fmp_tool.py` — FMP tool definition for Perplexity Agent API
- `database/migrations/006_add_fmp_screener.sql` — `fmp_screener` column on
  strategies

---

## Multi-Timeframe Chart Analysis

Claude analyzes **multiple timeframes per ticker** concurrently. A strategy
defines three timeframe sets:

| Config Field            | Default                                             | Example         | Purpose                        |
| ----------------------- | --------------------------------------------------- | --------------- | ------------------------------ |
| `chart_timeframe`       | `"D"`                                               | `"D"`           | Primary timeframe              |
| `additional_timeframes` | `["4H", "W"]`                                       | `["4H", "W"]`   | Supplementary swing timeframes |
| `short_timeframes`      | `[]`                                                | `["15m", "1H"]` | Intraday/scalp timeframes      |
| `short_tf_indicators`   | `["VWAP", "Stochastic", "EMA_20", "ATR", "Volume"]` | —               | Indicator set for short TFs    |

All timeframes for a ticker run concurrently via `asyncio.gather`. Short
timeframes use a different indicator set optimized for intraday analysis.

**Supported timeframes:** 15m, 1H, 2H, 4H, D, W, M

---

## Supported Chart Indicators

The full indicator list and their Chart-Img v2 study mappings are defined in
`INDICATOR_MAP` and `INDICATOR_INPUTS` in `services/chart_image.py`. Includes
EMAs, SMAs, RSI, MACD, Bollinger Bands, Stochastic, ATR, VWAP, Volume, OBV, CCI,
Ichimoku, DMI, and Parabolic SAR.

---

## Database

Supabase PostgreSQL accessed via the Supabase Python SDK (PostgREST over HTTPS).
**Not raw SQL connections** — this eliminates IPv6/pooler/DNS issues on Railway.
All queries use the fluent `.table().select().eq()...execute()` pattern. The
backend uses the `service_role` key which bypasses Row Level Security.

Schema is managed via raw SQL migration files in `database/migrations/` (not
Alembic). All tables use TEXT UUIDs as primary keys (`uuid.uuid4().hex`).
Multi-tenant: all user-facing tables include a `user_id` column for data
isolation.

### Tables

Core tables: `strategies`, `pipeline_runs`, `stage_outputs`, `recommendations`,
`decisions`, `outcomes`, `reflections`, `chart_images`. All user-facing tables
include `user_id` for multi-tenant isolation. See
`database/migrations/001_initial.sql` for the full schema.

**Notable:** `chart_images` table exists but is currently unused in code (chart
paths are stored in `stage_outputs`). Decisions, outcomes, and reflections are
fully wired: REST APIs, reflection generation, and frontend journal views (see
Self-Learning Loop).

### Migrations

Sequential SQL files in `database/migrations/` (001–010 and beyond). Noteworthy
additions beyond the initial schema: **006** `fmp_screener`, **007** `user_prompt`
on `pipeline_runs`, **008** `user_id` on `reflections`, **009** ATR in chart
indicators metadata, **010** recommendations `SELL` → `SHORT`. See the directory
for the authoritative list.

### RLS Strategy

RLS enabled on all tables with zero policies = full deny for anon key. Backend
uses service_role key (bypasses RLS).

---

## API Endpoints

| Method | Path                            | Auth  | Rate Limit | Description                                                     |
| ------ | ------------------------------- | ----- | ---------- | --------------------------------------------------------------- |
| `GET`  | `/health`                       | No    | No         | Health check with DB connectivity verification                  |
| `POST` | `/api/pipeline/run`             | Yes   | 5/min      | Trigger pipeline run (strategy_id, manual_tickers, user_prompt) |
| `GET`  | `/api/pipeline/status/{run_id}` | Yes   | No         | Get full pipeline result (reconstructs from DB)                 |
| `GET`  | `/api/pipeline/runs`            | Yes   | No         | List recent pipeline runs (last 100)                            |
| `GET`  | `/api/pipeline/runs/{run_id}`   | Yes   | No         | Alias for status endpoint                                       |
| `GET`  | `/api/strategies`               | Yes   | No         | List user strategies (excludes templates)                       |
| `GET`  | `/api/strategies/templates`     | Yes\* | No         | List built-in strategy templates (\*no auth enforced)           |
| `GET`  | `/api/strategies/{strategy_id}` | Yes   | No         | Get single strategy by ID                                       |
| `POST` | `/api/strategies`               | Yes   | No         | Create new strategy (201)                                       |
| `POST` | `/api/charts/fetch`             | Yes   | No         | On-demand chart image fetch                                     |
| `GET`  | `/api/settings/api-keys/status` | Yes   | No         | Check which API keys are configured                             |
| `POST` | `/api/decisions/recommendations/{id}/decision` | Yes | No | Record follow/pass on a recommendation (201)             |
| `GET`  | `/api/decisions`                | Yes   | No         | List decisions (`decision_filter`, pagination)                 |
| `GET`  | `/api/decisions/{id}`           | Yes   | No         | Get one decision                                                 |
| `DELETE` | `/api/decisions/{id}`         | Yes   | No         | Remove decision (cascade-deletes linked outcome)               |
| `POST` | `/api/outcomes/decisions/{id}/outcome` | Yes | No | Log trade outcome for a "following" decision (201)       |
| `PUT`  | `/api/outcomes/{id}`            | Yes   | No         | Update an outcome                                                |
| `GET`  | `/api/outcomes`                 | Yes   | No         | List outcomes (pagination)                                       |
| `GET`  | `/api/recommendations`          | Yes   | No         | List recommendations with joined decision/outcome status       |
| `GET`  | `/api/recommendations/{id}`     | Yes   | No         | One recommendation with status (trade journal row)             |
| `GET`  | `/api/insights/overview`      | Yes   | No         | Aggregated performance + confidence calibration                 |
| `POST` | `/api/insights/reflect`         | Yes   | No         | Generate reflection (requires ≥5 outcomes)                      |
| `GET`  | `/api/insights/reflections/latest` | Yes | No        | Latest reflection (404 if none)                                  |

**Rate limiting:** Global default 60/min via SlowAPI. Pipeline trigger is 5/min.

**Missing endpoints:** No PUT/PATCH/DELETE for strategies. No standalone DELETE
for outcomes (remove via decision delete). No list endpoint for reflection
history (only latest).

---

## Environment Variables

### Backend (`.env` or Railway env vars)

| Variable              | Required   | Description                                      |
| --------------------- | ---------- | ------------------------------------------------ |
| `PERPLEXITY_API_KEY`  | Yes        | Perplexity Agent API (sonar model)               |
| `ANTHROPIC_API_KEY`   | Yes        | Claude Vision API                                |
| `GOOGLE_API_KEY`      | Yes        | Gemini with Google Search grounding              |
| `OPENAI_API_KEY`      | Yes        | GPT bull/bear/judge debate                       |
| `CHARTIMG_API_KEY`    | Yes        | Chart-Img v2 chart generation                    |
| `FMP_API_KEY`         | No         | Financial Modeling Prep (optional pre-screening) |
| `SUPABASE_URL`        | Yes (prod) | Supabase project URL                             |
| `SUPABASE_KEY`        | Yes (prod) | Supabase service_role key (bypasses RLS)         |
| `SUPABASE_JWT_SECRET` | Yes (prod) | For JWT verification (legacy, JWKS preferred)    |
| `ALLOWED_ORIGINS`     | Yes (prod) | CORS allowed origins (frontend domain)           |

### Frontend (`.env` or Vercel env vars)

| Variable                 | Required | Description                                    |
| ------------------------ | -------- | ---------------------------------------------- |
| `VITE_API_URL`           | Yes      | Backend URL (default: `http://localhost:8420`) |
| `VITE_SUPABASE_URL`      | Yes      | Supabase project URL                           |
| `VITE_SUPABASE_ANON_KEY` | Yes      | Supabase anon key for auth                     |

---

## Frontend Conventions

- **React 19** functional components with hooks only (no class components)
- **TypeScript 5.9** strict mode
- **Tailwind v4** with `@theme` directive — dark theme only, CSS custom
  properties in `theme/globals.css`
- **Color palette:** GitHub Dark inspired — `bg-primary: #0d1117`,
  `bg-secondary: #161b22`, `accent-green: #3fb950`, `accent-red: #f85149`,
  `accent-blue: #58a6ff`, `accent-yellow: #d29922`
- **Vite 8** with React SWC plugin and Tailwind v4 Vite plugin
- Backend communication via `api/client.ts` using native `fetch` — no external
  HTTP library
- All TypeScript interfaces in `types/index.ts` must mirror the Python Pydantic
  models exactly
- **Lucide React** for all icons
- **React Router v7** for client-side routing
- **Supabase JS SDK** for authentication (email/password, JWT tokens)

### Frontend Views

| Route         | View                | Status                                                        |
| ------------- | ------------------- | ------------------------------------------------------------- |
| `/`           | RecommendationsView | Active — main dashboard with ticker list + 5-tab detail panel |
| `/history`    | HistoryView         | Active — pipeline run history table                           |
| `/strategies` | StrategiesView      | Active — template + user strategy grid                        |
| `/insights`   | InsightsView        | Active — trade journal, performance overview, reflection panel, calibration |
| `/settings`   | SettingsView        | Active — account info + API key status                        |
| `/login`      | LoginPage           | Active — Supabase auth login/signup                           |

### Detail Panel Tabs (RecommendationsView)

| Tab       | Component      | Data Source                                                        |
| --------- | -------------- | ------------------------------------------------------------------ |
| Overview  | `OverviewTab`  | Perplexity fundamentals (market cap, P/E, highlights, risks)       |
| Chart     | `ChartTab`     | Claude chart analysis + annotated chart images + PriceLevelMap SVG |
| Sentiment | `SentimentTab` | Gemini sentiment score, catalysts, sector sentiment                |
| Synthesis | `SynthesisTab` | GPT recommendation, trade params, bull/bear debate cases           |
| Feedback  | `FeedbackTab`  | Follow/pass decisions, outcome logging, undo (syncs with Insights)  |
| Raw Data  | `RawTab`       | Full pipeline result JSON dump                                     |

### Notable Frontend Features

- **Multi-mode CommandBar** — auto-classifies input as
  discovery/analysis/combined/prompt mode with color-coded indicators
- **Collapsible ticker sidebar** — 320px expanded with full cards, 48px
  collapsed with just symbols
- **Ad-hoc chart fetching** — ChartTab can fetch chart images for timeframes not
  in the pipeline run
- **SVG PriceLevelMap** — interactive visualization of
  support/resistance/entry/stop/target levels
- **Expandable chart lightbox** — click to enlarge chart images with backdrop
  blur
- **Insights + Feedback loop** — `InsightsView` (`useInsights`) and
  `FeedbackTab` share state via `lib/feedbackSync.ts` (CustomEvent) so journal
  edits stay consistent across routes
- **TradingViewWidget component** — fully built with indicator mapping but
  **currently not rendered** (reserved for future live chart integration)

---

## Cloud Architecture

```
Vercel (React SPA) ──JWT──→ Railway (FastAPI backend) ──PostgREST──→ Supabase PostgreSQL
                                    │
                                    ├──→ Supabase Auth (JWKS JWT verification)
                                    ├──→ Supabase Storage (chart image uploads)
                                    ├──→ Perplexity Agent API (screening)
                                    ├──→ Google GenAI (sentiment)
                                    ├──→ Anthropic Vision (chart analysis)
                                    ├──→ OpenAI (debate synthesis)
                                    ├──→ Chart-Img v2 (chart generation)
                                    └──→ FMP API (pre-screening, optional)
```

- **Auth flow:** Frontend uses Supabase JS SDK for login/signup → gets JWT →
  sends JWT in `Authorization: Bearer` header to backend → backend verifies JWT
  via JWKS endpoint (`PyJWKClient` with 1-hour key cache, ES256 algorithm) →
  extracts `user_id` for data isolation. In dev mode without Supabase
  configured, falls back to `"dev-user-local"`.
- **Database:** Supabase PostgreSQL accessed via PostgREST (HTTPS), not raw SQL
  connections. Backend uses `supabase` Python SDK with service_role key.
- **Chart images:** Backend uploads PNGs to Supabase Storage `charts` bucket →
  stores public URL in stage_outputs → frontend loads images directly from
  Supabase CDN. Falls back to local filesystem when Supabase is not configured.
- **API keys:** In production, set as Railway environment variables. In
  development, loaded from `.env` via `python-dotenv`.
- **CORS:** Locked to frontend domain via `ALLOWED_ORIGINS` env var.

---

## Strategy System

Strategies are the core configuration unit. A strategy defines:

- **FMP pre-screening** (optional) — market filters, ratio constraints, crypto
  toggle
- **Perplexity screening** — prompt, constraints, max tickers
- **Gemini news** — recency window, news scope
- **Claude charts** — indicators, primary/additional/short timeframes, TA focus
- **GPT synthesis** — trading style, risk params, debate toggle

Users create strategies from templates. Templates are stored in
`templates/strategies.json` and loaded on first run via
`services/strategy.py → ensure_defaults()`.

### Strategy Templates

Templates are defined in `templates/strategies.json`. All include `fmp_screener`
config. Scalp templates disable debate for faster execution. Default market
focus is Canadian (TSX/TSXV). See the file for the current list of templates and
their configurations.

When implementing strategy-related features, remember that the strategy config
drives prompt construction at every stage. The prompt modules in
`pipeline/prompts/` all accept a `StrategyConfig` parameter.

---

## Perplexity Agent API

Perplexity uses the **Agent API** (`responses.create`) instead of the older chat
completions API. Key details:

- Model: `perplexity/sonar`
- Built-in `web_search` tool (always enabled)
- Optional FMP function-calling tool (when FMP key is configured)
- Max 3 tool-calling rounds per run
- Domain-filtered search based on strategy type:
  - **Canadian stocks**: BNN, Globe and Mail, Financial Post, TMX, etc.
  - **US stocks**: Seeking Alpha, MarketWatch, Yahoo Finance, etc.
  - **Crypto**: CoinDesk, The Block, CoinGecko, etc.
  - **Earnings**: Earnings Whispers, Estimize, etc.
- Discovery prompts include ET time and market session label (premarket/market
  hours/after hours)
- TradingView ticker format enforced (e.g., `TSX:ENB`, not `ENB.TO`)

---

## Exchange/Ticker Resolution

The chart service (`services/chart_image.py`) handles multi-exchange ticker
resolution:

- **EXCHANGE_SUFFIX_MAP** converts exchange suffixes to TradingView format:
  `.TO` → `TSX:`, `.V` → `TSXV:`, `.L` → `LSE:`, etc.
- For bare US tickers, tries NASDAQ → NYSE → AMEX sequentially via Chart-Img API
- First successful HTTP response wins
- Exchange prefixes are stripped in the collapsed ticker sidebar for readability

---

## Self-Learning Loop

The feedback loop is **implemented end-to-end** (backend, APIs, frontend).

**Runtime (each pipeline run):** Before GPT debate, `orchestrator.py` calls
`load_reflection_context(user_id)`, which loads the latest `injection_prompt` from
the `reflections` table. That text is passed into `build_judge_user_prompt()` in
`pipeline/prompts/gpt_debate.py` as `## HISTORICAL PERFORMANCE CONTEXT` so the
judge can calibrate confidence using concrete past performance.

**Reflection generation:** `services/reflection.py` implements
`generate_reflection(user_id)` — it aggregates decisions, outcomes, and related
`stage_outputs`, computes FinMem-style short-term (14-day) and long-term metrics
(patterns, sectors, timeframe alignment, confidence buckets, streaks), optionally
calls GPT for brief strategic advice, and **writes** a new row to `reflections`.
`POST /api/insights/reflect` triggers this and requires at least **5 logged
outcomes** per user.

**User-facing journal:** `InsightsView` shows performance overview, expandable
recommendation rows with inline follow/pass and outcome forms, latest reflection
text, and calibration buckets. `FeedbackTab` offers the same decision/outcome
workflow for the currently selected recommendation. Both use `api/client.ts` and
stay in sync via `notifyFeedbackChanged()` / `useFeedbackSync`.

**Still roadmap (not product gaps in wiring, but analytics depth):** per-strategy
performance rollups, prompt-version vs. outcome correlation in the UI, reflection
history list API, automated reflection scheduling, and incrementing
`strategies.run_count`.

---

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`) runs on push to `main` and on PRs to
`main`:

**Backend job:**

1. `uv run ruff check` — lint check
2. `uv run ruff format --check` — format check
3. `uv run ty check` — type check

**Frontend job:**

1. `bunx tsc --noEmit` — TypeScript type check
2. `bun run build` — production build

**Note:** CI does NOT currently trigger on pushes to `dev` or feature branches
(only `main` and PRs to `main`).

---

## Testing

**There are currently zero test files in the project.** No `test_*.py`, no
`conftest.py`, no test directories. The CI workflow only runs linting and type
checking, not tests. The `pyproject.toml` has `per-file-ignores` configured for
`tests/**` but the directory doesn't exist yet.

---

## Common Tasks

### Adding a new chart indicator option

1. Add the indicator name to the allowed values in `schemas.py`
   (`ChartAnalysis.indicator_readings`)
2. Add the indicator to `INDICATOR_MAP` (and `INDICATOR_INPUTS` if it needs
   custom params) in `services/chart_image.py` — these map to Chart-Img v2
   `studies[]` objects in the POST body
3. Update Claude's prompt in `pipeline/prompts/claude_chart.py` to describe how
   to read the indicator
4. Add the indicator as an option in the frontend strategy editor
   (`StrategyEditor.tsx`)

### Adding a new strategy template

1. Add the template JSON to `templates/strategies.json`
2. Set `is_template: true` in the strategy object
3. Include `fmp_screener` config (set `enabled: false` if not needed)
4. The template will appear in the TemplateSelector component automatically

### Changing a prompt

1. Edit the prompt in `pipeline/prompts/{stage}.py`
2. Bump the `PROMPT_VERSION` constant
3. The hash will automatically update and be tracked in pipeline runs
4. After accumulating outcomes, compare performance between prompt versions in
   the Insights view

### Adding a new pipeline stage

1. Create a new stage file in `pipeline/stages/`
2. Define input/output Pydantic schemas in `schemas.py`
3. Add the stage to the orchestrator's execution flow in `orchestrator.py`
4. Add a corresponding prompt file in `pipeline/prompts/`
5. Add API endpoints if the stage needs direct access
6. Update the frontend detail view to display the new stage's output
7. Add the corresponding TypeScript interfaces in `types/index.ts`

### Adding a new API endpoint

1. Add the route handler in the appropriate `api/*.py` router
2. Use `CurrentUser = Annotated[str, Depends(get_current_user)]` for auth
3. Define request/response Pydantic models
4. Add the corresponding method to the frontend `api/client.ts`

---

## Known Gaps / Future Work

- **`docs/ARCHITECTURE.md`** — still largely describes the legacy Tauri + SQLite
  desktop design. **Authoritative deployment architecture is in `CLAUDE.md`**
  and the Cloud Architecture section above; the long doc needs a full rewrite
  when time allows.
- **`docs/PRD.md`** — product narrative is useful; tech stack and "fully local"
  sections are obsolete (see banner at top of that file). **Use `CLAUDE.md` for
  current stack and hosting.**
- **`chart_images` table** exists in schema but is unused in code — chart paths
  are stored in `stage_outputs`. May be vestigial.
- **No strategy update/delete endpoints** — only list, get, and create exist.
- **`strategies.run_count`** — column exists; nothing increments it after runs.
- **Insights analytics depth** — no per-strategy performance in API/UI; no
  prompt-version vs. outcome dashboard; reflections list is "latest" only.
- **No test infrastructure** — zero test files anywhere in the project.
- **`TradingViewWidget` component** — fully built with indicator mapping but not
  rendered in any view.
- **`App.css`** — leftover Vite template styles, dead code.
- **`tailwind-merge`** — installed as dependency but not imported by any
  component.
