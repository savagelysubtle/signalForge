-- Migration 010: Rename action value SELL -> SHORT in recommendations table
-- "SELL" was semantically incorrect for a tool that identifies shorting opportunities.
-- Existing rows are migrated; constraint is updated to allow 'SHORT' instead of 'SELL'.
-- NOTE: Constraint must be dropped BEFORE the UPDATE to allow the new value.

-- Step 1: Drop the old check constraint first
ALTER TABLE recommendations
DROP CONSTRAINT IF EXISTS recommendations_action_check;

-- Step 2: Migrate existing data
UPDATE recommendations
SET action = 'SHORT'
WHERE action = 'SELL';

-- Step 3: Add the updated constraint
ALTER TABLE recommendations
ADD CONSTRAINT recommendations_action_check
CHECK (action IN ('BUY', 'SHORT', 'HOLD'));
