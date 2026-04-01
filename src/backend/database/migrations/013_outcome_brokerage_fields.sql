-- Add brokerage integration fields to outcomes table (all nullable for backward compatibility)
ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'manual';
ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS brokerage_order_id TEXT;
ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS commission REAL;
ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS fees REAL;
ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS currency TEXT;
ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS gross_pnl REAL;
ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS net_pnl REAL;
ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS entry_timestamp TIMESTAMPTZ;
ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS exit_timestamp TIMESTAMPTZ;
