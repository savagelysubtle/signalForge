---
name: History Strategy Column
overview:
  Add a "Strategy" column to the HistoryView table by resolving strategy names
  on the backend and displaying them in the frontend.
todos:
  - id: backend-model
    content:
      Add strategy_name field to PipelineRunSummary Pydantic model and resolve
      names via batch query in list_pipeline_runs()
    status: completed
  - id: frontend-type
    content:
      Add strategy_name to PipelineRunSummary TypeScript interface in
      types/index.ts
    status: completed
  - id: frontend-column
    content: Add Strategy column (header + cell) to HistoryView table
    status: completed
  - id: quality-check
    content: Run ruff + ty on backend, tsc on frontend
    status: completed
isProject: false
---

# Add Strategy Column to History View

## Current State

- `HistoryView` (`src/frontend/src/views/HistoryView.tsx`) renders 5 columns:
  Date, Tickers, Mode, Status, Duration
- Backend `list_pipeline_runs` in `src/backend/api/pipeline.py` returns
  `strategy_id` (nullable) but **not** the strategy name
- The `PipelineRunSummary` model (both Python and TypeScript) has no
  `strategy_name` field

## Changes Required

### 1. Backend: Add `strategy_name` to `PipelineRunSummary` response

**File:** `[src/backend/api/pipeline.py](src/backend/api/pipeline.py)`

- Add `strategy_name: str | None = None` to the `PipelineRunSummary` Pydantic
  model
- In `list_pipeline_runs()`, collect all unique non-null `strategy_id` values
  from the rows, batch-fetch their names from the `strategies` table in a single
  query, build a `{id: name}` map, and set `strategy_name` on each summary

```python
strategy_ids = list({r["strategy_id"] for r in rows if r["strategy_id"]})
strategy_names: dict[str, str] = {}
if strategy_ids:
    strat_resp = (
        await client.table("strategies")
        .select("id, name")
        .in_("id", strategy_ids)
        .execute()
    )
    strategy_names = {s["id"]: s["name"] for s in strat_resp.data}
```

Then when building each summary:
`strategy_name=strategy_names.get(r["strategy_id"])`

### 2. Frontend: Add `strategy_name` to TypeScript type

**File:** `[src/frontend/src/types/index.ts](src/frontend/src/types/index.ts)`

- Add `strategy_name: string | null;` to the `PipelineRunSummary` interface
  (after `strategy_id`)

### 3. Frontend: Render the Strategy column

**File:**
`[src/frontend/src/views/HistoryView.tsx](src/frontend/src/views/HistoryView.tsx)`

- Add a `<th>Strategy</th>` header between Date and Tickers (or after Tickers --
  between Tickers and Mode feels natural)
- Add a `<td>` that displays `run.strategy_name ?? "—"` with muted styling for
  the fallback dash
