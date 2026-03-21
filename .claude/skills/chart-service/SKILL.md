---
name: chart-service
description: >
  Work with the Chart-Img v2 chart image service and Supabase Storage in SignalForge.
  Use when modifying chart fetching, adding indicators, changing timeframes, working
  with annotated chart overlays, or debugging chart image issues. Covers the indicator
  map, timeframe map, exchange suffix map, and storage upload patterns.
---

# Chart Service

**File:** `src/backend/services/chart_image.py`

## Architecture

```
Chart-Img v2 API → PNG bytes → Supabase Storage upload → public URL
  └── annotated charts: adds horizontal lines (support/resistance/entry/stop/target)
```

## Key Maps

### INDICATOR_MAP

Maps strategy indicator names to Chart-Img `studies[]` objects:

| Indicator | Chart-Img study name     |
|-----------|--------------------------|
| RSI       | `RSI@tv-basicstudies`    |
| MACD      | `MACD@tv-basicstudies`   |
| Volume    | `Volume@tv-basicstudies` |
| EMA       | `MAExp@tv-basicstudies`  |
| SMA       | `MASimple@tv-basicstudies` |
| Bollinger | `BB@tv-basicstudies`     |
| VWAP      | `VWAP@tv-basicstudies`   |
| ATR       | `ATR@tv-basicstudies`    |
| Stochastic| `Stochastic@tv-basicstudies` |
| ADX       | `ADX@tv-basicstudies`    |

### TIMEFRAME_MAP

Maps strategy timeframes to Chart-Img interval values:

| Strategy | Chart-Img |
|----------|-----------|
| `1H`     | `60`      |
| `4H`     | `240`     |
| `D`      | `1D`      |
| `W`      | `1W`      |
| `M`      | `1M`      |

### EXCHANGE_SUFFIX_MAP

Maps exchange suffixes to TradingView exchange prefixes for symbol resolution.

## Adding a New Indicator

1. Add to `INDICATOR_MAP` in `chart_image.py`
2. If it needs custom input params, add to `INDICATOR_INPUTS`
3. Add to allowed values in `schemas.py` (documented in `chart_indicators` field)
4. Update Claude's prompt in `pipeline/prompts/claude_chart.py` to describe reading it
5. Add as option in frontend strategy editor

## Annotated Charts

`fetch_annotated_chart()` adds horizontal line overlays:

- **Support levels** (green dashed) — from `ChartAnalysis.key_levels` where `level_type == "support"`
- **Resistance levels** (red dashed) — from `key_levels` where `level_type == "resistance"`
- **Entry price** (blue solid) — from `Recommendation.entry_price`
- **Stop loss** (red solid) — from `Recommendation.stop_loss`
- **Take profit** (green solid) — from `Recommendation.take_profit`

These use Chart-Img v2 `drawings[]` in the POST body.

## Storage Paths

| Type       | Supabase path                                          |
|------------|--------------------------------------------------------|
| Base chart | `{user_id}/{run_id}/{ticker}_{timeframe}.png`          |
| Annotated  | `{user_id}/{run_id}/annotated/{ticker}_{timeframe}.png`|

Bucket: `charts` (public). URLs stored on `ChartAnalysis.chart_image_path` and `annotated_chart_path`.

## API Call Pattern

```python
async with httpx.AsyncClient() as client:
    response = await client.post(
        "https://api.chart-img.com/v2/tradingview/advanced-chart",
        headers={"x-api-key": api_key},
        json={
            "symbol": symbol,
            "interval": interval,
            "studies": studies,
            "drawings": drawings,  # for annotated charts
            "width": 800,
            "height": 600,
        },
    )
```
