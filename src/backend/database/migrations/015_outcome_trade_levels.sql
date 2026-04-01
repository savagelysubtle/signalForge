-- Add user-defined stop loss and take profit levels to outcomes.
-- These track the actual trade management levels the user set,
-- which may differ from the recommendation's suggested levels.

ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS stop_loss REAL;
ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS take_profit REAL;
