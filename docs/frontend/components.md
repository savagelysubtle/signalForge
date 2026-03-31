# Component Hierarchy

> **Source:** [`src/frontend/src/components/`](../../src/frontend/src/components/)

All components are React functional components with hooks (no class
components). TypeScript strict mode. Dark theme with Tailwind CSS.

---

## Component Tree

```
App
├── AuthProvider (context)
│   └── BrowserRouter
│       ├── LoginPage                    ← /login
│       └── ProtectedRoute
│           └── MainLayout              ← / (all protected routes)
│               ├── TopBar (nav pill)
│               └── <Outlet>
│                   ├── RecommendationsView    ← /
│                   │   ├── SearchScreen (no ?run param)
│                   │   └── ResultsScreen (?run=<id>)
│                   │       ├── TickerCardList
│                   │       │   └── TickerCard (×N)
│                   │       │       └── AssetTypeBadge
│                   │       └── DetailView (selected ticker)
│                   │           ├── OverviewTab
│                   │           │   └── PriceLevelMap
│                   │           ├── ChartTab
│                   │           │   └── TradingViewWidget (built, not rendered)
│                   │           ├── SentimentTab
│                   │           ├── SynthesisTab
│                   │           ├── FeedbackTab
│                   │           └── RawTab
│                   ├── HistoryView            ← /history
│                   ├── StrategiesView         ← /strategies
│                   ├── InsightsView           ← /insights
│                   └── SettingsView           ← /settings
```

---

## Layout Components

### `MainLayout`

The app shell. Renders a fixed `TopBar` (horizontal top nav) and an `<Outlet />` for the active view. The legacy `Sidebar` component exists but is not rendered — `TopBar` replaced it.

### `TopBar`

Horizontal navigation bar with logo left, centered nav pill (Dashboard / History / Strategies / Insights / Settings), and user/logout right. Semi-transparent background (`bg-bg-asphalt/80 backdrop-blur-md`). On results screen (`?run=` param), nav is hidden and a "Back to Search" button appears.

### `Sidebar`

Legacy navigation sidebar. Exists in code but **not rendered** — replaced by `TopBar`.

### `CommandBar`

Top bar containing:
- Strategy selector dropdown
- Pipeline trigger button ("Run Analysis")
- Manual ticker input
- Free-form prompt input
- Pipeline status indicator

---

## Recommendation Components

These compose the main dashboard at `/` (`RecommendationsView`).

### `TickerCardList`

A responsive grid of `TickerCard` components, one per ticker in the
latest pipeline result. Handles the empty state when no pipeline has run.

### `TickerCard`

Summary card for a single ticker showing:
- Ticker symbol and company name
- `AssetTypeBadge` (stock / ETF / crypto)
- Action badge (BUY / SHORT / HOLD)
- Confidence score
- Key metrics (entry, stop loss, take profit)

Clicking a card opens the `DetailView`.

### `DetailView`

An expanded panel showing all pipeline data for a selected ticker.
Uses a tabbed interface with **6 tabs**:

| Tab | Component | Data Source |
|-----|-----------|-------------|
| Overview | `OverviewTab` | Perplexity fundamentals + GPT recommendation |
| Chart | `ChartTab` | Claude chart analysis + annotated charts (lightbox, ad-hoc fetch) |
| Sentiment | `SentimentTab` | Gemini sentiment analysis |
| Synthesis | `SynthesisTab` | GPT bull/bear/judge debate |
| Feedback | `FeedbackTab` | Follow/pass decisions, outcome logging, undo |
| Raw | `RawTab` | Raw JSON for debugging |

### `OverviewTab`

Displays:
- Fundamentals (market cap, P/E, revenue growth, FCF)
- Key highlights and risk factors
- Recommendation summary (action, confidence, entry/stop/target)
- `PriceLevelMap` visualization

### `PriceLevelMap`

A visual representation of support/resistance levels, entry price,
stop loss, and take profit on a vertical price axis. Color-coded by
level type.

### `SentimentTab`

