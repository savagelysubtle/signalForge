# SignalForge — Technical Architecture

> **Version:** 0.1.0 (Draft)
> **Last Updated:** March 12, 2026

---

## 1. System Architecture Overview

SignalForge is a Tauri desktop application with a Python-first backend architecture. Tauri serves as a lightweight native shell — all business logic, LLM orchestration, data persistence, and API communication lives in Python. The frontend is React/TypeScript rendered in Tauri's WebView2 (Windows), communicating with the Python backend via local HTTP.

```
┌─────────────────────────────────────────────────────────┐
│                    Tauri Shell (Rust)                    │
│  ┌───────────────────────────────────────────────────┐  │
│  │              WebView2 (Windows)                    │  │
│  │  ┌─────────────────────────────────────────────┐  │  │
│  │  │         React/TypeScript Frontend            │  │  │
│  │  │  ┌──────────┐ ┌──────────┐ ┌────────────┐  │  │  │
│  │  │  │ Command  │ │  Recom-  │ │  History   │  │  │  │
│  │  │  │   Bar    │ │ mendation│ │   View     │  │  │  │
│  │  │  │          │ │  Cards   │ │            │  │  │  │
│  │  │  └──────────┘ └──────────┘ └────────────┘  │  │  │
│  │  │  ┌──────────┐ ┌──────────┐ ┌────────────┐  │  │  │
│  │  │  │ Strategy │ │ Insights │ │  Settings  │  │  │  │
│  │  │  │ Manager  │ │   View   │ │            │  │  │  │
│  │  │  └──────────┘ └──────────┘ └────────────┘  │  │  │
│  │  │  ┌─────────────────────────────────────┐    │  │  │
│  │  │  │   TradingView Embedded Widgets      │    │  │  │
│  │  │  │   (iframe: chart, TA, fundamentals) │    │  │  │
│  │  │  └─────────────────────────────────────┘    │  │  │
│  │  └─────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────┘  │
│                         │ HTTP (localhost)               │
│                         ▼                                │
│  ┌───────────────────────────────────────────────────┐  │
│  │            Python Backend (FastAPI)                │  │
│  │  ┌──────────────────────────────────────────────┐ │  │
│  │  │            Pipeline Orchestrator              │ │  │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │ │  │
│  │  │  │Perplexity│ │  Claude  │ │   Gemini     │ │ │  │
│  │  │  │ Stage    │ │  Stage   │ │   Stage      │ │ │  │
│  │  │  └──────────┘ └──────────┘ └──────────────┘ │ │  │
│  │  │  ┌──────────────────────────────────────────┐│ │  │
│  │  │  │           GPT Stage                      ││ │  │
│  │  │  │  ┌──────┐ ┌──────┐ ┌──────────────────┐ ││ │  │
│  │  │  │  │ Bull │ │ Bear │ │      Judge       │ ││ │  │
│  │  │  │  └──────┘ └──────┘ └──────────────────┘ ││ │  │
│  │  │  └──────────────────────────────────────────┘│ │  │
│  │  └──────────────────────────────────────────────┘ │  │
│  │  ┌──────────────┐ ┌─────────────────────────────┐│  │
│  │  │   SQLite DB   │ │   Validation Layer          ││  │
│  │  │              │ │   (Pydantic Models)          ││  │
│  │  └──────────────┘ └─────────────────────────────┘│  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
          │              │              │            │
          ▼              ▼              ▼            ▼
    ┌──────────┐  ┌──────────┐  ┌──────────┐ ┌──────────┐
    │Perplexity│  │Anthropic │  │ Google   │ │ OpenAI   │
    │  Sonar   │  │  Claude  │  │ Gemini   │ │  GPT     │
    │   API    │  │   API    │  │   API    │ │   API    │
    └──────────┘  └──────────┘  └──────────┘ └──────────┘
                       │
                  ┌──────────┐
                  │Chart-Img │
                  │   API    │
                  └──────────┘
```

---

## 2. Process Architecture

Tauri spawns the Python FastAPI backend as a sidecar process on application launch. The backend binds to a random available localhost port and communicates the port back to Tauri. The frontend makes HTTP requests to `http://localhost:{port}`.

```
Application Startup Sequence:
1. Tauri launches → spawns Python sidecar
2. Python FastAPI binds to localhost:{random_port}
3. Python writes port to a known temp file
4. Tauri reads port, passes to WebView via inject
5. React app initializes with backend URL
6. Health check: GET /health → 200 OK
7. App is ready
```

