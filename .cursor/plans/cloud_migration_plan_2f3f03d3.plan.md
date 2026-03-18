---
name: Cloud Migration Plan
overview:
  Migrate SignalForge from a local desktop app (FastAPI + React running on
  localhost) to a cloud-hosted web app using Railway (backend + Postgres),
  Vercel (frontend), and Supabase (auth + chart image storage). The migration is
  broken into 6 phases that can be implemented incrementally, with the app
  remaining functional locally throughout.
todos:
  - id: phase1-infra
    content:
      'Phase 1: Create Dockerfile, set up Railway/Vercel/Supabase projects,
      update .env.example'
    status: pending
  - id: phase2-db
    content:
      'Phase 2: Migrate SQLite to Postgres -- swap driver, add user_id columns,
      convert to Alembic migrations, update all queries'
    status: pending
  - id: phase3-backend
    content:
      'Phase 3: Backend cloud adaptation -- config overhaul, chart storage to
      Supabase, auth middleware, CORS, persistent pipeline state, fix paths'
    status: pending
  - id: phase4-frontend
    content:
      'Phase 4: Frontend auth -- Supabase Auth SDK, login page, protected
      routes, JWT in API calls, env-var URLs'
    status: pending
  - id: phase5-cicd
    content:
      'Phase 5: CI/CD -- GitHub Actions workflow, Railway + Vercel deployment
      configs'
    status: pending
  - id: phase6-hardening
    content:
      'Phase 6: Production hardening -- rate limiting, structured logging,
      Sentry, health checks, DB backups'
    status: pending
isProject: false
---

# SignalForge Cloud Migration Plan

## Target Architecture

```mermaid
graph TB
    subgraph vercel [Vercel]
        FE["React Frontend<br/>Static Site"]
    end

    subgraph supabase [Supabase]
        Auth["Supabase Auth<br/>JWT / Email+Password"]
        Storage["Supabase Storage<br/>Chart Images"]
    end

    subgraph railway [Railway]
        API["FastAPI Backend<br/>Python 3.14"]
        DB["PostgreSQL<br/>Railway Addon"]
    end

    subgraph external [External APIs]
        Perplexity
        Claude["Anthropic Claude"]
        Gemini["Google Gemini"]
        GPT["OpenAI GPT"]
        ChartImg["Chart-Img API"]
    end

    FE -->|"JWT in header"| API
    FE -->|"Login/Signup"| Auth
    FE -->|"Chart image URLs"| Storage
    API -->|"Verify JWT"| Auth
    API -->|"Store/fetch charts"| Storage
    API -->|"Read/Write"| DB
    API --> Perplexity
    API --> Claude
    API --> Gemini
    API --> GPT
    API --> ChartImg
```

## What Changes vs. What Stays

**Stays the same (zero changes):**

- All pipeline stage logic (`pipeline/stages/*.py`)
- All prompt files (`pipeline/prompts/*.py`)
- All Pydantic schemas (`pipeline/schemas.py`)
- Validation/retry logic (`pipeline/validation.py`)
- LLM SDK usage patterns
- Frontend component structure and UI
- TradingView widget integration

**Must change:**

- `config.py` -- remove `platformdirs`, use env vars
- `database/connection.py` -- SQLite to Postgres with connection pool
- `database/migrations/*.sql` -- convert to Postgres dialect + add `user_id`
- `services/keyring_service.py` -- simplify to pure `os.environ` reads
- `services/chart_image.py` -- local file writes to Supabase Storage
- `api/charts.py` -- `FileResponse` to Supabase Storage URLs
- `main.py` -- add auth middleware, lock CORS to Vercel domain
- `pipeline/orchestrator.py` -- DB-backed pipeline state instead of
  `_active_runs` dict
- `services/strategy.py` -- fix template path resolution
- `frontend/src/api/client.ts` -- env-var URL + JWT header
- `frontend/src/components/recommendations/ChartTab.tsx` -- fix hardcoded URL
- `frontend/src/App.tsx` -- add auth context + protected routes

---

