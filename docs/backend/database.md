# Database Schema

> **Engine:** PostgreSQL (Railway addon in production, Supabase-hosted)
> **Client:** Supabase Python SDK (`supabase-py`, async client)
> **Source:** [`src/backend/database/`](../../src/backend/database/)

---

## Connection Management

**File:** [`database/connection.py`](../../src/backend/database/connection.py)

The database connection is a Supabase `AsyncClient` singleton created at
startup and closed at shutdown via FastAPI's lifespan.

| Function | Purpose |
|----------|---------|
| `init_db()` | Create the async Supabase client from `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` |
| `get_db()` | Return the singleton client (raises if not initialized) |
| `close_db()` | Close the client connection |

The backend uses the **service role key** which bypasses Row Level Security.
The backend enforces data isolation itself by filtering on `user_id` in
every query.

---

## Schema

All tables use **TEXT UUIDs** as primary keys (`uuid.uuid4().hex`).
Multi-tenant tables include a `user_id` column. System templates use
`user_id = 'system'`.

### Entity Relationship

```
strategies ─────────┐
                     │ strategy_id
                     ▼
pipeline_runs ──────┬──────────────────────┐
  │                 │ run_id               │ run_id
  │                 ▼                      ▼
  │         stage_outputs          recommendations
  │                                   │
  │                                   │ recommendation_id
  │         chart_images              ▼
  │         (run_id FK)           decisions
  │                                   │
  │                                   │ decision_id
  │                                   ▼
  │                               outcomes
  │
  └──────────────────────────── reflections (standalone)
```

---

### `strategies`

Strategy configurations that drive every pipeline stage.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | UUID hex |
| `user_id` | TEXT NOT NULL | Owner (`"system"` for templates) |
| `name` | TEXT NOT NULL | Unique per user |
| `description` | TEXT | |
| `screening_prompt` | TEXT NOT NULL | Natural language for Perplexity |
| `constraint_style` | TEXT | `"tight"` or `"loose"` |
| `max_tickers` | INTEGER | Default 10 |
| `chart_indicators` | TEXT | JSON array: `["RSI", "MACD"]` |
| `chart_timeframe` | TEXT | `"D"`, `"4H"`, `"W"`, etc. |
| `secondary_timeframe` | TEXT | Added in migration 003 |
| `additional_timeframes` | TEXT | JSON array, added in migration 004 |
| `short_timeframes` | TEXT | JSON array, added in migration 005 |
| `short_tf_indicators` | TEXT | JSON array, added in migration 005 |
| `ta_focus` | TEXT | Free-form technical focus |
| `news_recency` | TEXT | `"today"`, `"week"`, `"month"` |
| `news_scope` | TEXT | `"company"`, `"sector"`, `"macro"` |
| `trading_style` | TEXT | |
| `risk_params` | TEXT | JSON object |
| `enable_debate` | BOOLEAN | Default TRUE |
| `is_template` | BOOLEAN | Default FALSE |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |
| `run_count` | INTEGER | Default 0 (column exists; never incremented in code) |
| `fmp_screener` | TEXT | JSON: `FmpScreenerConfig`, added in migration 006 |

**Unique constraint:** `(user_id, name)`

---

### `pipeline_runs`

Tracks each pipeline execution.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | UUID hex (= `run_id`) |
| `user_id` | TEXT NOT NULL | |
| `strategy_id` | TEXT FK → strategies | Nullable |
| `mode` | TEXT NOT NULL | `discovery`, `analysis`, `combined`, `prompt` |
| `manual_tickers` | TEXT | JSON array |
| `status` | TEXT | `running`, `completed`, `partial`, `failed` |
| `started_at` | TIMESTAMPTZ | |
| `completed_at` | TIMESTAMPTZ | |
| `duration_seconds` | REAL | |
| `prompt_versions` | TEXT | JSON: `{"perplexity": "hash", ...}` |
| `stage_errors` | TEXT | JSON array of error objects |
| `user_prompt` | TEXT | Free-form text for `prompt` mode, added in migration 007 |

---

### `stage_outputs`

Raw LLM prompt/response pairs for debugging and replay.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | |
| `run_id` | TEXT FK → pipeline_runs | |
| `stage` | TEXT NOT NULL | `perplexity`, `gemini`, `claude`, `gpt` |
| `ticker` | TEXT | Nullable (Perplexity has no per-ticker output) |
| `prompt_text` | TEXT | Full prompt sent to the LLM |
| `raw_response` | TEXT | Raw LLM response |
| `parsed_output` | TEXT | Error message on failure |
| `model_used` | TEXT | |
| `tokens_in` | INTEGER | |
| `tokens_out` | INTEGER | |
| `cost_estimate` | REAL | |
| `duration_ms` | INTEGER | |
| `status` | TEXT | `success`, `api_error`, `validation_failed` |
| `retry_count` | INTEGER | |
| `created_at` | TIMESTAMPTZ | |

---

### `chart_images`

