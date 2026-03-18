# SignalForge — Product Requirements Document

> **Working Title:** SignalForge
> **Author:** Steve
> **Version:** 0.1.0 (Draft)
> **Last Updated:** March 12, 2026

---

## 1. Product Overview

SignalForge is a desktop intelligence platform that orchestrates multiple AI models to analyze stocks and produce structured trading recommendations. It is **not** a trading platform — it generates actionable analysis that the user reviews and manually executes via TradingView (connected to Questrade).

The core premise: no single AI model excels at everything. Perplexity excels at grounded web research, Gemini at real-time news synthesis, Claude at visual chart pattern recognition, and GPT at quantitative reasoning. SignalForge chains them into a pipeline where each model handles what it does best, passing structured data downstream until a final recommendation emerges.

The system includes a self-learning feedback loop — the user logs which recommendations they followed, tracks outcomes, and the system uses this historical performance data to calibrate future recommendations.

---

## 2. Problem Statement

Retail traders who use multiple AI tools for stock analysis currently do so manually — copy-pasting between ChatGPT, Perplexity, and Claude, re-explaining context at each step, and mentally synthesizing conflicting signals. This workflow is:

- **Time-consuming:** Each analysis requires multiple browser tabs, re-prompting, and manual synthesis
- **Inconsistent:** The quality of analysis varies based on how well the user prompts each model
- **Unstructured:** Outputs are prose paragraphs, not actionable structured data
- **Memoryless:** No historical record of what was recommended, what was followed, and what worked
- **Unlearning:** The system never improves because there's no feedback mechanism

SignalForge automates the multi-model pipeline, enforces structured outputs, persists everything, and feeds historical performance back into the system.

---

## 3. Target User

**Primary:** The builder himself (Steve) — an independent developer and active trader using Questrade + TradingView, comfortable with technical tools, wants AI-augmented analysis without surrendering decision-making authority.

**Design principle:** Build for a sophisticated solo user first. Every architectural decision should prioritize depth of analysis and configurability over multi-user scalability.

---

## 4. Core Workflow

### 4.1 Analysis Trigger (On-Demand)

The user opens SignalForge and initiates an analysis in one of two ways:

**Discovery Mode:** Select a saved strategy from the strategy library. The strategy defines screening criteria, chart indicators, news window, and GPT parameters. Click "Run Analysis." Perplexity screens the market and returns N tickers matching the strategy criteria.

**Manual Mode:** Type comma-separated ticker symbols into the command bar. Optionally select a strategy to define how the downstream analysis stages behave (chart indicators, news window, etc.). Click "Run Analysis." Perplexity performs fundamental research on the specified tickers instead of screening.

**Combined Mode:** Select a strategy AND type additional tickers. The pipeline merges Perplexity's discovered tickers with the manual ones before proceeding to downstream stages.

### 4.2 Pipeline Execution

Once triggered, the pipeline runs through four stages:

1. **Perplexity (Screening/Research):** Returns a list of tickers with fundamental data as structured JSON
2. **Gemini (News Sentiment):** Gathers recent news for each ticker, scores sentiment, and extracts key catalysts. This runs before chart analysis so downstream stages have news context.
3. **Claude Vision (Chart Analysis):** Analyzes chart images for technical patterns. Claude receives Gemini's news/sentiment data alongside the chart, enabling news-aware technical analysis (e.g., interpreting a price gap as earnings-driven rather than a breakout pattern).
4. **GPT (Bull/Bear/Judge Debate):** Three GPT calls — a bull case, a bear case, and a judge synthesis. The judge also receives historical self-learning context. Outputs a final BUY/HOLD/SELL recommendation with confidence score, entry/stop/target levels, position sizing, and reasoning.

The user sees real-time pipeline status in the command bar (which stage is running, estimated time remaining).

### 4.3 Review & Decision

Recommendations appear as cards in the main panel. The user clicks a card to see the full detail view: Claude's annotated chart alongside a live TradingView widget, Perplexity's fundamentals, Gemini's sentiment, and GPT's full bull/bear/judge reasoning.

The user makes their decision — "Following" or "Passing" — with an optional note explaining why. This is a one-click action to minimize friction.

### 4.4 Execution (External)

The user switches to TradingView (which is already connected to their Questrade account) and places the trade manually. SignalForge never touches order execution.

### 4.5 Outcome Logging

After the trade plays out, the user returns to SignalForge's History view and logs the outcome: entry price, exit price, P&L, holding period, whether stop or target was hit. This is manual entry.

### 4.6 Self-Learning Cycle

Periodically (or on-demand), the system analyzes the accumulated data — recommendations, decisions, and outcomes — and generates reflection summaries. These summaries are injected into GPT's judge prompt on future runs, allowing the system to calibrate confidence scores, identify sector-specific blind spots, and learn from the user's override patterns.

---

## 5. Feature Requirements

### 5.1 Command Bar

