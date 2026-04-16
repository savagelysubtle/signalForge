---
name: Phase 5 — Self-Learning Feedback Loop (Backend First)
overview: |
  Build the backend API layer and reflection generation engine for SignalForge's self-learning loop. Users record trade decisions (following/passing) and outcomes (what actually happened), and the system generates performance-aware injection prompts that calibrate GPT's future recommendations. Database schema and pipeline injection point already exist — this plan adds the API endpoints, Pydantic models, and reflection engine.
todos:
  - id: pydantic-models
    content:
      Add feedback Pydantic models to schemas.py (DecisionCreate, OutcomeCreate,
      DecisionResponse, OutcomeResponse, ReflectionResponse,
      PerformanceOverview) + add id field to Recommendation
    status: pending
  - id: migration-reflection-userid
    content:
      Create migration 006_add_reflection_user_id.sql to add user_id column to
      reflections table
    status: pending
  - id: decisions-router
    content:
      Create api/decisions.py with POST decision, GET list, GET single endpoints
    status: pending
  - id: outcomes-router
    content: Create api/outcomes.py with POST outcome, GET list endpoints
    status: pending
  - id: reflections-router
    content:
      Create api/reflections.py with POST reflect, GET latest, GET overview
      endpoints
    status: pending
  - id: reflection-engine
    content:
      Expand services/reflection.py with generate_reflection() — metrics
      computation, template data section, LLM strategic advice, store to DB
    status: pending
  - id: wire-up
    content:
      Register 3 new routers in main.py, update orchestrator to pass user_id to
      load_reflection_context()
    status: pending
  - id: quality-check
    content: Run ruff format, ruff check, ty check — fix any issues
    status: pending
isProject: false
---

# Phase 5: Self-Learning Feedback Loop — Backend First

## Problem

SignalForge's pipeline produces recommendations but has no way to close the
feedback loop. The user cannot record whether they followed a recommendation,
log the trade outcome, or have the system learn from its track record. Without
this, the GPT judge operates blind — it can't know that it's been overconfident
in biotech, or that its SELL signals have a 30% accuracy rate.

The database tables (`decisions`, `outcomes`, `reflections`) and the pipeline
injection point (GPT judge reads `reflection_context` via
`build_judge_prompt()`) already exist. What's missing is everything that
**populates** those tables and exposes them via API.

## Solution

Build the backend API layer and reflection generation engine. The Insights tab
(frontend, follow-up plan) will be the central hub where users record decisions,
log outcomes, and view performance — but the backend comes first so it can be
tested independently.