Metadata for fetched chart images.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | |
| `run_id` | TEXT FK → pipeline_runs | |
| `ticker` | TEXT NOT NULL | |
| `timeframe` | TEXT NOT NULL | |
| `indicators` | TEXT | JSON array |
| `image_path` | TEXT NOT NULL | Supabase Storage URL |
| `image_hash` | TEXT | |
| `source_url` | TEXT | |
| `created_at` | TIMESTAMPTZ | |

---

### `recommendations`

Final trade recommendations from the GPT judge.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | |
| `run_id` | TEXT FK → pipeline_runs | |
| `user_id` | TEXT NOT NULL | |
| `ticker` | TEXT NOT NULL | |
| `action` | TEXT | `BUY`, `SHORT`, `HOLD` (migration 010 renamed SELL → SHORT) |
| `confidence` | REAL | 0.0–1.0 |
| `entry_price` | REAL | |
| `stop_loss` | REAL | |
| `take_profit` | REAL | |
| `position_size_pct` | REAL | |
| `risk_reward_ratio` | REAL | |
| `holding_period` | TEXT | |
| `bull_case` | TEXT | JSON: `DebateCase` |
| `bear_case` | TEXT | JSON: `DebateCase` |
| `judge_reasoning` | TEXT | |
| `key_factors` | TEXT | JSON array |
| `warnings` | TEXT | JSON array |
| `created_at` | TIMESTAMPTZ | |

---

### `decisions`

User decisions on whether to follow a recommendation.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | |
| `user_id` | TEXT NOT NULL | |
| `recommendation_id` | TEXT FK → recommendations | |
| `decision` | TEXT | `following` or `passing` |
| `reason` | TEXT | |
| `reason_category` | TEXT | |
| `decided_at` | TIMESTAMPTZ | |

---

### `outcomes`

Manually logged trade outcomes for the self-learning loop.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | |
| `user_id` | TEXT NOT NULL | |
| `decision_id` | TEXT FK → decisions | |
| `recommendation_id` | TEXT FK → recommendations | |
| `ticker` | TEXT NOT NULL | |
| `entry_price` | REAL | |
| `exit_price` | REAL | |
| `shares` | INTEGER | |
| `pnl_dollars` | REAL | |
| `pnl_percent` | REAL | |
| `holding_days` | INTEGER | |
| `exit_reason` | TEXT | |
| `notes` | TEXT | |
| `logged_at` | TIMESTAMPTZ | |

---

### `reflections`

Self-learning summaries generated from outcome analysis.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | |
| `user_id` | TEXT NOT NULL | Added in migration 008 (`DEFAULT 'system'`) |
| `generated_at` | TIMESTAMPTZ | |
| `recommendations_analyzed` | INTEGER | |
| `decisions_analyzed` | INTEGER | |
| `outcomes_analyzed` | INTEGER | |
| `date_range_start` | TIMESTAMPTZ | |
| `date_range_end` | TIMESTAMPTZ | |
| `summary_text` | TEXT | Human-readable (Insights view) |
| `injection_prompt` | TEXT | Prepended to GPT judge prompt |
| `metrics` | TEXT | JSON with performance stats |

---

## Row Level Security

RLS is enabled on **all tables**. However, no RLS policies are defined.
This means:

- **Anon key** (used by the frontend Supabase JS client for auth only) →
  **full deny** on all tables
- **Service role key** (used by the Python backend) → **bypasses RLS**

The backend enforces data isolation by filtering on `user_id` in every
query. This is a deliberate design choice: auth goes through the backend
API, never directly to the database from the frontend.

---

## Migrations

SQL migrations are stored in
[`database/migrations/`](../../src/backend/database/migrations/):

| File | Purpose |
|------|---------|
| `001_initial.sql` | Full schema: all 8 tables, indexes, RLS |
| `002_enable_rls.sql` | Ensure RLS is enabled (idempotent) |
| `003_add_secondary_timeframe.sql` | Add `secondary_timeframe` to strategies |
| `004_additional_timeframes.sql` | Add `additional_timeframes` JSON column |
| `005_short_timeframes.sql` | Add `short_timeframes` and `short_tf_indicators` |
| `006_add_fmp_screener.sql` | Add `fmp_screener` JSON column to strategies |
| `007_add_user_prompt.sql` | Add `user_prompt` TEXT to pipeline_runs |
| `008_add_user_id_to_reflections.sql` | Add `user_id` to reflections for multi-tenant isolation |
| `009_add_atr_to_chart_indicators.sql` | ATR metadata in chart indicators |
| `010_rename_sell_to_short.sql` | Rename `SELL` → `SHORT` in recommendations.action |

Migrations are applied manually via the Supabase SQL editor or CLI.
There is no automated migration runner yet.

---

## Indexes

The schema includes indexes for:

- **Foreign keys** — `pipeline_runs.strategy_id`, `stage_outputs.run_id`,
  `recommendations.run_id`, etc.
- **Query patterns** — `stage_outputs.stage`, `recommendations.ticker`,
  `outcomes.ticker`
- **Multi-tenancy** — `user_id` on strategies, pipeline_runs,
  recommendations, decisions, outcomes
