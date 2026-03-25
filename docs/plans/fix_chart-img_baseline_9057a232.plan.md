---
name: Fix Chart-Img Baseline
overview:
  Fix Chart-Img v2 API study names (the root cause of all chart failures) and
  strip timeframes back to only Daily + 4H to restore baseline functionality.
todos:
  - id: fix-indicator-map
    content:
      Fix INDICATOR_MAP in chart_image.py to use correct Chart-Img v2 study
      names (e.g. 'Moving Average Exponential' not 'EMA' or 'Exponential Moving
      Average')
    status: completed
  - id: strip-templates-to-baseline
    content:
      Update strategies.json templates to use only D + 4H timeframes (remove
      15m, 1H, W)
    status: completed
  - id: update-supabase-templates
    content:
      Run SQL to update existing template strategies in Supabase to match new
      template values
    status: completed
  - id: verify-and-test
    content: Restart backend, run a strategy, confirm charts work for D and 4H
    status: completed
isProject: false
---

# Fix Chart-Img v2 Study Names and Restore Baseline Timeframes

## Problem

ALL charts are broken. The `INDICATOR_MAP` in `chart_image.py` sends incorrect
study names to Chart-Img v2. The v2 API returns
`422: "must be a supported name"`. The baseline (commit `10ac45ec`) used v1
indicator names like `"Exponential Moving Average"`. The previous fix changed to
v1 abbreviations like `"EMA"`. **Neither is correct for v2.** The v2 API uses
its own naming, verified from the [v2 docs](https://doc.chart-img.com/):

- `"Exponential Moving Average"` (v1) -> `**"Moving Average Exponential"` (v2)
- `"Directional Movement Index"` (v1) -> `**"Directional Movement"` (v2)
- Other names like `"Relative Strength Index"`, `"Bollinger Bands"`, `"MACD"`,
  `"VWAP"` match between v1 and v2

Additionally, the templates have been expanded with 15m, 1H, and W timeframes
that the user wants removed until D + 4H is confirmed working.

## Solution

Two targeted changes: fix the indicator name mapping, and strip templates back
to D + 4H only.

## Implementation Steps

### Step 1: fix-indicator-map

Fix `INDICATOR_MAP` in
[src/backend/services/chart_image.py](src/backend/services/chart_image.py) to
use correct Chart-Img **v2** study names. The correct names come from the v2 API
documentation section headings and examples:

```python
INDICATOR_MAP: dict[str, str] = {
    "RSI": "Relative Strength Index",
    "MACD": "MACD",
    "Bollinger Bands": "Bollinger Bands",
    "Stochastic": "Stochastic",
    "ATR": "Average True Range",
    "EMA_20": "Moving Average Exponential",
    "EMA_50": "Moving Average Exponential",
    "SMA_50": "Moving Average",
    "SMA_200": "Moving Average",
    "VWAP": "VWAP",
    "Volume": "Volume",
    "OBV": "On Balance Volume",
    "CCI": "Commodity Channel Index",
    "Ichimoku": "Ichimoku Cloud",
    "DMI": "Directional Movement",
    "Parabolic SAR": "Parabolic SAR",
}
```

`INDICATOR_INPUTS` is already correct -- v2 uses `length` parameter name for
Moving Average and Moving Average Exponential studies (confirmed from v2 docs).

### Step 2: strip-templates-to-baseline

Update [templates/strategies.json](templates/strategies.json) to strip all
templates back to D + 4H baseline:

- **Momentum Breakout**: `chart_timeframe: "D"`, `additional_timeframes: ["4H"]`
  (was `["4H", "1H"]`)
- **Value Accumulation**: `chart_timeframe: "D"`,
  `additional_timeframes: ["4H"]` (was `W` primary with `["D", "4H"]`)
- **Mean Reversion**: `chart_timeframe: "D"`, `additional_timeframes: ["4H"]`
  (was `["4H", "1H"]`)
- **Earnings Play**: already `"D"` + `["4H"]` -- no change
- **Crypto Momentum**: `chart_timeframe: "D"`, `additional_timeframes: ["4H"]`
  (was `["4H", "1H"]`)
- **Intraday Scalp**: `chart_timeframe: "D"`, `additional_timeframes: ["4H"]`
  (was `"15m"` with `["1H", "4H", "D"]`)

### Step 3: update-supabase-templates

Run SQL against Supabase to update the existing strategy records to match the
new template values (same pattern as previous migration).

### Step 4: verify-and-test

- Restart backend, run a strategy, confirm Chart-Img returns 200 for D and 4H
  charts
- Confirm Claude analysis succeeds for both timeframes

## Risks / Open Questions

- **Intraday Scalp identity**: Stripping it to D + 4H makes it functionally
  identical to other templates. The user may want to remove it entirely or keep
  it with different indicators/params. Keeping it for now with just the
  timeframe change.
- **Existing user strategies in DB**: Users who already created strategies with
  15m/1H/W timeframes will still have those settings. The template update only
  affects NEW strategies created from templates. The `additional_timeframes`
  infrastructure stays intact so existing strategies still work once the
  indicator names are fixed.
- **Chart-Img v2 name stability**: The v2 names were verified from the official
  docs. If Chart-Img updates their API again, we'd need to re-verify.

## Branch

Current feature branch off `dev`.
