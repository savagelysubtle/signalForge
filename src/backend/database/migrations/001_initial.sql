-- SignalForge initial schema (PostgreSQL with multi-tenancy)
-- All tables use TEXT UUIDs as primary keys (uuid.uuid4().hex)
-- Multi-tenant: user_id added to top-level tables for data isolation
-- System templates use user_id = 'system'

-- Strategy definitions
CREATE TABLE strategies (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
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
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    run_count       INTEGER DEFAULT 0,
    is_template     BOOLEAN DEFAULT FALSE,

    -- Unique constraint per user (templates can share names across users)
    UNIQUE (user_id, name)
);

-- Pipeline run history
CREATE TABLE pipeline_runs (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    strategy_id     TEXT REFERENCES strategies(id),
    mode            TEXT NOT NULL CHECK (mode IN ('discovery', 'analysis', 'combined', 'prompt')),
    manual_tickers  TEXT,                   -- JSON array
    status          TEXT NOT NULL DEFAULT 'running',

    started_at      TIMESTAMPTZ NOT NULL,
    completed_at    TIMESTAMPTZ,
    duration_seconds REAL,

    prompt_versions TEXT,                   -- JSON: {"perplexity": "abc123", ...}
    stage_errors    TEXT                    -- JSON array of error objects
);

-- Raw LLM stage outputs (debugging and replay)
-- Inherits user scope through pipeline_runs foreign key
CREATE TABLE stage_outputs (
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

    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Chart images
-- Inherits user scope through pipeline_runs foreign key
CREATE TABLE chart_images (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES pipeline_runs(id),
    ticker          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    indicators      TEXT NOT NULL,           -- JSON array
    image_path      TEXT NOT NULL,
    image_hash      TEXT,
    source_url      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Final recommendations
CREATE TABLE recommendations (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES pipeline_runs(id),
    user_id         TEXT NOT NULL,
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

    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- User decisions on recommendations
CREATE TABLE decisions (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    recommendation_id TEXT NOT NULL REFERENCES recommendations(id),
    decision        TEXT NOT NULL CHECK (decision IN ('following', 'passing')),
    reason          TEXT,
    reason_category TEXT,
    decided_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Trade outcomes (manually entered)
CREATE TABLE outcomes (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
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
    logged_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Reflection summaries for self-learning
-- Inherits user scope through outcomes/decisions foreign keys
CREATE TABLE reflections (
    id              TEXT PRIMARY KEY,
    generated_at    TIMESTAMPTZ DEFAULT NOW(),

    recommendations_analyzed INTEGER,
    decisions_analyzed      INTEGER,
    outcomes_analyzed       INTEGER,
    date_range_start        TIMESTAMPTZ,
    date_range_end          TIMESTAMPTZ,

    summary_text    TEXT NOT NULL,
    injection_prompt TEXT NOT NULL,
    metrics         TEXT NOT NULL            -- JSON
);

-- Row Level Security: block direct access via the public anon key.
-- The Python backend uses the service_role key which bypasses RLS,
-- so no policies are needed — RLS-on with zero policies = full deny
-- for any client using the anon key (i.e. the frontend JS client).
ALTER TABLE strategies ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE stage_outputs ENABLE ROW LEVEL SECURITY;
ALTER TABLE chart_images ENABLE ROW LEVEL SECURITY;
ALTER TABLE recommendations ENABLE ROW LEVEL SECURITY;
ALTER TABLE decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE reflections ENABLE ROW LEVEL SECURITY;

-- Indexes for foreign key relationships
CREATE INDEX idx_pipeline_runs_strategy ON pipeline_runs(strategy_id);
CREATE INDEX idx_stage_outputs_run ON stage_outputs(run_id);
CREATE INDEX idx_stage_outputs_stage ON stage_outputs(stage);
CREATE INDEX idx_recommendations_run ON recommendations(run_id);
CREATE INDEX idx_recommendations_ticker ON recommendations(ticker);
CREATE INDEX idx_decisions_recommendation ON decisions(recommendation_id);
CREATE INDEX idx_outcomes_recommendation ON outcomes(recommendation_id);
CREATE INDEX idx_outcomes_ticker ON outcomes(ticker);

-- Indexes for multi-tenancy (user_id filtering)
CREATE INDEX idx_strategies_user ON strategies(user_id);
CREATE INDEX idx_pipeline_runs_user ON pipeline_runs(user_id);
CREATE INDEX idx_recommendations_user ON recommendations(user_id);
CREATE INDEX idx_decisions_user ON decisions(user_id);
CREATE INDEX idx_outcomes_user ON outcomes(user_id);
