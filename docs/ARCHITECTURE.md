# SignalForge — Technical Architecture

> **Version:** current
> **Last Updated:** March 2026
> **Authoritative reference:** [`CLAUDE.md`](../CLAUDE.md) at the repo root.

> **⚠️ Historical note:** A previous version of this document described a Tauri desktop shell + SQLite architecture. That design was never shipped. The document below reflects the **current cloud deployment**.

---

## 1. System Architecture Overview

SignalForge is a cloud-hosted web application. A React SPA (Vercel) communicates with a Python FastAPI backend (Railway) which persists data in Supabase PostgreSQL and stores chart images in Supabase Storage.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Browser (SPA)                                 │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │         React 19 + TypeScript 5.9 + Tailwind v4             │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │    │
│  │  │Dashboard │ │ History  │ │Strategies│ │   Insights   │   │    │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │    │
│  └────────────────────────── JWT Bearer ────────────────────────┘    │
└──────────────────────────────┬─────────────────────────────────────-┘
                               │ HTTPS
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                Railway (Docker)                                       │
│              Python 3.14 FastAPI backend                             │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                  Pipeline Orchestrator                        │   │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌───────────────────┐  │   │
│  │  │ Stage 0 │ │ Stage 1 │ │ Stage 2 │ │     Stage 3       │  │   │
│  │  │  FMP    │ │Perplexty│ │ Gemini  │ │  Claude Vision    │  │   │
│  │  │(optional│ │  Agent  │ │ Search  │ │  (multi-TF,       │  │   │
│  │  │pre-scrn)│ │   API   │ │grounding│ │   concurrent)     │  │   │
│  │  └─────────┘ └─────────┘ └─────────┘ └───────────────────┘  │   │
│  │  ┌──────────────────────────────────────────────────────────┐ │   │
│  │  │    Stage 4: GPT Bull/Bear/Judge Debate                   │ │   │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────────────────────┐ │ │   │
│  │  │  │   Bull   │ │   Bear   │ │   Judge (+ reflection)   │ │ │   │
│  │  │  └──────────┘ └──────────┘ └──────────────────────────┘ │ │   │
│  │  └──────────────────────────────────────────────────────────┘ │   │
│  │  ┌──────────────────────────────────────────────────────────┐ │   │
│  │  │   Stage 4.5: Annotated Charts (Chart-Img v2 overlays)   │ │   │
│  │  └──────────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                     │ PostgREST HTTPS          │ Storage HTTPS       │
└─────────────────────┼──────────────────────────┼────────────────────┘
                      ▼                           ▼
          ┌──────────────────────┐    ┌──────────────────────┐
          │  Supabase PostgreSQL  │    │  Supabase Storage    │
          │  (multi-tenant,       │    │  charts bucket:      │
          │   PostgREST API,      │    │  {uid}/{run}/{ticker}│
          │   service_role key)   │    │  _{timeframe}.png    │
          └──────────────────────┘    └──────────────────────┘
```

---

## 2. Process Architecture

There is no sidecar, no desktop shell, and no local database. The deployment model is:

```
User's Browser
    │
    │  HTTPS (Vercel CDN → SPA)
    ▼
React SPA on Vercel
    │
    │  HTTPS + JWT Bearer header
    ▼
FastAPI on Railway (Docker container)
    │  python-uvicorn, port 8420 in Railway
    ├──→ Supabase Auth (JWKS endpoint — ES256 JWT verification)
    ├──→ Supabase PostgreSQL (PostgREST, service_role key)
    ├──→ Supabase Storage (charts bucket)
    ├──→ Perplexity Agent API
    ├──→ Google GenAI (Gemini + Search grounding)
    ├──→ Anthropic Vision API (Claude)
    ├──→ OpenAI Chat Completions (GPT)
    ├──→ Chart-Img v2 API
    └──→ FMP (Financial Modeling Prep) — optional
