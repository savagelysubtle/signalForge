---
name: frontend-component
description: >
  Create React components and views in SignalForge's frontend. Use when adding new
  components to src/frontend/src/components/, creating new views, building new tabs
  for the detail panel, or working with the dark theme system. Covers component
  hierarchy, hook patterns, Tailwind v4 dark theme, and routing.
---

# Frontend Component

## Directory Structure

```
src/frontend/src/
├── components/
│   ├── auth/          # LoginPage, ProtectedRoute
│   ├── layout/        # MainLayout, Sidebar, CommandBar
│   ├── recommendations/  # DetailView, tabs, cards
│   └── shared/        # Reusable: AssetTypeBadge, TradingViewWidget
├── views/             # Top-level pages (routed)
├── hooks/             # Data fetching hooks
├── api/               # Backend client
├── context/           # AuthContext
├── types/             # TypeScript interfaces
└── theme/             # globals.css (CSS variables)
```

## Component Hierarchy

```
App → AuthProvider → BrowserRouter
  ├── /login → LoginPage
  └── ProtectedRoute → MainLayout (Sidebar + CommandBar + Outlet)
      ├── / → RecommendationsView (TickerCardList + DetailView)
      │       └── DetailView tabs: Overview, Chart, Sentiment, Synthesis, Raw
      ├── /history → HistoryView
      ├── /strategies → StrategiesView
      ├── /insights → InsightsView (placeholder)
      └── /settings → SettingsView
```

## Adding a New View

1. Create `src/frontend/src/views/MyView.tsx`
2. Add route in `App.tsx` inside the `<Route element={<MainLayout />}>` group
3. Add nav icon in `Sidebar.tsx` using lucide-react

## Adding a Detail Tab

1. Create `src/frontend/src/components/recommendations/MyTab.tsx`
2. Add tab button and panel in `DetailView.tsx`
3. Receive data via props from `DetailView` (which gets it from `RecommendationsView`)

## Dark Theme System

CSS variables defined in `src/frontend/src/theme/globals.css`:

| Variable                  | Value     | Use For                    |
|---------------------------|-----------|----------------------------|
| `--color-bg-primary`      | `#0d1117` | Page background            |
| `--color-bg-secondary`    | `#161b22` | Cards, panels              |
| `--color-bg-tertiary`     | `#21262d` | Hover states, borders      |
| `--color-border`          | `#30363d` | All borders                |
| `--color-text-primary`    | `#e6edf3` | Headings, primary text     |
| `--color-text-secondary`  | `#8b949e` | Labels, secondary text     |
| `--color-accent-green`    | `#3fb950` | Bullish, BUY, positive     |
| `--color-accent-red`      | `#f85149` | Bearish, SELL, negative    |
| `--color-accent-yellow`   | `#d29922` | Neutral, HOLD, warnings    |
| `--color-accent-blue`     | `#58a6ff` | Actions, links, active     |

Use as Tailwind classes: `bg-bg-primary`, `text-text-secondary`, `border-border`, etc.

## Patterns

- **Conditional classes:** Use `clsx` (imported, available everywhere)
- **Icons:** Use `lucide-react` — import individual icons
- **No shadcn/ui** — components are hand-built with Tailwind
- **No global state** beyond `AuthContext` — use hooks and props
- **Data flows down** via props from views to components

## Hook Pattern for Data Fetching

```typescript
export function useMyData() {
  const [data, setData] = useState<MyType | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await apiClient.myEndpoint();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  return { data, isLoading, error, refresh: fetch };
}
```

## Semantic Color Usage

| Concept      | Color   | Class              |
|--------------|---------|---------------------|
| Bullish/BUY  | Green   | `text-accent-green` |
| Bearish/SELL | Red     | `text-accent-red`   |
| Neutral/HOLD | Yellow  | `text-accent-yellow`|
| Actions/Links| Blue    | `text-accent-blue`  |
| High conf.   | Green   | `text-accent-green` |
| Low conf.    | Red     | `text-accent-red`   |
