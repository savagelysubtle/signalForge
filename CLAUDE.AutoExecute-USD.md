# CLAUDE.AutoExecute-USD.md — MCP / IBKR / Algo-Execution Layer

> **Branch lineage:** `AutoExecute-USD` (merged into `dev`). Use this file when
> working on the **MCP server**, **US equity execution via IBKR**, **outcome
> journaling**, or **execution-time risk gates**. For the rest of SignalForge,
> start with [`CLAUDE.md`](CLAUDE.md) and [`CLAUDE2.md`](CLAUDE2.md).

---

## Scope

The **core web product** remains analysis-only (recommendations in the UI). This
layer adds an **optional** path: Claude Code (or any MCP client) drives the same
backend **plus** a local **MCP server** that talks to **Interactive Brokers**
(TWS / Gateway) for **US stocks**, **long-only**, **USD**, with confirm-first
execution and extra risk checks.

Do **not** treat MCP execution as the default user flow; document when a change
only affects MCP vs the FastAPI app.

---

## Layout

| Path | Role |
| ---- | ---- |
| [`src/mcp_server/`](src/mcp_server/) | Installable MCP package (`uv`); stdio server |
| [`src/mcp_server/mcp_server/server.py`](src/mcp_server/mcp_server/server.py) | Tool registration |
| [`src/mcp_server/mcp_server/tools/`](src/mcp_server/mcp_server/tools/) | `pipeline`, `portfolio`, `execution`, `risk`, `reconciliation`, `monitoring` |
| [`src/mcp_server/mcp_server/ibkr/`](src/mcp_server/mcp_server/ibkr/) | Connection, orders, portfolio, fills, **risk_gates** |
| [`src/mcp_server/mcp_server/backend/client.py`](src/mcp_server/mcp_server/backend/client.py) | Authenticated HTTP to FastAPI |
| [`src/mcp_server/mcp_server/config.py`](src/mcp_server/mcp_server/config.py) | Env + **REGIME_POSITION_MULTIPLIERS** |
| [`.claude/skills/trade/SKILL.md`](.claude/skills/trade/SKILL.md) | User-facing trade workflow skill |

**Backend additions** (high level):

- `POST /api/outcomes/brokerage-open`, `GET /api/outcomes/open`, `PATCH /api/outcomes/{id}`, `GET /api/outcomes/daily-summary`
- `POST /api/execution/sector-concentration`
- `GET /api/scanner/heartbeat` (used for regime sizing when enabled)
- Pipeline: v2-only orchestrator, **circuit breaker** on LLM validation, **risk_validator** live-quote sanity, **risk_post_filter** ticker guard, **fetch_stock_sectors** (FMP profile) for sectors

---

## Environment (MCP + backend)

Load order for MCP `.env`: `cwd` → `src/mcp_server/.env` → **repo root `.env`** → `src/.env`. See [`src/mcp_server/.env.example`](src/mcp_server/.env.example) and root [`.env.example`](.env.example).

| Variable | Where | Purpose |
| -------- | ----- | ------- |
| `SIGNALFORGE_BACKEND_URL` | MCP | FastAPI base URL (e.g. `http://localhost:8420`) |
| `SIGNALFORGE_AUTH_TOKEN` | MCP | Supabase **access_token** (Bearer) — required for outcome APIs, sector check, daily summary |
| `FMP_API_KEY` | **Backend** | Sector concentration **enforcement**; without it, gate **skips** (does not block) |
| `AUTO_EXECUTE_ENABLED` | MCP | Allow `place_order(..., auto=true)` without `confirmed=true` when gates + confidence pass |
| `AUTO_EXECUTE_MIN_CONFIDENCE` | MCP | Default `0.75` |
| `SECTOR_CONCENTRATION_ENABLED` | MCP | Default `true` |
| `MAX_POSITIONS_PER_SECTOR` | MCP | Default `2` |
| `REGIME_SIZING_ENABLED` | MCP | Scale share count from **heartbeat** `regime_type` (default `false`) |
| `IBKR_*` | MCP | Host, port, client id, paper flag — see `.env.example` |

---

## MCP tools (cheat sheet)

| Tool | Use |
| ---- | --- |
| `run_pipeline`, `get_pipeline_progress`, `get_pipeline_result`, `list_strategies`, `list_recent_runs` | Analysis (backend) |
| `get_account_summary`, `get_positions`, `get_open_orders` | IBKR read |
| `preview_order`, `place_order`, `cancel_order`, `close_position` | Execution |
| `get_daily_pnl`, `get_risk_status`, `get_daily_performance_summary` | Risk + P&amp;L |
| **`sync_brokerage_exits`** | Match flat IBKR positions to open `ibkr` outcomes; PATCH exit + P&amp;L from **SLD** fills |
| **`check_position_health`** | Open outcomes vs positions: stop/R distance, bracket warning, untracked positions |

---

## Agent / implementation rules (this layer)

1. **Never bypass human confirmation** unless `AUTO_EXECUTE_ENABLED` **and** explicit `auto=true` **and** all risk gates pass and confidence ≥ threshold.
2. **Long-only / cash account** assumptions are enforced in **risk_gates**; SHORT is not executable for the default config.
3. **Outcome PATCH** uses **`OutcomePatch`** (`exclude_unset=True`) — do not use full PUT unless replacing every field intentionally.
4. **IBKR fills** may be empty until API subscriptions / session history is available; `sync_brokerage_exits` can return `flat_no_exit_fills` — handle in UX, do not silently assume fills exist.
5. After editing Python under `src/mcp_server/` or touched backend files: `uv run ruff format`, `ruff check`, `ty check` per [`CLAUDE.md`](CLAUDE.md).

---

## Quick workflows

**Analyze then trade (manual confirm):** `preview_order` → user confirms → `place_order(..., confirmed=true)`.

**Automation (opt-in):** set env → `place_order(..., auto=true)` after `preview_order` or when policy allows.

**End of day / after closes:** `sync_brokerage_exits` then `get_daily_performance_summary` (IBKR + logged outcomes).

**Risk review:** `get_risk_status`, `check_position_health`.

---

## Git workflow

Feature work for this stack: branch from **`dev`** (e.g. `feature/…`), not `main`. See [`CLAUDE.md` → Git Workflow](CLAUDE.md).

---

## Related docs

- [`CLAUDE.md`](CLAUDE.md) — project-wide rules and stack
- [`.claude/skills/trade/SKILL.md`](.claude/skills/trade/SKILL.md) — trade skill for agents
- [`src/mcp_server/.env.example`](src/mcp_server/.env.example) — MCP env template
