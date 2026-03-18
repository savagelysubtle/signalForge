# SignalForge — Frontend Agent Brief

> **Purpose:** Everything a frontend AI agent needs to build the React/TypeScript dashboard for SignalForge Phase 1.
> **Backend status:** Fully built, tested, running on `http://localhost:8420`.
> **Date:** March 13, 2026

---

## 1. What You're Building

A React + TypeScript + Tailwind dashboard for SignalForge — a desktop stock/crypto analysis platform. Phase 1 focuses on the **Perplexity screening stage only**. The backend is complete. Your job is the frontend.

The app will eventually run inside a Tauri desktop shell, but for now build it as a standalone Vite + React app that talks to the FastAPI backend over localhost.

---

## 2. Tech Stack (Non-Negotiable)

| Layer | Technology |
|-------|-----------|
| Framework | React 18+ with functional components + hooks (no class components) |
| Language | TypeScript (strict mode) |
| Build tool | Vite |
| Styling | Tailwind CSS (dark theme only) |
| UI components | shadcn/ui (Radix primitives) |
| Package manager | `bun` (not npm) |
| HTTP client | `fetch` via a thin `api/client.ts` wrapper — no axios |
| State | React hooks + context (no Redux — app is simple enough) |
| Routing | React Router v6 (sidebar nav between views) |
| Charts/Viz | Recharts or lightweight alternative for future insights charts |

**Install location:** `src/frontend/` (sibling to `src/backend/`).

---

## 3. Backend API Reference

Base URL: `http://localhost:8420`

All endpoints return JSON. CORS is enabled for all origins.

### 3.1 Health

```
GET /health
→ { "status": "ok", "version": "0.1.0" }
```

### 3.2 Pipeline Endpoints (prefix: `/api/pipeline`)

**Trigger a run:**
```
POST /api/pipeline/run
Body: {
  "strategy_id": "uuid-string" | null,    // optional — picks a saved strategy
  "manual_tickers": ["AAPL", "NVDA"]      // optional — direct ticker list
}
// At least one of strategy_id or manual_tickers must be provided.
// Both = "combined" mode (merges discovery + manual tickers).

→ { "run_id": "hex-uuid", "status": "completed" }
// Note: this call blocks until the pipeline finishes (~5-15 seconds).
// Show a loading/spinner state in the UI while waiting.
```

**Get full result:**
```
GET /api/pipeline/status/{run_id}
→ PipelineResult (see TypeScript interfaces below)
```

**List past runs:**
```
GET /api/pipeline/runs
→ [{ "id": "...", "strategy_id": "..." | null, "mode": "analysis", "status": "completed", "started_at": "ISO8601", "duration_seconds": 5.6 }, ...]
```

**Get a specific past run:**
```
GET /api/pipeline/runs/{run_id}
→ PipelineResult
```

### 3.3 Strategy Endpoints (prefix: `/api/strategies`)

**List user strategies (excluding templates):**
```
GET /api/strategies
→ StrategyConfig[]
```

**List built-in templates:**
```
GET /api/strategies/templates
→ StrategyConfig[]   // these have is_template: true
```

**Get single strategy:**
```
GET /api/strategies/{strategy_id}
→ StrategyConfig
```

**Create strategy:**
```
POST /api/strategies
Body: StrategyConfig (full object)
→ StrategyConfig (201 Created)
```

### 3.4 Settings Endpoints (prefix: `/api/settings`)

**Check which API keys are set:**
```
GET /api/settings/api-keys/status
→ { "keys": { "perplexity": true, "anthropic": false, "google": false, "openai": false, "chartimg": false } }
// Keys are in .env file. Values are NEVER returned — only boolean status.
```

**Reload .env without restart:**
```
POST /api/settings/api-keys/reload
→ { "status": "ok" }
```

---

## 4. TypeScript Interfaces

These **must** mirror the Python Pydantic models exactly. Place in `src/frontend/src/types/index.ts`.

