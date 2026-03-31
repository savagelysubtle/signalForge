-- Questrade OAuth token storage for brokerage integration.
-- Refresh tokens are single-use; every exchange invalidates the old one.
-- The api_server URL changes on each refresh and is the base for all API calls.

CREATE TABLE IF NOT EXISTS questrade_tokens (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL UNIQUE,
    refresh_token   TEXT NOT NULL,
    access_token    TEXT,
    api_server      TEXT,
    account_id      TEXT,
    account_type    TEXT,
    expires_at      TIMESTAMPTZ,
    is_practice     BOOLEAN DEFAULT FALSE,
    connected_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_questrade_tokens_user ON questrade_tokens(user_id);