```

**Auth flow:**
1. Frontend calls `supabase.auth.signInWithPassword()` → receives JWT (ES256)
2. JWT is attached to every API call as `Authorization: Bearer <token>`
3. FastAPI middleware (`middleware/auth.py`) verifies JWT via JWKS endpoint with `PyJWKClient`
4. `user_id` (JWT `sub` claim) is extracted and injected into every handler via `CurrentUser` dependency
5. Dev fallback: when `SUPABASE_URL` is unset, returns `"dev-user-local"` for local development without auth

---

## 3. Pipeline Architecture

### 3.1 Full Pipeline Flow

```
Stage 0 (Optional): FMP Pre-Screening
    │  Stock screener (company-screener API) + ratios-ttm enrichment
    │  OR crypto batch quotes + market-cap filtering
    │  Output: enriched ticker list passed to Perplexity
    ↓ (skip if FMP_API_KEY not set or fmp_screener.enabled=false)

Stage 1: Perplexity Screening/Research
    │  Agent API (responses.create) with web_search tool
    │  Optional FMP function-calling tool (max 3 tool rounds)
    │  Discovery mode: screen market | Analysis mode: research tickers
    │  Output: ScreeningResult (tickers, fundamentals, news_urls)
    ↓

Stage 2: Gemini Sentiment (per ticker, Semaphore(5))
    │  Google GenAI SDK with Google Search grounding
    │  Uses Perplexity news_urls for grounded analysis
    │  Output: SentimentAnalysis per ticker
    ↓

Stage 3: Claude Chart Analysis (per ticker × per timeframe, asyncio.gather)
    │  Anthropic Vision API with base64 chart PNG
    │  Primary + additional + short timeframes ALL concurrent
    │  Receives news context from Gemini
    │  Output: ChartAnalysis per ticker per timeframe
    ↓

Stage 4: GPT Debate (per ticker)
    │  Bull + Bear run in parallel (asyncio.gather)
    │  Judge runs sequentially after both complete
    │  Optional (enable_debate=false → single synthesis call)
    │  Receives reflection_context from reflections table
    │  Output: Recommendation per ticker
    ↓

Stage 4.5: Annotated Charts
    │  Chart-Img v2 with horizontal line drawings[]
    │  Entry / stop loss / take profit / key levels
    │  Max 5 drawings per chart (PRO plan limit)
    │  Output: annotated PNGs uploaded to Supabase Storage
```

### 3.2 Pipeline Modes

| Mode | Trigger | Behaviour |
|------|---------|-----------|
| `discovery` | `strategy_id` only | Perplexity screens market for new opportunities |
| `analysis` | `manual_tickers` only | Perplexity researches given tickers |
| `combined` | `strategy_id` + `manual_tickers` | Both screening and targeted research |
| `prompt` | `user_prompt` free text | Natural language drives screening |

### 3.3 Pydantic Schemas (Data Contracts)

All stage outputs are validated Pydantic models. Raw LLM JSON is never passed between stages.

| Model | Stage | Key Fields |
|-------|-------|-----------|
| `ScreeningResult` | 1 | `tickers`, `fundamental_data[]`, `news_urls` |
| `SentimentAnalysis` | 2 | `ticker`, `sentiment_score`, `catalysts[]`, `sector_sentiment` |
| `ChartAnalysis` | 3 | `ticker`, `timeframe`, `trend_direction`, `patterns_detected[]`, `key_levels`, `overall_bias` |
| `Recommendation` | 4 | `ticker`, `action` (`BUY`/`SHORT`/`HOLD`), `confidence`, `entry_price`, `stop_loss`, `take_profit`, `risk_reward_ratio`, `bull_case`, `bear_case`, `judge_reasoning` |
| `PipelineResult` | output | `run_id`, `screening`, `chart_analyses[]`, `sentiment_analyses[]`, `recommendations[]`, `stage_errors[]`, `prompt_versions` |

### 3.4 Degraded Pipeline

If a non-critical stage fails, the pipeline continues:

- **FMP fails** → Perplexity proceeds without pre-screened data
- **Gemini fails** → Claude proceeds without news context; GPT judge is told sentiment is unavailable
- **Claude fails** → GPT proceeds with fundamentals + sentiment only (no chart analysis)
- **Stage errors** accumulate in `PipelineResult.stage_errors`; the GPT judge's `DATA AVAILABILITY` section explicitly notes missing data

### 3.5 Concurrency Control

| Stage | Semaphore | Notes |
|-------|-----------|-------|
| Perplexity | `Semaphore(3)` | Per-ticker analysis |
| Gemini | `Semaphore(5)` | Per-ticker |
| Claude | `Semaphore(3)` | Per-ticker per-timeframe |
| FMP | `Semaphore(5)` | Enrichment calls |
| GPT Bull + Bear | `asyncio.gather` | Parallel, no semaphore |

---

## 4. Database

**Engine:** Supabase PostgreSQL
**Client:** Supabase Python async SDK (`create_async_client`), PostgREST over HTTPS
**Key:** service_role key (bypasses RLS); backend enforces `user_id` filtering on every query

### 4.1 Entity Relationship

```
strategies ─────────────────────────────────────────┐
                                                     │ strategy_id (FK)
                                                     ▼
