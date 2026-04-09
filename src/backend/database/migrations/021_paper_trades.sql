-- Automated paper tracking rows (T+1d / T+3d / T+5d price checks for signal quality)

CREATE TABLE paper_trades (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('BUY', 'SHORT')),
    entry_price REAL NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    strategy_name TEXT NOT NULL DEFAULT '',
    check_day INTEGER NOT NULL CHECK (check_day IN (1, 3, 5)),
    check_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'failed')),
    actual_price REAL,
    pnl_pct REAL,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_paper_trades_pending ON paper_trades (status, check_at)
    WHERE status = 'pending';
CREATE INDEX idx_paper_trades_user ON paper_trades (user_id);
CREATE INDEX idx_paper_trades_run ON paper_trades (run_id);

ALTER TABLE paper_trades ENABLE ROW LEVEL SECURITY;
