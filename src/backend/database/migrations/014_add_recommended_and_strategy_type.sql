-- 014: Add recommended and strategy_type columns to strategies

ALTER TABLE strategies ADD COLUMN IF NOT EXISTS recommended BOOLEAN DEFAULT FALSE;
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS strategy_type TEXT DEFAULT 'swing';