pipeline_runs ──────────┬────────────────────────────┤
      │                 │ run_id (FK)                │ run_id (FK)
      │                 ▼                            ▼
      │          stage_outputs               recommendations
      │                                           │
      │                                           │ recommendation_id (FK)
      │                                           ▼
      │          chart_images                  decisions
      │          (run_id FK)                      │
      │                                           │ decision_id (FK)
      │                                           ▼
      │                                        outcomes
      │
      └──────────────────────────── reflections (standalone, user_id)
```

### 4.2 Table Summary

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `strategies` | Pipeline configuration | `user_id`, `name`, `chart_indicators`, `fmp_screener` (JSON), `enable_debate`, `run_count` |
| `pipeline_runs` | Execution history | `user_id`, `strategy_id`, `mode`, `status`, `prompt_versions` (JSON), `user_prompt`, `stage_errors` |
| `stage_outputs` | Raw LLM data | `run_id`, `stage`, `ticker`, `prompt_text`, `raw_response`, `model_used`, `duration_ms`, `status` |
| `chart_images` | Chart metadata | `run_id`, `ticker`, `timeframe`, `image_path` (Supabase CDN URL) — *currently vestigial* |
| `recommendations` | GPT judge outputs | `user_id`, `run_id`, `ticker`, `action` (BUY/SHORT/HOLD), `confidence`, `entry_price`, `stop_loss`, `take_profit`, `bull_case`, `bear_case`, `judge_reasoning` |
| `decisions` | User follow/pass | `user_id`, `recommendation_id`, `decision` (following/passing), `reason`, `reason_category`, `decided_at` |
| `outcomes` | Trade results | `user_id`, `decision_id`, `recommendation_id`, `ticker`, `entry_price`, `exit_price`, `pnl_dollars`, `pnl_percent`, `holding_days`, `exit_reason` |
| `reflections` | Self-learning memory | `user_id`, `injection_prompt`, `summary_text`, `metrics` (JSON), `outcomes_analyzed` |

### 4.3 Migrations

Sequential SQL files in `src/backend/database/migrations/`. Applied manually via Supabase SQL editor. There is no automated migration runner.

| File | Purpose |
|------|---------|
| `001_initial.sql` | Full schema: all 8 tables, indexes, RLS |
| `002_enable_rls.sql` | Ensure RLS is enabled (idempotent) |
| `003_add_secondary_timeframe.sql` | `secondary_timeframe` on strategies |
| `004_additional_timeframes.sql` | `additional_timeframes` JSON column on strategies |
| `005_short_timeframes.sql` | `short_timeframes` and `short_tf_indicators` on strategies |
| `006_add_fmp_screener.sql` | `fmp_screener` JSON column on strategies |
| `007_add_user_prompt.sql` | `user_prompt` TEXT on pipeline_runs |
| `008_add_user_id_to_reflections.sql` | `user_id` on reflections for multi-tenant isolation |
| `009_add_atr_to_chart_indicators.sql` | ATR metadata in chart indicators |
| `010_rename_sell_to_short.sql` | Rename `SELL` → `SHORT` in recommendations.action |

### 4.4 Row Level Security

RLS is enabled on all tables with zero policies (full deny for the anon key). The service_role key bypasses RLS entirely. The backend enforces data isolation by always filtering on `user_id`.

---

## 5. API Design

### 5.1 Authentication

All endpoints except `GET /health` require `Authorization: Bearer <Supabase JWT>`.

Middleware (`middleware/auth.py`):
1. Extract token from `Authorization` header
2. Verify via JWKS (`PyJWKClient`, 1-hour key cache, ES256 algorithm)
3. Return `user_id` (JWT `sub` claim)
4. Dev fallback: `SUPABASE_URL` unset → `"dev-user-local"`

### 5.2 Rate Limiting

- **Global:** 60 requests/minute per IP (SlowAPI)
- **Pipeline trigger:** 5 requests/minute

### 5.3 Endpoint Reference

| Method | Path | Auth | Rate | Description |
|--------|------|------|------|-------------|
| `GET` | `/health` | No | — | Liveness + DB connectivity check |
| `POST` | `/api/pipeline/run` | Yes | 5/min | Trigger pipeline run |
| `GET` | `/api/pipeline/status/{run_id}` | Yes | — | Full `PipelineResult` |
| `GET` | `/api/pipeline/runs` | Yes | — | Recent runs (last 100) |
| `GET` | `/api/pipeline/runs/{run_id}` | Yes | — | Alias for status endpoint |
| `GET` | `/api/strategies` | Yes | — | User strategies |
| `GET` | `/api/strategies/templates` | Yes* | — | Built-in templates |
| `GET` | `/api/strategies/{id}` | Yes | — | Single strategy |
| `POST` | `/api/strategies` | Yes | — | Create strategy (201) |
| `POST` | `/api/charts/fetch` | Yes | — | On-demand chart image |
| `GET` | `/api/settings/api-keys/status` | Yes | — | Which API keys are configured |
| `POST` | `/api/decisions/recommendations/{id}/decision` | Yes | — | Record follow/pass (201) |
| `GET` | `/api/decisions` | Yes | — | List decisions (filterable) |
| `GET` | `/api/decisions/{id}` | Yes | — | Single decision |
| `DELETE` | `/api/decisions/{id}` | Yes | — | Delete decision (cascade-deletes outcome) |
| `POST` | `/api/outcomes/decisions/{id}/outcome` | Yes | — | Log trade outcome (201) |
| `PUT` | `/api/outcomes/{id}` | Yes | — | Update outcome |
| `GET` | `/api/outcomes` | Yes | — | List outcomes |
| `GET` | `/api/recommendations` | Yes | — | Recommendations with decision/outcome status |
| `GET` | `/api/recommendations/{id}` | Yes | — | Single recommendation with status |
| `GET` | `/api/insights/overview` | Yes | — | Aggregated performance + calibration |
| `POST` | `/api/insights/reflect` | Yes | — | Generate reflection (requires ≥5 outcomes) |
| `GET` | `/api/insights/reflections/latest` | Yes | — | Most recent reflection |

**Missing endpoints (known gaps):** No PUT/PATCH/DELETE for strategies. No DELETE for outcomes (only cascade via decision delete). No reflection history list (only latest).

---

## 6. Frontend Architecture

### 6.1 Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | React 19 (functional components + hooks only) |
| Language | TypeScript 5.9 (strict mode) |
| Build | Vite 8 with React SWC plugin |
| Styling | Tailwind CSS v4 with `@theme` directive |
| Router | React Router v7 |
| Icons | Lucide React |
| Auth client | Supabase JS SDK (`@supabase/supabase-js`) |
| Animation | `motion/react` (AnimatePresence, staggered reveals) |
| HTTP | Native `fetch` (no Axios) |
| Fonts | JetBrains Mono (data/tickers) + Satoshi (body) |
| Package manager | `bun` |

### 6.2 Design System (Urban Finance)

Dark theme only. CSS variables in `theme/globals.css`:

| Token | Hex | Role |
|-------|-----|------|
| `--bg-void` | `#08090d` | Deepest background |
| `--bg-asphalt` | `#0f1118` | Primary surface |
| `--bg-concrete` | `#181c27` | Cards / inputs |
| `--accent-profit` | `#00e59b` | Bullish / positive |
| `--accent-loss` | `#ff3b5c` | Bearish / negative |
| `--accent-signal` | `#4d8dff` | Links / active state |
| `--accent-alert` | `#ffb224` | Warnings / pending |

