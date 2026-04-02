-- Migration 018: Signal freshness fields on recommendations
-- Adds three columns that track when a signal was generated and how long it
-- remains actionable, so the frontend can display staleness warnings.

ALTER TABLE recommendations
ADD COLUMN IF NOT EXISTS signal_generated_at TIMESTAMPTZ DEFAULT NULL;

ALTER TABLE recommendations
ADD COLUMN IF NOT EXISTS price_at_signal DOUBLE PRECISION DEFAULT NULL;

ALTER TABLE recommendations
ADD COLUMN IF NOT EXISTS entry_valid_window TEXT DEFAULT NULL;
