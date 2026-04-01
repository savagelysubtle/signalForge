# CLAUDE.md — SignalForge Quick Reference

> Lightweight project context for AI agents. For full details on any section, see
> [`CLAUDE2.md`](CLAUDE2.md).

---

## What Is This Project?

SignalForge is a cloud-hosted **stock and crypto** analysis platform that chains
an optional FMP pre-screener plus four AI models (Perplexity → Gemini → Claude →
GPT) into a pipeline producing structured trading recommendations. It does
**NOT** execute trades — the user trades manually in TradingView.

---

## Agent Rules (READ FIRST)

1. **Use subagents aggressively.** Delegate to Explorer, Researcher, Debugger,
   Implementer, Quality, Git, or Strategist subagents. Keep main context clean.
2. **Use skills wherever they fit.** Check available skills before starting work.
3. **Parallel subagents** when tasks are independent.
4. **Context hygiene.** Summarize subagent results; don't dump raw output.
5. **Plan before building** for non-trivial (multi-file / architectural) changes.
6. **Ask questions** for ambiguous or multi-step tasks.

---

## Tech Stack

| Layer        | Technology                                            |
| ------------ | ----------------------------------------------------- |
| Frontend     | React 19 + TypeScript 5.9 + Tailwind v4 + Vite 8     |
| Backend      | Python 3.14 (FastAPI) — ALL business logic lives here |
| Hosting      | Vercel (frontend), Railway (backend)                  |
| Database     | Supabase PostgreSQL via PostgREST (not raw SQL)       |
| Auth         | Supabase Auth (ES256 JWT via JWKS)                    |
| Storage      | Supabase Storage (`charts` bucket)                    |
| Pkg managers | `uv` (Python), `bun` (frontend)                      |
| Quality      | `ruff` (lint/format), `ty` (type check), `tsc`        |
| LLM SDKs     | openai, anthropic, google-generativeai, perplexityai  |
| Data APIs    | FMP (Financial Modeling Prep), Chart-Img v2           |
| License      | AGPL v3.0                                             |

---

## Python Code Style (STRICT)

- **Formatter:** `ruff format` | **Linter:** `ruff check` | **Types:** `ty check`
- Line length 100, f-strings only, type hints required, Google-style docstrings
- See [`CLAUDE2.md` → Python Code Style](CLAUDE2.md#python-code-style--full-example)
  for full example and config dumps

---

## Code Quality Commands

```bash
cd src/backend
uv run ruff format          # format
uv run ruff check --fix     # lint + auto-fix
uv run ty check             # type check
```

After editing Python: run format + lint. Before completing a task: run ty check.
Never use `# noqa` or `# type: ignore` without a justification comment.

---

## Project Structure

```
signalForge/
├── src/backend/          # Python 3.14 FastAPI
│   ├── api/              # Route handlers
│   ├── pipeline/         # LLM engine: orchestrator, schemas, validation, stages/, prompts/, tools/
│   ├── services/         # Business logic (chart_image, fmp_service, strategy, keyring, reflection)
│   ├── database/         # Supabase connection + SQL migrations
│   └── middleware/       # JWT auth
├── src/frontend/src/     # React 19 + TypeScript 5.9 + Tailwind v4
│   ├── views/            # Recommendations, History, Strategies, Insights, Settings, Login
│   ├── components/       # auth/, layout/, shared/, recommendations/
│   ├── hooks/            # usePipeline, useStrategies, useApiKeyStatus, useInsights
│   ├── api/client.ts     # HTTP client with JWT auth
│   └── types/index.ts    # TypeScript interfaces (must mirror Pydantic schemas)
├── templates/strategies.json
└── .github/workflows/ci.yml
```

---

## Pipeline Overview

```
Stage 0: FMP Pre-Screening (optional)
  → Stage 1: Perplexity (screening/discovery)
    → Stage 2: Gemini (news/sentiment per ticker)
      → Stage 3: Claude Vision (chart analysis, multi-timeframe concurrent)
        → Stage 4: GPT (bull/bear/judge debate, optional per strategy)
          → Stage 4.5: Annotated Charts (Chart-Img v2)
```

Modes: `discovery` | `analysis` | `combined` | `prompt`. Failed stages degrade
gracefully — GPT always gets a chance to synthesize available data.

See [`CLAUDE2.md` → Pipeline Architecture](CLAUDE2.md#pipeline-architecture) for
stage contract, concurrency, degraded pipeline, and prompt versioning details.

---

## Git Workflow

- **`main`** — production (auto-deploys to Railway). Protected, PR-only.
- **`dev`** — integration branch. Feature branches merge here.
- **Feature branches** — `feature/<name>`, branch from `dev`, PR into `dev`.
- **AI agents:** NEVER push to `main`. ALWAYS branch from `dev`.

---

## Development Workflow

```bash
cd src/backend && uv run uvicorn main:app --reload --port 8420   # backend
cd src/frontend && bun run dev                                    # frontend
```

---

## Critical Reminders

1. **Never execute trades.** Analysis and recommendations only.
2. **API keys in `.env` (dev) or env vars (prod)**, never in DB or committed files.
3. **Every LLM output must be Pydantic-validated.** No raw JSON dicts.
4. **Prompts are versioned.** Bump `PROMPT_VERSION` when changing prompts.
5. **Failed stages don't kill the pipeline.** Use the degraded pattern.
6. **Bull/bear debate is optional** per strategy (`enable_debate` flag).
7. **Chart images → Supabase Storage** (`charts` bucket), not local filesystem.
8. **Frontend never calls LLM APIs directly.** All through FastAPI backend.
9. **All endpoints (except `/health`) require Supabase JWT.**
10. **Database via PostgREST** — `.table().select().eq()...execute()` pattern.
11. **TypeScript types must mirror Pydantic models.** Use schema-sync skill.

---

## Detailed Reference

For full details on any of these topics, see [`CLAUDE2.md`](CLAUDE2.md):

- Python code style example and ruff/ty config
- Pipeline stage contract, flow diagram, concurrency, degraded fallback
- Prompt versioning system
- FMP integration (stock/crypto screening, tool calling)
- Multi-timeframe chart analysis and supported indicators
- Database schema, tables, migrations, RLS
- Full API endpoint table
- Environment variables (backend + frontend)
- Frontend conventions, views, detail panel tabs, notable features
- Cloud architecture diagram and auth flow
- Strategy system and templates
- Perplexity Agent API and exchange/ticker resolution
- Self-learning loop (reflections, feedback sync)
- CI/CD pipeline details
- Common tasks (add indicator, add template, change prompt, add stage, add endpoint)
- Known gaps and future work
