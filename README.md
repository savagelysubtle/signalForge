# SignalForge

AI-powered stock analysis platform that chains four LLM models into a structured pipeline producing trading recommendations. **This app does not execute trades** — you review recommendations and trade manually in TradingView.

## How It Works

```
User triggers analysis
    → Perplexity screens stocks (fundamentals)
    → Gemini gathers news & sentiment
    → Claude analyzes charts with news context (Vision)
    → GPT synthesizes via bull/bear/judge debate
    → Dashboard displays recommendations
    → User decides to follow or pass
    → Logs outcome → System learns
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend hosting | Vercel (static site, auto-deploy) |
| Backend hosting | Railway (Docker, auto-deploy) |
| Auth | Supabase Auth (email/password, JWT) |
| Frontend | React + TypeScript + Tailwind (dark theme) |
| Backend | Python 3.14 (FastAPI) — all business logic |
| Database | PostgreSQL (Railway addon) |
| Chart storage | Supabase Storage |
| Package Mgr | `uv` (Python), `bun` (frontend) |
| LLM SDKs | `openai`, `anthropic`, `google-generativeai` |
| Validation | Pydantic v2 |
| Linting | `ruff` (Black rules) |

## Prerequisites

- **Python 3.14** — install via [python.org](https://www.python.org/) or `winget install Python.Python.3.14`
- **uv** — `winget install astral-sh.uv` or `pip install uv`
- **Bun** — `winget install Oven-sh.Bun`
- **Git** — `winget install Git.Git`

## Setup

### 1. Clone & install dependencies

```bash
git clone https://github.com/savagelysubtle/signalForge.git
cd signalForge

# Backend
cd src/backend
uv sync --all-groups --python 3.14

# Frontend
cd ../frontend
bun install
```

### 2. Configure environment

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```
# LLM API Keys
PERPLEXITY_API_KEY=your-key-here
ANTHROPIC_API_KEY=your-key-here
GOOGLE_API_KEY=your-key-here
OPENAI_API_KEY=your-key-here
CHARTIMG_API_KEY=your-key-here

# Cloud infrastructure (get these from your Supabase project settings)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-role-key
SUPABASE_JWT_SECRET=your-jwt-secret

# Database (local Postgres or leave blank for SQLite fallback)
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/signalforge
```

For the frontend, create `src/frontend/.env.local`:

```
VITE_API_URL=http://localhost:8420
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-key
```

> These files are gitignored. Never commit real keys.

### 3. Run the app

Open two terminals:

```bash
# Terminal 1 — Backend (auto-reload)
cd src/backend
uv run uvicorn main:app --reload --port 8420

# Terminal 2 — Frontend (dev server)
cd src/frontend
bun run dev
```

The frontend runs at `http://localhost:5173` and talks to the backend at `http://localhost:8420`.

## Project Structure

```
src/
├── backend/              # Python — ALL business logic
│   ├── main.py           # FastAPI entry point
│   ├── config.py         # App configuration
│   ├── pipeline/         # 4-stage LLM pipeline
│   │   ├── stages/       # One file per LLM provider
│   │   ├── prompts/      # Versioned prompt templates
│   │   ├── schemas.py    # Pydantic models (stage contracts)
│   │   └── orchestrator.py
│   ├── services/         # Business logic services
│   ├── api/              # FastAPI route handlers
│   └── database/         # SQLite schema and queries
│
├── frontend/             # React + TypeScript
│   ├── src/
│   │   ├── components/   # UI components by view
│   │   ├── hooks/        # Data fetching hooks
│   │   ├── api/          # Backend HTTP client
│   │   └── types/        # TypeScript interfaces
│   └── ...
│
docs/
├── ARCHITECTURE.md       # Full technical architecture
└── PRD.md                # Product requirements
```

## Pipeline Architecture

The pipeline runs four stages sequentially (with internal parallelism):

1. **Perplexity** — screens stocks by fundamentals (discovery or analysis mode)
2. **Gemini** — gathers news and scores sentiment per ticker
3. **Claude Vision** — analyzes chart images WITH news context from Gemini
4. **GPT Debate** — bull & bear cases (parallel) → judge synthesizes final recommendation

If a stage fails, the pipeline continues in degraded mode. GPT always gets a chance to synthesize whatever data is available.

## Contributing

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Make changes and test locally
3. Push and open a PR: `git push -u origin feature/your-feature`

### Code style

- **Python:** `ruff` with Black formatting, Google-style docstrings, type hints required
- **TypeScript:** `prettier`, strict mode
- Run `uv run ruff check` and `uv run ruff format` before committing

## Architecture Docs

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full technical architecture including database schema, API endpoints, frontend layout, and self-learning loop details.

## License

Private project — not open source.
