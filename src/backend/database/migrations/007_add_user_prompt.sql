-- Migration 007: Add user_prompt column to pipeline_runs
-- Stores the free-form user prompt when pipeline is run in "prompt" mode.

ALTER TABLE pipeline_runs
ADD COLUMN IF NOT EXISTS user_prompt TEXT;
