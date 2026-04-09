-- Migration 021: Pre-GPT ML snapshot on recommendations (training / analytics joins)
-- Populated at pipeline time when an independent gate model is available.

ALTER TABLE recommendations
ADD COLUMN IF NOT EXISTS pre_gpt_ml_probability DOUBLE PRECISION DEFAULT NULL;

ALTER TABLE recommendations
ADD COLUMN IF NOT EXISTS pre_gpt_ml_direction TEXT DEFAULT NULL;
