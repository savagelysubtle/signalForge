-- Add columns for the autonomous trade journal feature:
--   - last_synced_at on questrade_tokens for sync debouncing
--   - auto_confirmed on pending_matches to distinguish auto vs manual confirm
--   - auto_followed on decisions to track Questrade-initiated follows

ALTER TABLE questrade_tokens ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;

ALTER TABLE pending_matches ADD COLUMN IF NOT EXISTS auto_confirmed BOOLEAN DEFAULT FALSE;

ALTER TABLE decisions ADD COLUMN IF NOT EXISTS auto_followed BOOLEAN DEFAULT FALSE;
