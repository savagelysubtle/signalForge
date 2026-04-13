-- Migration 024: Add raw_gpt_confidence to recommendations
-- The pipeline now stores the original GPT confidence before ML gate
-- and calibration adjustments modify it.

ALTER TABLE recommendations
    ADD COLUMN IF NOT EXISTS raw_gpt_confidence REAL DEFAULT NULL;

COMMENT ON COLUMN recommendations.raw_gpt_confidence IS
    'Original GPT confidence before ML gate / calibration adjustments.';
