-- Migration 017: Pipeline v2 schema additions
-- Adds NO_TRADE and WATCH to the action CHECK constraint,
-- adds track_agreement JSONB and confidence_adjustment TEXT columns
-- to the recommendations table.

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
