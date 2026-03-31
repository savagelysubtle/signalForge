# Frontend Overview

> **Stack:** React 19 · TypeScript (strict) · Tailwind CSS v4 · Vite 8 · bun
> **Source:** [`src/frontend/`](../../src/frontend/)

The frontend is a dark-themed single-page application that displays pipeline
results, manages strategies, and embeds TradingView widgets. It never calls
LLM APIs directly — all data flows through the Python backend via REST.

---

## Project Structure

```
src/frontend/src/
├── main.tsx                      # Entry point (StrictMode, globals.css)
├── App.tsx                       # Router + AuthProvider
├── api/
│   └── client.ts                 # HTTP client (fetch + Supabase JWT)
├── assets/                       # SVG logos and brand assets
├── components/
│   ├── auth/
│   │   ├── LoginPage.tsx         # Supabase email/password login
│   │   └── ProtectedRoute.tsx    # Redirect to /login if unauthenticated
│   ├── layout/
│   │   ├── MainLayout.tsx        # Shell: TopBar + outlet
│   │   ├── TopBar.tsx            # Horizontal nav (logo, centered nav pill, user/logout)
│   │   ├── Sidebar.tsx           # Navigation sidebar (legacy — TopBar replaced it)
│   │   └── CommandBar.tsx        # Pipeline trigger + mode classification
│   ├── recommendations/
│   │   ├── TickerCardList.tsx     # Grid of ticker cards
│   │   ├── TickerCard.tsx         # Individual ticker summary card
│   │   ├── DetailView.tsx        # Expanded detail panel (6 tabs)
│   │   ├── OverviewTab.tsx       # Fundamentals + recommendation
│   │   ├── SentimentTab.tsx      # Gemini sentiment analysis
│   │   ├── ChartTab.tsx          # Chart images + lightbox + ad-hoc fetch
│   │   ├── SynthesisTab.tsx      # GPT bull/bear/judge debate
│   │   ├── FeedbackTab.tsx       # Follow/pass decisions + outcome logging
│   │   ├── RawTab.tsx            # Raw JSON data
│   │   └── PriceLevelMap.tsx     # Visual support/resistance map
│   └── shared/
│       ├── TradingViewWidget.tsx  # Embedded TradingView iframe (built, not rendered)
│       ├── AssetTypeBadge.tsx     # Stock/ETF/Crypto badge
│       └── Skeleton.tsx          # Loading skeleton component
├── context/
│   └── AuthContext.tsx            # Supabase auth state provider
├── hooks/
│   ├── usePipeline.ts             # Pipeline trigger + polling
│   ├── useStrategies.ts           # Strategy list fetching
│   ├── useApiKeyStatus.ts         # API key status check
│   └── useInsights.ts             # Decisions, outcomes, reflections
├── lib/
│   ├── supabase.ts                # Supabase client instance
│   └── feedbackSync.ts            # CustomEvent bus (FeedbackTab ↔ InsightsView)
├── theme/
│   └── globals.css                # Tailwind v4 CSS variables, dark theme
├── types/
│   └── index.ts                   # TypeScript interfaces (mirrors Python schemas)
└── views/
    ├── RecommendationsView.tsx    # Main dashboard (default route)
    ├── HistoryView.tsx            # Past pipeline runs
    ├── StrategiesView.tsx         # Strategy manager
    ├── InsightsView.tsx           # Performance insights
    └── SettingsView.tsx           # API key status + config
```

---

## Routing

Routes are defined in `App.tsx` using `react-router-dom`:

```
/login          → LoginPage (public)
/               → ProtectedRoute → MainLayout
  /             → RecommendationsView (index)
  /history      → HistoryView
  /strategies   → StrategiesView
  /insights     → InsightsView
  /settings     → SettingsView
```

`ProtectedRoute` checks `useAuth()` — if not authenticated, redirects to
`/login`. `MainLayout` renders the `Sidebar`, `CommandBar`, and an
`<Outlet />` for child views.

---

## Data Flow

```
View
  │  calls
  ▼
Hook (usePipeline, useStrategies, etc.)
  │  calls
  ▼
api/client.ts  →  request<T>(path, options)
  │                  │
  │  attaches        │  fetch()
  │  Bearer JWT      │
  ▼                  ▼
Supabase Auth    Backend API (localhost:8420)
(session/token)
```

1. **Views** call **hooks** for data fetching and mutations.
2. **Hooks** call functions on the `api` object in `api/client.ts`.
3. **`request<T>()`** attaches the Supabase JWT from the current session
   and calls the backend.
4. Responses are typed with generics matching the TypeScript interfaces
   in `types/index.ts`.

---

## Authentication

- **Provider:** Supabase Auth (email/password)
- **Client:** `@supabase/supabase-js` initialized in `lib/supabase.ts`
- **State:** `AuthContext` provides `user`, `session`, `signIn()`,
  `signUp()`, `signOut()` via React context
- **Token flow:** `supabase.auth.getSession()` → extract `access_token` →
  send as `Authorization: Bearer <token>` on every API call

---

## API Client