| Requirement | Priority | Notes |
|---|---|---|
| Text input for comma-separated tickers | P0 | Simple text field, no autocomplete needed for MVP |
| Strategy dropdown selector | P0 | Populated from saved strategies in SQLite |
| "Run Analysis" button | P0 | Triggers pipeline execution |
| Pipeline status indicator | P0 | Shows current stage, ticker being processed, elapsed time |
| Combined mode (strategy + manual tickers) | P1 | Merge both inputs into a single pipeline run |

### 5.2 Recommendations View (Default)

| Requirement | Priority | Notes |
|---|---|---|
| Recommendation cards list (left panel) | P0 | Scrollable, compact: ticker, action, confidence, one-line summary |
| Detail view (right panel) | P0 | Expands on card click |
| Chart tab: Claude's analyzed chart image | P0 | Static image from pipeline |
| Chart tab: Live TradingView Advanced Chart widget | P0 | Iframe embed, symbol updates dynamically |
| Side-by-side chart layout | P0 | Claude's image left, TV widget right |
| Fundamentals tab: Perplexity research summary | P0 | Structured display of screening/research data |
| Sentiment tab: Gemini analysis | P0 | Sentiment score, key catalysts, news sources |
| Synthesis tab: GPT reasoning | P0 | Full bull case, bear case, and judge synthesis |
| Raw Data tab: All LLM outputs | P1 | JSON viewer for debugging |
| "Following" / "Passing" buttons | P0 | One-click with optional note modal |
| TradingView Technical Analysis widget | P1 | TV's own buy/sell ratings as second opinion |
| TradingView Fundamental Data widget | P1 | Key financials alongside Perplexity data |

### 5.3 History View

| Requirement | Priority | Notes |
|---|---|---|
| Table of past recommendations | P0 | Date, ticker, action, confidence, decision, outcome, P&L |
| Filter by ticker, strategy, action, date range | P0 | Standard table filtering |
| Filter by confidence level range | P1 | Slider or range input |
| Click row to view full analysis snapshot | P0 | Shows the analysis as it was at recommendation time |
| Editable outcome column | P0 | Manual entry: entry price, exit price, P&L, holding period |
| Export to CSV/JSON | P2 | For external analysis |

### 5.4 Strategy Manager

| Requirement | Priority | Notes |
|---|---|---|
| List of saved strategies | P0 | Name, description, last run, recommendation count |
| Template system: pick a base strategy, customize | P0 | Pre-built templates for common styles |
| Strategy config: Perplexity prompt + constraint style | P0 | Text editor for prompt, tight/loose toggle |
| Strategy config: Chart indicators | P0 | Multi-select from available indicators |
| Strategy config: Chart timeframe | P0 | Dropdown: 4H, Daily, Weekly |
| Strategy config: News recency window | P0 | Dropdown: Today, Past Week, Past Month |
| Strategy config: Trading style context for GPT | P0 | Text field for holding period, risk params |
| Strategy config: Bull/bear debate toggle | P1 | Enable/disable per strategy |
| Strategy performance stats | P1 | Win rate, avg confidence, recommendation count |
| Create / Edit / Duplicate / Delete strategies | P0 | Standard CRUD |
| Pre-built strategy templates | P0 | 3-5 starting templates (momentum, value, etc.) |

### 5.5 Insights / Reflections View

| Requirement | Priority | Notes |
|---|---|---|
| Confidence calibration chart | P1 | GPT confidence vs actual win rate |
| Strategy performance comparison | P1 | Which strategies produce best results |
| Sector performance breakdown | P2 | Win rate by sector |
| Override accuracy | P1 | When user passes on a recommendation, were they right? |
| Claude TA accuracy | P2 | How often Claude's pattern detection was correct |
| Prompt version performance tracking | P2 | Compare prompt iterations |
| Generate reflection summary button | P1 | Trigger self-learning analysis on demand |

### 5.6 Settings

| Requirement | Priority | Notes |
|---|---|---|
| API key management (Perplexity, Claude, Gemini, GPT) | P0 | Secure local storage, never transmitted |
| Chart Image API configuration | P0 | API key for chart generation service |
| Default strategy selection | P1 | Which strategy loads on app launch |
| Pipeline timeout configuration | P1 | Per-stage and total timeout limits |
| Database backup/export | P2 | Export SQLite file |

---

## 6. Non-Functional Requirements

### 6.1 Performance

- Pipeline execution for 5 tickers should complete in under 60 seconds (parallel stages help)
- Dashboard should feel responsive — card clicks, tab switches, and scroll should be instant
- TradingView widget iframe should load within 2 seconds of symbol change

### 6.2 Reliability

- Every LLM call has a retry layer with exponential backoff (max 2 retries)
- Every LLM output is validated against a Pydantic schema before passing downstream
- If a stage fails after retries, the pipeline continues with degraded data (e.g., if Gemini fails, GPT proceeds without sentiment data, noting the gap)
- All API responses are logged to SQLite regardless of success/failure

