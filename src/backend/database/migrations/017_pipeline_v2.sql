-- Migration 017: Pipeline v2 schema additions
-- Phase 3: Adds NO_TRADE and WATCH to the action CHECK constraint,
--           adds track_agreement JSONB and confidence_adjustment TEXT columns
--           to the recommendations table.
-- Phase 6: Adds failure_mode, structured_analysis, slippage, and timing
--           columns to outcomes; adds pattern_statistics to reflections.

-- =========================================================================
-- Phase 3: Recommendation action expansion + track agreement
-- =========================================================================

-- Step 1: Drop the existing check constraint
ALTER TABLE recommendations
DROP CONSTRAINT IF EXISTS recommendations_action_check;

-- Step 2: Add the updated constraint with new action values
ALTER TABLE recommendations
ADD CONSTRAINT recommendations_action_check
CHECK (action IN ('BUY', 'SHORT', 'HOLD', 'NO_TRADE', 'WATCH'));

-- Step 3: Add track agreement column (JSONB for the TrackAgreement model)
ALTER TABLE recommendations
ADD COLUMN IF NOT EXISTS track_agreement JSONB DEFAULT NULL;

-- Step 4: Add confidence adjustment column
ALTER TABLE recommendations
ADD COLUMN IF NOT EXISTS confidence_adjustment TEXT DEFAULT '';

-- =========================================================================
-- Phase 6: Feedback loop enhancement — outcomes enrichment
-- =========================================================================

-- Step 5: Add failure mode classification to outcomes
ALTER TABLE outcomes
ADD COLUMN IF NOT EXISTS failure_mode TEXT DEFAULT NULL;

-- Step 6: Add structured analysis JSONB (StructuredOutcomeAnalysis)
ALTER TABLE outcomes
ADD COLUMN IF NOT EXISTS structured_analysis JSONB DEFAULT NULL;

-- Step 7: Add slippage tracking (signal price vs actual fill)
ALTER TABLE outcomes
ADD COLUMN IF NOT EXISTS slippage_pct DOUBLE PRECISION DEFAULT NULL;

-- Step 8: Add time-to-execution tracking (signal → trade, in minutes)
ALTER TABLE outcomes
ADD COLUMN IF NOT EXISTS time_to_execution_minutes DOUBLE PRECISION DEFAULT NULL;

-- =========================================================================
-- Phase 6: Feedback loop enhancement — reflections enrichment
-- =========================================================================

-- Step 9: Add pattern statistics JSONB to reflections
-- Stores track agreement win rates, EMA cross age stats, failure mode
-- frequencies, and other v2 analytics computed during reflection generation.
ALTER TABLE reflections
ADD COLUMN IF NOT EXISTS pattern_statistics JSONB DEFAULT NULL;
