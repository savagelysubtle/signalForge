# CLAUDE.md — SignalForge Project Context

> This file provides context for AI coding assistants working on the SignalForge project.
> Read this before making any changes to the codebase.

---

## What Is This Project?

SignalForge is a cloud-hosted **stock and crypto** analysis platform that chains an optional FMP pre-screener plus four AI models (Perplexity, Gemini, Claude, GPT) into a pipeline that produces structured trading recommendations. It does NOT execute trades — the user reviews recommendations and trades manually in TradingView (connected to Questrade).

The core loop: User triggers analysis → FMP pre-screens (optional) → Perplexity screens stocks/crypto → Gemini gathers news/sentiment → Claude reads charts with news context (multiple timeframes) → GPT synthesizes via bull/bear/judge debate → Stage 4.5 generates annotated charts → Dashboard displays recommendations → User decides to follow or pass → Logs outcome → System learns.

---

## Agent Rules (READ FIRST)

1. **Use subagents aggressively.** Delegate exploration, research, debugging, and implementation to subagents whenever possible. Keep the main conversation context clean and focused on orchestration and user communication. If a task can be handed to a subagent, it should be.

2. **Use skills wherever they fit.** Before starting work, check available skills and apply any that match the current task (code quality, task workflow, dispatch routing, etc.). Skills encode proven workflows — use them instead of improvising.

3. **Subagent delegation guidelines:**
   - **Explorer** — codebase search, tracing data flows, understanding features, mapping dependencies
   - **Researcher** — web research on packages, APIs, docs, code examples, version compatibility
   - **Debugger** — errors, test failures, unexpected behavior
   - **Implementer** — focused code changes on a single task
   - **Quality** — formatting, linting, type checking after code changes
   - **Git** — commits, branches, PRs, all version control operations
   - **Strategist** — planning and architecture before large changes

4. **Parallel subagents.** Launch multiple subagents concurrently when their tasks are independent (e.g., explorer + researcher, or multiple implementers on unrelated files).

5. **Context hygiene.** The main agent should summarize subagent results for the user rather than dumping raw output. Keep the main thread readable.

6. **Use Plan mode for anything beyond trivial changes.** If a task touches more than one file, involves architectural decisions, or has multiple valid approaches, switch to Plan mode first. Design the approach collaboratively before writing code. Only skip planning for single-file, obvious fixes. **Write every plan to a `.plan.md` file in `.cursor/plans/`** using the format described below.

7. **Ask questions — more than you think you should.** Before implementing, clarify requirements, edge cases, and preferences with the user. Do not assume intent. Ask about scope, expected behavior, error handling, naming preferences, and trade-offs. Better to ask one extra question than to build the wrong thing and rework it.

---

## Plan File Format

All non-trivial plans MUST be persisted as `.plan.md` files in `.cursor/plans/`. This keeps plans discoverable, trackable, and resumable across sessions.

**Filename:** `<short-snake-case-description>_<8-char-hex>.plan.md`
(e.g., `fix_chart_ticker_mismatch_49e0ca2c.plan.md`)

**Structure:**

```markdown
---
name: Human-readable plan title
overview:
  2-3 sentence summary of the problem and the chosen approach.
  Should be enough context for someone unfamiliar to understand the plan.
todos:
  - id: step-1-short-id
    content: Description of what this step does
    status: pending
  - id: step-2-short-id
    content: Description of what this step does
    status: pending
  - id: step-3-short-id
    content: Description of what this step does
    status: pending
isProject: false
---

# Plan Title

## Problem

What is broken, missing, or being improved? Include concrete symptoms or user impact.

## Solution

High-level approach. Why this approach over alternatives?
Include diagrams (mermaid) if the data flow or architecture is non-obvious.

## Implementation Steps

### Step 1: <step-1-short-id>

What to change, which files, and how. Include code snippets showing the intended diff
when helpful. Reference files with markdown links:
`[path/to/file.py](path/to/file.py)`

### Step 2: <step-2-short-id>

(repeat for each step)

## Risks / Open Questions

- Anything uncertain or requiring user input before proceeding
- Edge cases to watch for
- Breaking change potential

## Branch

Which branch this work happens on (e.g., `feature/my-feature` off `dev`).
```

**Rules for plan files:**

