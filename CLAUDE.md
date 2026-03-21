# CLAUDE.md — SignalForge Project Context

> This file provides context for AI coding assistants working on the SignalForge project.
> Read this before making any changes to the codebase.

---

## What Is This Project?

SignalForge is a cloud-hosted stock analysis platform that chains four AI models (Perplexity, Claude, Gemini, GPT) into a pipeline that produces structured trading recommendations. It does NOT execute trades — the user reviews recommendations and trades manually in TradingView (connected to Questrade).

The core loop: User triggers analysis → Perplexity screens stocks → Gemini gathers news/sentiment → Claude reads charts with news context → GPT synthesizes via bull/bear/judge debate → Dashboard displays recommendations → User decides to follow or pass → Logs outcome → System learns.

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
| Frontend hosting | Vercel (static site) |
| Backend hosting | Railway (Docker container) |
| Auth | Supabase Auth (email/password, JWT) |
| Frontend | React + TypeScript + Tailwind (dark theme) |
| Backend | Python 3.14 (FastAPI) — ALL business logic lives here |
| Database | PostgreSQL (Railway addon) |
| Chart storage | Supabase Storage (public bucket) |
| Package manager | `uv` (Python), `bun` (frontend) |
| LLM SDKs | `openai`, `anthropic`, `google-generativeai` |
| Validation | Pydantic v2 |
| Async | `asyncio` + `httpx` |
| Linting / Formatting | `ruff` (Black-compatible) |
| Type checking | `ty` (Astral's type checker) |

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

### Sequential Stages & Parallel Execution

Perplexity gathers news article URLs alongside fundamentals and passes them to Gemini for grounded sentiment analysis. Gemini runs before Claude so that Claude receives news context for chart analysis. Claude analyzes **two timeframes** per ticker (primary + `secondary_timeframe` from strategy config, e.g. Daily + 4H) concurrently. Bull + Bear GPT calls run concurrently. After GPT, Stage 4.5 generates annotated chart images with key-level overlays via Chart-Img v2 drawings.

```python
# Perplexity screens + gathers news URLs
screening = await run_perplexity(config)

# Gemini uses Perplexity-provided article URLs for grounded sentiment
sentiment_analyses = await run_gemini_stage(tickers, config, ticker_news)

# Claude runs both timeframes per ticker concurrently
chart_analyses = await run_claude_stage(tickers, config, sentiment_analyses)

# Bull + Bear are parallel, Judge is sequential
bull_cases, bear_cases = await asyncio.gather(
    run_gpt_bull(tickers, screening, chart_analyses, sentiment_analyses, config),
    run_gpt_bear(tickers, screening, chart_analyses, sentiment_analyses, config),
    return_exceptions=True,
)

# Stage 4.5: Annotated charts with horizontal lines (support/resistance/entry/stop/target)
# Runs after GPT so trade parameters are available for overlay
await asyncio.gather(*[annotate(ca) for ca in chart_analyses])
```

### Degraded Pipeline

If a non-critical stage fails, the pipeline continues. The `PipelineResult.stage_errors` list tracks all failures.

- If **Gemini** fails, Claude proceeds without news context (the prompt omits the "Recent News Context" section). GPT judge is told sentiment data is unavailable.
- If **Claude** fails after receiving news, GPT proceeds with Perplexity fundamentals + Gemini sentiment only (no chart analysis).
- The GPT judge prompt explicitly notes which data is missing so it can adjust confidence accordingly.

### Prompt Versioning

Every prompt is stored as a Python constant with a version hash. When a prompt changes, the hash changes. The hash is stored in `pipeline_runs.prompt_versions` so you can correlate prompt iterations with outcome performance.

```python
# In pipeline/prompts/gpt_judge.py
PROMPT_VERSION = "v2"  # bump this when prompt changes

GPT_JUDGE_SYSTEM_PROMPT = """You are a senior portfolio manager..."""

def get_prompt_hash() -> str:
    return hashlib.sha256(GPT_JUDGE_SYSTEM_PROMPT.encode()).hexdigest()[:8]
```

---

## Database

PostgreSQL (Railway addon in production, can use local Postgres in development). The schema is managed via Alembic migrations in `database/migrations/`. All tables use TEXT UUIDs as primary keys (`uuid.uuid4().hex`). Multi-tenant: all user-facing tables include a `user_id` column for data isolation.

**Core tables:** `strategies`, `pipeline_runs`, `stage_outputs`, `chart_images`, `recommendations`, `decisions`, `outcomes`, `reflections`.

See `docs/ARCHITECTURE.md` section 4 for full schema.

**Important:** Never store API keys in the database. In production, they are set as Railway environment variables. In development, they go in the `.env` file at the project root (gitignored). See `.env.example` for the template. Keys are loaded at startup by `services/keyring_service.py` using `python-dotenv`.

---

## Frontend Conventions

- React functional components with hooks only (no class components)
- TypeScript strict mode
- Dark theme only — use CSS variables from `theme/dark.css`
- TradingView widgets embedded via iframes — recreate iframe on symbol change, don't try to update in place
- Backend communication via `api/client.ts` using fetch — no external HTTP library needed
- All TypeScript interfaces in `types/index.ts` must mirror the Python Pydantic models exactly

---

## Project Structure Quick Reference

```
src/backend/                 # Python — ALL business logic
  pipeline/                  # The 4-stage LLM pipeline
    stages/                  # One file per LLM provider
    prompts/                 # Prompt templates (versioned)
    schemas.py               # Pydantic models (stage contracts)
    orchestrator.py          # Pipeline execution engine
  services/                  # Business logic services
  api/                       # FastAPI route handlers
  database/                  # PostgreSQL connection and queries

src/frontend/                # React + TypeScript
  components/                # UI components grouped by view
  hooks/                     # React hooks for data fetching
  api/                       # Backend HTTP client
  types/                     # TypeScript interfaces

```

---

## Cloud Architecture

```
Vercel (frontend) ──JWT──→ Railway (FastAPI backend) ──SQL──→ Railway Postgres
                                    │
                                    ├──→ Supabase Auth (JWT verification)
                                    └──→ Supabase Storage (chart images)
```

- **Auth flow:** Frontend uses Supabase JS SDK for login/signup → gets JWT → sends JWT in `Authorization: Bearer` header to backend → backend verifies JWT using `SUPABASE_JWT_SECRET` → extracts `user_id` for data isolation.
- **Chart images:** Backend uploads PNGs to Supabase Storage `charts` bucket → stores public URL in database → frontend loads images directly from Supabase CDN.
- **API keys:** In production, set as Railway environment variables. In development, loaded from `.env` via `python-dotenv`.
- **CORS:** Locked to frontend domain via `ALLOWED_ORIGINS` env var.

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
```

---

## Critical Reminders

1. **This app never executes trades.** If you find yourself writing code that places orders, stop. The user executes in TradingView manually.

2. **API keys go in `.env` (dev) or environment variables (production), never in the database or committed config files.** See `.env.example` and `services/keyring_service.py`.

3. **Every LLM output must be Pydantic-validated.** No raw JSON dicts flowing through the pipeline. If it's not a validated model, it's a bug.

4. **Prompts are versioned.** When you change a prompt, bump the version constant. The hash gets stored with every pipeline run for performance tracking.

5. **Failed stages don't kill the pipeline.** Use the degraded pattern. GPT should always get a chance to synthesize whatever data is available.

6. **The bull/bear debate is optional per strategy.** Check `strategy.enable_debate` before making 3 GPT calls. If disabled, make a single synthesis call.

7. **Chart images are stored in Supabase Storage** in the `charts` bucket, organized as `{user_id}/{run_id}/{ticker}_{timeframe}.png`. Annotated charts (with key-level overlays) go under `{user_id}/{run_id}/annotated/{ticker}_{timeframe}.png`. The public URLs are stored on the `ChartAnalysis` model (`chart_image_path` and `annotated_chart_path`). In local development, images can fall back to local filesystem storage. Never store data files in the project/repo tree.

8. **The frontend never calls LLM APIs directly.** All API communication goes through the Python backend. The frontend only talks to FastAPI.

9. **All API endpoints (except `/health`) require a valid Supabase JWT** in the `Authorization: Bearer` header. The backend verifies the JWT and extracts `user_id` for multi-tenant data isolation.

10. **TradingView widgets are free public iframes.** No API key needed. Dark theme, transparent background, dynamic symbol updates.

---

## Strategy System

Strategies are the core configuration unit. A strategy defines:
- How Perplexity screens (prompt, constraints, max tickers)
- How Claude analyzes charts (indicators, timeframe, focus)
- How Gemini reads news (recency window, scope)
- How GPT decides (trading style, risk params, debate toggle)

Users create strategies from templates. Templates are stored in `templates/strategies.json` and loaded on first run.

When implementing strategy-related features, remember that the strategy config drives prompt construction at every stage. The prompt modules in `pipeline/prompts/` all accept a `StrategyConfig` parameter.

---

## Self-Learning Loop

The reflection engine (`services/reflection.py`) queries `outcomes` and `decisions` tables, computes performance metrics, and generates two text blobs:
1. A human-readable summary for the Insights view
2. A GPT injection prompt that gets prepended to the judge system prompt

The injection prompt is critical — it's how the system calibrates over time. It should contain concrete stats (win rates, confidence calibration, sector performance) not vague advice.

Reflections are triggered manually or after N outcome entries (configurable in settings).

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
3. The template will appear in the TemplateSelector component automatically

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
