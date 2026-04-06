-- 020_heartbeat_scanner.sql
-- Market Heartbeat + Strategy Scanner tables

-- MARKET STATE (singleton row, always upserted)
CREATE TABLE IF NOT EXISTS market_state (
    id TEXT PRIMARY KEY DEFAULT 'singleton',

    -- VIX
    vix_spot FLOAT,
    vix_3m FLOAT,
    vix_structure TEXT,
    vix_percentile_1y FLOAT,
    vix_estimate TEXT,

    -- Regime (replaces Perplexity output)
    regime_type TEXT,
    regime_confidence FLOAT,
    breadth_estimate TEXT,
    breadth_score FLOAT,
    dominant_sectors JSONB DEFAULT '[]',
    defensive_rotation BOOLEAN DEFAULT FALSE,
    summary TEXT DEFAULT '',
    implications TEXT DEFAULT '',

    -- Put/Call ratio
    pc_ratio FLOAT,
    pc_ratio_5d_avg FLOAT,
    pc_signal TEXT,

    -- SPY / Market
    spy_price FLOAT,
    spy_above_50ma BOOLEAN,
    spy_above_200ma BOOLEAN,
    spy_5d_return FLOAT,
    spy_20d_return FLOAT,

    -- Sector rotation
    leading_sectors JSONB DEFAULT '[]',
    lagging_sectors JSONB DEFAULT '[]',
    sector_scores JSONB DEFAULT '{}',

    -- Session context
    market_session TEXT,
    next_macro_event TEXT,

    -- HMM
    hmm_regime TEXT,
    hmm_probs JSONB DEFAULT '{}',

    -- Metadata
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    fast_refresh_at TIMESTAMPTZ,
    slow_refresh_at TIMESTAMPTZ
);

-- SCANNER RESULTS (one row per ticker+strategy per scan)
CREATE TABLE IF NOT EXISTS scanner_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_run_id TEXT NOT NULL,
    scanned_at TIMESTAMPTZ DEFAULT NOW(),
    strategy_type TEXT NOT NULL,
    ticker TEXT NOT NULL,

    -- Scores
    rule_score FLOAT,
    ml_probability FLOAT,
    ml_model_version TEXT,
    combined_score FLOAT,

    -- Context at scan time
    regime_type TEXT,
    vix_spot FLOAT,

    -- Rule match detail
    matched_rules JSONB DEFAULT '[]',
    rule_details JSONB DEFAULT '{}',

    -- Technical snapshot at scan time
    rsi FLOAT,
    ema_alignment TEXT,
    volume_ratio FLOAT,
    momentum_score FLOAT,
    atr_pct FLOAT,

    -- Flags
    earnings_within_5d BOOLEAN DEFAULT FALSE,
    promoted_to_pipeline BOOLEAN DEFAULT FALSE,
    promoted_at TIMESTAMPTZ,
    promoted_run_id TEXT,

    UNIQUE(scan_run_id, strategy_type, ticker)
);

-- SCAN RUNS (one row per scanner execution)
CREATE TABLE IF NOT EXISTS scan_runs (
    id TEXT PRIMARY KEY,
    triggered_by TEXT,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_seconds FLOAT,
    universe_size INT,
    setups_found INT,
    strategies_with_setups JSONB DEFAULT '{}',
    regime_type TEXT,
    status TEXT DEFAULT 'running'
);

-- INDEXES
CREATE INDEX IF NOT EXISTS idx_scanner_results_scanned_at
    ON scanner_results(scanned_at DESC);
CREATE INDEX IF NOT EXISTS idx_scanner_results_strategy
    ON scanner_results(strategy_type, combined_score DESC);
CREATE INDEX IF NOT EXISTS idx_scanner_results_scan_run
    ON scanner_results(scan_run_id);
CREATE INDEX IF NOT EXISTS idx_scan_runs_started
    ON scan_runs(started_at DESC);

-- ROW LEVEL SECURITY
ALTER TABLE market_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE scanner_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE scan_runs ENABLE ROW LEVEL SECURITY;
