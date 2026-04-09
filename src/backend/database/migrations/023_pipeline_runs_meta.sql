-- 023: JSON meta blob on pipeline_runs (cost summary, scanner hints, etc.).

ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS meta TEXT;

COMMENT ON COLUMN pipeline_runs.meta IS
    'JSON object: e.g. cost totals from PipelineCostTracker, scanner_tickers_added, flags.';
