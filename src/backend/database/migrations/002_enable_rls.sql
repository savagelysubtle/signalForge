-- Enable Row Level Security on all tables.
--
-- With RLS enabled and no policies defined, the public anon key has
-- zero access to any table. The Python backend uses the service_role
-- key which bypasses RLS, so backend operations are unaffected.
--
-- Run this migration against your Supabase Postgres instance if you
-- created the schema before RLS was added to 001_initial.sql.

ALTER TABLE strategies ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE stage_outputs ENABLE ROW LEVEL SECURITY;
ALTER TABLE chart_images ENABLE ROW LEVEL SECURITY;
ALTER TABLE recommendations ENABLE ROW LEVEL SECURITY;
ALTER TABLE decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE reflections ENABLE ROW LEVEL SECURITY;