### 6.3 Security

- API keys stored locally using OS keyring (Windows Credential Manager via `keyring` library)
- No API keys transmitted anywhere except to their respective API endpoints
- No telemetry, no cloud sync, no external data transmission beyond the four LLM APIs and chart image API
- All data stays local in SQLite

### 6.4 Privacy

- Fully local application — no user accounts, no cloud services, no tracking
- SQLite database stored in user's app data directory
- No data leaves the machine except API calls to Perplexity, Anthropic, Google, OpenAI, and the chart image service

---

## 7. Tech Stack

| Component | Technology | Rationale |
|---|---|---|
| Desktop shell | Tauri 2.x (Rust) | Lightweight, native feel, Steve knows Rust |
| Frontend | React + TypeScript | Rich widget ecosystem, TradingView embeds work in webview |
| Backend | Python (FastAPI) | All pipeline logic, LLM orchestration, DB access |
| Database | SQLite | Simple, local, no server, portable |
| LLM clients | `openai`, `anthropic`, `google-generativeai` SDKs | Official Python SDKs for each provider |
| Validation | Pydantic v2 | Schema validation for all LLM outputs |
| Async | `asyncio` + `httpx` | Parallel pipeline stages |
| Chart generation | Chart-Img API (TradingView charts) | Generates chart images for Claude Vision |
| Package management | `uv` | Fast, Astral ecosystem |
| Linting | `ruff` (Black rules, f-string format) | Steve's standard Python tooling |

---

## 8. MVP Phasing

### Phase 1: Screening Foundation

- Perplexity screening module (discovery mode only)
- SQLite database with core schema
- Minimal Tauri shell with command bar and results display
- Single hardcoded strategy
- No chart analysis, no sentiment, no GPT synthesis
- **Value:** Usable stock screener with AI-powered research

### Phase 2: News Sentiment

- Gemini integration with Google Search grounding
- Sentiment scoring and catalyst extraction
- Sentiment tab in detail view
- **Value:** AI-powered screening + real-time news context for downstream stages

### Phase 3: Chart Analysis

- Claude Vision integration
- Chart-Img API integration
- Claude receives Gemini's news/sentiment data as context for chart interpretation
- Chart display in detail view (static images)
- Configurable indicators per strategy
- **Value:** Full data pipeline (fundamentals + sentiment + news-aware technicals)

### Phase 4: GPT Synthesis + Decision Engine

- GPT bull/bear/judge debate pattern
- Final recommendation generation
- Following/Passing decision logging
- Recommendation cards with full detail view
- **Value:** Complete analysis pipeline with actionable recommendations

### Phase 5: Self-Learning Loop

- Manual outcome logging
- Reflection summary generation
- Historical performance analytics (Insights view)
- Reflection context injection into GPT judge prompt
- Prompt versioning and tracking
- **Value:** System that improves over time

### Phase 6: Strategy Library + Polish

- Strategy CRUD with template system
- Pre-built strategy templates
- TradingView widget embeds (Advanced Chart, TA, Fundamentals)
- Manual ticker input + combined mode
- History view with filtering
- Full dashboard polish
- **Value:** Complete product

---

## 9. Cost Estimation

For approximately 10 tickers per analysis run, 2 runs per day:

| Service | Per-Run Cost (10 tickers) | Daily Cost (2 runs) | Monthly Cost |
|---|---|---|---|
| Perplexity Sonar Pro | ~$0.05 | ~$0.10 | ~$3 |
| Claude Sonnet (Vision) | ~$0.50 | ~$1.00 | ~$30 |
| Gemini 2.5 Pro | Free tier (50/day) | $0 | $0 |
| GPT (3x calls for debate) | ~$0.90 | ~$1.80 | ~$54 |
| Chart-Img API | ~$0.10 | ~$0.20 | ~$6 |
| **Total** | **~$1.55** | **~$3.10** | **~$93** |

Costs scale linearly with ticker count and run frequency. The bull/bear debate triples the GPT cost but is the largest quality lever in the system.

---

## 10. Success Metrics

Since this is a personal tool, success is measured by:

- **Usage:** Do I actually use it daily before trading?
- **Decision quality:** Is my win rate improving over time?
- **Override accuracy:** When I disagree with GPT, am I right more often than GPT?
- **Confidence calibration:** Does GPT's confidence score correlate with actual outcomes?
- **Time savings:** Am I spending less time on manual multi-tab analysis?
- **Strategy evolution:** Am I creating and refining strategies based on performance data?

---

## 11. Out of Scope

- Automated trade execution (by design — human in the loop always)
- Multi-user support or accounts
- Cloud sync or remote access
- Real-time streaming data (use TradingView for that)
- Options analysis (stocks and ETFs only for MVP)
- Backtesting engine (may be added later, but not in initial scope)
- Mobile app
- Broker API integration for order placement
