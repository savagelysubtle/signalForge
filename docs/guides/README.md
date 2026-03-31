# Development Guides

Step-by-step instructions for common development tasks.

---

## Adding a New Chart Indicator

1. **Add the indicator to the map** in
   [`services/chart_image.py`](../../src/backend/services/chart_image.py):

   Add an entry to `INDICATOR_MAP` mapping the indicator name to a
   Chart-Img v2 `studies[]` object. If the indicator needs custom input
   parameters, add them to `INDICATOR_INPUTS` as well.

   ```python
   INDICATOR_MAP["Bollinger_Bands"] = {
       "name": "Bollinger Bands",
       "forceOverlay": True,
   }
   INDICATOR_INPUTS["Bollinger_Bands"] = {"in_0": 20, "in_1": 2.0}
   ```

2. **Add to allowed values** in
   [`pipeline/schemas.py`](../../src/backend/pipeline/schemas.py):

   If the schema validates indicator names, add the new indicator to the
   allowed list.

3. **Update Claude's prompt** in
   [`pipeline/prompts/claude_chart.py`](../../src/backend/pipeline/prompts/claude_chart.py):

   Describe how to read the indicator so Claude knows what to look for
   in the chart image. Bump `PROMPT_VERSION`.

4. **Add to the frontend strategy editor**:

   Add the indicator as an option in the strategy editor component so
   users can select it when creating/editing strategies.

---

## Adding a New Strategy Template

1. **Add the template JSON** to
   [`templates/strategies.json`](../../templates/strategies.json):

   ```json
   {
     "name": "My New Strategy",
     "description": "What this strategy does",
     "screening_prompt": "Natural language instruction for Perplexity...",
     "constraint_style": "tight",
     "max_tickers": 8,
     "chart_indicators": ["RSI", "MACD", "Volume", "EMA_50", "EMA_200"],
     "chart_timeframe": "D",
     "additional_timeframes": ["4H", "W"],
     "short_timeframes": [],
     "short_tf_indicators": ["VWAP", "Stochastic", "EMA_20", "ATR", "Volume"],
     "ta_focus": "What Claude should focus on in chart analysis",
     "news_recency": "week",
     "news_scope": "company",
     "trading_style": "Description of trading approach and timeframe",
     "risk_params": {
       "max_position_pct": 5.0,
       "min_risk_reward": 2.0,
       "max_portfolio_risk_pct": 15.0
     },
     "enable_debate": true,
     "is_template": true
   }
   ```

2. **Reload templates**: The template only loads if the `strategies` table
   is empty. To add a template to an existing database:
   - Insert it directly via the Supabase SQL editor or dashboard
   - Or drop all rows from `strategies` and restart the backend to re-seed

3. **Include `fmp_screener`** — all templates should include an `fmp_screener`
   block. Set `"enabled": false` if FMP pre-screening is not desired for that
   strategy:

   ```json
   "fmp_screener": {
     "enabled": false,
     "is_crypto": false,
     "country": "Canada",
     "exchange": "TSX",
     "market_cap_min": 500000000,
     "market_cap_max": null,
     "volume_min": 100000,
     "limit": 20,
     "enrich_with_ratios": true
   }
   ```

4. The template appears automatically in the frontend's template selector.

---

## Changing a Prompt

1. **Edit the prompt** in the appropriate file under
   [`pipeline/prompts/`](../../src/backend/pipeline/prompts/):

   | Stage | File |
   |-------|------|
   | Perplexity (discovery) | `perplexity_discovery.py` |
   | Perplexity (analysis) | `perplexity_analysis.py` |
   | Gemini (sentiment) | `gemini_sentiment.py` |
   | Claude (chart) | `claude_chart.py` |
   | GPT (bull/bear/judge) | `gpt_debate.py` |
   | Regime classifier | `regime_classifier.py` |

2. **Bump `PROMPT_VERSION`**: Increment the version string (e.g.,
   `"v3"` → `"v4"`). The hash updates automatically.

3. **Test**: Run a pipeline with the new prompt and verify the output
   validates against the Pydantic schema.

4. **Track performance**: After accumulating outcomes with the new prompt,
   compare performance between prompt versions in the Insights view
   (prompt hashes are stored in `pipeline_runs.prompt_versions`).