Photo background (`bg-urban-finance.jpg`) — desaturated metropolitan skyline — is a fixed layer visible through all views via `MainLayout`.

### 6.3 Routing

```
/login              → LoginPage (public)
/                   → ProtectedRoute → MainLayout
  /                 → RecommendationsView
                      SearchScreen (no ?run param)
                      ResultsScreen (with ?run=<run_id>)
  /history          → HistoryView
  /strategies       → StrategiesView
  /insights         → InsightsView
  /settings         → SettingsView
```

### 6.4 Component Hierarchy

```
App → AuthProvider → BrowserRouter
  ├── /login → LoginPage
  └── ProtectedRoute → MainLayout (TopBar + Outlet)
      ├── / → RecommendationsView
      │       ├── SearchScreen (CommandBar, strategy cards)
      │       └── ResultsScreen
      │           ├── TickerCardList → TickerCard × N
      │           └── DetailView (6-tab panel)
      │               ├── OverviewTab (Perplexity fundamentals + PriceLevelMap)
      │               ├── ChartTab (chart images + lightbox + ad-hoc fetch)
      │               ├── SentimentTab (Gemini sentiment + catalysts)
      │               ├── SynthesisTab (GPT bull/bear/judge debate)
      │               ├── FeedbackTab (decision + outcome + undo)
      │               └── RawTab (full JSON)
      ├── /history → HistoryView
      ├── /strategies → StrategiesView
      ├── /insights → InsightsView
      │   ├── StatsGrid (win rate, P&L, W/L/BE, avg return)
      │   ├── RecommendationJournal (expandable rows + inline forms)
      │   ├── ReflectionPanel (injection_prompt + summary_text)
      │   └── CalibrationPanel (confidence bucket win rates)
      └── /settings → SettingsView
```

