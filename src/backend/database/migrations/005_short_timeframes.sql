-- Add short-timeframe columns to strategies table
-- Supports a separate indicator set for intraday timeframes (15m, 1H)

ALTER TABLE strategies
ADD COLUMN IF NOT EXISTS short_timeframes TEXT;

ALTER TABLE strategies
ADD COLUMN IF NOT EXISTS short_tf_indicators TEXT;