```typescript
// ---------------------------------------------------------------------------
// Perplexity Stage (the only active stage in Phase 1)
// ---------------------------------------------------------------------------

export interface FundamentalData {
  ticker: string;
  company_name: string;
  asset_type: "stock" | "etf" | "crypto";
  sector: string;
  market_cap: string | null;
  pe_ratio: number | null;
  revenue_growth: string | null;
  free_cash_flow: string | null;
  key_highlights: string[];
  risk_factors: string[];
  sources: string[];
}

export interface ScreeningResult {
  mode: "discovery" | "analysis";
  strategy_name: string | null;
  tickers: FundamentalData[];
  screening_summary: string;
  timestamp: string; // ISO 8601
}

// ---------------------------------------------------------------------------
// Claude Vision Stage (Phase 2 — define now, render later)
// ---------------------------------------------------------------------------

export interface TechnicalLevel {
  price: number;
  level_type: "support" | "resistance";
  strength: "strong" | "moderate" | "weak";
}

export interface IndicatorReading {
  indicator: string;
  value: string;
  signal: "bullish" | "bearish" | "neutral";
  notes: string;
}

export interface ChartAnalysis {
  ticker: string;
  timeframe: string;
  trend_direction: "bullish" | "bearish" | "neutral" | "transitioning";
  trend_strength: "strong" | "moderate" | "weak";
  key_levels: TechnicalLevel[];
  patterns_detected: string[];
  indicator_readings: IndicatorReading[];
  volume_analysis: string;
  overall_bias: "strongly_bullish" | "bullish" | "neutral" | "bearish" | "strongly_bearish";
  confidence: "high" | "medium" | "low";
  summary: string;
  chart_image_path: string;
}

// ---------------------------------------------------------------------------
// Gemini Sentiment Stage (Phase 3 — define now, render later)
// ---------------------------------------------------------------------------

export interface NewsCatalyst {
  headline: string;
  source: string;
  impact: "positive" | "negative" | "neutral";
  significance: "high" | "medium" | "low";
}

export interface SentimentAnalysis {
  ticker: string;
  sentiment_score: number; // -1.0 to 1.0
  sentiment_label: "strongly_bearish" | "bearish" | "neutral" | "bullish" | "strongly_bullish";
  key_catalysts: NewsCatalyst[];
  news_recency: string;
  sector_sentiment: string;
  summary: string;
}

// ---------------------------------------------------------------------------
// GPT Debate Stage (Phase 4 — define now, render later)
// ---------------------------------------------------------------------------

export interface DebateCase {
  ticker: string;
  stance: "bull" | "bear";
  key_arguments: string[];
  strongest_signal: string;
  weakest_counter: string;
  confidence: number; // 0.0 to 1.0
}

export interface Recommendation {
  ticker: string;
  action: "BUY" | "SELL" | "HOLD";
  confidence: number; // 0.0 to 1.0
  entry_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  position_size_pct: number;
  risk_reward_ratio: number | null;
  holding_period: string;
  bull_case: DebateCase | null;
  bear_case: DebateCase | null;
  judge_reasoning: string;
  key_factors: string[];
  warnings: string[];
}

// ---------------------------------------------------------------------------
// Pipeline Result (full run output)
// ---------------------------------------------------------------------------

export interface PipelineResult {
  run_id: string;
  timestamp: string; // ISO 8601
  strategy_name: string | null;
  mode: "discovery" | "analysis" | "combined";
  input_tickers: string[];
  screening: ScreeningResult | null;
  chart_analyses: ChartAnalysis[];       // empty in Phase 1
  sentiment_analyses: SentimentAnalysis[]; // empty in Phase 1
  recommendations: Recommendation[];     // empty in Phase 1
  stage_errors: StageError[];
  total_duration_seconds: number;
  prompt_versions: Record<string, string>;
}

export interface StageError {
  stage: string;
  error: string;
  type: string;
}

// ---------------------------------------------------------------------------
// Pipeline Run Summary (for listing)
// ---------------------------------------------------------------------------

export interface PipelineRunSummary {
  id: string;
  strategy_id: string | null;
  mode: string;
  status: string; // "running" | "completed" | "failed" | "partial"
  started_at: string;
  duration_seconds: number | null;
}

// ---------------------------------------------------------------------------
// Strategy Config
// ---------------------------------------------------------------------------

export interface RiskParams {
  max_position_pct: number;
  min_risk_reward: number;
  max_portfolio_risk_pct: number;
}

export interface StrategyConfig {
  id: string;
  name: string;
  description: string;
  screening_prompt: string;
  constraint_style: "tight" | "loose";
  max_tickers: number;
  chart_indicators: string[];
  chart_timeframe: string;
  ta_focus: string | null;
  news_recency: "today" | "week" | "month";
  news_scope: "company" | "sector" | "macro";
  trading_style: string;
  risk_params: RiskParams;
  enable_debate: boolean;
  is_template: boolean;
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export interface ApiKeyStatus {
  keys: Record<string, boolean>;
}
```

