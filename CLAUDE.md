# CLAUDE.md — SignalForge Project Context

> This file provides context for AI coding assistants working on the SignalForge project.
> Read this before making any changes to the codebase.

---

## What Is This Project?

SignalForge is a desktop stock analysis platform that chains four AI models (Perplexity, Claude, Gemini, GPT) into a pipeline that produces structured trading recommendations. It does NOT execute trades — the user reviews recommendations and trades manually in TradingView (connected to Questrade).

The core loop: User triggers analysis → Perplexity screens stocks → Claude reads charts + Gemini reads news (parallel) → GPT synthesizes via bull/bear/judge debate → Dashboard displays recommendations → User decides to follow or pass → Logs outcome → System learns.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Desktop shell | Tauri 2.x (Rust) — thin wrapper only |
| Frontend | React + TypeScript + Tailwind (dark theme) |
| Backend | Python 3.14 (FastAPI) — ALL business logic lives here |
| Database | SQLite (WAL mode) |
| Package manager | `uv` (Python), `bun` (frontend) |
| LLM SDKs | `openai`, `anthropic`, `google-generativeai` |
| Validation | Pydantic v2 |
| Async | `asyncio` + `httpx` |
| Linting | `ruff` (Black rules) |

---

## Python Code Style (STRICT)

These rules are non-negotiable. Every Python file must follow them.

```python
# Linting: ruff with Black formatting rules
# Line length: 88 (Black default)
# String formatting: f-strings ONLY (no .format(), no %)
# Type hints: REQUIRED on all function signatures
# Docstrings: Google style, REQUIRED on all public functions/classes
# Imports: sorted by ruff (isort-compatible)

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

**Ruff configuration** (`pyproject.toml`):

```toml
[tool.ruff]
line-length = 88
target-version = "py314"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "N",   # pep8-naming
    "UP",  # pyupgrade
    "B",   # flake8-bugbear
    "SIM", # flake8-simplify
    "TCH", # flake8-type-checking
]

[tool.ruff.format]
quote-style = "double"
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

### Parallel Execution

Claude + Gemini stages run concurrently. Bull + Bear GPT calls run concurrently. Use `asyncio.gather()` with `return_exceptions=True` to handle partial failures:

```python
claude_result, gemini_result = await asyncio.gather(
    run_claude_stage(tickers, config),
    run_gemini_stage(tickers, config),
    return_exceptions=True,
)
# Check if either is an Exception and handle degraded state
```

### Degraded Pipeline

If a non-critical stage fails (Gemini sentiment, for example), the pipeline continues. The GPT judge prompt explicitly notes what data is missing. The `PipelineResult.stage_errors` list tracks all failures.

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

SQLite with WAL mode. The schema is defined in `database/migrations/`. All tables use TEXT UUIDs as primary keys (`uuid.uuid4().hex`).

**Core tables:** `strategies`, `pipeline_runs`, `stage_outputs`, `chart_images`, `recommendations`, `decisions`, `outcomes`, `reflections`.

See `docs/ARCHITECTURE.md` section 4 for full schema.

**Important:** Never store API keys in SQLite. They go in Windows Credential Manager via the `keyring` library (`services/keyring.py`).

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
  database/                  # SQLite schema and queries

src/frontend/                # React + TypeScript
  components/                # UI components grouped by view
  hooks/                     # React hooks for data fetching
  api/                       # Backend HTTP client
  types/                     # TypeScript interfaces

src/tauri/                   # Rust — Tauri shell only
  src/main.rs                # Sidecar management
```

---

## Development Workflow

```bash
# Start backend (auto-reload)
cd src/backend
uv run uvicorn main:app --reload --port 8420

# Start frontend (dev server)
cd src/frontend
bun run dev

# Start Tauri (dev mode — wraps both)
cd src/tauri
cargo tauri dev
```

---

## Critical Reminders

1. **This app never executes trades.** If you find yourself writing code that places orders, stop. The user executes in TradingView manually.

2. **API keys go in OS keyring, never SQLite or config files.** Check `services/keyring.py`.

3. **Every LLM output must be Pydantic-validated.** No raw JSON dicts flowing through the pipeline. If it's not a validated model, it's a bug.

4. **Prompts are versioned.** When you change a prompt, bump the version constant. The hash gets stored with every pipeline run for performance tracking.

5. **Failed stages don't kill the pipeline.** Use the degraded pattern. GPT should always get a chance to synthesize whatever data is available.

6. **The bull/bear debate is optional per strategy.** Check `strategy.enable_debate` before making 3 GPT calls. If disabled, make a single synthesis call.

7. **Chart images are stored in AppData** at `%APPDATA%\SignalForge\charts\` (resolved via `platformdirs`), referenced by path in SQLite. Don't base64-encode them in the database. Never store data files in the project/repo tree.

8. **The frontend never calls LLM APIs directly.** All API communication goes through the Python backend. The frontend only talks to FastAPI.

9. **SQLite WAL mode** is set at connection time. This allows the frontend to read while the backend writes during pipeline execution.

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
2. Update the Chart-Img API URL builder in `services/chart_image.py` to include the indicator
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
