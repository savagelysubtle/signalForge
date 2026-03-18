-- Add 'prompt' to the allowed pipeline_runs.mode values.
-- SQLite does not support ALTER CHECK, so we recreate the table.

PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS pipeline_runs_new (
    id              TEXT PRIMARY KEY,
    strategy_id     TEXT REFERENCES strategies(id),
    mode            TEXT NOT NULL CHECK (mode IN ('discovery', 'analysis', 'combined', 'prompt')),
    manual_tickers  TEXT,
    status          TEXT NOT NULL DEFAULT 'running',

    started_at      DATETIME NOT NULL,
    completed_at    DATETIME,
    duration_seconds REAL,

    prompt_versions TEXT,
    stage_errors    TEXT
);

INSERT OR IGNORE INTO pipeline_runs_new
    SELECT * FROM pipeline_runs;

DROP TABLE IF EXISTS pipeline_runs;

ALTER TABLE pipeline_runs_new RENAME TO pipeline_runs;

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_strategy ON pipeline_runs(strategy_id);

PRAGMA foreign_keys = ON;
