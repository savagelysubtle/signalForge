---
name: Strategy timeframe control
overview:
  Update each strategy template's timeframe fields so the strategy dictates
  which charts Claude analyzes and pipes to GPT. No code changes needed -- only
  template data in strategies.json and Supabase.
todos:
  - id: update-templates-json
    content: Update strategies.json with per-strategy timeframe configurations
    status: completed
  - id: update-supabase
    content:
      Run SQL to update template strategies in Supabase with matching timeframe
      values
    status: completed
  - id: verify-backend
    content: Verify backend reloads cleanly and no regressions
    status: completed
isProject: false
---

# Strategy-Controlled Claude Analysis Timeframes

## Problem

All 6 strategy templates currently analyze all 5 timeframes (15m, 1H, 4H, D, W)
through Claude and into GPT. This overwhelms GPT with too many charts for
focused strategies. A swing trade strategy should only analyze 4H/D/W; an
intraday scalp should only analyze 15m/1H/4H.

## Why no code changes are needed

The pipeline already supports this:

- `chart_timeframe` -- the primary TF, always analyzed by Claude using
  `chart_indicators`
- `additional_timeframes` -- extra higher TFs analyzed with `chart_indicators`
- `short_timeframes` -- short TFs analyzed with `short_tf_indicators`

The Claude stage loops (`claude.py` lines 221-245) already skip duplicates with
`if extra_tf != config.chart_timeframe`. The frontend ChartTab already shows
"Chart-only view" for any timeframe without a `ChartAnalysis`, using an ad-hoc
chart fetch from `POST /api/charts/fetch`.

**"No Strategy" runs preserve all 5 timeframes** via Pydantic field defaults in
`schemas.py`.

## Strategy-to-Timeframe Mapping

| Strategy           | Claude Analyzes | chart_timeframe | additional_timeframes | short_timeframes |
| ------------------ | --------------- | --------------- | --------------------- | ---------------- |
| Momentum Breakout  | 4H, D, W        | D               | ["4H", "W"]           | []               |
| Value Accumulation | 4H, D, W        | D               | ["4H", "W"]           | []               |
| Mean Reversion     | 4H, D, W        | D               | ["4H", "W"]           | []               |
| Earnings Play      | 1H, 4H, D       | D               | ["4H"]                | ["1H"]           |
| Crypto Momentum    | 4H, D, W        | D               | ["4H", "W"]           | []               |
| Intraday Scalp     | 15m, 1H, 4H     | 4H              | []                    | ["15m", "1H"]    |

**Note on Intraday Scalp:** Setting `chart_timeframe: "4H"` makes 4H the primary
(analyzed with RSI/MACD/Vol/EMA50/EMA200 for structural context). The
`_sync_timeframes` validator may populate `additional_timeframes` from
`secondary_timeframe`, but the loop's `if extra_tf != config.chart_timeframe`
dedup check prevents double analysis. Setting `secondary_timeframe: "4H"` keeps
this clean.

## Implementation Steps

### Step 1: Update strategies.json

In [templates/strategies.json](templates/strategies.json), update each template:

- **Momentum Breakout, Value Accumulation, Mean Reversion, Crypto Momentum:**
  Set `"short_timeframes": []` (remove 15m/1H from Claude analysis). Keep
  `additional_timeframes: ["4H", "W"]`.
- **Earnings Play:** Set `"additional_timeframes": ["4H"]`,
  `"short_timeframes": ["1H"]`.
- **Intraday Scalp:** Set `"chart_timeframe": "4H"`,
  `"secondary_timeframe": "4H"`, `"additional_timeframes": []`,
  `"short_timeframes": ["15m", "1H"]`.

### Step 2: Update Supabase template rows

Run SQL to update the 6 template strategies with matching values. One UPDATE per
distinct configuration (3 groups: swing-like, earnings, intraday).

### Step 3: Verify

Confirm backend reloads cleanly and the frontend still shows all 5 timeframe
buttons (non-analyzed ones will use ad-hoc fetch and show "Chart-only view").

## Risks / Open Questions

- **Ad-hoc chart indicators:** When a user clicks a non-analyzed timeframe, the
  frontend fetches an ad-hoc chart using `chartIndicators` (the higher-TF set).
  This means a 15m ad-hoc chart for a Momentum Breakout run would show
  RSI/MACD/EMA50/EMA200 instead of VWAP/Stochastic/EMA20/ATR. This is cosmetic
  only (no analysis) and acceptable for now.
- **No pipeline code changes** means this is very low risk and easily reversible
  by changing template data back.