### 6.5 State & Data Flow

```
View
  │  calls
  ▼
Hook (usePipeline / useStrategies / useInsights / useApiKeyStatus)
  │  calls
  ▼
api/client.ts  →  request<T>(path, options)
  │  attaches Supabase JWT Bearer
  ▼
FastAPI backend (Railway)
```

Hooks:

| Hook | Purpose |
|------|---------|
| `usePipeline` | Run pipeline, poll progress, load history |
| `useStrategies` | List strategies and templates |
| `useApiKeyStatus` | Check which API keys are set |
| `useInsights` | Fetch overview, recommendations, latest reflection; record decisions/outcomes; trigger reflection |

Cross-view sync: `lib/feedbackSync.ts` fires a `signalforge:feedback-changed` CustomEvent whenever `FeedbackTab` or `InsightsView` mutates decisions/outcomes, so both views stay current without a page reload.

### 6.6 Type System

`src/frontend/src/types/index.ts` mirrors `src/backend/pipeline/schemas.py`. Every Pydantic model field must have a matching TypeScript interface field. Key interfaces include:

- Pipeline types: `ScreeningResult`, `SentimentAnalysis`, `ChartAnalysis`, `Recommendation`, `PipelineResult`
- Strategy types: `StrategyConfig`, `RiskParams`, `FmpScreenerConfig`
- Feedback loop types: `DecisionCreate/Response`, `OutcomeCreate/Response`, `ReflectionResponse`, `PerformanceOverview`, `RecommendationWithStatus`, `ConfidenceCalibration`

---

## 7. Strategy System

Strategies are the primary configuration unit. They control every pipeline stage:

| Section | Key Config Fields |
|---------|------------------|
| FMP pre-screening | `fmp_screener.enabled`, `is_crypto`, `country`, `exchange`, `sector`, `market_cap_min/max`, `pe_max`, `roe_min` |
| Perplexity | `screening_prompt`, `constraint_style`, `max_tickers` |
| Gemini | `news_recency`, `news_scope` |
| Claude | `chart_indicators[]`, `chart_timeframe`, `additional_timeframes[]`, `short_timeframes[]`, `short_tf_indicators[]`, `ta_focus` |
| GPT | `trading_style`, `risk_params`, `enable_debate` |

Templates are seeded from `templates/strategies.json` by `services/strategy.py → ensure_defaults()` on first startup. Templates use `user_id = "system"` and `is_template = true`.

---

## 8. Self-Learning Loop

The system includes a complete feedback loop that feeds historical trade performance back into the GPT judge:

