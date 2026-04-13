-- Migration 026: Confidence Engine v2
-- Adds split confidence fields for the new prior→boosters→calibrated architecture.
-- Keeps existing `confidence` column intact for backward compatibility.

ALTER TABLE recommendations
  ADD COLUMN IF NOT EXISTS win_probability REAL DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS setup_quality_score REAL DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS llm_conviction TEXT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS prior_base_rate REAL DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS confidence_v2 REAL DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS setup_type TEXT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS confidence_drivers JSONB DEFAULT NULL;
