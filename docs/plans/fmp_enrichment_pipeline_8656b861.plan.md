---
name: FMP Enrichment Pipeline
overview:
  'Build the full FMP enrichment pipeline: add response models and fetch
  functions for insider trading, financial scores, price changes, earnings
  calendar, and analyst consensus; extend FmpEnrichedStock with ~20 new signal
  fields; build a composite scoring engine with per-strategy configurable
  weights; expand FmpScreenerConfig with signal-based filters; update all 7
  strategy templates with tailored FMP signal configs; sync TypeScript types.'
todos: []
isProject: true
phases:
  - name: 'Phase 1: Response Models + Fetch Functions'
    todos:
      - id: response-models
        content:
          Add Pydantic response models for insider stats, financial scores,
          price changes, earnings calendar, earnings surprises, analyst
          recommendations, and price target consensus
        status: pending
      - id: fetch-functions
        content:
          Add async fetch wrapper functions for all 7 new FMP endpoints with
          error handling and semaphore rate limiting
        status: pending
  - name: 'Phase 2: Extend FmpEnrichedStock'
    todos:
      - id: extend-enriched-model
        content:
          'Add ~20 new fields to FmpEnrichedStock: price momentum (1D/1M/3M/6M),
          RVOL, Piotroski, Altman Z, insider net buys/ratio, analyst
          consensus/buy count/target upside, earnings date/beat rate, free
          float, composite scores (4 dimensions + overall)'
        status: pending
      - id: bulk-enrichment
        content:
          Build _enrich_batch() that fetches all signal data for a batch of
          symbols in parallel using asyncio.gather, then merges into
          FmpEnrichedStock instances
        status: pending
  - name: 'Phase 3: Scoring Engine + Schema'
    todos:
      - id: scoring-engine
        content:
          Build composite scoring engine with 4 dimensions (fundamental,
          momentum, sentiment, quality), percentile ranking across candidate
          pool, and configurable weights
        status: pending
      - id: expand-schema
        content:
          'Add new fields to FmpScreenerConfig: piotroski_min,
          require_insider_buying, rvol_min, earnings_within_days,
          scoring_weights dict. Update _apply_post_filters()'
        status: pending
      - id: typescript-sync
        content:
          Sync new FmpScreenerConfig fields and FmpEnrichedStock fields to
          TypeScript interfaces
        status: pending
  - name: 'Phase 4: Integration + Templates'
    todos:
      - id: wire-screen-and-enrich
        content:
          Update screen_and_enrich() to call _enrich_batch(), apply composite
          scoring, apply all post-filters (old + new), sort by composite score,
          apply sector concentration guard
        status: pending
      - id: update-tool-and-params
        content:
          Update fmp_tool.py tool definition and screen_stocks_from_params()
          with new signal parameters
        status: pending
      - id: update-fmp-context
        content:
          Update pipeline/fmp_context.py formatters to include new fields (if
          FmpEnrichedStock field names changed)
        status: pending
      - id: update-strategies
        content:
          Update all 7 strategy templates in strategies.json with tailored
          fmp_screener configs using new signal fields and scoring weights
        status: pending
      - id: quality-check
        content: Run ruff format, ruff check, ty check on all modified files
        status: pending
---

# FMP Enrichment Pipeline — Full Build

## Problem

`FmpEnrichedStock` defines only ~22 basic fields (ratios + metrics). The model
has no insider data, no Piotroski/Altman scores, no price momentum, no RVOL, no
earnings dates, no analyst consensus, and no composite scoring. These FMP
endpoints exist but have no fetch functions, no response models, and no
integration into `screen_and_enrich()`. Strategy templates can't control what
they can't screen for.

## Solution

Build end-to-end in 6 phases:

1. **Response models + fetch functions** for 6 new FMP endpoints (bulk where
   possible)
2. **Extend `FmpEnrichedStock`** with ~20 signal fields + update merge logic
3. **Composite scoring engine** with percentile ranking and per-strategy weight
   overrides
4. **Expand `FmpScreenerConfig`** with signal-based filters + scoring weights
5. **Wire into `screen_and_enrich()`** — fetch, merge, score, filter, sort
6. **Update strategy templates** with tailored signal configs per strategy
   purpose

## Key Files

- `src/backend/services/fmp_service.py` — models, fetch functions, scoring,
  enrichment
- `src/backend/pipeline/schemas.py` — `FmpScreenerConfig` expansion
- `src/frontend/src/types/index.ts` — TypeScript sync
- `templates/strategies.json` — strategy template updates
- `src/backend/pipeline/tools/fmp_tool.py` — tool definition expansion
- `src/backend/pipeline/fmp_context.py` — formatters (may need field updates)

## FMP Endpoints to Add

- `/stable/insider-trading-statistics?symbol=X` — net insider buys/sells
- `/stable/financial-scores?symbol=X` — Piotroski (0-9), Altman Z
- `/stable/stock-price-change?symbol=X` — 1D/5D/1M/3M/6M/1Y % changes
- `/stable/earning-calendar?from=DATE&to=DATE` — upcoming earnings dates (bulk)
- `/stable/earnings-surprises?symbol=X` — beat/miss history for beat rate
- `/stable/analyst-stock-recommendations?symbol=X` — buy/hold/sell consensus
- `/stable/price-target-consensus?symbol=X` — analyst target price upside

## Composite Scoring Design

- **4 dimensions**: Fundamental (ROE, margins, Piotroski), Momentum (price
  changes, RVOL), Sentiment (insider, analyst consensus), Quality (Altman Z,
  debt/equity, current ratio)
- Each dimension scored 0-100 via percentile ranking across the candidate pool
- Weighted composite = w*f * F + w*m * M + w*s * S + w*q * Q
- Default weights:
  `{"fundamental": 0.25, "momentum": 0.25, "sentiment": 0.25, "quality": 0.25}`
- Strategies override weights (e.g., Momentum Breakout: momentum=0.40, Value:
  fundamental=0.40)

## Strategy Signal Mapping

- **Momentum Breakout**: `rvol_min=1.5`, momentum weight 0.40, quality weight
  0.10
- **Value Accumulation**: `pe_max=20`, `roe_min=10`, `piotroski_min=5`,
  `require_insider_buying=true`, fundamental weight 0.40
- **Mean Reversion**: `piotroski_min=4`, `debt_equity_max=2.0`, quality weight
  0.35
- **Earnings Play**: `earnings_within_days=14`, sentiment weight 0.35
- **Intraday Scalp**: `rvol_min=2.0`, momentum weight 0.50, no enrichment delay
- **Crypto strategies**: No FMP signal enrichment (no change)

## Risks

- **API call budget**: Each enriched stock needs ~5 API calls. With 50
  candidates, that's ~250 calls. At 750/min tier this is fine, but we should
  batch and parallelize efficiently.
- **Latency**: More API calls = slower Stage 0. Mitigate with `asyncio.gather`
  and the existing semaphore.
- **Missing data**: Many TSX stocks may not have Piotroski/insider data. Filters
  must gracefully handle `None` (skip filter if data unavailable).