```
recommendations (DB)
    │
    │  user records
    ▼
decisions (DB)            ← POST /api/decisions/recommendations/{id}/decision
    │
    │  user logs
    ▼
outcomes (DB)             ← POST /api/outcomes/decisions/{id}/outcome
    │
    │  user triggers (requires ≥5 outcomes)
    ▼
reflection generation     ← POST /api/insights/reflect
    │  services/reflection.py
    │  FinMem two-layer memory:
    │    SHORT-TERM (14d): streak, suppression alerts
    │    LONG-TERM (all-time): pattern accuracy, sector win rates,
    │                          TF alignment, confidence calibration
    │  Optional GPT-4o-mini strategic advice
    ▼
reflections table (DB)
    │
    │  on next pipeline run
    ▼
load_reflection_context(user_id)
    │
    └──→ injected as ## HISTORICAL PERFORMANCE CONTEXT into GPT judge prompt
```

---

## 9. API Key Management

API keys are **never** stored in the database. In development they come from `.env`. In production they are Railway environment variables.

| Variable | Service |
|----------|---------|
| `PERPLEXITY_API_KEY` | Perplexity Agent API |
| `ANTHROPIC_API_KEY` | Claude Vision API |
| `GOOGLE_API_KEY` | Gemini with Search grounding |
| `OPENAI_API_KEY` | GPT bull/bear/judge |
| `CHARTIMG_API_KEY` | Chart-Img v2 |
| `FMP_API_KEY` | FMP (optional) |
| `SUPABASE_URL` | Supabase project |
| `SUPABASE_KEY` | service_role key (bypasses RLS) |
| `SUPABASE_JWT_SECRET` | Legacy — JWKS is preferred |
| `ALLOWED_ORIGINS` | CORS origins (frontend domain) |

---

## 10. Prompt Versioning

Every LLM prompt has a version constant and an 8-char SHA-256 hash:

```python
JUDGE_PROMPT_VERSION = "v7"   # bump when prompt changes

def get_judge_hash() -> str:
    return prompt_hash(JUDGE_SYSTEM_PROMPT)  # 8-char SHA-256 hex
```

The orchestrator stores all stage hashes in `pipeline_runs.prompt_versions` as JSON:

```json
{
  "regime": "a1b2c3d4",
  "perplexity": "e5f6a7b8",
  "gemini": "c9d0e1f2",
  "claude": "a3b4c5d6",
  "gpt_bull": "e7f8a9b0",
  "gpt_bear": "c1d2e3f4",
  "gpt_judge": "a5b6c7d8"
}
```

Correlating hashes with `recommendations.run_id` → `decisions` → `outcomes` allows prompt A/B analysis (not yet surfaced in the Insights UI).

---

## 11. Project Structure

