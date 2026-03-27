-- Add user_id to reflections table for multi-tenant isolation
ALTER TABLE reflections ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'system';
CREATE INDEX IF NOT EXISTS idx_reflections_user ON reflections(user_id);