---

## 5. Real API Response Example

This is a real response from `GET /api/pipeline/status/{run_id}` after running AAPL, NVDA, TSLA through Perplexity. Use this to design your components:

```json
{
  "run_id": "3a5aa0cab45e4fd4a0caa6bac61e1aac",
  "timestamp": "2026-03-13T18:29:36.576657Z",
  "strategy_name": null,
  "mode": "analysis",
  "input_tickers": ["AAPL", "NVDA", "TSLA"],
  "screening": {
    "mode": "analysis",
    "strategy_name": null,
    "tickers": [
      {
        "ticker": "AAPL",
        "company_name": "Apple Inc",
        "asset_type": "stock",
        "sector": "Technology",
        "market_cap": null,
        "pe_ratio": null,
        "revenue_growth": null,
        "free_cash_flow": null,
        "key_highlights": [
          "Strong long-term total return growth: $10,000 invested in 2010 grew to $338,579 by 2026",
          "YTD 2026 return -4.32% as of March 2026"
        ],
        "risk_factors": [
          "Recent YTD decline in 2026",
          "Historical volatility with negative returns in some years like 2022 (-26.40%)"
        ],
        "sources": ["totalrealreturns.com"]
      },
      {
        "ticker": "NVDA",
        "company_name": "NVIDIA Corporation",
        "asset_type": "stock",
        "sector": "Technology",
        "market_cap": null,
        "pe_ratio": null,
        "revenue_growth": null,
        "free_cash_flow": "$ undisclosed (FCF margin 44.8%)",
        "key_highlights": [
          "Exceptional long-term growth: $10,000 invested in 2010 grew to $7.6M by 2026",
          "High profitability: Gross margin 71.3%, operating margin 60.6%, ROE 107.6%",
          "Strong historical returns: +239% in 2023, +171% in 2024"
        ],
        "risk_factors": [
          "YTD 2026 return -2.06%",
          "High valuation: Overvaluation 12% vs intrinsic value $160.77",
          "Past drawdowns like -50% in 2022"
        ],
        "sources": ["alphaspread.com", "totalrealreturns.com"]
      },
      {
        "ticker": "TSLA",
        "company_name": "Tesla Inc",
        "asset_type": "stock",
        "sector": "Automotive",
        "market_cap": null,
        "pe_ratio": null,
        "revenue_growth": null,
        "free_cash_flow": "$ undisclosed (FCF margin 6.6%)",
        "key_highlights": [
          "Solid long-term growth: $10,000 invested in 2010 grew to $2.5M by 2026",
          "Recent outperformance vs NVDA over 12 months (+64% vs +58%)",
          "Strong historical returns: +101% in 2023, +62% in 2024"
        ],
        "risk_factors": [
          "YTD 2026 return -11.35%",
          "High overvaluation 88% vs intrinsic value $47.17",
          "Lower margins: Gross 18%, net 4%, ROE 4.9%",
          "Significant past decline -65% in 2022"
        ],
        "sources": ["alphaspread.com", "totalrealreturns.com"]
      }
    ],
    "screening_summary": "AAPL, NVDA, and TSLA show exceptional long-term total returns since 2010, led by NVDA, but all face YTD declines in 2026. NVDA excels in profitability margins and ROE, while TSLA lags in margins but has recent relative outperformance. Limited current fundamental metrics available; high valuations noted for NVDA and TSLA.",
    "timestamp": "2026-03-13T11:29:42.173449"
  },
  "chart_analyses": [],
  "sentiment_analyses": [],
  "recommendations": [],
  "stage_errors": [],
  "total_duration_seconds": 5.6,
  "prompt_versions": { "perplexity": "ad0f6cb0" }
}
```