- **Create the plan file BEFORE writing any code.** The plan is the first artifact.
- **Update todo statuses** in the frontmatter as steps are completed (`pending` → `completed`).
- **One plan per feature/task.** Don't combine unrelated work into a single plan.
- **Keep steps atomic.** Each todo should be completable and verifiable independently.
- **Include file references.** Every step should name the files it touches.
- **Generate the hex suffix** from any 8 hex characters (e.g., first 8 of a UUID).

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend hosting | Vercel (static site, SPA rewrite) |
| Backend hosting | Railway (Docker container, Python 3.14-slim) |
| Auth | Supabase Auth (email/password, ES256 JWT via JWKS) |
| Database | Supabase PostgreSQL (accessed via PostgREST, not raw SQL) |
| Chart storage | Supabase Storage (public `charts` bucket) |
| Frontend | React 19 + TypeScript 5.9 + Tailwind v4 + Vite 8 |
| Routing | React Router v7 |
| Icons | Lucide React |
| Backend | Python 3.14 free-threaded (FastAPI) — ALL business logic lives here |
| Package manager | `uv` (Python), `bun` (frontend) |
| LLM SDKs | `openai`, `anthropic`, `google-generativeai`, `perplexityai` |
| Data APIs | FMP (Financial Modeling Prep), Chart-Img v2 |
| Validation | Pydantic v2 |
| Async | `asyncio` + `httpx` |
| DB Client | `supabase` Python SDK (PostgREST over HTTPS) |
| Linting / Formatting | `ruff` (Black-compatible) |
| Type checking | `ty` (Astral's type checker) |
| CI | GitHub Actions (ruff + ty for backend, tsc + build for frontend) |
| License | AGPL v3.0 |

---

## Python Code Style (STRICT)

These rules are non-negotiable. Every Python file must follow them.

- **Formatter:** `ruff format` (Black-compatible — double quotes, spaces, magic trailing commas)
- **Linter:** `ruff check` (pycodestyle, pyflakes, isort, bugbear, pyupgrade, simplify)
- **Type checker:** `ty check` (Astral's type checker — same team as ruff/uv)
- **Line length:** 100
- **String formatting:** f-strings ONLY (no `.format()`, no `%`)
- **Type hints:** REQUIRED on all function signatures
- **Docstrings:** Google style, REQUIRED on all public functions/classes
- **Imports:** sorted by ruff (isort-compatible)

```python
# Example of correct style:
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

## Code Quality Tooling (MANDATORY)

All Python code MUST pass `ruff` and `ty` before committing. Both tools are installed as dev dependencies (`uv sync` installs them). The authoritative configuration lives in `src/backend/pyproject.toml`.

### Running the tools

```bash
cd src/backend

# Format (Black-compatible)
uv run ruff format

# Lint (auto-fix what it can)
uv run ruff check --fix

# Type check
uv run ty check
```

### Rules for AI agents

1. **After writing or editing Python files**, run `uv run ruff format` and `uv run ruff check --fix` from `src/backend/`.
2. **Before considering a task complete**, run `uv run ty check` and fix any type errors you introduced.
3. **Never disable ruff rules inline** (`# noqa`) without explaining why in a code comment.
4. **Never use `# type: ignore`** without a specific error code and explanation (e.g., `# type: ignore[override] — Pydantic model_validate signature`).

### Ruff configuration (`pyproject.toml`)

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

### ty configuration (`pyproject.toml`)

```toml
[tool.ty.environment]
root = ["."]
python-version = "3.14"

[tool.ty.terminal]
output-format = "full"
error-on-warning = false
```

---

## Key Architectural Patterns

### Pipeline Stage Contract

Every LLM stage has the same pattern:

1. Build prompt from strategy config + upstream data
2. Call LLM API
3. Parse response as JSON
4. Validate against Pydantic schema
5. On validation failure: retry with error context (max 2 retries)
6. On success: return validated model
7. On final failure: return `None`, log error, mark stage as degraded

```python
# This pattern is implemented in pipeline/validation.py
# Use the retry decorator for all LLM calls:

@with_validation_retry(schema=ChartAnalysis, max_retries=2)
async def call_claude_chart_analysis(prompt: str, image: bytes) -> ChartAnalysis:
    ...
```

The `validation.py` module also handles JSON extraction from LLM responses — stripping markdown fences, `<think>` tags, and other wrapper text before parsing.

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

| Mode | Trigger | Behavior |
|------|---------|----------|
| `discovery` | strategy_id only, no tickers | Screen market for new opportunities |
| `analysis` | manual_tickers only, no strategy | Research specific tickers |
| `combined` | strategy_id + manual_tickers | Both screening and targeted research |
| `prompt` | user_prompt free-form text | Natural language drives screening |

### LLM Models

| Stage | Provider | Model | API Style |
|-------|----------|-------|-----------|
| Perplexity | Perplexity | `perplexity/sonar` | Agent API (`responses.create`) with tool calling |
| Gemini | Google | `gemini-2.5-pro` | Google GenAI SDK with Search grounding |
| Claude | Anthropic | `claude-opus-4-6` | Vision API with base64 chart images |
| GPT | OpenAI | `gpt-5.4` | Chat completions (bull/bear/judge roles) |

### Concurrency Control

Per-stage semaphores prevent API rate limit issues:
- Perplexity: `Semaphore(3)`
- Gemini: `Semaphore(5)`
- Claude: `Semaphore(3)`
- FMP: `Semaphore(5)`

Bull + Bear GPT calls run in `asyncio.gather`. Judge is sequential after both complete.

### Degraded Pipeline

If a non-critical stage fails, the pipeline continues. The `PipelineResult.stage_errors` list tracks all failures.

- If **FMP** fails or is not configured, Perplexity proceeds without pre-screened data.
- If **Gemini** fails, Claude proceeds without news context (the prompt omits the "Recent News Context" section). GPT judge is told sentiment data is unavailable.
- If **Claude** fails after receiving news, GPT proceeds with Perplexity fundamentals + Gemini sentiment only (no chart analysis).
- The GPT judge prompt explicitly notes which data is missing via a `DATA AVAILABILITY` section so it can adjust confidence accordingly.

### Prompt Versioning

Every prompt is stored as a Python constant with a version hash. When a prompt changes, the hash changes. The hash is stored in `pipeline_runs.prompt_versions` so you can correlate prompt iterations with outcome performance.

```python
# In pipeline/prompts/gpt_debate.py
PROMPT_VERSION = "v3"  # bump this when prompt changes

GPT_JUDGE_SYSTEM_PROMPT = """You are a senior portfolio manager..."""

def get_prompt_hash() -> str:
    return hashlib.sha256(GPT_JUDGE_SYSTEM_PROMPT.encode()).hexdigest()[:8]
```

**Current prompt versions:** Perplexity Discovery v12, Perplexity Analysis v8, Gemini Sentiment v2, Claude Chart v4, GPT Bull v1, GPT Bear v1, GPT Judge v3.

---

## FMP Integration (Financial Modeling Prep)

FMP provides Stage 0 pre-screening and is also available as a Perplexity tool-calling function.

### Stock Screening Flow
1. `/stable/company-screener` — filter by country, exchange, sector, industry, market cap, price, volume, beta, ETF toggle
2. Concurrent `ratios-ttm` + `key-metrics-ttm` enrichment per result
3. Client-side post-filtering: P/E range, min ROE, max debt/equity
4. Results passed as context to Perplexity prompt

### Crypto Screening Flow
1. `/stable/batch-crypto-quotes` — fetch all crypto quotes
2. Client-side filtering by market cap, volume, price range
3. Sort by market cap, limit results

### Strategy-Level Config
Every strategy has an optional `fmp_screener` JSON field (`FmpScreenerConfig` model) controlling:
- `enabled`, `is_crypto`, `country`, `exchange`, `sector`, `industry`
- `market_cap_min/max`, `price_min/max`, `volume_min`, `beta_min/max`
- `is_actively_trading`, `is_etf`, `limit`
- `pe_max`, `pe_min`, `roe_min`, `debt_equity_max`, `enrich_with_ratios`

### Perplexity Tool Calling
FMP is exposed as a function tool (`pipeline/tools/fmp_tool.py`) so Perplexity can dynamically invoke the screener with different parameters during its Agent API conversation. Max 3 tool-calling rounds per run.

### Key Files
- `services/fmp_service.py` — FMP API client, screening, enrichment
- `pipeline/tools/fmp_tool.py` — FMP tool definition for Perplexity Agent API
- `database/migrations/006_add_fmp_screener.sql` — `fmp_screener` column on strategies

---

## Multi-Timeframe Chart Analysis

Claude analyzes **multiple timeframes per ticker** concurrently. A strategy defines three timeframe sets:

| Config Field | Default | Example | Purpose |
|-------------|---------|---------|---------|
| `chart_timeframe` | `"D"` | `"D"` | Primary timeframe |
| `additional_timeframes` | `["4H", "W"]` | `["4H", "W"]` | Supplementary swing timeframes |
| `short_timeframes` | `[]` | `["15m", "1H"]` | Intraday/scalp timeframes |
| `short_tf_indicators` | `["VWAP", "Stochastic", "EMA_20", "ATR", "Volume"]` | — | Indicator set for short TFs |

All timeframes for a ticker run concurrently via `asyncio.gather`. Short timeframes use a different indicator set optimized for intraday analysis.

**Supported timeframes:** 15m, 1H, 2H, 4H, D, W, M

---

## Supported Chart Indicators (16 total)

| Indicator | Chart-Img v2 Study | Custom Params |
|-----------|-------------------|---------------|
| RSI | `RSI@tv-basicstudies` | — |
| MACD | `MACD@tv-basicstudies` | — |
| Bollinger Bands | `BollingerBands@tv-basicstudies` | — |
| Stochastic | `Stochastic@tv-basicstudies` | — |
| ATR | `ATR@tv-basicstudies` | — |
| EMA_20 | `MAExp@tv-basicstudies` | `length=20` |
| EMA_50 | `MAExp@tv-basicstudies` | `length=50` |
| EMA_200 | `MAExp@tv-basicstudies` | `length=200` |
| SMA_50 | `MASimple@tv-basicstudies` | `length=50` |
| SMA_200 | `MASimple@tv-basicstudies` | `length=200` |
| VWAP | `VWAP@tv-basicstudies` | — |
| Volume | `Volume@tv-basicstudies` | — |
| OBV | `OBV@tv-basicstudies` | — |
| CCI | `CCI@tv-basicstudies` | — |
| Ichimoku Cloud | `IchimokuCloud@tv-basicstudies` | — |
| DMI | `DMI@tv-basicstudies` | — |
| Parabolic SAR | `PSAR@tv-basicstudies` | — |

---

## Database

Supabase PostgreSQL accessed via the Supabase Python SDK (PostgREST over HTTPS). **Not raw SQL connections** — this eliminates IPv6/pooler/DNS issues on Railway. All queries use the fluent `.table().select().eq()...execute()` pattern. The backend uses the `service_role` key which bypasses Row Level Security.

Schema is managed via raw SQL migration files in `database/migrations/` (not Alembic). All tables use TEXT UUIDs as primary keys (`uuid.uuid4().hex`). Multi-tenant: all user-facing tables include a `user_id` column for data isolation.

### Tables

| Table | Multi-tenant | Purpose |
|-------|-------------|---------|
| `strategies` | `user_id` | Strategy configs. `is_template` flag for system templates. |
| `pipeline_runs` | `user_id` | Pipeline execution history. FK to strategies. Status: running/completed/partial/failed. |
| `stage_outputs` | via run_id FK | Raw LLM prompts, responses, metadata per stage per ticker. |
| `chart_images` | via run_id FK | Chart image metadata (path, hash, indicators). **Note: currently unused in code — chart paths stored in stage_outputs.** |
| `recommendations` | `user_id` | Final BUY/SELL/HOLD recommendations with trade params and debate cases. |
| `decisions` | `user_id` | User decisions on recommendations (following/passing). **No API endpoints yet.** |
| `outcomes` | `user_id` | Manual trade outcome logging (entry/exit/PnL). **No API endpoints yet.** |
| `reflections` | N/A | Self-learning summaries with injection prompts. |

### Migrations (6 files)

| Migration | Purpose |
|-----------|---------|
| `001_initial.sql` | Full schema: 8 tables, RLS, indexes |
| `002_enable_rls.sql` | Idempotent RLS enablement |
| `003_add_secondary_timeframe.sql` | `secondary_timeframe` column on strategies |
| `004_additional_timeframes.sql` | `additional_timeframes` JSON array column |
| `005_short_timeframes.sql` | `short_timeframes` + `short_tf_indicators` columns |
| `006_add_fmp_screener.sql` | `fmp_screener` JSON column for FMP pre-screening config |

### RLS Strategy
RLS enabled on all tables with zero policies = full deny for anon key. Backend uses service_role key (bypasses RLS).

---

## API Endpoints

| Method | Path | Auth | Rate Limit | Description |
|--------|------|------|------------|-------------|
| `GET` | `/health` | No | No | Health check with DB connectivity verification |
| `POST` | `/api/pipeline/run` | Yes | 5/min | Trigger pipeline run (strategy_id, manual_tickers, user_prompt) |
| `GET` | `/api/pipeline/status/{run_id}` | Yes | No | Get full pipeline result (reconstructs from DB) |
| `GET` | `/api/pipeline/runs` | Yes | No | List recent pipeline runs (last 100) |
| `GET` | `/api/pipeline/runs/{run_id}` | Yes | No | Alias for status endpoint |
| `GET` | `/api/strategies` | Yes | No | List user strategies (excludes templates) |
| `GET` | `/api/strategies/templates` | Yes* | No | List built-in strategy templates (*no auth enforced) |
| `GET` | `/api/strategies/{strategy_id}` | Yes | No | Get single strategy by ID |
| `POST` | `/api/strategies` | Yes | No | Create new strategy (201) |
| `POST` | `/api/charts/fetch` | Yes | No | On-demand chart image fetch |
| `GET` | `/api/settings/api-keys/status` | Yes | No | Check which API keys are configured |

**Rate limiting:** Global default 60/min via SlowAPI. Pipeline trigger is 5/min.

**Missing endpoints:** No PUT/PATCH/DELETE for strategies. No CRUD for decisions or outcomes (needed for self-learning loop).

---

## Environment Variables

### Backend (`.env` or Railway env vars)

| Variable | Required | Description |
|----------|----------|-------------|
| `PERPLEXITY_API_KEY` | Yes | Perplexity Agent API (sonar model) |
| `ANTHROPIC_API_KEY` | Yes | Claude Vision API |
| `GOOGLE_API_KEY` | Yes | Gemini with Google Search grounding |
| `OPENAI_API_KEY` | Yes | GPT bull/bear/judge debate |
| `CHARTIMG_API_KEY` | Yes | Chart-Img v2 chart generation |
| `FMP_API_KEY` | No | Financial Modeling Prep (optional pre-screening) |
| `SUPABASE_URL` | Yes (prod) | Supabase project URL |
| `SUPABASE_KEY` | Yes (prod) | Supabase service_role key (bypasses RLS) |
| `SUPABASE_JWT_SECRET` | Yes (prod) | For JWT verification (legacy, JWKS preferred) |
| `ALLOWED_ORIGINS` | Yes (prod) | CORS allowed origins (frontend domain) |

### Frontend (`.env` or Vercel env vars)

| Variable | Required | Description |
|----------|----------|-------------|
| `VITE_API_URL` | Yes | Backend URL (default: `http://localhost:8420`) |
| `VITE_SUPABASE_URL` | Yes | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Yes | Supabase anon key for auth |

---

## Frontend Conventions

- **React 19** functional components with hooks only (no class components)
- **TypeScript 5.9** strict mode
- **Tailwind v4** with `@theme` directive — dark theme only, CSS custom properties in `theme/globals.css`
- **Color palette:** GitHub Dark inspired — `bg-primary: #0d1117`, `bg-secondary: #161b22`, `accent-green: #3fb950`, `accent-red: #f85149`, `accent-blue: #58a6ff`, `accent-yellow: #d29922`
- **Vite 8** with React SWC plugin and Tailwind v4 Vite plugin
- Backend communication via `api/client.ts` using native `fetch` — no external HTTP library
- All TypeScript interfaces in `types/index.ts` must mirror the Python Pydantic models exactly
- **Lucide React** for all icons
- **React Router v7** for client-side routing
- **Supabase JS SDK** for authentication (email/password, JWT tokens)

### Frontend Views

| Route | View | Status |
|-------|------|--------|
| `/` | RecommendationsView | Active — main dashboard with ticker list + 5-tab detail panel |
| `/history` | HistoryView | Active — pipeline run history table |
| `/strategies` | StrategiesView | Active — template + user strategy grid |
| `/insights` | InsightsView | **Stub** — "Coming in Phase 5" |
| `/settings` | SettingsView | Active — account info + API key status |
| `/login` | LoginPage | Active — Supabase auth login/signup |

### Detail Panel Tabs (RecommendationsView)

| Tab | Component | Data Source |
|-----|-----------|-------------|
| Overview | `OverviewTab` | Perplexity fundamentals (market cap, P/E, highlights, risks) |
| Chart | `ChartTab` | Claude chart analysis + annotated chart images + PriceLevelMap SVG |
| Sentiment | `SentimentTab` | Gemini sentiment score, catalysts, sector sentiment |
| Synthesis | `SynthesisTab` | GPT recommendation, trade params, bull/bear debate cases |
| Raw Data | `RawTab` | Full pipeline result JSON dump |

### Notable Frontend Features
- **Multi-mode CommandBar** — auto-classifies input as discovery/analysis/combined/prompt mode with color-coded indicators
- **Collapsible ticker sidebar** — 320px expanded with full cards, 48px collapsed with just symbols
- **Ad-hoc chart fetching** — ChartTab can fetch chart images for timeframes not in the pipeline run
- **SVG PriceLevelMap** — interactive visualization of support/resistance/entry/stop/target levels
- **Expandable chart lightbox** — click to enlarge chart images with backdrop blur
- **TradingViewWidget component** — fully built with indicator mapping but **currently not rendered** (reserved for future live chart integration)

---

## Project Structure

```
signalForge/
├── CLAUDE.md                        # This file — AI assistant context
├── README.md                        # Project overview
├── Dockerfile                       # Python 3.14-slim backend container
├── railway.toml                     # Railway deployment config
├── LICENSE                          # AGPL v3.0
├── .env.example                     # Backend env template
├── .node-version                    # Node 22
├── .github/workflows/ci.yml         # GitHub Actions CI
│
├── templates/
│   └── strategies.json              # 7 strategy templates (seed data)
│
├── docs/                            # Project documentation
│   ├── DEPLOY.md                    # Deployment guide (current)
│   ├── ARCHITECTURE.md              # ⚠️ OUTDATED (still references Tauri/SQLite)
│   ├── PRD.md                       # ⚠️ PARTIALLY OUTDATED (tech stack section)
│   ├── backend/                     # Backend docs (api-reference, pipeline, services, database)
│   ├── frontend/                    # Frontend docs (components, routing)
│   ├── guides/                      # How-to guides (indicators, templates, prompts)
│   ├── research/                    # Research notes (Perplexity optimization)
│   └── plans/                       # Completed/historical plan files
│
├── src/backend/                     # Python 3.14 — ALL business logic
│   ├── main.py                      # FastAPI entry point, lifespan, CORS, rate limiting
│   ├── config.py                    # Settings from env vars, AppData paths
│   ├── pyproject.toml               # Dependencies, ruff/ty config
│   ├── .python-version              # 3.14+freethreaded
│   │
│   ├── api/                         # FastAPI route handlers (4 routers)
│   │   ├── pipeline.py              # /api/pipeline/* endpoints
│   │   ├── strategies.py            # /api/strategies/* endpoints
│   │   ├── charts.py                # /api/charts/* endpoints
│   │   └── settings.py              # /api/settings/* endpoints
│   │
│   ├── middleware/
│   │   └── auth.py                  # JWT validation via Supabase JWKS (ES256)
│   │
│   ├── pipeline/                    # LLM pipeline engine
│   │   ├── orchestrator.py          # Pipeline execution, mode determination, stage wiring
│   │   ├── schemas.py               # All Pydantic v2 models (stage contracts)
│   │   ├── validation.py            # JSON extraction, Pydantic validation, retry decorator
│   │   ├── stages/                  # One file per LLM provider
│   │   │   ├── perplexity.py        # Stage 1: Agent API + web search + FMP tool
│   │   │   ├── gemini.py            # Stage 2: Google Search grounding
│   │   │   ├── claude.py            # Stage 3: Vision API (multi-timeframe)
│   │   │   └── gpt.py               # Stage 4: Bull/bear/judge debate
│   │   ├── prompts/                 # Versioned prompt templates
│   │   │   ├── perplexity_discovery.py  # Discovery mode (v12)
│   │   │   ├── perplexity_analysis.py   # Analysis mode (v8)
│   │   │   ├── gemini_sentiment.py      # Sentiment (v2)
│   │   │   ├── claude_chart.py          # Chart analysis (v4)
│   │   │   └── gpt_debate.py           # Bull/Bear/Judge (v1/v1/v3)
│   │   └── tools/
│   │       └── fmp_tool.py          # FMP screener tool for Perplexity Agent API
│   │
│   ├── services/                    # Business logic services
│   │   ├── keyring_service.py       # API key management (6 providers)
│   │   ├── strategy.py              # Strategy CRUD + template loading
│   │   ├── chart_image.py           # Chart-Img v2 API + Supabase Storage uploads
│   │   ├── fmp_service.py           # FMP stock/crypto screener + enrichment
│   │   └── reflection.py            # Reflection context loader (read-only)
│   │
│   ├── database/
│   │   ├── connection.py            # Supabase AsyncClient singleton
│   │   └── migrations/              # 6 SQL migration files (001-006)
│   │
│   └── utils/
│       └── hashing.py               # SHA-256 prompt hashing
│
├── src/frontend/                    # React 19 + TypeScript 5.9 + Tailwind v4
│   ├── vercel.json                  # SPA rewrite rule
│   ├── .env.example                 # Frontend env template
│   ├── package.json                 # Vite 8, React 19, React Router 7
│   │
│   └── src/
│       ├── App.tsx                  # Router + AuthProvider + route definitions
│       ├── main.tsx                 # React root
│       ├── api/client.ts            # Centralized HTTP client with JWT auth
│       ├── context/AuthContext.tsx   # Supabase auth context
│       ├── lib/supabase.ts          # Supabase client initialization
│       ├── types/index.ts           # ALL TypeScript interfaces (mirrors Pydantic)
│       ├── theme/globals.css        # Dark theme tokens + Tailwind v4 @theme
│       ├── hooks/                   # usePipeline, useStrategies, useApiKeyStatus
│       ├── views/                   # 5 main views + LoginPage
│       └── components/
│           ├── auth/                # LoginPage, ProtectedRoute
│           ├── layout/              # MainLayout, Sidebar, CommandBar
│           ├── shared/              # AssetTypeBadge, TradingViewWidget
│           └── recommendations/     # TickerCardList, TickerCard, DetailView, 5 tab components, PriceLevelMap
```

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

- **Auth flow:** Frontend uses Supabase JS SDK for login/signup → gets JWT → sends JWT in `Authorization: Bearer` header to backend → backend verifies JWT via JWKS endpoint (`PyJWKClient` with 1-hour key cache, ES256 algorithm) → extracts `user_id` for data isolation. In dev mode without Supabase configured, falls back to `"dev-user-local"`.
- **Database:** Supabase PostgreSQL accessed via PostgREST (HTTPS), not raw SQL connections. Backend uses `supabase` Python SDK with service_role key.
- **Chart images:** Backend uploads PNGs to Supabase Storage `charts` bucket → stores public URL in stage_outputs → frontend loads images directly from Supabase CDN. Falls back to local filesystem when Supabase is not configured.
- **API keys:** In production, set as Railway environment variables. In development, loaded from `.env` via `python-dotenv`.
- **CORS:** Locked to frontend domain via `ALLOWED_ORIGINS` env var.

---

## Strategy System

Strategies are the core configuration unit. A strategy defines:
- **FMP pre-screening** (optional) — market filters, ratio constraints, crypto toggle
- **Perplexity screening** — prompt, constraints, max tickers
- **Gemini news** — recency window, news scope
- **Claude charts** — indicators, primary/additional/short timeframes, TA focus
- **GPT synthesis** — trading style, risk params, debate toggle

Users create strategies from templates. Templates are stored in `templates/strategies.json` and loaded on first run via `services/strategy.py → ensure_defaults()`.

### Strategy Templates (7 total)

| Template | Asset Type | Primary TF | Additional TFs | Short TFs | Debate |
|----------|-----------|------------|----------------|-----------|--------|
| Momentum Breakout | TSX stocks | D | 4H, W | — | Yes |
| Value Accumulation | TSX stocks | D | 4H, W | — | Yes |
| Mean Reversion | TSX stocks | D | 4H, W | — | Yes |
| Earnings Play | TSX stocks | D | 4H | 1H | Yes |
| Crypto Swing | Crypto | D | 4H, W | — | Yes |
| Crypto Intraday Scalp | Crypto | 4H | — | 15m, 1H | **No** |
| Intraday Scalp | TSX stocks | 4H | — | 15m, 1H | **No** |

All templates include `fmp_screener` config. Scalp templates disable debate for faster execution. Default market focus is Canadian (TSX/TSXV).

When implementing strategy-related features, remember that the strategy config drives prompt construction at every stage. The prompt modules in `pipeline/prompts/` all accept a `StrategyConfig` parameter.

---

## Perplexity Agent API

Perplexity uses the **Agent API** (`responses.create`) instead of the older chat completions API. Key details:

- Model: `perplexity/sonar`
- Built-in `web_search` tool (always enabled)
- Optional FMP function-calling tool (when FMP key is configured)
- Max 3 tool-calling rounds per run
- Domain-filtered search based on strategy type:
  - **Canadian stocks**: BNN, Globe and Mail, Financial Post, TMX, etc.
  - **US stocks**: Seeking Alpha, MarketWatch, Yahoo Finance, etc.
  - **Crypto**: CoinDesk, The Block, CoinGecko, etc.
  - **Earnings**: Earnings Whispers, Estimize, etc.
- Discovery prompts include ET time and market session label (premarket/market hours/after hours)
- TradingView ticker format enforced (e.g., `TSX:ENB`, not `ENB.TO`)

---

## Exchange/Ticker Resolution

The chart service (`services/chart_image.py`) handles multi-exchange ticker resolution:

- **EXCHANGE_SUFFIX_MAP** converts exchange suffixes to TradingView format: `.TO` → `TSX:`, `.V` → `TSXV:`, `.L` → `LSE:`, etc. (13 exchanges)
- For bare US tickers, tries NASDAQ → NYSE → AMEX sequentially via Chart-Img API
- First successful HTTP response wins
- Exchange prefixes are stripped in the collapsed ticker sidebar for readability

---

## Self-Learning Loop

The reflection engine (`services/reflection.py`) currently only **reads** the latest reflection injection prompt from the `reflections` table. Full reflection **generation** (computing win rates, confidence calibration, sector performance from `outcomes` + `decisions` tables) is planned for Phase 5 (Insights view).

The injection prompt, when populated, gets prepended to the GPT judge system prompt — this is how the system calibrates over time. It should contain concrete stats, not vague advice.

**Phase 5 prerequisites (not yet built):**
- API endpoints for creating decisions (follow/pass on recommendations)
- API endpoints for logging outcomes (trade results with entry/exit/PnL)
- Reflection generation engine to compute metrics
- Insights view to display performance data

---

## Git Workflow

**Branch model:** `main` is production (auto-deploys to Railway). `dev` is the integration branch. All work happens on feature branches off `dev`.

- **`main`** — Protected. Requires a PR with 1 approving review. No direct pushes, no force pushes, no deletions. Merging to `main` triggers Railway deployment.
- **`dev`** — Integration branch. Feature branches merge here via PR. Test and stabilize before promoting to `main`.
- **Feature branches** — Named `feature/<short-description>` (e.g. `feature/chart-improvements`). Branch off `dev`, PR back into `dev`.

```bash
# Start new work
git checkout dev
git pull origin dev
git checkout -b feature/my-feature

# When done, push and open PR into dev
git push -u origin feature/my-feature
# Then open PR: base=dev, compare=feature/my-feature

# To promote dev to production
# Open PR: base=main, compare=dev (requires 1 approval)
```

**Rules for AI agents:**
- NEVER push directly to `main`. Always use PRs.
- ALWAYS branch from `dev` for new work, not from `main`.
- When committing, commit to the current feature branch or `dev` — never to `main`.

---

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`) runs on push to `main` and on PRs to `main`:

**Backend job:**
1. `uv run ruff check` — lint check
2. `uv run ruff format --check` — format check
3. `uv run ty check` — type check

**Frontend job:**
1. `bunx tsc --noEmit` — TypeScript type check
2. `bun run build` — production build

**Note:** CI does NOT currently trigger on pushes to `dev` or feature branches (only `main` and PRs to `main`).

---

## Testing

**There are currently zero test files in the project.** No `test_*.py`, no `conftest.py`, no test directories. The CI workflow only runs linting and type checking, not tests. The `pyproject.toml` has `per-file-ignores` configured for `tests/**` but the directory doesn't exist yet.

---

## Development Workflow

```bash
# Start backend (auto-reload)
cd src/backend
uv run uvicorn main:app --reload --port 8420

# Start frontend (dev server)
cd src/frontend
bun run dev

# Code quality (run from src/backend/)
uv run ruff format            # format all Python files (Black-compatible)
uv run ruff check --fix       # lint and auto-fix
uv run ty check               # type check

# Frontend type check (run from src/frontend/)
bunx tsc --noEmit
```

---

## Critical Reminders

1. **This app never executes trades.** If you find yourself writing code that places orders, stop. The user executes in TradingView manually.

2. **API keys go in `.env` (dev) or environment variables (production), never in the database or committed config files.** See `.env.example` and `services/keyring_service.py`. There are 6 providers: perplexity, anthropic, google, openai, chartimg, fmp.

3. **Every LLM output must be Pydantic-validated.** No raw JSON dicts flowing through the pipeline. If it's not a validated model, it's a bug.

4. **Prompts are versioned.** When you change a prompt, bump the version constant. The hash gets stored with every pipeline run for performance tracking.

5. **Failed stages don't kill the pipeline.** Use the degraded pattern. GPT should always get a chance to synthesize whatever data is available. The `DATA AVAILABILITY` section in GPT prompts explicitly notes missing data.

6. **The bull/bear debate is optional per strategy.** Check `strategy.enable_debate` before making 3 GPT calls. If disabled, make a single synthesis call. Scalp templates disable debate for speed.

7. **Chart images are stored in Supabase Storage** in the `charts` bucket, organized as `{user_id}/{run_id}/{ticker}_{timeframe}.png`. Annotated charts go under `{user_id}/{run_id}/annotated/{ticker}_{timeframe}.png`. Falls back to local filesystem when Supabase is not configured. Never store data files in the project/repo tree.

8. **The frontend never calls LLM APIs directly.** All API communication goes through the Python backend. The frontend only talks to FastAPI.

9. **All API endpoints (except `/health`) require a valid Supabase JWT** in the `Authorization: Bearer` header. The backend verifies the JWT via JWKS and extracts `user_id` for multi-tenant data isolation. In dev mode, falls back to `"dev-user-local"`.

10. **Database is accessed via Supabase PostgREST**, not raw SQL connections. Use the fluent `.table().select().eq()...execute()` pattern from the `supabase` Python SDK.

11. **FMP pre-screening is optional.** If `FMP_API_KEY` is not set or `fmp_screener.enabled` is false on the strategy, Stage 0 is skipped entirely. The pipeline works fine without it.

12. **Multi-timeframe analysis runs concurrently.** Claude gets primary + additional + short timeframes all at once via `asyncio.gather`. GPT receives all timeframe analyses grouped by ticker.

13. **TypeScript types must mirror Pydantic models.** The `types/index.ts` file must stay in sync with `pipeline/schemas.py`. Use the schema-sync skill when modifying either file.

---

## Common Tasks

### Adding a new chart indicator option

1. Add the indicator name to the allowed values in `schemas.py` (`ChartAnalysis.indicator_readings`)
2. Add the indicator to `INDICATOR_MAP` (and `INDICATOR_INPUTS` if it needs custom params) in `services/chart_image.py` — these map to Chart-Img v2 `studies[]` objects in the POST body
3. Update Claude's prompt in `pipeline/prompts/claude_chart.py` to describe how to read the indicator
4. Add the indicator as an option in the frontend strategy editor (`StrategyEditor.tsx`)

### Adding a new strategy template

1. Add the template JSON to `templates/strategies.json`
2. Set `is_template: true` in the strategy object
3. Include `fmp_screener` config (set `enabled: false` if not needed)
4. The template will appear in the TemplateSelector component automatically

### Changing a prompt

1. Edit the prompt in `pipeline/prompts/{stage}.py`
2. Bump the `PROMPT_VERSION` constant
3. The hash will automatically update and be tracked in pipeline runs
4. After accumulating outcomes, compare performance between prompt versions in the Insights view

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

- **`docs/ARCHITECTURE.md`** is heavily outdated — still describes Tauri desktop shell, SQLite, sidecar process. Needs full rewrite for cloud architecture.
- **`docs/PRD.md`** tech stack section is outdated — references Tauri 2.x, SQLite, PyInstaller. Core requirements are still valid.
- **`chart_images` table** exists in schema but is unused in code — chart paths are stored in stage_outputs. May be vestigial.
- **No strategy update/delete endpoints** — only list, get, and create exist.
- **No decisions/outcomes API** — needed for Phase 5 self-learning loop.
- **Insights view is a stub** — "Coming in Phase 5".
- **No test infrastructure** — zero test files anywhere in the project.
- **`TradingViewWidget` component** — fully built with indicator mapping but not rendered in any view.
- **`App.css`** — leftover Vite template styles, dead code.
- **`tailwind-merge`** — installed as dependency but not imported by any component.
