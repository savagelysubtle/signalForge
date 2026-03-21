---
name: signalforge-quality
description: >
  Run code quality checks for the SignalForge project. Use when formatting Python code,
  running linters, type checking, checking TypeScript types, or verifying code quality
  before committing. Covers ruff format, ruff check, ty check for backend, and tsc for
  frontend. Also checks for type drift between Python and TypeScript schemas.
---

# SignalForge Quality

## Quick Reference

### Backend (Python)

```bash
cd src/backend
uv run ruff format          # format (Black-compatible)
uv run ruff check --fix     # lint + auto-fix
uv run ty check             # type check
```

### Frontend (TypeScript)

```bash
cd src/frontend
bunx tsc --noEmit           # type check
bun run lint                # ESLint
bun run build               # full build (tsc + vite)
```

### Cross-Stack

```bash
cd <repo-root>
python .cursor/skills/schema-sync/scripts/check_type_drift.py
```

## Full Quality Workflow

Run in this order after making changes:

1. **Format** — `uv run ruff format` (backend)
2. **Lint** — `uv run ruff check --fix` (backend)
3. **Type check backend** — `uv run ty check`
4. **Type check frontend** — `bunx tsc --noEmit`
5. **Type drift** — run `check_type_drift.py` (if schemas changed)
6. **Build** — `bun run build` (frontend, catches anything tsc misses)

## Configuration

### Ruff (`src/backend/pyproject.toml`)

- Line length: 100
- Target: Python 3.14
- Rules: E, W, F, I, B, C4, UP, SIM, RUF
- Ignored: E501, B008, C901, B905
- Known first-party: database, pipeline, services, api, utils, middleware, config

### ty (`src/backend/pyproject.toml`)

- Root: `["."]`
- Python version: 3.14
- Output format: full

### ESLint (`src/frontend/eslint.config.js`)

- Flat config with typescript-eslint
- react-hooks and react-refresh plugins

### TypeScript (`src/frontend/tsconfig.app.json`)

- Strict mode, noUnusedLocals, noUnusedParameters

## Rules

- Never disable ruff rules inline (`# noqa`) without a comment explaining why
- Never use `# type: ignore` without a specific error code
- Format before committing — `uv run ruff format` is non-negotiable
- Run `ty check` before considering Python work complete
