-- Add FMP screener configuration column to strategies table.
-- Stores JSON config for the Financial Modeling Prep pre-screening stage.
-- NULL means FMP screening is disabled for that strategy.

ALTER TABLE strategies ADD COLUMN IF NOT EXISTS fmp_screener TEXT;
