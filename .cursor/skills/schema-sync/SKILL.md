---
name: schema-sync
description: >
  Synchronize Pydantic models (Python) with TypeScript interfaces.
  Use when editing src/backend/pipeline/schemas.py or src/frontend/src/types/index.ts,
  when adding fields to pipeline models, or when a type mismatch is suspected between
  backend and frontend. Prevents the #1 cross-stack bug: type drift.
---

# Schema Sync

Keep `src/backend/pipeline/schemas.py` and `src/frontend/src/types/index.ts` in lockstep.

## Type Mapping

| Python (Pydantic)           | TypeScript                          |
|-----------------------------|-------------------------------------|
| `str`                       | `string`                            |
| `int`, `float`              | `number`                            |
| `bool`                      | `boolean`                           |
| `list[X]`                   | `X[]`                               |
| `dict[str, str]`            | `Record<string, string>`            |
| `X \| None`                 | `X \| null`                         |
| `Literal["a", "b"]`         | `"a" \| "b"`                        |
| `datetime`                  | `string` (ISO 8601)                 |
| `Field(ge=0.0, le=1.0)`    | `number` (add `// 0.0 to 1.0`)     |
| `Field(default_factory=list)` | `X[]` (no `\| null`)             |
| Nested `BaseModel`          | Separate `interface`                |
| `BaseModel \| None`         | `Interface \| null`                 |

## Current Model Pairs (must match)

| Python class         | TypeScript interface    |
|----------------------|-------------------------|
| `FundamentalData`    | `FundamentalData`       |
| `ScreeningResult`    | `ScreeningResult`       |
| `TechnicalLevel`     | `TechnicalLevel`        |
| `IndicatorReading`   | `IndicatorReading`      |
| `ChartAnalysis`      | `ChartAnalysis`         |
| `NewsCatalyst`       | `NewsCatalyst`          |
| `SentimentAnalysis`  | `SentimentAnalysis`     |
| `DebateCase`         | `DebateCase`            |
| `Recommendation`     | `Recommendation`        |
| `PipelineResult`     | `PipelineResult`        |
| `RiskParams`         | `RiskParams`            |
| `StrategyConfig`     | `StrategyConfig`        |

TypeScript has two extras with no Python match: `StageError`, `PipelineRunSummary`, `ApiKeyStatus`.

## Automated Drift Detection

Run `scripts/check_type_drift.py` to detect mismatches:

```bash
python .cursor/skills/schema-sync/scripts/check_type_drift.py \
  --schemas src/backend/pipeline/schemas.py \
  --types src/frontend/src/types/index.ts
```

## Workflow

1. **Run drift checker** to see current mismatches
2. **Read both files** before making changes
2. **Edit the Python model first** — it is the source of truth
3. **Mirror the change** to the TypeScript interface, applying type mapping
4. **Preserve defaults** — Python `Field(default_factory=list)` → TS `X[]` (not `X[] | null`)
5. **Preserve comments** — keep section dividers and annotations in both files
6. **Check for consumers** — search frontend components for usage of the changed field

## Conventions

- Field names use `snake_case` in both Python and TypeScript (no camelCase conversion)
- Python `datetime` → TypeScript `string` with `// ISO 8601` comment
- `Literal` unions in Python → string union types in TypeScript
- `Field(ge=X, le=Y)` constraints are documented as TS comments, not enforced at runtime
- `dict` in Python `stage_errors: list[dict]` → `StageError[]` in TypeScript (typed interface)