**Why sidecar over embedded:** Tauri's Rust backend could theoretically call Python via PyO3, but the complexity isn't worth it. A sidecar process is simpler to develop, debug, and deploy. The localhost HTTP overhead is negligible for this use case (we're making multi-second LLM API calls — a few milliseconds of local HTTP is invisible).

**Process lifecycle:** Tauri owns the Python process. On app close, Tauri sends SIGTERM to the sidecar. The Python process has a shutdown hook that commits any pending SQLite transactions and closes connections cleanly.

---

## 3. Pipeline Architecture

### 3.1 Pipeline Flow

```
                    ┌─────────────────┐
                    │   User Input    │
                    │                 │
                    │  Strategy OR    │
                    │  Manual Tickers │
                    │  OR Both        │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   STAGE 1       │
                    │   Perplexity    │
                    │                 │
                    │  Discovery:     │
                    │  Screen stocks  │
                    │                 │
                    │  Analysis:      │
                    │  Research given  │
                    │  tickers        │
                    └────────┬────────┘
                             │
                     Validated ticker list
                     + fundamentals (JSON)
                             │
                    ┌────────┴────────┐
                    │                 │
                    ▼                 ▼
           ┌──────────────┐  ┌──────────────┐
           │   STAGE 2a   │  │   STAGE 2b   │
           │   Claude     │  │   Gemini     │
           │   Vision     │  │   News       │
           │              │  │              │
           │  Fetch chart │  │  Search news │
           │  images,     │  │  for each    │
           │  analyze TA  │  │  ticker,     │
           │  patterns    │  │  score       │
           │              │  │  sentiment   │
           └──────┬───────┘  └──────┬───────┘
                  │                 │
           TA data (JSON)    Sentiment (JSON)
                  │                 │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │   STAGE 3       │
                  │   GPT Debate    │
                  │                 │
                  │  ┌───────────┐  │
                  │  │   Bull    │──┐
                  │  └───────────┘  │
                  │  ┌───────────┐  │ (parallel)
                  │  │   Bear    │──┘
                  │  └───────────┘  │
                  │        │        │
                  │        ▼        │
                  │  ┌───────────┐  │
                  │  │   Judge   │  │
                  │  │ + History │  │
                  │  │ + Reflect │  │
                  │  └───────────┘  │
                  └────────┬────────┘
                           │
                    Recommendations
                       (JSON)
                           │
                           ▼
                  ┌─────────────────┐
                  │   Store in DB   │
                  │   + Send to     │
                  │   Frontend      │
                  └─────────────────┘
```

### 3.2 Stage Contracts (Pydantic Models)

Every stage has a defined input and output schema. Data only flows downstream after Pydantic validation passes.

**Perplexity Output Schema:**

```python
class FundamentalData(BaseModel):
    """Fundamental data for a single ticker from Perplexity screening."""

    ticker: str
    company_name: str
    sector: str
    market_cap: str
    pe_ratio: float | None
    revenue_growth: str | None
    free_cash_flow: str | None
    key_highlights: list[str]
    risk_factors: list[str]
    sources: list[str]


class ScreeningResult(BaseModel):
    """Complete output from Perplexity screening/research stage."""

    mode: Literal["discovery", "analysis"]
    strategy_name: str | None
    tickers: list[FundamentalData]
    screening_summary: str
    timestamp: datetime
```

**Claude Vision Output Schema:**

```python
class TechnicalLevel(BaseModel):
    """A support or resistance price level."""

    price: float
    level_type: Literal["support", "resistance"]
    strength: Literal["strong", "moderate", "weak"]


class IndicatorReading(BaseModel):
    """Reading from a single technical indicator."""

    indicator: str  # e.g., "RSI", "MACD", "Bollinger Bands"
    value: str  # e.g., "67.3", "Bullish crossover"
    signal: Literal["bullish", "bearish", "neutral"]
    notes: str


class ChartAnalysis(BaseModel):
    """Complete output from Claude Vision chart analysis."""

    ticker: str
    timeframe: str  # e.g., "Daily", "4H", "Weekly"
    trend_direction: Literal["bullish", "bearish", "neutral", "transitioning"]
    trend_strength: Literal["strong", "moderate", "weak"]
    key_levels: list[TechnicalLevel]
    patterns_detected: list[str]  # e.g., ["head_and_shoulders", "double_bottom"]
    indicator_readings: list[IndicatorReading]
    volume_analysis: str
    overall_bias: Literal["strongly_bullish", "bullish", "neutral", "bearish", "strongly_bearish"]
    confidence: Literal["high", "medium", "low"]
    summary: str
    chart_image_path: str  # local path to the analyzed chart image
```

**Gemini Sentiment Output Schema:**

```python
class NewsCatalyst(BaseModel):
    """A single news catalyst affecting sentiment."""

    headline: str
    source: str
    impact: Literal["positive", "negative", "neutral"]
    significance: Literal["high", "medium", "low"]


class SentimentAnalysis(BaseModel):
    """Complete output from Gemini news sentiment analysis."""

    ticker: str
    sentiment_score: float  # -1.0 (bearish) to 1.0 (bullish)
    sentiment_label: Literal["strongly_bearish", "bearish", "neutral", "bullish", "strongly_bullish"]
    key_catalysts: list[NewsCatalyst]
    news_recency: str  # e.g., "Past 7 days"
    sector_sentiment: str
    summary: str
```

**GPT Debate Output Schema:**

```python
class DebateCase(BaseModel):
    """Bull or Bear argument for a single ticker."""

    ticker: str
    stance: Literal["bull", "bear"]
    key_arguments: list[str]
    strongest_signal: str
    weakest_counter: str
    confidence: float  # 0.0 to 1.0


class Recommendation(BaseModel):
    """Final judge recommendation for a single ticker."""

    ticker: str
    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float  # 0.0 to 1.0
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    position_size_pct: float  # percentage of portfolio
    risk_reward_ratio: float | None
    holding_period: str  # e.g., "3-5 days", "1-2 weeks"
    bull_case: DebateCase
    bear_case: DebateCase
    judge_reasoning: str
    key_factors: list[str]
    warnings: list[str]


class PipelineResult(BaseModel):
    """Complete output from a full pipeline run."""

    run_id: str
    timestamp: datetime
    strategy_name: str | None
    mode: Literal["discovery", "analysis", "combined"]
    input_tickers: list[str]  # manually entered tickers (if any)
    screening: ScreeningResult
    chart_analyses: list[ChartAnalysis]
    sentiment_analyses: list[SentimentAnalysis]
    recommendations: list[Recommendation]
    stage_errors: list[dict]  # any stages that failed
    total_duration_seconds: float
    prompt_versions: dict[str, str]  # stage_name -> prompt version hash
```

### 3.3 Retry & Validation Layer

Every LLM call is wrapped in a retry handler:

```
Call LLM
  → Parse response as JSON
  → Validate against Pydantic schema
  → If validation fails:
      → Retry with error context appended to prompt
      → "Your previous response failed validation: {error}. 
         Please respond with valid JSON matching this schema: {schema}"
      → Max 2 retries per call
  → If all retries fail:
      → Log the failure
      → Mark stage as "degraded" in PipelineResult
      → Continue pipeline without this stage's data
      → GPT judge prompt notes which data is missing
```

### 3.4 Parallel Execution

Stages 2a (Claude) and 2b (Gemini) are independent and run concurrently via `asyncio.gather()`. Within each stage, individual ticker analyses can also run in parallel (with rate limiting to respect API quotas).

The GPT stage's bull and bear calls are also parallel. Only the judge call is sequential (it requires bull + bear outputs).

```python
# Pseudocode for pipeline orchestration
async def run_pipeline(config: PipelineConfig) -> PipelineResult:
    # Stage 1: Sequential
    screening = await run_perplexity_stage(config)
    tickers = extract_tickers(screening, config.manual_tickers)

    # Stage 2: Parallel (Claude + Gemini)
    chart_analyses, sentiment_analyses = await asyncio.gather(
        run_claude_stage(tickers, config),
        run_gemini_stage(tickers, config),
    )

    # Stage 3: GPT Debate
    # Bull and Bear are parallel, Judge is sequential
    reflection = await load_reflection_context()
    bull_cases, bear_cases = await asyncio.gather(
        run_gpt_bull(tickers, screening, chart_analyses, sentiment_analyses, config),
        run_gpt_bear(tickers, screening, chart_analyses, sentiment_analyses, config),
    )
    recommendations = await run_gpt_judge(
        tickers, screening, chart_analyses, sentiment_analyses,
        bull_cases, bear_cases, reflection, config,
    )

    return PipelineResult(...)
```

---

## 4. Database Schema

SQLite with WAL mode for concurrent read access from the frontend while the backend writes.

### 4.1 Core Tables

```sql
-- Strategy definitions
CREATE TABLE strategies (
    id              TEXT PRIMARY KEY,   -- UUID
    name            TEXT NOT NULL UNIQUE,
    description     TEXT,
    
    -- Perplexity config
    screening_prompt    TEXT NOT NULL,
    constraint_style    TEXT NOT NULL CHECK (constraint_style IN ('tight', 'loose')),
    max_tickers         INTEGER DEFAULT 10,
    
    -- Claude config
    chart_indicators    TEXT NOT NULL,   -- JSON array: ["RSI", "MACD", "BB"]
    chart_timeframe     TEXT NOT NULL DEFAULT 'D',  -- "4H", "D", "W"
    ta_focus            TEXT,            -- e.g., "divergences", "breakouts"
    
    -- Gemini config
    news_recency        TEXT NOT NULL DEFAULT 'week',  -- "today", "week", "month"
    news_scope          TEXT NOT NULL DEFAULT 'company', -- "company", "sector", "macro"
    
    -- GPT config
    trading_style       TEXT,            -- e.g., "swing trader, 3-10 day holds"
    risk_params         TEXT,            -- JSON: max position size, min RR ratio, etc.
    enable_debate       BOOLEAN DEFAULT TRUE,
    
    -- Metadata
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    run_count        INTEGER DEFAULT 0,
    is_template     BOOLEAN DEFAULT FALSE
);

-- Pipeline run history
CREATE TABLE pipeline_runs (
    id              TEXT PRIMARY KEY,   -- UUID
    strategy_id     TEXT REFERENCES strategies(id),
    mode            TEXT NOT NULL CHECK (mode IN ('discovery', 'analysis', 'combined')),
    manual_tickers  TEXT,               -- JSON array of manually entered tickers
    status          TEXT NOT NULL DEFAULT 'running',  -- running, completed, failed, partial
    
    -- Timing
    started_at      DATETIME NOT NULL,
    completed_at    DATETIME,
    duration_seconds REAL,
    
    -- Prompt tracking
    prompt_versions TEXT,               -- JSON: {"perplexity": "abc123", "claude": "def456", ...}
    
    -- Error tracking
    stage_errors    TEXT                -- JSON array of error objects
);

-- Raw LLM stage outputs (for debugging and replay)
CREATE TABLE stage_outputs (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES pipeline_runs(id),
    stage           TEXT NOT NULL,      -- "perplexity", "claude", "gemini", "gpt_bull", "gpt_bear", "gpt_judge"
    ticker          TEXT,               -- NULL for perplexity screening (multi-ticker)
    
    -- Request/Response
    prompt_text     TEXT NOT NULL,       -- the full prompt sent
    raw_response    TEXT NOT NULL,       -- raw LLM response (before parsing)
    parsed_output   TEXT,               -- validated JSON output (NULL if validation failed)
    
    -- Metadata
    model_used      TEXT NOT NULL,       -- e.g., "sonar-pro", "claude-sonnet-4-20250514"
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    cost_estimate   REAL,               -- estimated cost in USD
    duration_ms     INTEGER,
    status          TEXT NOT NULL,       -- "success", "validation_failed", "api_error", "timeout"
    retry_count     INTEGER DEFAULT 0,
    
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Chart images
CREATE TABLE chart_images (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES pipeline_runs(id),
    ticker          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    indicators      TEXT NOT NULL,       -- JSON array of indicator names
    image_path      TEXT NOT NULL,       -- local filesystem path to PNG
    image_hash      TEXT,               -- SHA-256 for dedup
    source_url      TEXT,               -- Chart-Img API URL used
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Final recommendations (parsed from GPT judge output)
CREATE TABLE recommendations (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES pipeline_runs(id),
    ticker          TEXT NOT NULL,
    
    -- Recommendation
    action          TEXT NOT NULL CHECK (action IN ('BUY', 'SELL', 'HOLD')),
    confidence      REAL NOT NULL,      -- 0.0 to 1.0
    entry_price     REAL,
    stop_loss       REAL,
    take_profit     REAL,
    position_size_pct REAL,
    risk_reward_ratio REAL,
    holding_period  TEXT,
    
    -- Reasoning
    bull_case       TEXT NOT NULL,       -- JSON: DebateCase
    bear_case       TEXT NOT NULL,       -- JSON: DebateCase
    judge_reasoning TEXT NOT NULL,
    key_factors     TEXT NOT NULL,       -- JSON array
    warnings        TEXT,               -- JSON array
    
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- User decisions on recommendations
CREATE TABLE decisions (
    id              TEXT PRIMARY KEY,
    recommendation_id TEXT NOT NULL REFERENCES recommendations(id),
    decision        TEXT NOT NULL CHECK (decision IN ('following', 'passing')),
    reason          TEXT,               -- optional note
    reason_category TEXT,               -- "disagreed", "already_positioned", "risk_too_high", "missed_window", "other"
    decided_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Trade outcomes (manually entered)
CREATE TABLE outcomes (
    id              TEXT PRIMARY KEY,
    decision_id     TEXT NOT NULL REFERENCES decisions(id),
    recommendation_id TEXT NOT NULL REFERENCES recommendations(id),
    ticker          TEXT NOT NULL,
    
    -- Trade data
    entry_price     REAL,
    exit_price      REAL,
    shares          INTEGER,
    pnl_dollars     REAL,
    pnl_percent     REAL,
    holding_days    INTEGER,
    exit_reason     TEXT,               -- "hit_target", "hit_stop", "manual_exit", "time_exit"
    
    notes           TEXT,
    logged_at       DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Generated reflection summaries for self-learning
CREATE TABLE reflections (
    id              TEXT PRIMARY KEY,
    generated_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- Analysis scope
    recommendations_analyzed INTEGER,
    decisions_analyzed      INTEGER,
    outcomes_analyzed       INTEGER,
    date_range_start        DATETIME,
    date_range_end          DATETIME,
    
    -- Generated insights
    summary_text    TEXT NOT NULL,       -- human-readable summary
    injection_prompt TEXT NOT NULL,      -- the text injected into GPT judge context
    
    -- Performance metrics at time of generation
    metrics         TEXT NOT NULL        -- JSON: overall win rate, by sector, by confidence tier, etc.
);

-- Indexes
CREATE INDEX idx_pipeline_runs_strategy ON pipeline_runs(strategy_id);
CREATE INDEX idx_stage_outputs_run ON stage_outputs(run_id);
CREATE INDEX idx_stage_outputs_stage ON stage_outputs(stage);
CREATE INDEX idx_recommendations_run ON recommendations(run_id);
CREATE INDEX idx_recommendations_ticker ON recommendations(ticker);
CREATE INDEX idx_decisions_recommendation ON decisions(recommendation_id);
CREATE INDEX idx_outcomes_recommendation ON outcomes(recommendation_id);
CREATE INDEX idx_outcomes_ticker ON outcomes(ticker);
```

---

## 5. API Design (FastAPI Backend)

### 5.1 Pipeline Endpoints

```
POST   /api/pipeline/run          -- Trigger a pipeline run
GET    /api/pipeline/status/{id}  -- Poll pipeline status (SSE upgrade possible later)
GET    /api/pipeline/runs         -- List past pipeline runs
GET    /api/pipeline/runs/{id}    -- Get full pipeline result
```

### 5.2 Recommendation Endpoints

```
GET    /api/recommendations                    -- List recommendations (with filters)
GET    /api/recommendations/{id}               -- Get single recommendation with all data
POST   /api/recommendations/{id}/decision      -- Log following/passing decision
POST   /api/recommendations/{id}/outcome       -- Log trade outcome
```

### 5.3 Strategy Endpoints

```
GET    /api/strategies              -- List all strategies
GET    /api/strategies/templates    -- List built-in templates
POST   /api/strategies              -- Create strategy
PUT    /api/strategies/{id}         -- Update strategy
DELETE /api/strategies/{id}         -- Delete strategy
POST   /api/strategies/{id}/duplicate -- Duplicate strategy
GET    /api/strategies/{id}/stats   -- Get strategy performance stats
```

### 5.4 Insights Endpoints

```
GET    /api/insights/overview       -- Overall performance metrics
GET    /api/insights/calibration    -- Confidence vs actual win rate data
GET    /api/insights/strategies     -- Strategy comparison data
GET    /api/insights/overrides      -- User override accuracy data
POST   /api/insights/reflect        -- Trigger reflection generation
GET    /api/reflections             -- List generated reflections
GET    /api/reflections/latest      -- Get most recent reflection
```

### 5.5 System Endpoints

```
GET    /health                      -- Health check
GET    /api/settings                -- Get app settings (non-sensitive)
PUT    /api/settings                -- Update app settings
POST   /api/settings/api-keys       -- Store API key (goes to OS keyring)
GET    /api/settings/api-keys/status -- Check which API keys are configured (no values)
```

---

## 6. Frontend Architecture

### 6.1 Layout Structure

```
┌──────────────────────────────────────────────────────────────┐
│ ┌────┐ ┌──────────── Command Bar ──────────────────────────┐ │
│ │    │ │ [Strategy ▼] [AAPL, TSLA, NVDA    ] [▶ Run]  ◉   │ │
│ │ S  │ └───────────────────────────────────────────────────┘ │
│ │ I  │ ┌─── Cards List ───┐ ┌───── Detail View ──────────┐  │
│ │ D  │ │                  │ │                             │  │
│ │ E  │ │ ┌──────────────┐ │ │  ▲ BUY NVDA  (0.87)        │  │
│ │ B  │ │ │ NVDA  BUY    │ │ │  Entry: $142  Stop: $135   │  │
│ │ A  │ │ │ ████░  0.87  │ │ │  Target: $158  RR: 2.3     │  │
│ │ R  │ │ │ RSI diverg.. │◄├─│                             │  │
│ │    │ │ └──────────────┘ │ │ ┌─────────────────────────┐ │  │
│ │ ── │ │ ┌──────────────┐ │ │ │ [Chart][Fund][Sent][Syn]│ │  │
│ │ 📊 │ │ │ AAPL  HOLD   │ │ │ ├─────────────────────────┤ │  │
│ │ 📜 │ │ │ ████░  0.52  │ │ │ │ ┌──────────┬──────────┐│ │  │
│ │ 📋 │ │ │ Mixed sign.. │ │ │ │ │ Claude's │ Live TV  ││ │  │
│ │ 💡 │ │ └──────────────┘ │ │ │ │ Chart    │ Widget   ││ │  │
│ │ ⚙  │ │ ┌──────────────┐ │ │ │ │ Image    │ (iframe) ││ │  │
│ │    │ │ │ TSLA  SELL   │ │ │ │ │          │          ││ │  │
│ │    │ │ │ ████░  0.71  │ │ │ │ └──────────┴──────────┘│ │  │
│ │    │ │ │ Bearish MA.. │ │ │ └─────────────────────────┘ │  │
│ │    │ │ └──────────────┘ │ │                             │  │
│ │    │ │                  │ │  [✓ Following]  [✗ Passing]  │  │
│ └────┘ └──────────────────┘ └─────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 6.2 Sidebar Navigation

| Icon | View | Description |
|------|------|-------------|
| 📊 | Recommendations | Default view. Pipeline results and recommendation cards |
| 📜 | History | Past recommendations, decisions, outcomes table |
| 📋 | Strategies | Strategy library with template system and editor |
| 💡 | Insights | Self-learning analytics and reflection summaries |
| ⚙ | Settings | API keys, app configuration, database management |

### 6.3 Key Frontend Components

**CommandBar:** Always visible at top. Strategy dropdown + ticker text input + Run button + pipeline status badge. The status badge shows: idle (gray), running (pulsing blue with stage name), completed (green), error (red).

**RecommendationCard:** Compact card showing ticker, action badge (green BUY / red SELL / gray HOLD), confidence bar, and one-line summary. Selected card has highlighted border. Cards are sorted by confidence descending by default.

**DetailView:** Right panel that populates when a card is selected. Tabbed interface:
- **Chart:** Side-by-side layout. Left: Claude's analyzed chart image (static PNG). Right: TradingView Advanced Chart widget (live iframe, symbol set dynamically).
- **Fundamentals:** Perplexity's research data rendered as structured content. Optionally includes TradingView Fundamental Data widget.
- **Sentiment:** Gemini's sentiment score (large number with color), catalyst list, sector sentiment context.
- **Synthesis:** Three-column layout — Bull case | Bear case | Judge reasoning. Or a sequential layout if screen width is limited.
- **Raw:** JSON tree viewer for debugging all stage outputs.

**DecisionButtons:** "Following" (green) and "Passing" (red) buttons at the bottom of DetailView. Clicking opens a minimal modal: reason category dropdown (optional) + free text note (optional) + confirm button.

### 6.4 TradingView Widget Integration

Widgets are embedded via iframes. The Advanced Chart widget URL is constructed dynamically:

```
https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js

Config object:
{
  "symbol": "{ticker}",          // dynamically set
  "width": "100%",
  "height": "100%",
  "colorTheme": "dark",          // matches dashboard theme
  "isTransparent": true,         // blends with dark background
  "locale": "en",
  "interval": "D",               // matches strategy timeframe
  "studies": ["RSI@tv-basicstudies", "MACD@tv-basicstudies"],
  "allow_symbol_change": true    // user can navigate in widget
}
```

The widget iframe is recreated (not just updated) when the ticker changes, to ensure clean state.

### 6.5 Theming

Dark theme only. CSS variables for consistency:

```css
:root {
  --bg-primary: #0d1117;        /* GitHub dark style */
  --bg-secondary: #161b22;
  --bg-tertiary: #21262d;
  --border: #30363d;
  --text-primary: #e6edf3;
  --text-secondary: #8b949e;
  --accent-green: #3fb950;       /* BUY, Following */
  --accent-red: #f85149;         /* SELL, Passing */
  --accent-yellow: #d29922;      /* HOLD, warnings */
  --accent-blue: #58a6ff;        /* links, active states */
  --confidence-high: #3fb950;
  --confidence-mid: #d29922;
  --confidence-low: #f85149;
}
```

---

## 7. Strategy Configuration System

### 7.1 Strategy Object

A strategy is a complete configuration for a pipeline run. It contains:

```python
class StrategyConfig(BaseModel):
    """Complete strategy configuration."""

    # Identity
    id: str
    name: str
    description: str

    # Perplexity Stage
    screening_prompt: str          # The actual prompt template
    constraint_style: Literal["tight", "loose"]
    max_tickers: int = 10

    # Claude Stage
    chart_indicators: list[str]    # e.g., ["RSI", "MACD", "Bollinger Bands"]
    chart_timeframe: str           # "4H", "D", "W"
    ta_focus: str | None           # e.g., "Focus on divergences and breakout patterns"

    # Gemini Stage
    news_recency: Literal["today", "week", "month"]
    news_scope: Literal["company", "sector", "macro"]

    # GPT Stage
    trading_style: str             # e.g., "Swing trader, 3-10 day holds, max 5% position size"
    risk_params: RiskParams
    enable_debate: bool = True
```

### 7.2 Template System

Pre-built templates serve as starting points. Users pick a template and customize it.

**Included Templates:**

| Template | Screen Style | Indicators | Timeframe | News Window | Trading Style |
|----------|-------------|------------|-----------|-------------|---------------|
| Momentum Breakout | Tight: high relative volume, 52-week high proximity | RSI, Volume, 20/50 EMA | Daily | Today | Day to swing, 2-5 days |
| Value Accumulation | Loose: undervalued names, insider buying | 50/200 SMA, MACD, Volume | Weekly | Past Month | Position, 2-8 weeks |
| Mean Reversion | Tight: oversold RSI <30, near support | RSI, Bollinger Bands, Stochastic | Daily | Past Week | Swing, 3-7 days |
| Earnings Play | Tight: reporting within 2 weeks, high IV | Bollinger Bands, Volume, ATR | Daily | Past Week | Event-driven, 1-5 days |
| Dividend Growth | Loose: growing dividends, low payout ratio | 200 SMA, MACD, Volume | Weekly | Past Month | Long-term, 4+ weeks |

### 7.3 Strategy Editor UI

The template system uses a two-step flow:

1. **Pick a template** — grid of template cards, each showing name, description, and key parameters
2. **Customize** — form view with all parameters editable, pre-populated from template

The form groups parameters by stage:
- **Screening** section: prompt text editor, constraint toggle, max tickers slider
- **Chart Analysis** section: indicator checkboxes, timeframe dropdown, TA focus text field
- **News Analysis** section: recency dropdown, scope dropdown
- **Decision Engine** section: trading style text field, risk parameter fields, debate toggle

---

## 8. Self-Learning Feedback Loop

### 8.1 Data Flow

```
Recommendation generated
        │
        ▼
User logs decision (following/passing + reason)
        │
        ▼
Trade executes in TradingView (external)
        │
        ▼
User logs outcome (entry, exit, P&L, holding period)
        │
        ▼
System accumulates decision+outcome data
        │
        ▼
Reflection engine analyzes patterns
        │
        ▼
Generates reflection summary + injection prompt
        │
        ▼
Injected into GPT judge context on next pipeline run
```

### 8.2 Reflection Generation

The reflection engine queries the outcomes table and produces two outputs:

1. **Human-readable summary** (shown in Insights view):
   "Over the last 30 days, the system produced 47 recommendations. You followed 31 (66%). Of those followed: 19 profitable (61% win rate), avg gain +4.2%, avg loss -2.1%. Your override accuracy (passing on recommendations that would have lost): 69%. Confidence calibration: recommendations scored 0.8+ had a 71% win rate; scored 0.5-0.8 had 48% win rate."

2. **GPT injection prompt** (prepended to judge context):
   "HISTORICAL PERFORMANCE CONTEXT: Based on 47 recent recommendations, your confidence scores are calibrated approximately 12% too high. BUY signals in technology have a 68% hit rate. SELL signals have only a 41% hit rate — consider higher thresholds for SELL calls. The human overrides your recommendation 34% of the time and is correct in 69% of overrides — respect the human's judgment, especially on SELL calls. Mean profitable hold is 5.2 days; extend holding period estimates accordingly."

### 8.3 Reflection Triggers

- Manual: User clicks "Generate Reflection" in Insights view
- Automatic: After every 10 outcome entries (configurable)
- The most recent reflection is always used for GPT injection

---

## 9. API Key Management

### 9.1 Storage

API keys are stored in the Windows Credential Manager via Python's `keyring` library. They are never written to SQLite, config files, or logs.

```python
import keyring

SERVICE_NAME = "signalforge"

def store_api_key(provider: str, key: str) -> None:
    keyring.set_password(SERVICE_NAME, provider, key)

def get_api_key(provider: str) -> str | None:
    return keyring.get_password(SERVICE_NAME, provider)

# Providers: "perplexity", "anthropic", "google", "openai", "chartimg"
```

### 9.2 First-Run Setup

On first launch, the Settings view prompts for API keys. A status indicator shows which keys are configured (green checkmark) vs missing (red X). The pipeline refuses to run if required keys are missing, with a clear message directing the user to Settings.

---

## 10. Error Handling & Resilience

### 10.1 Error Categories

| Category | Example | Handling |
|----------|---------|----------|
| API key missing | No Anthropic key configured | Block pipeline, direct to Settings |
| API rate limit | Perplexity 429 Too Many Requests | Exponential backoff, max 3 retries |
| API error | Claude 500 Internal Server Error | Retry twice, then mark stage degraded |
| Validation failure | GPT returns invalid JSON | Retry with error context in prompt |
| Timeout | Gemini takes >30s | Cancel, mark stage degraded |
| Chart image failure | Chart-Img API down | Skip Claude stage, note in pipeline result |
| Network failure | No internet connection | Fail pipeline immediately with clear error |

### 10.2 Degraded Pipeline

When a non-critical stage fails, the pipeline continues. GPT's judge prompt explicitly acknowledges missing data:

"NOTE: Gemini sentiment analysis is unavailable for this run due to API error. Base your assessment on fundamental screening and technical analysis only. Indicate reduced confidence in your recommendations due to missing sentiment data."

### 10.3 Logging

All API calls are logged to the `stage_outputs` table with full request/response data, timing, token counts, and cost estimates. This serves as both a debugging tool and an audit trail.

---

## 11. Project Structure

```
signalforge/
├── src/
│   ├── backend/                    # Python (FastAPI)
│   │   ├── main.py                 # FastAPI app entry point
│   │   ├── config.py               # App configuration
│   │   ├── database/
│   │   │   ├── connection.py       # SQLite connection management
│   │   │   ├── models.py           # SQLAlchemy or raw SQL models
│   │   │   └── migrations/         # Schema migrations
│   │   ├── pipeline/
│   │   │   ├── orchestrator.py     # Pipeline execution engine
│   │   │   ├── stages/
│   │   │   │   ├── perplexity.py   # Perplexity screening/research
│   │   │   │   ├── claude.py       # Claude Vision chart analysis
│   │   │   │   ├── gemini.py       # Gemini news sentiment
│   │   │   │   └── gpt.py         # GPT bull/bear/judge debate
│   │   │   ├── schemas.py          # Pydantic models (stage contracts)
│   │   │   ├── prompts/
│   │   │   │   ├── perplexity_discovery.py
│   │   │   │   ├── perplexity_analysis.py
│   │   │   │   ├── claude_chart.py
│   │   │   │   ├── gemini_sentiment.py
│   │   │   │   ├── gpt_bull.py
│   │   │   │   ├── gpt_bear.py
│   │   │   │   └── gpt_judge.py
│   │   │   └── validation.py       # Retry and validation logic
│   │   ├── services/
│   │   │   ├── strategy.py         # Strategy CRUD
│   │   │   ├── recommendation.py   # Recommendation queries
│   │   │   ├── decision.py         # Decision logging
│   │   │   ├── outcome.py          # Outcome logging
│   │   │   ├── reflection.py       # Self-learning engine
│   │   │   ├── chart_image.py      # Chart-Img API client
│   │   │   └── keyring.py          # API key management
│   │   ├── api/
│   │   │   ├── pipeline.py         # Pipeline endpoints
│   │   │   ├── recommendations.py  # Recommendation endpoints
│   │   │   ├── strategies.py       # Strategy endpoints
│   │   │   ├── insights.py         # Insights endpoints
│   │   │   └── settings.py         # Settings endpoints
│   │   └── utils/
│   │       ├── logging.py
│   │       └── hashing.py          # Prompt version hashing
│   │
│   ├── frontend/                   # React + TypeScript
│   │   ├── src/
│   │   │   ├── App.tsx
│   │   │   ├── components/
│   │   │   │   ├── layout/
│   │   │   │   │   ├── Sidebar.tsx
│   │   │   │   │   ├── CommandBar.tsx
│   │   │   │   │   └── MainLayout.tsx
│   │   │   │   ├── recommendations/
│   │   │   │   │   ├── CardList.tsx
│   │   │   │   │   ├── RecommendationCard.tsx
│   │   │   │   │   ├── DetailView.tsx
│   │   │   │   │   ├── ChartTab.tsx
│   │   │   │   │   ├── FundamentalsTab.tsx
│   │   │   │   │   ├── SentimentTab.tsx
│   │   │   │   │   ├── SynthesisTab.tsx
│   │   │   │   │   └── DecisionButtons.tsx
│   │   │   │   ├── history/
│   │   │   │   │   ├── HistoryTable.tsx
│   │   │   │   │   └── OutcomeEditor.tsx
│   │   │   │   ├── strategies/
│   │   │   │   │   ├── StrategyList.tsx
│   │   │   │   │   ├── StrategyEditor.tsx
│   │   │   │   │   └── TemplateSelector.tsx
│   │   │   │   ├── insights/
│   │   │   │   │   ├── OverviewDashboard.tsx
│   │   │   │   │   ├── CalibrationChart.tsx
│   │   │   │   │   └── StrategyComparison.tsx
│   │   │   │   ├── settings/
│   │   │   │   │   ├── ApiKeyManager.tsx
│   │   │   │   │   └── AppSettings.tsx
│   │   │   │   └── shared/
│   │   │   │       ├── TradingViewWidget.tsx
│   │   │   │       ├── ConfidenceBar.tsx
│   │   │   │       └── ActionBadge.tsx
│   │   │   ├── hooks/
│   │   │   │   ├── usePipeline.ts
│   │   │   │   ├── useRecommendations.ts
│   │   │   │   └── useStrategies.ts
│   │   │   ├── api/
│   │   │   │   └── client.ts       # HTTP client for backend
│   │   │   ├── types/
│   │   │   │   └── index.ts        # TypeScript interfaces (mirror Pydantic)
│   │   │   └── theme/
│   │   │       └── dark.css
│   │   ├── index.html
│   │   ├── package.json
│   │   └── tsconfig.json
│   │
│   └── tauri/                      # Tauri (Rust)
│       ├── src/
│       │   └── main.rs             # Sidecar management, window config
│       ├── tauri.conf.json
│       └── Cargo.toml
│
├── data/                           # Local data directory
│   ├── signalforge.db              # SQLite database
│   └── charts/                     # Downloaded chart images
│
├── templates/                      # Built-in strategy templates
│   └── strategies.json
│
├── pyproject.toml                  # Python project config (uv)
├── ARCHITECTURE.md
├── PRD.md
├── CLAUDE.md
└── README.md
```

---

## 12. Deployment & Distribution

### 12.1 Development

```bash
# Backend
cd src/backend
uv sync
uv run uvicorn main:app --reload --port 8420

# Frontend
cd src/frontend
npm install
npm run dev

# Tauri (dev mode)
cd src/tauri
cargo tauri dev
```

### 12.2 Production Build

Tauri bundles the frontend into the binary. The Python backend is bundled as a sidecar using PyInstaller or Nuitka, producing a single executable that Tauri spawns.

```bash
# Build Python sidecar
cd src/backend
pyinstaller --onefile main.py --name signalforge-backend

# Build Tauri app (includes frontend + sidecar)
cd src/tauri
cargo tauri build
```

The final output is a `.msi` installer for Windows containing:
- The Tauri executable (with embedded frontend)
- The Python sidecar binary
- Default strategy templates
- Empty SQLite database with schema

---

## Appendix A: External API Reference

| API | Base URL | Auth | SDK |
|-----|----------|------|-----|
| Perplexity Sonar | `https://api.perplexity.ai` | Bearer token | `openai` (compatible) |
| Anthropic Claude | `https://api.anthropic.com` | `x-api-key` header | `anthropic` |
| Google Gemini | `https://generativelanguage.googleapis.com` | API key | `google-generativeai` |
| OpenAI GPT | `https://api.openai.com` | Bearer token | `openai` |
| Chart-Img | `https://api.chart-img.com` | API key param | `httpx` (direct) |
| TradingView Widgets | `https://s3.tradingview.com` | None (public) | iframe embed |

## Appendix B: Questrade API (Read-Only, Future Use)

Questrade's API can provide account balances, positions, and historical trades via OAuth 2.0. This is out of scope for MVP but documented here for future integration:

- Auth: OAuth 2.0 with refresh token rotation (tokens expire in 30 minutes)
- Base URL: Dynamic (provided in token response, e.g., `https://api01.iq.questrade.com/v1`)
- Available: Account data, positions, balances, market data, historical candles, streaming L1 quotes
- Not available: Trade execution (requires partner status)
- Useful for: Auto-populating outcomes, verifying positions, syncing portfolio state