## Phase 1: Infrastructure and Project Setup

**Goal:** Get all three platforms provisioned and connected, with a Dockerfile
for the backend.

### 1.1 Supabase Project

- Create a Supabase project (free tier: 2 projects, 500MB DB, 1GB storage)
- Enable Email/Password auth (simplest for 2 users, no OAuth needed)
- Create a `charts` storage bucket (public read, authenticated write)
- Note the project URL, anon key, service role key, and JWT secret

### 1.2 Railway Project

- Create a Railway project, add a PostgreSQL addon
- Configure environment variables:
  - `DATABASE_URL` (auto-set by Railway Postgres addon)
  - `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_JWT_SECRET`
  - `PERPLEXITY_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`,
    `OPENAI_API_KEY`, `CHARTIMG_API_KEY`
  - `ALLOWED_ORIGINS=https://your-app.vercel.app`
  - `ENVIRONMENT=production`
- Connect to GitHub repo for auto-deploy

### 1.3 Vercel Project

- Connect GitHub repo, set root directory to `src/frontend`
- Set environment variable: `VITE_API_URL=https://your-backend.up.railway.app`
- Set environment variable: `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`
- Auto-deploys on push to `main`

### 1.4 Backend Dockerfile

- Create `Dockerfile` at project root
- Base image: `python:3.14-slim`
- Install `uv`, copy `pyproject.toml` + `uv.lock`, run `uv sync`
- Copy `src/backend/` and `templates/`
- CMD: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Railway detects the Dockerfile and builds automatically

### 1.5 Update `.env.example`

- Add new cloud-related variables alongside existing API keys:

```
  DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
  SUPABASE_URL=https://your-project.supabase.co
  SUPABASE_SERVICE_KEY=your-service-role-key
  SUPABASE_JWT_SECRET=your-jwt-secret
  ENVIRONMENT=development
  ALLOWED_ORIGINS=http://localhost:5173


```

---

## Phase 2: Database Migration (SQLite to PostgreSQL)

**Goal:** Replace SQLite with Postgres while keeping the app runnable locally
during development.

### 2.1 Swap database driver

- Replace `aiosqlite` with `asyncpg` in
  [pyproject.toml](src/backend/pyproject.toml)
- Add `sqlalchemy[asyncio]` + `alembic` for migrations
- Update [connection.py](src/backend/database/connection.py):
  - Replace single `aiosqlite.Connection` with `asyncpg` connection pool
  - Read `DATABASE_URL` from env var
  - Remove SQLite PRAGMAs (WAL mode, foreign keys)
  - Replace `executescript()` with standard `execute()`

### 2.2 Add multi-tenancy (user_id)

- Add `user_id TEXT NOT NULL` column to: `strategies`, `pipeline_runs`,
  `recommendations`, `decisions`, `outcomes`
- Add indexes on `user_id` for all affected tables
- `stage_outputs`, `chart_images`, `reflections` inherit user scope through
  `run_id` foreign key (no direct `user_id` needed)
- Strategy templates (`is_template = true`) have `user_id = 'system'` -- visible
  to all users

### 2.3 Convert migrations to Alembic

- Initialize Alembic in `src/backend/`
- Convert [001_initial.sql](src/backend/database/migrations/001_initial.sql) and
  [002_add_prompt_mode.sql](src/backend/database/migrations/002_add_prompt_mode.sql)
  to Alembic Python migrations
- Key SQL dialect changes:
  - `BOOLEAN` stays (Postgres native)
  - `DATETIME` becomes `TIMESTAMP WITH TIME ZONE`
  - `TEXT PRIMARY KEY` stays (UUIDs as text)
  - `AUTOINCREMENT` not needed (already using UUIDs)
  - Remove `CREATE TABLE IF NOT EXISTS` idempotency -- Alembic tracks versions

### 2.4 Update all database queries

- Every query function in `services/*.py` needs `user_id` filtering:

```python
  # Before
  await db.execute("SELECT * FROM strategies WHERE id = ?", (id,))
  # After
  await pool.fetchrow("SELECT * FROM strategies WHERE id = $1 AND user_id = $2", id, user_id)


```

