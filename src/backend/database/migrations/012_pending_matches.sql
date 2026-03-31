-- Pending trade matches linking Questrade executions to SignalForge recommendations.
-- Matches stay "pending" until the user confirms or rejects them.

CREATE TABLE IF NOT EXISTS pending_matches (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    recommendation_id   TEXT NOT NULL,
    questrade_order_id  TEXT NOT NULL,
    ticker              TEXT NOT NULL,
    side                TEXT NOT NULL,
    avg_price           REAL NOT NULL,
    total_shares        INTEGER NOT NULL,
    total_commission    REAL DEFAULT 0,
    currency            TEXT DEFAULT 'CAD',
    executed_at         TIMESTAMPTZ NOT NULL,
    match_score         REAL NOT NULL,
    match_reason        TEXT,
    status              TEXT DEFAULT 'pending',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pending_matches_user ON pending_matches(user_id);
CREATE INDEX IF NOT EXISTS idx_pending_matches_status ON pending_matches(user_id, status);