---

## 6. Phase 1 Views to Build

### 6.1 Layout Shell

```
┌──────────────────────────────────────────────────────────────┐
│ ┌────┐ ┌──────────── Command Bar ──────────────────────────┐ │
│ │ S  │ │ [Strategy ▼] [AAPL, TSLA, NVDA    ] [▶ Run]  ◉   │ │
│ │ I  │ └───────────────────────────────────────────────────┘ │
│ │ D  │ ┌─────────────────────────────────────────────────┐   │
│ │ E  │ │                                                 │   │
│ │ B  │ │              Main Content Area                  │   │
│ │ A  │ │         (varies by active view)                 │   │
│ │ R  │ │                                                 │   │
│ └────┘ └─────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

- **Sidebar** — icon-based nav: Recommendations (active), History, Strategies, Insights (placeholder), Settings
- **Command Bar** — always visible at top of main area
- **Main Content** — renders the active view

### 6.2 Command Bar

Components:
1. **Strategy dropdown** — populated from `GET /api/strategies/templates` (and user strategies when they exist). Shows name. Selecting one sets `strategy_id` for the run.
2. **Ticker input** — comma-separated text field (e.g., "AAPL, NVDA, TSLA"). No autocomplete needed.
3. **Run button** — triggers `POST /api/pipeline/run`. Disabled while running.
4. **Status indicator** — idle (gray dot), running (pulsing blue + "Analyzing..."), completed (green check), error (red X with tooltip).

Behavior:
- At least one of strategy or tickers must be filled to enable Run.
- On click: disable button, show pulsing status, `POST /api/pipeline/run`, on response navigate to Recommendations view showing the result.
- The POST blocks for ~5-15 seconds. Show a loading state.

### 6.3 Recommendations View (Primary View)

**Left panel — Ticker cards:** One card per ticker from `screening.tickers[]`. Each card shows:
- Ticker symbol (large, bold)
- Company name (smaller, muted)
- Asset type badge ("stock" / "crypto" / "etf")
- Sector
- Key highlights (first 1-2 items, truncated)
- Number of risk factors as a subtle count

Cards are clickable. Selected card gets a highlighted border.

**Right panel — Detail View:** Shows full data for the selected ticker. Tabbed interface:

- **Overview tab (Phase 1 primary):**
  - Company name, sector, asset type
  - Market cap, P/E, revenue growth, FCF (show "N/A" for nulls)
  - Key highlights list (bulleted, green accent)
  - Risk factors list (bulleted, red accent)
  - Sources list (links if URLs, otherwise plain text)

- **Chart tab (Phase 1 — TradingView widget only):**
  - Embed a live TradingView Advanced Chart widget (public iframe, no API key needed)
  - Set the symbol dynamically based on selected ticker
  - Dark theme, transparent background
  - Recreate the iframe when ticker changes (don't try to update in place)
  - The Claude chart image panel will be empty/placeholder until Phase 2

- **Sentiment tab:** Placeholder with "Coming in Phase 3" message
- **Synthesis tab:** Placeholder with "Coming in Phase 4" message
- **Raw tab:** JSON viewer showing the full `PipelineResult` (great for debugging)

**Bottom of detail panel:**
- Screening summary text (from `screening.screening_summary`)
- Pipeline metadata: mode, duration, timestamp

### 6.4 History View

A table of past pipeline runs from `GET /api/pipeline/runs`:
- Columns: Date, Mode, Status, Tickers (comma-joined from input_tickers), Duration, Strategy
- Click a row to load its full result and switch to Recommendations view
- Status badges: "completed" (green), "partial" (yellow), "failed" (red)

### 6.5 Strategies View

Two sections:
1. **Templates** — grid of cards from `GET /api/strategies/templates`. Each shows name, description, key params (timeframe, max_tickers, constraint_style). Click a template to create a strategy from it (future: opens editor pre-populated from template).
2. **My Strategies** — list from `GET /api/strategies`. Initially empty until user creates from template.

Phase 1 scope: read-only display of templates. Strategy creation can be a stretch goal.

### 6.6 Settings View

- **API Keys section:** For each provider (perplexity, anthropic, google, openai, chartimg), show the name and a green checkmark or red X based on `GET /api/settings/api-keys/status`.
- Explain that keys are configured in the `.env` file at the project root.
- "Reload Keys" button that calls `POST /api/settings/api-keys/reload` (for after editing .env without restarting the server).
- No key input fields — keys stay in .env, never exposed in the UI.

---

## 7. Theme (Dark Only)

Use these CSS variables (GitHub dark inspired):

```css
:root {
  --bg-primary: #0d1117;
  --bg-secondary: #161b22;
  --bg-tertiary: #21262d;
  --border: #30363d;
  --text-primary: #e6edf3;
  --text-secondary: #8b949e;
  --accent-green: #3fb950;
  --accent-red: #f85149;
  --accent-yellow: #d29922;
  --accent-blue: #58a6ff;
}
```

Tailwind should be configured with these as custom colors. All backgrounds should use the dark palette. No light mode.

---

## 8. TradingView Widget Embed

These are free public widgets — no API key needed. Use an iframe approach:

```typescript
// The widget script URL
const WIDGET_SCRIPT = "https://s.tradingview.com/external-embedding/embed-widget-advanced-chart.js";

