-- Add additional_timeframes column to strategies table
-- Replaces the single secondary_timeframe with a JSON array of extra timeframes
-- e.g. '["1H", "4H", "D"]' allows analyzing multiple chart timeframes per ticker

ALTER TABLE strategies
ADD COLUMN IF NOT EXISTS additional_timeframes TEXT;

-- Migrate existing secondary_timeframe values into the new column
UPDATE strategies
SET additional_timeframes = '["' || secondary_timeframe || '"]'
WHERE additional_timeframes IS NULL
  AND secondary_timeframe IS NOT NULL;