**Hybrid reflection approach:** Pure Python string formatting for the data/stats
section (deterministic, free), plus an LLM call for a strategic self-advice
paragraph (nuanced pattern recognition that templates can't capture).

## What Already Exists

| Component                                    | File                                                                  | Status                        |
| -------------------------------------------- | --------------------------------------------------------------------- | ----------------------------- |
| DB tables (decisions, outcomes, reflections) | `database/migrations/001_initial.sql`                                 | Complete                      |
| Reflection loader                            | `services/reflection.py` → `load_reflection_context()`                | Complete (read-only)          |
| Pipeline injection                           | `pipeline/orchestrator.py:227` → `pipeline/prompts/gpt_debate.py:440` | Complete                      |
| Recommendation model                         | `pipeline/schemas.py:133` → `class Recommendation`                    | Complete (missing `id` field) |
| InsightsView placeholder                     | `src/frontend/src/views/InsightsView.tsx`                             | Stub ("Coming in Phase 5")    |

---

## Implementation Steps

### Step 1: pydantic-models

**File:** `[src/backend/pipeline/schemas.py](src/backend/pipeline/schemas.py)`
(append after existing models)

Add feedback loop models:

```python
# --- Feedback Loop (Phase 5) ---

class DecisionCreate(BaseModel):
    """Request body for recording a decision on a recommendation."""
    decision: Literal["following", "passing"]
    reason: str = ""
    reason_category: str = ""  # "risk_too_high", "timing", "conviction", etc.

class DecisionResponse(BaseModel):
    """Decision record returned from the API."""
    id: str
    user_id: str
    recommendation_id: str
    decision: Literal["following", "passing"]
    reason: str = ""
    reason_category: str = ""
    decided_at: str  # ISO 8601
    # Denormalized from recommendation for list views
    ticker: str = ""
    action: str = ""
    confidence: float = 0.0

class OutcomeCreate(BaseModel):
    """Request body for logging a trade outcome."""
    entry_price: float | None = None
    exit_price: float | None = None
    shares: int | None = None
    pnl_dollars: float | None = None
    pnl_percent: float | None = None
    holding_days: int | None = None
    exit_reason: str = ""  # "hit_target", "hit_stop", "manual_exit", "time_exit"
    notes: str = ""

class OutcomeResponse(BaseModel):
    """Outcome record returned from the API."""
    id: str
    user_id: str
    decision_id: str
    recommendation_id: str
    ticker: str
    entry_price: float | None = None
    exit_price: float | None = None
    shares: int | None = None
    pnl_dollars: float | None = None
    pnl_percent: float | None = None
    holding_days: int | None = None
    exit_reason: str = ""
    notes: str = ""
    logged_at: str

class ReflectionResponse(BaseModel):
    """Reflection summary returned from the API."""
    id: str
    generated_at: str
    recommendations_analyzed: int
    decisions_analyzed: int
    outcomes_analyzed: int
    date_range_start: str | None
    date_range_end: str | None
    summary_text: str
    injection_prompt: str
    metrics: dict

class PerformanceOverview(BaseModel):
    """Aggregated performance metrics for the insights dashboard."""
    total_recommendations: int = 0
    total_decisions: int = 0
    total_following: int = 0
    total_passing: int = 0
    total_outcomes: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    win_rate: float | None = None
    total_pnl_dollars: float = 0.0
    avg_pnl_percent: float | None = None
    avg_holding_days: float | None = None
    best_trade: dict | None = None
    worst_trade: dict | None = None
    confidence_calibration: list[dict] = Field(default_factory=list)
```

Also add `id: str = ""` to existing `Recommendation` model (line 133). Default
empty so LLM parsing is unaffected; populated when loading from DB via
`_load_recommendations()`.

### Step 2: migration-reflection-userid

**New file:**
`[src/backend/database/migrations/006_add_reflection_user_id.sql](src/backend/database/migrations/006_add_reflection_user_id.sql)`

```sql
ALTER TABLE reflections ADD COLUMN user_id TEXT NOT NULL DEFAULT 'system';
CREATE INDEX idx_reflections_user ON reflections(user_id);
```

### Step 3: decisions-router

**New file:** `[src/backend/api/decisions.py](src/backend/api/decisions.py)`

Follow pattern from `[api/pipeline.py](src/backend/api/pipeline.py)` (uses
`CurrentUser` dependency, `get_db()` Supabase client).

Endpoints:

`**POST /api/recommendations/{recommendation_id}/decision`

- Auth: `CurrentUser`
- Body: `DecisionCreate`
- Logic: Verify recommendation exists and belongs to user. Check no existing
  decision (prevent doubles). Insert into `decisions` with `uuid4().hex`.
  Denormalize ticker/action/confidence from recommendation into response.
- Returns: `DecisionResponse`

`**GET /api/decisions`

- Auth: `CurrentUser`
- Params: `limit=50`, `offset=0`, `decision_filter` (optional:
  "following"/"passing")
- Logic: Query decisions filtered by user_id, join with recommendations for
  denormalized fields
- Returns: `list[DecisionResponse]`

`**GET /api/decisions/{decision_id}`

- Auth: `CurrentUser`
- Returns: `DecisionResponse`

### Step 4: outcomes-router

**New file:** `[src/backend/api/outcomes.py](src/backend/api/outcomes.py)`

`**POST /api/decisions/{decision_id}/outcome`

- Auth: `CurrentUser`
- Body: `OutcomeCreate`
- Logic: Verify decision exists, belongs to user, and is "following" (can't log
  outcomes for passes). Check no existing outcome. Look up `recommendation_id`
  and `ticker` from the decision. Insert into `outcomes`.
- Returns: `OutcomeResponse`

`**GET /api/outcomes`

- Auth: `CurrentUser`
- Params: `limit=50`, `offset=0`
- Returns: `list[OutcomeResponse]`

### Step 5: reflections-router

**New file:** `[src/backend/api/reflections.py](src/backend/api/reflections.py)`

`**POST /api/insights/reflect`

- Auth: `CurrentUser`
- Logic: Check minimum 5 outcomes exist. Call `generate_reflection(user_id)`.
- Returns: `ReflectionResponse`

`**GET /api/reflections/latest`

- Auth: `CurrentUser`
- Logic: Query reflections table, filter by user_id, order by generated_at desc,
  limit 1
- Returns: `ReflectionResponse` (404 if none)

`**GET /api/insights/overview`

- Auth: `CurrentUser`
- Logic: Aggregate query across decisions + outcomes + recommendations
- Returns: `PerformanceOverview`

### Step 6: reflection-engine

**File:**
`[src/backend/services/reflection.py](src/backend/services/reflection.py)`
(major expansion)

Add `generate_reflection(user_id: str) -> ReflectionResponse`:

**Phase 1 — Query:** Fetch all decisions, outcomes, and linked recommendations
for the user.

**Phase 2 — Metrics (pure Python):**

```python
def _compute_metrics(outcomes, decisions, recommendations) -> dict:
    # Win/loss/breakeven counts
    # Win rate
    # Total and average P&L
    # Confidence calibration buckets:
    #   High (>0.75), Medium (0.55-0.75), Low (<0.55)
    #   For each: actual win rate vs expected (avg confidence in bucket)
    # Action accuracy: BUY vs SELL win rates
    # Holding period stats
    # Best/worst trades
```

**Phase 3 — Data section (pure Python template):**

```
=== PERFORMANCE DATA (N trades, date_range) ===
Overall: Xw/Yl/Zbe, W% win rate
Total P&L: $X, Avg per trade: Y%
Confidence calibration:
  High (>0.75): X% actual win rate (N trades) — OVERCONFIDENT/CALIBRATED
  Medium (0.55-0.75): X% actual (N trades)
  Low (<0.55): X% actual (N trades)
Action accuracy: BUY W%, SELL X%
```

**Phase 4 — Strategic advice (LLM call):** Pass raw metrics dict to GPT with a
system prompt like:

> "You are reviewing your own trading recommendation history. Based on these
> performance metrics, write 2-3 sentences of concrete self-advice for future
> recommendations. Focus on specific biases, blind spots, or calibration issues.
> Be blunt and data-driven."

This costs ~$0.01 per generation and adds nuance templates can't capture.

**Phase 5 — Combine and store:**

- `injection_prompt` = data section + "\n\n" + strategic advice
- `summary_text` = human-readable report card (similar format but more verbose,
  for Insights view)
- Store in `reflections` table with user_id, counts, date range, metrics JSON

**Also update** `load_reflection_context()` signature to accept
`user_id: str = ""` and filter by it.

### Step 7: wire-up

**File:** `[src/backend/main.py](src/backend/main.py)`

- Import and register the 3 new routers with `app.include_router()`

**File:**
`[src/backend/pipeline/orchestrator.py](src/backend/pipeline/orchestrator.py)`

- Line ~227: Change `load_reflection_context()` to
  `load_reflection_context(user_id)`
- The `user_id` is already available in scope at this point

### Step 8: quality-check

```bash
cd src/backend
uv run ruff format
uv run ruff check --fix
uv run ty check
```

---

## Key Design Decisions

1. **Outcomes require a decision first** — DB enforces
   `outcomes.decision_id NOT NULL`. User must record "Take Trade" before they
   can log an outcome. This captures pass/follow ratio which is valuable
   calibration data.
2. **Hybrid reflection engine** — Pure Python for stats (deterministic, free),
   LLM for strategic self-advice (nuanced, ~$0.01/generation). The LLM section
   gives GPT the ability to recognize non-obvious patterns ("you keep getting
   burned on earnings-week momentum plays").
3. **Insights tab is the central hub** (frontend follow-up) — All decision
   recording, outcome logging, and performance viewing happens in the Insights
   tab. History view stays for pipeline run history.
4. **Recommendation.id plumbing** — Add `id: str = ""` to the Pydantic model.
   Default empty string means LLM output parsing is unaffected. Set when loading
   from DB.

## Risks / Open Questions

- **Sector data for metrics** — Sector info lives in stage_outputs (Perplexity
  data), not on recommendations directly. First pass can skip sector breakdown
  or add a join through pipeline_runs → stage_outputs.
- **Override analysis (what if I passed?)** — Tracking what happened to stocks
  the user passed on requires external price data. Defer to a future
  enhancement.
- **Concurrent reflection generation** — If triggered twice rapidly, could
  create duplicates. Mitigate with a simple "generated in last 5 minutes" check.
- **Empty state** — Refuse reflection generation with < 5 outcomes. Overview
  endpoint returns zeros gracefully.

## Verification

1. Start backend:
   `cd src/backend && uv run uvicorn main:app --reload --port 8420`
2. Run migration against Railway Postgres (or local)
3. Test decision flow:
   `POST /api/recommendations/{id}/decision {"decision":"following"}`
4. Test outcome flow:
   `POST /api/decisions/{id}/outcome {"entry_price":150,"exit_price":160,"shares":10}`
5. Test overview: `GET /api/insights/overview` → verify metrics
6. Test reflection: `POST /api/insights/reflect` → verify injection_prompt
   stored
7. Run pipeline → verify reflection context appears in GPT judge prompt
8. Run `ruff format && ruff check && ty check` — all clean

## Branch

`feature/phase-5-feedback-loop` off `dev`