- Replace `?` placeholders with `$1, $2, ...` (asyncpg syntax)
- Replace `db.execute_insert` patterns with `RETURNING id` clauses

---

## Phase 3: Backend Cloud Adaptation

**Goal:** Remove all local filesystem dependencies and add authentication.

### 3.1 Config overhaul ([config.py](src/backend/config.py))

- Remove `platformdirs` import and `AppDataPaths` class
- New config reads everything from env vars:

```python
  class Settings(BaseModel):
      database_url: str
      supabase_url: str
      supabase_service_key: str
      supabase_jwt_secret: str
      allowed_origins: list[str]
      environment: Literal["development", "production"]
      port: int = 8420


```

- In development: `python-dotenv` loads `.env`; in production: Railway sets env
  vars
- Remove `paths.ensure_directories()` -- no local dirs to create

### 3.2 Chart image storage ([services/chart_image.py](src/backend/services/chart_image.py))

- Add `supabase` Python SDK (storage client)
- After fetching chart PNG from Chart-Img API, upload to Supabase Storage:

```python
  supabase.storage.from_("charts").upload(
      path=f"{user_id}/{run_id}/{ticker}_{timeframe}.png",
      file=image_bytes,
      file_options={"content-type": "image/png"}
  )


```

- Store the Supabase public URL in `chart_images.image_path` instead of local
  path
- Remove [api/charts.py](src/backend/api/charts.py) `FileResponse` endpoint --
  frontend loads images directly from Supabase Storage URL

### 3.3 Auth middleware ([main.py](src/backend/main.py))

- Create `middleware/auth.py` with a FastAPI dependency:

```python
  async def get_current_user(authorization: str = Header(...)) -> str:
      token = authorization.replace("Bearer ", "")
      payload = jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
      return payload["sub"]  # Supabase user UUID


```

- Apply as dependency to all API routes except `/health`
- Pass `user_id` to all service functions for data isolation

### 3.4 CORS lockdown ([main.py](src/backend/main.py))

- Replace `allow_origins=["*"]` with `allow_origins=settings.allowed_origins`
- In dev: `["http://localhost:5173"]`
- In prod: `["https://your-app.vercel.app"]`

### 3.5 Pipeline state persistence ([pipeline/orchestrator.py](src/backend/pipeline/orchestrator.py))

- Replace `_active_runs: dict[str, PipelineResult] = {}` with DB-backed status
- Write pipeline status to `pipeline_runs` table as stages complete
- `get_run_status()` reads from DB instead of in-memory dict
- This also enables the frontend to poll status across backend restarts

### 3.6 Template loading ([services/strategy.py](src/backend/services/strategy.py))

- Replace `Path(__file__).resolve().parents[3]` with a path relative to the
  package:

```python
  TEMPLATES_PATH = Path(__file__).parent.parent.parent.parent / "templates" / "strategies.json"


```

- Or better: bundle `templates/strategies.json` inside the Docker image at a
  known path and reference via env var

### 3.7 Keyring service simplification ([services/keyring_service.py](src/backend/services/keyring_service.py))

- Remove `.env` file path traversal (`parents[3]` hack)
- Keep `load_env()` for local dev (loads `.env` via `python-dotenv`)
- In production, `os.environ` is pre-populated by Railway -- `load_env()` is a
  no-op
- Remove the `/api/settings/api-keys/reload` endpoint -- no file to reload in
  cloud

---

## Phase 4: Frontend Auth and Cloud URLs

**Goal:** Add login/signup, JWT-authenticated API calls, and environment-driven
URLs.

### 4.1 Add Supabase Auth SDK

- `bun add @supabase/supabase-js`
- Create `src/lib/supabase.ts`:

```typescript
import { createClient } from '@supabase/supabase-js';
export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
);
```

### 4.2 Auth context and protected routes

- Create `src/context/AuthContext.tsx` -- React context wrapping
  `supabase.auth.onAuthStateChange()`
