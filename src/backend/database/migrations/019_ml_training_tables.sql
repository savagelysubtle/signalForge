-- Migration 019: ML Training & Inference Tables
-- Adds tables shared between the training pipeline and live inference:
--   - feature_snapshots: ML feature vectors from live runs
--   - ml_models: Model registry with versioning and judge verdicts
--   - ml_judge_reports: Judge evaluation results per model version
--   - ml_shadow_predictions: Shadow mode prediction logs (ML vs GPT)

-- =========================================================================
-- feature_snapshots — one row per (ticker, date, strategy_type, timeframe)
-- Written by live pipeline at signal time, read by training for retraining
-- =========================================================================
CREATE TABLE IF NOT EXISTS feature_snapshots (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    snapshot_date   TIMESTAMPTZ NOT NULL,
    strategy_type   TEXT NOT NULL,
    timeframe       TEXT NOT NULL DEFAULT 'D',
    features        JSONB NOT NULL DEFAULT '{}',

    -- Outcome columns (filled in after holding period expires)
    return_5d       DOUBLE PRECISION,
    return_10d      DOUBLE PRECISION,
    return_20d      DOUBLE PRECISION,
    direction_5d    TEXT CHECK (direction_5d IN ('UP', 'DOWN', 'FLAT')),
    direction_10d   TEXT CHECK (direction_10d IN ('UP', 'DOWN', 'FLAT')),
    direction_20d   TEXT CHECK (direction_20d IN ('UP', 'DOWN', 'FLAT')),
    max_favorable_excursion   DOUBLE PRECISION,
    max_adverse_excursion     DOUBLE PRECISION,
    stop_hit        BOOLEAN,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feature_snapshots_ticker_date
    ON feature_snapshots (ticker, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_feature_snapshots_strategy
    ON feature_snapshots (strategy_type, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_feature_snapshots_user
    ON feature_snapshots (user_id);

-- =========================================================================
-- ml_models — model registry with version, metrics, judge verdict
-- Written by training pipeline, read by live inference for model loading
-- =========================================================================
CREATE TABLE IF NOT EXISTS ml_models (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    model_version   TEXT NOT NULL,
    training_date   TIMESTAMPTZ NOT NULL,
    artifact_path   TEXT NOT NULL,

    -- Training configuration
    training_config JSONB NOT NULL DEFAULT '{}',
    feature_names   JSONB NOT NULL DEFAULT '[]',

    -- Performance metrics
    metrics         JSONB NOT NULL DEFAULT '{}',
    overall_accuracy DOUBLE PRECISION,
    brier_score     DOUBLE PRECISION,
    information_coefficient DOUBLE PRECISION,

    -- Judge evaluation
    judge_verdict   TEXT CHECK (judge_verdict IN ('PASS', 'CONDITIONAL_PASS', 'FAIL')),
    approved_strategies JSONB DEFAULT '[]',

    -- Status
    status          TEXT NOT NULL DEFAULT 'trained'
                    CHECK (status IN ('trained', 'evaluated', 'shadow', 'active', 'retired')),
    is_active       BOOLEAN NOT NULL DEFAULT FALSE,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ml_models_version
    ON ml_models (model_version);
CREATE INDEX IF NOT EXISTS idx_ml_models_status
    ON ml_models (status);
CREATE INDEX IF NOT EXISTS idx_ml_models_user
    ON ml_models (user_id);

-- =========================================================================
-- ml_judge_reports — judge evaluation results per model version
-- Written by training pipeline, read by ML dashboard
-- =========================================================================
CREATE TABLE IF NOT EXISTS ml_judge_reports (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    model_version   TEXT NOT NULL,
    judge_verdict   TEXT NOT NULL CHECK (judge_verdict IN ('PASS', 'CONDITIONAL_PASS', 'FAIL')),
    report          JSONB NOT NULL DEFAULT '{}',

    -- Key metrics (denormalized for fast queries)
    overall_accuracy    DOUBLE PRECISION,
    ece                 DOUBLE PRECISION,
    drift_status        TEXT CHECK (drift_status IN ('healthy', 'warning', 'caution', 'quarantine')),
    overfit_risk        TEXT CHECK (overfit_risk IN ('low', 'medium', 'high')),

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ml_judge_reports_version
    ON ml_judge_reports (model_version);
CREATE INDEX IF NOT EXISTS idx_ml_judge_reports_user
    ON ml_judge_reports (user_id);

-- =========================================================================
-- ml_shadow_predictions — shadow mode logs for ML vs GPT comparison
-- Written by live pipeline in shadow mode, read by dashboard
-- =========================================================================
CREATE TABLE IF NOT EXISTS ml_shadow_predictions (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    strategy_type   TEXT NOT NULL,
    prediction_date TIMESTAMPTZ NOT NULL,

    -- ML prediction
    ml_prediction   JSONB NOT NULL DEFAULT '{}',
    ml_direction    TEXT CHECK (ml_direction IN ('UP', 'DOWN', 'FLAT')),
    ml_confidence   DOUBLE PRECISION,
    ml_reliability  DOUBLE PRECISION,

    -- GPT prediction (for comparison)
    gpt_prediction  JSONB NOT NULL DEFAULT '{}',
    gpt_action      TEXT,
    gpt_confidence  DOUBLE PRECISION,

    -- Model info
    model_version   TEXT NOT NULL,

    -- Outcome (filled in later)
    actual_direction TEXT CHECK (actual_direction IN ('UP', 'DOWN', 'FLAT')),
    actual_return_5d  DOUBLE PRECISION,
    actual_return_10d DOUBLE PRECISION,
    ml_correct       BOOLEAN,
    gpt_correct      BOOLEAN,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ml_shadow_ticker_date
    ON ml_shadow_predictions (ticker, prediction_date);
CREATE INDEX IF NOT EXISTS idx_ml_shadow_run
    ON ml_shadow_predictions (run_id);
CREATE INDEX IF NOT EXISTS idx_ml_shadow_user
    ON ml_shadow_predictions (user_id);

-- =========================================================================
-- RLS policies (consistent with existing tables)
-- =========================================================================
ALTER TABLE feature_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE ml_models ENABLE ROW LEVEL SECURITY;
ALTER TABLE ml_judge_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE ml_shadow_predictions ENABLE ROW LEVEL SECURITY;

CREATE POLICY feature_snapshots_user_policy ON feature_snapshots
    FOR ALL USING (auth.uid()::text = user_id);
CREATE POLICY ml_models_user_policy ON ml_models
    FOR ALL USING (auth.uid()::text = user_id);
CREATE POLICY ml_judge_reports_user_policy ON ml_judge_reports
    FOR ALL USING (auth.uid()::text = user_id);
CREATE POLICY ml_shadow_predictions_user_policy ON ml_shadow_predictions
    FOR ALL USING (auth.uid()::text = user_id);
