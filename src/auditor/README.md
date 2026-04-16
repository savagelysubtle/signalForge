# SignalForge Pipeline Auditor

Grades pipeline recommendations against historical price data to measure how
accurate the pipeline's calls actually were.

Pulls every recommendation from Supabase (BUY, SHORT, WATCH, HOLD, NO_TRADE),
downloads real OHLCV prices via yfinance, and scores each recommendation across
four dimensions.

## Grading Dimensions

| Dimension | Applies to | What it measures |
|---|---|---|
| **Active Trade** | BUY, SHORT | Triple-barrier walk-forward using GPT's SL/TP levels (or ATR fallback). Labels: `TP_HIT`, `SL_HIT`, `TIME_EXIT`. |
| **Watch / Entry** | WATCH, HOLD | Did price reach the suggested `entry_price` within the valid window? If so, would the trade have been profitable? |
| **Direction** | All actions | Over the holding period, did the price move the way the pipeline predicted? |
| **Timing** | All with `holding_period` | Was the predicted holding period accurate? Labels: `EARLY`, `ON_TIME`, `LATE`, `EXPIRED`. |

A **confidence calibration** report is also generated — bucketing recommendations
by confidence level and comparing predicted confidence to actual win rate.

## Quick Start

```bash
cd src/auditor
uv sync --python 3.14 --prerelease=allow

# Full audit (pulls from Supabase, fetches prices, grades, reports)
uv run --python 3.14 python -m auditor run

# Filter by date range
uv run --python 3.14 python -m auditor run --since 2025-06-01 --until 2026-04-15

# Filter by tickers
uv run --python 3.14 python -m auditor run --tickers AAPL,NVDA,BTC

# Custom output directory
uv run --python 3.14 python -m auditor run --output-dir ./my_audit

# Regenerate report from a previous run's parquet file
uv run --python 3.14 python -m auditor report --input ./audit_results/graded_recs.parquet
```

## Requirements

- Python 3.14+
- `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` in your `.env` (repo root)
- Internet access for yfinance price downloads

## CLI Reference

### `audit run`

Pull recommendations, fetch prices, grade, and generate a report.

| Flag | Default | Description |
|---|---|---|
| `--since` | — | Only include recs created on or after this date (YYYY-MM-DD) |
| `--until` | — | Only include recs created on or before this date |
| `--tickers` | — | Comma-separated ticker filter |
| `--output-dir` | `./audit_results` | Directory for parquet + JSON output |
| `--max-horizon` | `20` | Max trading days to look forward for barrier resolution |
| `--parquet-data` | — | Path to `ml_training` data directory for ParquetStore fallback |
| `-v, --verbose` | off | Debug logging |

### `audit report`

Regenerate a report from previously saved graded data (no Supabase or price
fetching required).

| Flag | Default | Description |
|---|---|---|
| `--input` | *(required)* | Path to `graded_recs.parquet` from a previous run |
| `--output-dir` | same as input | Directory for JSON output |
| `-v, --verbose` | off | Debug logging |

## Output Files

Each run produces two artifacts in the output directory:

- **`graded_recs.parquet`** — one row per recommendation with all grading
  columns (trade label, direction, timing, returns, MFE/MAE, etc.)
- **`audit_report.json`** — aggregated report with win rates, calibration
  buckets, timing breakdown, top winners/losers

## Package Structure

```
src/auditor/
├── pyproject.toml
└── auditor/
    ├── __init__.py
    ├── __main__.py      # python -m auditor entry point
    ├── cli.py           # Click CLI (run, report)
    ├── config.py        # Env var loading (.env)
    ├── models.py        # Pydantic models for grades and reports
    ├── pull.py          # Supabase data puller
    ├── prices.py        # yfinance fetcher + ParquetStore fallback
    ├── grader.py        # Core grading engine (4 dimensions)
    └── report.py        # Rich console output + JSON/parquet export
```

## How It Works

1. **Pull** — Fetches all recommendations from Supabase, joined with pipeline
   runs (for strategy name), decisions (follow/pass), and outcomes (logged P&L).
2. **Price Fetch** — Downloads daily OHLCV from yfinance for each unique ticker.
   Falls back to `ml_training`'s ParquetStore if the data directory is provided.
3. **Grade** — Walks forward through price bars from the signal date, applying
   all four grading dimensions to each recommendation.
4. **Report** — Aggregates results by action, strategy, and confidence bucket.
   Prints a Rich console summary and saves JSON + parquet.