- Create `src/components/auth/LoginPage.tsx` -- email/password login + signup
  form
- Create `src/components/auth/ProtectedRoute.tsx` -- redirects to login if not
  authenticated
- Wrap all routes in `App.tsx` with `ProtectedRoute`

### 4.3 API client updates ([client.ts](src/frontend/src/api/client.ts))

- Replace hardcoded `BASE_URL`:

```typescript
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8420';
```

- Add JWT to all requests:

```typescript
const {
  data: { session },
} = await supabase.auth.getSession();
headers['Authorization'] = `Bearer ${session?.access_token}`;
```

- Fix [ChartTab.tsx](src/frontend/src/components/recommendations/ChartTab.tsx)
  hardcoded URL -- chart images now come as Supabase Storage URLs from the API
  response, no URL construction needed

### 4.4 Vite config ([vite.config.ts](src/frontend/vite.config.ts))

- Add dev proxy for local development (avoids CORS issues):

```typescript
  server: {
    proxy: { "/api": "http://localhost:8420" }
  }


```

### 4.5 Settings view update

- Remove API key reload button (keys are managed server-side now)
- Add user profile section (email, logout button)
- Show which API keys are configured (status endpoint still works)

---

## Phase 5: CI/CD and Deployment Pipeline

**Goal:** Automated testing, linting, and deployment on every push.

### 5.1 GitHub Actions workflow (`.github/workflows/ci.yml`)

```yaml
# On push to main:
# 1. Backend: ruff check + ruff format --check + ty check
# 2. Frontend: bun install + tsc --noEmit + bun run build
# 3. Both pass -> Railway auto-deploys backend, Vercel auto-deploys frontend
```

### 5.2 Railway configuration

- `railway.toml` or `Procfile` at project root
- Build command: `docker build`
- Start command: handled by Dockerfile CMD
- Health check: `GET /health`

### 5.3 Vercel configuration

- `vercel.json` in `src/frontend/` for SPA routing:

```json
{ "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }] }
```

---

## Phase 6: Production Hardening

**Goal:** Make the app reliable and monitorable.

### 6.1 Rate limiting

- Add `slowapi` to backend for per-user rate limiting on `/api/pipeline/run`
- Prevents accidental double-triggers and abuse

### 6.2 Structured logging

- Replace `print()` statements with `structlog` or Python's `logging` with JSON
  formatter
- Railway captures stdout logs automatically

### 6.3 Error monitoring

- Add Sentry SDK (free tier: 5K errors/mo) for backend error tracking
- Frontend: Sentry React SDK for catching UI errors

### 6.4 Health checks

- Expand `/health` to check DB connectivity and Supabase Storage reachability
- Railway uses this for zero-downtime deploys

### 6.5 Database backups

- Railway Postgres includes automated daily backups on paid plans
- Alternatively, set up a cron job to `pg_dump` to Supabase Storage

---

## Estimated Monthly Cost (2 users)

| Service   | Tier              | Cost                                   |
| --------- | ----------------- | -------------------------------------- |
| Railway   | Hobby ($5 credit) | ~$5-10/mo (backend compute + Postgres) |
| Vercel    | Free              | $0                                     |
| Supabase  | Free              | $0 (auth + 1GB storage)                |
| **Total** |                   | **~$5-10/mo**                          |

Note: LLM API costs (OpenAI, Anthropic, etc.) are separate and depend on usage
volume.

---

## Implementation Order

Phases 1-4 are the core migration. Phase 5-6 are polish. Each phase results in a
working state:

- After Phase 1: Infrastructure provisioned, Docker build working
- After Phase 2: Database on Postgres, schema migrated
- After Phase 3: Backend runs in cloud, no local filesystem dependencies
- After Phase 4: Frontend has auth, talks to cloud backend -- **app is usable in
  cloud**
- After Phase 5: Automated deploys on git push
- After Phase 6: Production-grade reliability

Recommend implementing phases 2+3 together (they're tightly coupled), then phase
4, then 1+5 (deployment), then 6.

Suggested development branch: `feature/cloud-migration`
