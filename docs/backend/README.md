# Backend Overview

> **Stack:** Python 3.14 · FastAPI · Pydantic v2 · Supabase (PostgreSQL) · uv
> **Source:** [`src/backend/`](../../src/backend/)

The backend is the brain of SignalForge. It hosts all business logic, the
LLM pipeline, database access, and REST API. The frontend never calls LLM
APIs directly — everything goes through this FastAPI server.

---

## Project Structure

```
src/backend/
├── main.py                    # FastAPI app, lifespan, CORS, rate limiting
├── config.py                  # Settings from env vars, AppData paths
├── api/                       # Route handlers (4 routers)
│   ├── pipeline.py            # /api/pipeline/* — trigger and query runs
│   ├── strategies.py          # /api/strategies/* — CRUD strategies
│   ├── charts.py              # /api/charts/* — on-demand chart images
│   └── settings.py            # /api/settings/* — API key status
├── middleware/
│   └── auth.py                # JWT verification, CurrentUser dependency
├── pipeline/                  # The LLM analysis pipeline
│   ├── orchestrator.py        # Execution engine (runs all stages)
│   ├── schemas.py             # Pydantic models (data contracts)
│   ├── validation.py          # JSON extraction, retry logic
│   ├── stages/                # One file per LLM provider
│   │   ├── perplexity.py      # Stage 1: stock screening
│   │   ├── gemini.py          # Stage 2: news sentiment
│   │   ├── claude.py          # Stage 3: chart analysis
│   │   └── gpt.py             # Stage 4: bull/bear/judge debate
│   └── prompts/               # Versioned prompt templates
│       ├── perplexity_discovery.py
│       ├── perplexity_analysis.py
│       ├── gemini_sentiment.py
│       ├── claude_chart.py
│       └── gpt_debate.py
├── services/                  # Business logic layer
│   ├── strategy.py            # Strategy CRUD + template seeding
│   ├── chart_image.py         # Chart-Img v2 API + Supabase Storage
│   ├── keyring_service.py     # API key loading from env
│   └── reflection.py          # Self-learning context from outcomes
├── database/
│   ├── connection.py          # Supabase async client (singleton)
│   └── migrations/            # SQL schema files (001–005)
└── utils/
    └── hashing.py             # Prompt hash utility
```

---

## Application Startup

The app uses FastAPI's `lifespan` context manager. On startup:

1. **`load_env()`** — loads `.env` file for API keys and config
2. **`init_db()`** — creates the Supabase async client singleton
3. **`ensure_defaults()`** — seeds strategy templates from
   `templates/strategies.json` if the `strategies` table is empty

On shutdown:

1. **`close_db()`** — cleanly closes the Supabase client

---

## Configuration

There is no `config/` directory. All config lives in a single
[`config.py`](../../src/backend/config.py) at the backend root.

### Settings (from environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENVIRONMENT` | `development` | `development` or `production` |
| `DATABASE_URL` | *(empty)* | PostgreSQL connection string (production) |
| `SUPABASE_URL` | *(empty)* | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | *(empty)* | Supabase service role key |
| `SUPABASE_JWT_SECRET` | *(empty)* | JWT verification secret |
| `SUPABASE_ANON_KEY` | *(empty)* | Supabase anonymous key |
| `ALLOWED_ORIGINS` | `http://localhost:5173` | Comma-separated CORS origins |
| `PORT` | `8420` | HTTP server port |

### API Keys (loaded by `keyring_service.py`)

| Variable | Service |
|----------|---------|
| `PERPLEXITY_API_KEY` | Perplexity Sonar Pro |
| `ANTHROPIC_API_KEY` | Claude Vision |
| `GOOGLE_API_KEY` | Gemini |
| `OPENAI_API_KEY` | GPT |
| `CHART_IMG_API_KEY` | Chart-Img v2 |

All keys come from `.env` in development or Railway environment variables in
production. Never stored in the database or committed to version control.

---

## Middleware

### Authentication (`middleware/auth.py`)

All API endpoints (except `GET /health`) require a valid Supabase JWT in
the `Authorization: Bearer <token>` header.

- **`get_current_user()`** — FastAPI dependency that verifies the JWT,
  extracts `sub` (user UUID), and returns it as a string.
- **`CurrentUser`** — `Annotated[str, Depends(get_current_user)]` for
  convenient injection into route handlers.
- **Dev fallback** — when `SUPABASE_URL` is unset, returns `"dev-user-local"`
  to allow local development without auth.

### Rate Limiting

SlowAPI `Limiter` applies a default rate of **60 requests/minute** per
client IP. The pipeline trigger endpoint has a tighter limit of
**5 requests/minute**.

### CORS

`CORSMiddleware` is configured from `settings.allowed_origins`. In
development this defaults to `http://localhost:5173` (Vite dev server).

---

## Running Locally

```bash
cd src/backend
uv run uvicorn main:app --reload --port 8420
```

The backend binds to `http://localhost:8420`. The frontend dev server
(port 5173) proxies API calls here.

---

## Code Quality

```bash
cd src/backend
uv run ruff format          # format (Black-compatible)
uv run ruff check --fix     # lint + auto-fix
uv run ty check             # type check
```

See [CLAUDE.md](../../CLAUDE.md) for the full ruff and ty configuration.

---

## Related Docs

- [API Reference](api-reference.md) — all endpoints
- [Pipeline Deep Dive](pipeline.md) — the LLM pipeline
- [Services Layer](services.md) — business logic
- [Database Schema](database.md) — tables and migrations
