# API Reference

> **Base URL:** `http://localhost:8420` (development) or Railway deployment URL
> **Auth:** All endpoints (except `/health`) require `Authorization: Bearer <supabase-jwt>`

---

## Health Check

### `GET /health`

Check backend and database connectivity. No auth required.

**Response:**

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

## Pipeline

**Router prefix:** `/api/pipeline`
**Source:** [`api/pipeline.py`](../../src/backend/api/pipeline.py)

### `POST /api/pipeline/run`

Trigger a new analysis pipeline run. Rate limited to **5/minute**.

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `strategy_id` | `string` | No* | Strategy UUID for discovery screening |
| `manual_tickers` | `string[]` | No* | Ticker symbols to research directly |
| `user_prompt` | `string` | No* | Free-form screening prompt |

*At least one of these must be provided.

**Mode selection:**

| Inputs provided | Mode |
|----------------|------|
| `user_prompt` (± strategy) | `prompt` |
| `strategy_id` + `manual_tickers` | `combined` |
| `strategy_id` only | `discovery` |
| `manual_tickers` only | `analysis` |

**Response:** `201`

```json
{
  "run_id": "a1b2c3d4e5f6...",
  "status": "completed"
}
```

**Errors:**
- `400` — no strategy, tickers, or prompt provided
- `429` — rate limit exceeded

---

### `GET /api/pipeline/status/{run_id}`

Get the full result of a pipeline run including all stage outputs.

**Response:** `PipelineResult`

```json
{
  "run_id": "a1b2c3d4...",
  "strategy_name": "Momentum Breakout",
  "mode": "discovery",
  "input_tickers": [],
  "screening": {
    "mode": "discovery",
    "strategy_name": "Momentum Breakout",
    "tickers": [
      {
        "ticker": "TSX:CNQ",
        "company_name": "Canadian Natural Resources",
        "asset_type": "stock",
        "sector": "Energy",
        "market_cap": "$85B",
        "pe_ratio": 12.5,
        "revenue_growth": "+15% YoY",
        "free_cash_flow": "$2.3B",
        "key_highlights": ["..."],
        "risk_factors": ["..."],
        "sources": ["..."],
        "news_urls": ["https://..."]
      }
    ],
    "screening_summary": "..."
  },
  "sentiment_analyses": [
    {
      "ticker": "TSX:CNQ",
      "sentiment_score": 0.65,
      "sentiment_label": "bullish",
      "key_catalysts": [
        {
          "headline": "...",
          "source": "Reuters",
          "url": "https://...",
          "impact": "positive",
          "significance": "high"
        }
      ],
      "summary": "..."
    }
  ],
  "chart_analyses": [
    {
      "ticker": "TSX:CNQ",
      "timeframe": "D",
      "current_price": 45.50,
      "trend_direction": "bullish",
      "trend_strength": "strong",
      "key_levels": [
        { "price": 44.00, "level_type": "support", "strength": "strong" }
      ],
      "indicator_readings": [
        { "indicator": "RSI", "value": "62", "signal": "bullish" }
      ],
      "overall_bias": "bullish",
      "confidence": "high",
      "summary": "...",
      "chart_image_path": "https://...",
      "annotated_chart_path": "https://..."
    }
  ],
  "recommendations": [
    {
      "ticker": "TSX:CNQ",
      "action": "BUY",
      "confidence": 0.82,
      "entry_price": 45.50,
      "stop_loss": 43.00,
      "take_profit": 50.00,
      "position_size_pct": 4.5,
      "risk_reward_ratio": 1.8,
      "holding_period": "3-5 days",
      "bull_case": { "ticker": "TSX:CNQ", "stance": "bull", "key_arguments": ["..."] },
      "bear_case": { "ticker": "TSX:CNQ", "stance": "bear", "key_arguments": ["..."] },
      "judge_reasoning": "...",
      "key_factors": ["..."],
      "warnings": ["..."]
    }
  ],
  "stage_errors": [],
  "total_duration_seconds": 45.2,
  "prompt_versions": {
    "perplexity": "abc123",
    "gemini": "def456",
    "claude": "ghi789",
    "gpt_bull": "jkl012",
    "gpt_bear": "mno345",
    "gpt_judge": "pqr678"
  }
}
```

**Errors:**
- `404` — run not found or does not belong to user

---

### `GET /api/pipeline/runs`

List recent pipeline runs for the current user (last 100).

**Response:** `PipelineRunSummary[]`

```json
[
  {
    "id": "a1b2c3d4...",
    "strategy_id": "s1t2r3a4...",
    "mode": "discovery",
    "status": "completed",
    "started_at": "2026-03-24T14:30:00Z",
    "duration_seconds": 45.2,
    "tickers": ["TSX:CNQ", "TSX:ENB"]
  }
]
```

---

### `GET /api/pipeline/runs/{run_id}`

Alias for `/api/pipeline/status/{run_id}`.

---

## Strategies

**Router prefix:** `/api/strategies`
**Source:** [`api/strategies.py`](../../src/backend/api/strategies.py)

### `GET /api/strategies`

List all user-created strategies (excludes templates).

**Response:** `StrategyConfig[]`

---

### `GET /api/strategies/templates`

List all built-in strategy templates. No auth required beyond JWT.

**Response:** `StrategyConfig[]`

---

### `GET /api/strategies/{strategy_id}`

Get a single strategy by ID (must belong to user or be a system template).

**Response:** `StrategyConfig`

**Errors:**
- `404` — strategy not found

---

### `POST /api/strategies`

Create a new strategy.

**Request body:** `StrategyConfig` (see [Pipeline docs](pipeline.md) for the
full field list)

**Response:** `201` — the created `StrategyConfig` with generated `id`

---

## Charts

**Router prefix:** `/api/charts`
**Source:** [`api/charts.py`](../../src/backend/api/charts.py)

### `POST /api/charts/fetch`

Fetch a chart image on-demand (outside of a pipeline run).

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `ticker` | `string` | Yes | Ticker symbol (TradingView format) |
| `timeframe` | `string` | Yes | Chart timeframe (see supported list below) |
| `indicators` | `string[]` | No | Indicator names to overlay |

**Supported timeframes:** `1m`, `3m`, `5m`, `15m`, `30m`, `1H`, `2H`, `4H`,
`D`, `W`, `M`

**Response:**

```json
{
  "ticker": "TSX:CNQ",
  "timeframe": "D",
  "image_url": "https://supabase-cdn.../charts/..."
}
```

**Errors:**
- `400` — unsupported timeframe
- `502` — Chart-Img API error

---

## Settings

**Router prefix:** `/api/settings`
**Source:** [`api/settings.py`](../../src/backend/api/settings.py)

### `GET /api/settings/api-keys/status`

Check which API keys are configured. Values are never returned, only
boolean presence.

**Response:**

```json
{
  "keys": {
    "perplexity": true,
    "anthropic": true,
    "google": true,
    "openai": true,
    "chart_img": true,
    "supabase_url": true,
    "supabase_service_key": true
  }
}
```
