-- Add expected_value column to recommendations
-- EV = confidence * R:R - (1 - confidence)
ALTER TABLE recommendations
ADD COLUMN IF NOT EXISTS expected_value REAL DEFAULT NULL;
