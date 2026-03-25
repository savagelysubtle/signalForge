---
name: Fix chart ticker mismatch
overview:
  Standardize the entire pipeline on TradingView ticker format. Perplexity
  returns TV-format tickers, Chart-Img and TradingView widget use them natively,
  and Claude's result ticker is overridden to match the pipeline input.
todos:
  - id: fix-ticker-override
    content:
      Add result.ticker = ticker in claude.py _analyze_ticker after result
      validation
    status: completed
  - id: fix-perplexity-prompts
    content:
      Add TradingView ticker format instructions to both Perplexity system
      prompts (discovery + analysis) and bump PROMPT_VERSION to v2
    status: completed
  - id: merge-deploy
    content: Merge feature -> dev -> main and push to deploy
    status: completed
isProject: false
---

# Standardize Pipeline on TradingView Ticker Format

## Problem

Perplexity returns bare tickers (`ZDC`, `ENB`) with no exchange context.
Chart-Img resolves them to TradingView format on the chart (`TSXV:ZDC`). Claude
reads the TV-format ticker from the chart. The pipeline tickers no longer match,
breaking frontend chart display.

## Solution

Use TradingView format as the single ticker standard across the entire pipeline.
This is the natural choice because Chart-Img, Claude's chart images, and the
frontend TradingView widget all use it natively.

```mermaid
flowchart LR
  Perplexity -->|"TSXV:ZDC"| ChartImg
  ChartImg -->|"TSXV:ZDC on chart"| Claude
  Claude -->|"ticker: TSXV:ZDC"| GPT
  GPT -->|"TSXV:ZDC"| Frontend
  Frontend -->|"TSXV:ZDC === TSXV:ZDC"| Match[Chart Displayed]
```

## Fix 1: Override ticker in Claude result (safety net)

In
`[src/backend/pipeline/stages/claude.py](src/backend/pipeline/stages/claude.py)`,
`_analyze_ticker()` lines 155-158 become:

```python
if result is not None:
    result.ticker = ticker
    result.chart_image_path = image_path
    metadata["status"] = "success"
```

Claude might still misread the ticker from the chart. This ensures it always
matches the pipeline's canonical ticker.

## Fix 2: Perplexity prompts return TradingView format

Add ticker format rules to both system prompts in:

- `[src/backend/pipeline/prompts/perplexity_discovery.py](src/backend/pipeline/prompts/perplexity_discovery.py)`
- `[src/backend/pipeline/prompts/perplexity_analysis.py](src/backend/pipeline/prompts/perplexity_analysis.py)`

Add after the crypto instructions:

```
Ticker format rules (CRITICAL -- use TradingView format):
- US stocks/ETFs: plain ticker (e.g. AAPL, SPY, TSLA)
- Canadian TSX: prefix TSX: (e.g. TSX:ENB, TSX:CNQ, TSX:SHOP)
- Canadian TSXV: prefix TSXV: (e.g. TSXV:ZDC)
- London LSE: prefix LSE: (e.g. LSE:SHEL)
- Australian ASX: prefix ASX: (e.g. ASX:BHP)
- German XETR: prefix XETR: (e.g. XETR:SAP)
- Other international: use EXCHANGE:SYMBOL format per TradingView conventions
- Crypto: plain symbol (e.g. BTC, ETH, SOL)
- NEVER return Yahoo Finance format with suffixes like .TO, .V, .L
```

Bump `PROMPT_VERSION` to `"v2"` in both files.

## Yahoo-to-TradingView converter (kept as fallback)

The `_to_tradingview_symbol()` function in
`[src/backend/services/chart_image.py](src/backend/services/chart_image.py)`
stays in place. If a Yahoo-format ticker (e.g. `ENB.TO`) reaches Chart-Img from
manual input or an LLM not following instructions, the converter catches it
automatically. No changes to this file.

## Branch

Already on `feature/fix-chart-ticker-mismatch` off `dev`.