```
signalForge/
├── CLAUDE.md                    # ← authoritative project handbook
├── README.md                    # Getting started + quick reference
├── Dockerfile                   # Railway backend container
│
├── src/backend/                 # Python 3.14 FastAPI
│   ├── main.py                  # App factory, lifespan, CORS, rate limiting
│   ├── config.py                # Settings from env vars
│   ├── api/                     # Route handlers (8 routers)
│   │   ├── pipeline.py          # /api/pipeline/*
│   │   ├── strategies.py        # /api/strategies/*
│   │   ├── charts.py            # /api/charts/*
│   │   ├── settings.py          # /api/settings/*
│   │   ├── decisions.py         # /api/decisions/*
│   │   ├── outcomes.py          # /api/outcomes/*
│   │   ├── recommendations.py   # /api/recommendations/*
│   │   └── insights.py          # /api/insights/*
│   ├── middleware/
│   │   └── auth.py              # JWT verification, CurrentUser dependency
│   ├── pipeline/
│   │   ├── orchestrator.py      # Execution engine
│   │   ├── schemas.py           # All Pydantic models
│   │   ├── validation.py        # JSON extraction + retry logic
│   │   ├── stages/              # One file per stage
│   │   │   ├── perplexity.py    # Stage 1
│   │   │   ├── gemini.py        # Stage 2
│   │   │   ├── claude.py        # Stage 3
│   │   │   ├── gpt.py           # Stage 4
│   │   │   ├── regime.py        # Market regime classifier
│   │   │   └── risk_validator.py # Risk parameter validation
│   │   ├── prompts/             # Versioned prompt templates
│   │   │   ├── perplexity_discovery.py
│   │   │   ├── perplexity_analysis.py
│   │   │   ├── gemini_sentiment.py
│   │   │   ├── claude_chart.py
│   │   │   ├── gpt_debate.py
│   │   │   └── regime_classifier.py
│   │   └── tools/               # Perplexity function-calling tools
│   │       └── fmp_tool.py      # FMP tool definition for Agent API
│   ├── services/                # Business logic
│   │   ├── strategy.py          # Strategy CRUD + template seeding
│   │   ├── chart_image.py       # Chart-Img v2 + Supabase Storage
│   │   ├── fmp_service.py       # FMP pre-screening (Stage 0)
│   │   ├── keyring_service.py   # API key loading
│   │   └── reflection.py        # Self-learning context
│   ├── database/
│   │   ├── connection.py        # Supabase async client singleton
│   │   └── migrations/          # SQL schema files (001–010+)
│   └── utils/
│       └── hashing.py           # prompt_hash() utility
│
├── src/frontend/src/            # React 19 + TypeScript 5.9
│   ├── views/                   # Top-level pages (routed)
│   │   ├── RecommendationsView.tsx
│   │   ├── HistoryView.tsx
│   │   ├── StrategiesView.tsx
│   │   ├── InsightsView.tsx     # 1024-line trade journal + analytics
│   │   └── SettingsView.tsx
│   ├── components/
│   │   ├── auth/                # LoginPage, ProtectedRoute
│   │   ├── layout/              # MainLayout, TopBar, CommandBar
│   │   ├── recommendations/     # DetailView, 6 tabs, TickerCard*, PriceLevelMap
│   │   └── shared/              # Skeleton, TradingViewWidget, AssetTypeBadge
│   ├── hooks/
│   │   ├── usePipeline.ts
│   │   ├── useStrategies.ts
│   │   ├── useApiKeyStatus.ts
│   │   └── useInsights.ts       # Decisions, outcomes, reflections
│   ├── lib/
│   │   ├── supabase.ts          # Supabase JS client
│   │   └── feedbackSync.ts      # CustomEvent bus (FeedbackTab ↔ InsightsView)
│   ├── api/client.ts            # HTTP client (all 22+ endpoint methods)
│   ├── types/index.ts           # TypeScript interfaces (mirrors Pydantic schemas)
│   └── theme/globals.css        # CSS variables, Urban Finance design system
│
├── templates/strategies.json    # Strategy template seed data
└── .github/workflows/ci.yml     # CI: ruff + ty (backend), tsc + build (frontend)
```

---

## 12. Deployment

### Railway (Backend)

- Dockerfile at repo root builds the Python backend
- Environment variables set in Railway dashboard
- Auto-deploys on push to `main`

### Vercel (Frontend)

- Static build of `src/frontend` via `bun run build`
- SPA rewrite: all paths serve `index.html`
- Environment variables (`VITE_*`) set in Vercel dashboard
- Auto-deploys on push to `main`

### Supabase

- PostgreSQL database — run migrations manually via SQL editor
- Auth — email/password enabled, PKCE disabled
- Storage — `charts` bucket (public read, service_role write)

### CI/CD

GitHub Actions (`.github/workflows/ci.yml`) runs on push to `main` and PRs to `main`:

**Backend job:** `ruff check` → `ruff format --check` → `ty check`

**Frontend job:** `bunx tsc --noEmit` → `bun run build`

---

## 13. Known Gaps

| Gap | Notes |
|-----|-------|
| `run_count` not incremented | Column exists on `strategies`; nothing increments it |
| No strategy update/delete endpoints | Only list, get, create |
| No per-strategy performance analytics | Reflections are user-wide, not per-strategy |
| No prompt A/B analytics UI | Hash infrastructure exists; not surfaced in Insights |
| No reflection history list | Only `GET /insights/reflections/latest` |
| `chart_images` table vestigial | Chart paths stored in `stage_outputs` instead |
| No test infrastructure | Zero test files in the project |
| `TradingViewWidget` unused | Built but not rendered in any view |