**File:** `api/client.ts`

A thin wrapper around `fetch` that auto-attaches auth headers:

| Function | Method | Endpoint |
|----------|--------|----------|
| `api.health()` | GET | `/health` |
| `api.runPipeline(body)` | POST | `/api/pipeline/run` |
| `api.getPipelineResult(runId)` | GET | `/api/pipeline/status/{runId}` |
| `api.getPipelineProgress(runId)` | GET | `/api/pipeline/runs/{runId}` |
| `api.listPipelineRuns()` | GET | `/api/pipeline/runs` |
| `api.listStrategies()` | GET | `/api/strategies` |
| `api.listTemplates()` | GET | `/api/strategies/templates` |
| `api.fetchChart(body)` | POST | `/api/charts/fetch` |
| `api.getApiKeyStatus()` | GET | `/api/settings/api-keys/status` |
| `api.createDecision(recId, body)` | POST | `/api/decisions/recommendations/{id}/decision` |
| `api.listDecisions(...)` | GET | `/api/decisions` |
| `api.getDecision(id)` | GET | `/api/decisions/{id}` |
| `api.deleteDecision(id)` | DELETE | `/api/decisions/{id}` |
| `api.createOutcome(decId, body)` | POST | `/api/outcomes/decisions/{id}/outcome` |
| `api.updateOutcome(id, body)` | PUT | `/api/outcomes/{id}` |
| `api.listOutcomes(...)` | GET | `/api/outcomes` |
| `api.listRecommendations(...)` | GET | `/api/recommendations` |
| `api.getRecommendationStatus(id)` | GET | `/api/recommendations/{id}` |
| `api.getPerformanceOverview()` | GET | `/api/insights/overview` |
| `api.triggerReflection()` | POST | `/api/insights/reflect` |
| `api.getLatestReflection()` | GET | `/api/insights/reflections/latest` |

The base URL comes from `VITE_API_URL` (defaults to
`http://localhost:8420`).

---

## Type System

**File:** `types/index.ts`

All TypeScript interfaces mirror the Python Pydantic models in
`pipeline/schemas.py`. When a field is added to a Pydantic model, the
corresponding TypeScript interface must be updated to match.

Key types:

| TypeScript Interface | Python Model | Used For |
|---------------------|-------------|----------|
| `FundamentalData` | `FundamentalData` | Perplexity output |
| `ScreeningResult` | `ScreeningResult` | Stage 1 result |
| `SentimentAnalysis` | `SentimentAnalysis` | Gemini output |
| `ChartAnalysis` | `ChartAnalysis` | Claude output |
| `Recommendation` | `Recommendation` | GPT judge output |
| `PipelineResult` | `PipelineResult` | Full pipeline run |
| `StrategyConfig` | `StrategyConfig` | Strategy definition |
| `RiskParams` | `RiskParams` | Risk configuration |
| `DecisionCreate` | `DecisionCreate` | Follow/pass decision input |
| `DecisionResponse` | `DecisionResponse` | Decision with recommendation data |
| `OutcomeCreate` | `OutcomeCreate` | Trade outcome input |
| `OutcomeResponse` | `OutcomeResponse` | Stored outcome |
| `ReflectionResponse` | `ReflectionResponse` | Reflection with injection prompt |
| `PerformanceOverview` | `PerformanceOverview` | Aggregated stats |
| `RecommendationWithStatus` | `RecommendationWithStatus` | Rec + decision + outcome |
| `ConfidenceCalibration` | `ConfidenceCalibration` | Win rate by confidence bucket |

---

## Theming

- **Dark theme only** — no light mode toggle
- **CSS variables** defined in `theme/globals.css`
- **Tailwind v4** with custom theme tokens
- Components use Tailwind utility classes referencing CSS variables

---

## TradingView Widgets

`TradingViewWidget.tsx` is **built but not currently rendered** in any view (reserved for future live chart integration). When rendered, it embeds the free public TradingView widget via iframe with dark theme and no API key required.

---

## Running Locally

```bash
cd src/frontend
bun run dev
```

The dev server runs at `http://localhost:5173` and proxies API calls to
`http://localhost:8420`.

### `useInsights`

Orchestrates the full self-learning feedback loop UI.

- `overview` — `PerformanceOverview` from `/api/insights/overview`
- `recommendations` — `RecommendationWithStatus[]` from `/api/recommendations`
- `reflection` — latest `ReflectionResponse` from `/api/insights/reflections/latest`
- `isGenerating` — boolean while reflection is being generated
- `recordDecision(recId, body)` — POST + notify feedbackSync + refetch
- `logOutcome(decisionId, body)` — POST + notify + refetch
- `undoDecision(decisionId)` — DELETE + notify + refetch
- `generateReflection()` — POST to `/api/insights/reflect`

Listens to `useFeedbackSync` so it auto-refreshes when `FeedbackTab` mutates data.

---

- [Components](components.md) — component hierarchy and patterns
- [API Reference](../backend/api-reference.md) — backend endpoints
- [Backend Overview](../backend/README.md) — the other half
