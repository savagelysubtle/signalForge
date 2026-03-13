-- SignalForge initial schema
-- All tables use TEXT UUIDs as primary keys (uuid.uuid4().hex)
-- WAL mode and foreign keys are set in connection.py, not here.

-- Strategy definitions
CREATE TABLE IF NOT EXISTS strategies (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT,

    -- Perplexity config
    screening_prompt    TEXT NOT NULL,
    constraint_style    TEXT NOT NULL CHECK (constraint_style IN ('tight', 'loose')),
    max_tickers         INTEGER DEFAULT 10,

    -- Claude config
    chart_indicators    TEXT NOT NULL,       -- JSON array: ["RSI", "MACD", "BB"]
    chart_timeframe     TEXT NOT NULL DEFAULT 'D',
    ta_focus            TEXT,

    -- Gemini config
    news_recency        TEXT NOT NULL DEFAULT 'week',
    news_scope          TEXT NOT NULL DEFAULT 'company',

    -- GPT config
    trading_style       TEXT,
    risk_params         TEXT,               -- JSON object
    enable_debate       BOOLEAN DEFAULT TRUE,

    -- Metadata
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    run_count       INTEGER DEFAULT 0,
    is_template     BOOLEAN DEFAULT FALSE
);

-- Pipeline run history
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              TEXT PRIMARY KEY,
    strategy_id     TEXT REFERENCES strategies(id),
    mode            TEXT NOT NULL CHECK (mode IN ('discovery', 'analysis', 'combined')),
    manual_tickers  TEXT,                   -- JSON array
    status          TEXT NOT NULL DEFAULT 'running',

    started_at      DATETIME NOT NULL,
    completed_at    DATETIME,
    duration_seconds REAL,

    prompt_versions TEXT,                   -- JSON: {"perplexity": "abc123", ...}
    stage_errors    TEXT                    -- JSON array of error objects
);

-- Raw LLM stage outputs (debugging and replay)
CREATE TABLE IF NOT EXISTS stage_outputs (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES pipeline_runs(id),
    stage           TEXT NOT NULL,
    ticker          TEXT,

    prompt_text     TEXT NOT NULL,
    raw_response    TEXT NOT NULL,
    parsed_output   TEXT,

    model_used      TEXT NOT NULL,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    cost_estimate   REAL,
    duration_ms     INTEGER,
    status          TEXT NOT NULL,
    retry_count     INTEGER DEFAULT 0,

    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Chart images
CREATE TABLE IF NOT EXISTS chart_images (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES pipeline_runs(id),
    ticker          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    indicators      TEXT NOT NULL,           -- JSON array
    image_path      TEXT NOT NULL,
    image_hash      TEXT,
    source_url      TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Final recommendations
CREATE TABLE IF NOT EXISTS recommendations (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES pipeline_runs(id),
    ticker          TEXT NOT NULL,

    action          TEXT NOT NULL CHECK (action IN ('BUY', 'SELL', 'HOLD')),
    confidence      REAL NOT NULL,
    entry_price     REAL,
    stop_loss       REAL,
    take_profit     REAL,
    position_size_pct REAL,
    risk_reward_ratio REAL,
    holding_period  TEXT,

    bull_case       TEXT NOT NULL,           -- JSON: DebateCase
    bear_case       TEXT NOT NULL,           -- JSON: DebateCase
    judge_reasoning TEXT NOT NULL,
    key_factors     TEXT NOT NULL,           -- JSON array
    warnings        TEXT,                    -- JSON array

    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- User decisions on recommendations
CREATE TABLE IF NOT EXISTS decisions (
    id              TEXT PRIMARY KEY,
    recommendation_id TEXT NOT NULL REFERENCES recommendations(id),
    decision        TEXT NOT NULL CHECK (decision IN ('following', 'passing')),
    reason          TEXT,
    reason_category TEXT,
    decided_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Trade outcomes (manually entered)
CREATE TABLE IF NOT EXISTS outcomes (
    id              TEXT PRIMARY KEY,
    decision_id     TEXT NOT NULL REFERENCES decisions(id),
    recommendation_id TEXT NOT NULL REFERENCES recommendations(id),
    ticker          TEXT NOT NULL,

    entry_price     REAL,
    exit_price      REAL,
    shares          INTEGER,
    pnl_dollars     REAL,
    pnl_percent     REAL,
    holding_days    INTEGER,
    exit_reason     TEXT,

    notes           TEXT,
    logged_at       DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Reflection summaries for self-learning
CREATE TABLE IF NOT EXISTS reflections (
    id              TEXT PRIMARY KEY,
    generated_at    DATETIME DEFAULT CURRENT_TIMESTAMP,

    recommendations_analyzed INTEGER,
    decisions_analyzed      INTEGER,
    outcomes_analyzed       INTEGER,
    date_range_start        DATETIME,
    date_range_end          DATETIME,

    summary_text    TEXT NOT NULL,
    injection_prompt TEXT NOT NULL,
    metrics         TEXT NOT NULL            -- JSON
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_strategy ON pipeline_runs(strategy_id);
CREATE INDEX IF NOT EXISTS idx_stage_outputs_run ON stage_outputs(run_id);
CREATE INDEX IF NOT EXISTS idx_stage_outputs_stage ON stage_outputs(stage);
CREATE INDEX IF NOT EXISTS idx_recommendations_run ON recommendations(run_id);
CREATE INDEX IF NOT EXISTS idx_recommendations_ticker ON recommendations(ticker);
CREATE INDEX IF NOT EXISTS idx_decisions_recommendation ON decisions(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_recommendation ON outcomes(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_ticker ON outcomes(ticker);