// Config (passed as innerHTML of a script tag inside a div)
const config = {
  symbol: ticker,        // e.g., "NASDAQ:AAPL" or just "AAPL"
  width: "100%",
  height: "100%",
  colorTheme: "dark",
  isTransparent: true,
  locale: "en",
  interval: "D",
  allow_symbol_change: true,
  studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies"],
};
```

**Critical:** Recreate the entire container div + script when the ticker changes. Do NOT try to update the widget in place — it won't work.

---

## 9. API Client Pattern

Create a thin wrapper in `src/frontend/src/api/client.ts`:

```typescript
const BASE_URL = "http://localhost:8420";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || response.statusText);
  }
  return response.json();
}

export const api = {
  health: () => request<{ status: string; version: string }>("/health"),

  // Pipeline
  runPipeline: (body: { strategy_id?: string; manual_tickers?: string[] }) =>
    request<{ run_id: string; status: string }>("/api/pipeline/run", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getPipelineResult: (runId: string) =>
    request<PipelineResult>(`/api/pipeline/status/${runId}`),
  listPipelineRuns: () =>
    request<PipelineRunSummary[]>("/api/pipeline/runs"),

  // Strategies
  listStrategies: () => request<StrategyConfig[]>("/api/strategies"),
  listTemplates: () => request<StrategyConfig[]>("/api/strategies/templates"),

  // Settings
  getApiKeyStatus: () => request<ApiKeyStatus>("/api/settings/api-keys/status"),
  reloadApiKeys: () =>
    request<{ status: string }>("/api/settings/api-keys/reload", { method: "POST" }),
};
```

---

## 10. Component File Structure

```
src/frontend/
├── index.html
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── vite.config.ts
├── src/
│   ├── main.tsx
│   ├── App.tsx                          // Router + layout shell
│   ├── api/
│   │   └── client.ts                   // HTTP client (see above)
│   ├── types/
│   │   └── index.ts                    // All TypeScript interfaces
│   ├── theme/
│   │   └── globals.css                 // Tailwind + CSS variables
│   ├── hooks/
│   │   ├── usePipeline.ts             // run pipeline, fetch results
│   │   ├── useStrategies.ts           // fetch strategies/templates
│   │   └── useApiKeyStatus.ts         // fetch key status
│   ├── components/
│   │   ├── layout/
│   │   │   ├── Sidebar.tsx            // Icon nav
│   │   │   ├── CommandBar.tsx         // Strategy + tickers + run button
│   │   │   └── MainLayout.tsx         // Shell with sidebar + command bar + content
│   │   ├── recommendations/
│   │   │   ├── TickerCard.tsx         // Compact card for a single ticker
│   │   │   ├── TickerCardList.tsx     // Scrollable list of ticker cards
│   │   │   ├── DetailView.tsx         // Right panel with tabs
│   │   │   ├── OverviewTab.tsx        // Fundamentals display
│   │   │   ├── ChartTab.tsx           // TradingView widget
│   │   │   └── RawTab.tsx             // JSON viewer
│   │   ├── history/
│   │   │   └── HistoryTable.tsx       // Past runs table
│   │   ├── strategies/
│   │   │   ├── TemplateGrid.tsx       // Template cards
│   │   │   └── StrategyList.tsx       // User strategies
│   │   ├── settings/
│   │   │   └── ApiKeyStatus.tsx       // Key status display + reload
│   │   └── shared/
│   │       ├── TradingViewWidget.tsx   // Reusable TV iframe component
│   │       ├── StatusBadge.tsx         // Pipeline status indicator
│   │       ├── AssetTypeBadge.tsx      // stock/etf/crypto badge
│   │       └── LoadingSpinner.tsx
│   └── views/
│       ├── RecommendationsView.tsx     // Cards + Detail layout
│       ├── HistoryView.tsx
│       ├── StrategiesView.tsx
│       ├── InsightsView.tsx            // Placeholder
│       └── SettingsView.tsx
```

---

## 11. Key UX Requirements

1. **The pipeline call blocks for 5-15 seconds.** Show a clear loading state — pulsing indicator, disabled button, "Analyzing AAPL, NVDA, TSLA..." text.

2. **Null fields are common.** Perplexity often returns `null` for `market_cap`, `pe_ratio`, etc. Display "N/A" gracefully — never show "null" or crash on missing data.

3. **The app is dark-theme only.** No light mode toggle, no system preference detection.

4. **Sidebar should be narrow** — icon-only with tooltips, or icon + short label. Think VS Code activity bar.

5. **Cards should feel clickable** — hover states, pointer cursor, selected highlight.

6. **The detail panel should fill available space.** On a 1920px monitor, the card list takes ~300px, the detail panel gets the rest.

7. **TradingView widget must be recreated on ticker change**, not updated. Destroy the old iframe, create a new one.

8. **Empty states matter.** Before any run: "Run an analysis to see results." No strategies yet: "Create a strategy from a template." No history: "No past runs yet."

---

## 12. What NOT to Build Yet

These are future phases. Define the interfaces but don't build UI for:

- Chart image display (Phase 2 — Claude Vision)
- Sentiment display (Phase 3 — Gemini)
- Bull/Bear/Judge synthesis display (Phase 4 — GPT)
- Following/Passing decision buttons (Phase 4)
- Outcome logging (Phase 5)
- Insights/Reflections analytics (Phase 5)
- Strategy editor form (Phase 6 — just show templates read-only for now)

Add placeholder tabs/sections with "Coming in Phase N" messages so the UI structure is ready.

---

## 13. Quick Start for Development

```bash
cd src/frontend
bun create vite . --template react-ts
bun install
bun add tailwindcss @tailwindcss/vite
bun add react-router-dom
# Add shadcn/ui components as needed

# Start dev server
bun run dev

# Backend should already be running:
# cd src/backend && uv run --python 3.14 uvicorn main:app --port 8420
```

Verify backend is up: `curl http://localhost:8420/health`

---

## 14. Summary of Endpoints to Use

| Action | Method | Endpoint | When |
|--------|--------|----------|------|
| Check backend health | GET | `/health` | App startup |
| Run analysis | POST | `/api/pipeline/run` | User clicks Run |
| Get full result | GET | `/api/pipeline/status/{id}` | After run completes |
| List past runs | GET | `/api/pipeline/runs` | History view |
| List templates | GET | `/api/strategies/templates` | Strategy dropdown + Strategies view |
| List user strategies | GET | `/api/strategies` | Strategy dropdown + Strategies view |
| Check API keys | GET | `/api/settings/api-keys/status` | Settings view |
| Reload .env keys | POST | `/api/settings/api-keys/reload` | Settings view |
