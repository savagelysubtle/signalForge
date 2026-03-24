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
│               ├── Sidebar
│               ├── CommandBar
│               └── <Outlet>
│                   ├── RecommendationsView    ← /
│                   │   ├── TickerCardList
│                   │   │   └── TickerCard (×N)
│                   │   │       └── AssetTypeBadge
│                   │   └── DetailView (selected ticker)
│                   │       ├── OverviewTab
│                   │       │   └── PriceLevelMap
│                   │       ├── SentimentTab
│                   │       ├── ChartTab
│                   │       │   └── TradingViewWidget
│                   │       ├── SynthesisTab
│                   │       └── RawTab
│                   ├── HistoryView            ← /history
│                   ├── StrategiesView         ← /strategies
│                   ├── InsightsView           ← /insights
│                   └── SettingsView           ← /settings
```

---

## Layout Components

### `MainLayout`

The app shell. Renders a fixed `Sidebar`, a top `CommandBar`, and an
`<Outlet />` for the active view.

### `Sidebar`

Navigation links to each view. Highlights the active route.

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
- Action badge (BUY / SELL / HOLD)
- Confidence score
- Key metrics (entry, stop loss, take profit)

Clicking a card opens the `DetailView`.

### `DetailView`

An expanded panel showing all pipeline data for a selected ticker.
Uses a tabbed interface:

| Tab | Component | Data Source |
|-----|-----------|-------------|
| Overview | `OverviewTab` | Perplexity fundamentals + GPT recommendation |
| Sentiment | `SentimentTab` | Gemini sentiment analysis |
| Chart | `ChartTab` | Claude chart analysis + TradingView widget |
| Synthesis | `SynthesisTab` | GPT bull/bear/judge debate |
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
| `InsightsView` | `/insights` | Performance analytics from the reflection engine |
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

### `useApiKeyStatus`

Checks which API keys are configured on the backend.

- `status` — `Record<string, boolean>` key presence map
- `isLoading` — boolean loading state
