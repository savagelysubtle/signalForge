# Frontend Overview

> **Stack:** React 18 · TypeScript (strict) · Tailwind CSS v4 · Vite · bun
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
│   │   ├── MainLayout.tsx        # Shell: sidebar + command bar + outlet
│   │   ├── Sidebar.tsx           # Navigation sidebar
│   │   └── CommandBar.tsx        # Top bar with pipeline controls
│   ├── recommendations/
│   │   ├── TickerCardList.tsx     # Grid of ticker cards
│   │   ├── TickerCard.tsx         # Individual ticker summary card
│   │   ├── DetailView.tsx        # Expanded detail panel (tabbed)
│   │   ├── OverviewTab.tsx       # Fundamentals + recommendation
│   │   ├── SentimentTab.tsx      # Gemini sentiment analysis
│   │   ├── ChartTab.tsx          # Chart images + TradingView widget
│   │   ├── SynthesisTab.tsx      # GPT bull/bear/judge debate
│   │   ├── RawTab.tsx            # Raw JSON data
│   │   └── PriceLevelMap.tsx     # Visual support/resistance map
│   └── shared/
│       ├── TradingViewWidget.tsx  # Embedded TradingView iframe
│       └── AssetTypeBadge.tsx     # Stock/ETF/Crypto badge
├── context/
│   └── AuthContext.tsx            # Supabase auth state provider
├── hooks/
│   ├── usePipeline.ts             # Pipeline trigger + polling
│   ├── useStrategies.ts           # Strategy list fetching
│   └── useApiKeyStatus.ts         # API key status check
├── lib/
│   └── supabase.ts                # Supabase client instance
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
| `api.listPipelineRuns()` | GET | `/api/pipeline/runs` |
| `api.listStrategies()` | GET | `/api/strategies` |
| `api.listTemplates()` | GET | `/api/strategies/templates` |
| `api.fetchChart(body)` | POST | `/api/charts/fetch` |
| `api.getApiKeyStatus()` | GET | `/api/settings/api-keys/status` |

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

---

## Theming

- **Dark theme only** — no light mode toggle
- **CSS variables** defined in `theme/globals.css`
- **Tailwind v4** with custom theme tokens
- Components use Tailwind utility classes referencing CSS variables

---

## TradingView Widgets

`TradingViewWidget.tsx` embeds the free public TradingView widget via
iframe. Key behaviors:

- Widget is **recreated** (not updated) when the ticker changes — the
  iframe is destroyed and a new one is mounted
- Dark theme with transparent background
- No API key required (public embeddable widgets)

---

## Running Locally

```bash
cd src/frontend
bun run dev
```

The dev server runs at `http://localhost:5173` and proxies API calls to
`http://localhost:8420`.

---

## Related Docs

- [Components](components.md) — component hierarchy and patterns
- [API Reference](../backend/api-reference.md) — backend endpoints
- [Backend Overview](../backend/README.md) — the other half