Displays Gemini sentiment analysis:
- Sentiment score (-1.0 to +1.0) with color bar
- Sentiment label (strongly bearish → strongly bullish)
- Key catalysts with impact and significance badges
- Sector sentiment summary

### `FeedbackTab`

The 6th detail panel tab. Provides the per-recommendation feedback workflow:

- **Decision section** — "Follow Trade" (instant save) or "Pass" (reason category + notes)
- **Outcome section** — 6 numeric fields (entry/exit/shares/P&L$/P&L%/hold days) with auto-P&L calculation when entry + exit + shares are all filled; exit reason dropdown
- **Undo** — delete a decision (cascade-deletes the linked outcome)
- **Edit** — re-open the outcome form for a closed trade

Fires `notifyFeedbackChanged()` on every mutation so `InsightsView` re-fetches automatically.

### `ChartTab`

Displays:
- Chart images from Claude's analysis (multiple timeframes)
- Annotated chart images with key-level overlays
- Embedded `TradingViewWidget` for live charting
- Chart timeframe selector for on-demand fetching

### `SynthesisTab`

Displays the GPT debate:
- Bull case arguments
- Bear case arguments
- Judge reasoning and final verdict
- Key factors and warnings

### `RawTab`

Displays the raw JSON data for any pipeline stage. Useful for debugging
and verifying what the LLMs actually returned.

---

## Shared Components

### `TradingViewWidget`

Embeds the free public TradingView advanced chart widget via iframe.

Props:
- `symbol` — TradingView symbol (e.g., `"TSX:ENB"`)
- `interval` — chart interval

The widget is **destroyed and recreated** on symbol change (TradingView
embeds don't support dynamic symbol updates).

### `AssetTypeBadge`

A small badge showing `Stock`, `ETF`, or `Crypto` with appropriate
color styling. Used on ticker cards.

---

## Auth Components

### `LoginPage`

Email/password login form using Supabase Auth. Handles sign-in and
sign-up flows.

### `ProtectedRoute`

Wraps child routes. Checks `useAuth()` for an active session. If not
authenticated, redirects to `/login`.

---

## Views

Views are top-level page components rendered by the router. They
compose smaller components and call hooks for data.

| View | Route | Purpose |
|------|-------|---------|
| `RecommendationsView` | `/` | Main dashboard with ticker cards and detail panel |
| `HistoryView` | `/history` | List of past pipeline runs with drill-down |
| `StrategiesView` | `/strategies` | Strategy list, template browser, editor |
| `InsightsView` | `/insights` | Trade journal, performance overview, reflection panel, confidence calibration |
| `SettingsView` | `/settings` | API key status and application configuration |

---

## Hooks

Custom hooks encapsulate data fetching and state management.

### `usePipeline`

Triggers pipeline runs and polls for results.

- `triggerRun(params)` — POST to `/api/pipeline/run`
- `result` — the latest `PipelineResult`
- `isRunning` — boolean loading state
- Polls `/api/pipeline/status/{runId}` until completion

### `useStrategies`

Fetches strategy lists.

- `strategies` — user's saved strategies
- `templates` — built-in templates
- `isLoading` — boolean loading state

### `useInsights`

Orchestrates the self-learning feedback loop — fetches performance data, triggers reflections, and records decisions/outcomes.

- `overview` — `PerformanceOverview` (win rate, P&L, calibration buckets)
- `recommendations` — `RecommendationWithStatus[]` (recs enriched with decision + outcome)
- `reflection` — latest `ReflectionResponse`
- `isGenerating` — boolean while reflection is being generated
- `recordDecision(recId, body)` — POST + notify feedbackSync + refetch
- `logOutcome(decisionId, body)` — POST + notify + refetch
- `undoDecision(decisionId)` — DELETE + notify + refetch
- `generateReflection()` — POST to `/api/insights/reflect` (requires ≥5 outcomes)

Listens to `useFeedbackSync` so it auto-refreshes when `FeedbackTab` mutates data.