---

## Configuring FMP Pre-Screening on a Strategy

FMP (Financial Modeling Prep) is an optional Stage 0 screener. It runs before Perplexity to produce a pre-filtered ticker list.

**Prerequisite:** `FMP_API_KEY` must be set as an environment variable.

### Adding FMP config to a strategy template

Add or update the `fmp_screener` field in [`templates/strategies.json`](../../templates/strategies.json):

```json
"fmp_screener": {
  "enabled": true,
  "is_crypto": false,
  "country": "Canada",
  "exchange": "TSX",
  "sector": null,
  "industry": null,
  "market_cap_min": 100000000,
  "market_cap_max": null,
  "price_min": 1.0,
  "price_max": null,
  "volume_min": 50000,
  "beta_min": null,
  "beta_max": null,
  "is_actively_trading": true,
  "is_etf": false,
  "limit": 20,
  "pe_max": 40.0,
  "pe_min": null,
  "roe_min": null,
  "debt_equity_max": null,
  "enrich_with_ratios": true
}
```

### FMP Screener Config fields

| Field | Type | Purpose |
|-------|------|---------|
| `enabled` | bool | Master switch — if false, Stage 0 is skipped entirely |
| `is_crypto` | bool | Crypto path: uses batch-crypto-quotes instead of company-screener |
| `country` | str | Filter by country (e.g., `"Canada"`, `"US"`) |
| `exchange` | str | Filter by exchange (e.g., `"TSX"`, `"NASDAQ"`) |
| `market_cap_min/max` | float | Market cap range in dollars |
| `volume_min` | int | Minimum average volume |
| `enrich_with_ratios` | bool | Fetch `ratios-ttm` + `key-metrics-ttm` per result (slower but richer context) |
| `pe_max/min` | float | Post-filter by P/E ratio |
| `roe_min` | float | Post-filter by return on equity |
| `debt_equity_max` | float | Post-filter by debt/equity ratio |

---

1. **Define schemas** in
   [`pipeline/schemas.py`](../../src/backend/pipeline/schemas.py):

   Create Pydantic models for the stage's input and output.

2. **Create the prompt** in `pipeline/prompts/`:

   - Define `PROMPT_VERSION` and the system/user prompts
   - Implement `build_*_prompt()` and `get_prompt_hash()`

3. **Create the stage** in `pipeline/stages/`:

   - Implement the LLM call function
   - Use `@with_validation_retry(schema=YourModel, max_retries=2)`
   - Implement the public `run_*()` function

4. **Wire into the orchestrator** in
   [`pipeline/orchestrator.py`](../../src/backend/pipeline/orchestrator.py):

   Add the stage call at the appropriate point in `run_pipeline()`. Handle
   failures with the degraded pattern (try/except, append to
   `stage_errors`, continue).

5. **Add API endpoints** if the stage needs direct access (optional).

6. **Update the frontend** to display the new stage's output in the
   detail view (new tab in `DetailView`).

7. **Update `PipelineResult`** to include the new stage's data.

8. **Sync TypeScript types** in `types/index.ts` with any new Pydantic
   models.

---

## Adding a New API Endpoint

1. **Choose the router** in `api/` or create a new one.

2. **Define request/response models** as Pydantic `BaseModel` classes.

3. **Implement the handler**:

   ```python
   @router.get("/my-endpoint", response_model=MyResponse)
   async def my_endpoint(user_id: CurrentUser) -> MyResponse:
       ...
   ```

   Use `CurrentUser` dependency for auth. All endpoints except `/health`
   require authentication.

4. **Register the router** in `main.py`:

   ```python
   from api.my_router import router as my_router
   app.include_router(my_router, prefix="/api")
   ```

5. **Add the client function** in `api/client.ts`:

   ```typescript
   myEndpoint: () => request<MyResponse>("/api/my-endpoint"),
   ```

6. **Update TypeScript types** if the response introduces new shapes.

---

## Running Code Quality Checks

```bash
cd src/backend

# Format (Black-compatible)
uv run ruff format

# Lint (auto-fix)
uv run ruff check --fix

# Type check
uv run ty check
```

Always run these before committing. See [CLAUDE.md](../../CLAUDE.md) for
the full ruff and ty configuration.
