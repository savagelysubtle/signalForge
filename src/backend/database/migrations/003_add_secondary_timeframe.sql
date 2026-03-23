-- Add secondary_timeframe column to strategies table
-- Allows each strategy to define a secondary chart timeframe (e.g., "1H", "15m")
-- Defaults to "4H" to match existing StrategyConfig behavior

ALTER TABLE strategies
ADD COLUMN IF NOT EXISTS secondary_timeframe TEXT NOT NULL DEFAULT '4H';
