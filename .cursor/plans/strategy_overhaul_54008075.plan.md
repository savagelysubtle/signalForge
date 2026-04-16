---
name: Strategy Overhaul
overview:
  Full rewrite of `templates/strategies.json` — replace all 9 existing strategy
  templates with 5 focused strategies designed around what the audit data shows
  actually works on TSX, plus fix the SHORT SL/TP validation bug in the auditor
  grader.
todos:
  - id: strategies
    content: Rewrite templates/strategies.json with 5 new strategy templates
    status: pending
  - id: short-fix
    content: Fix SHORT SL/TP direction validation in auditor grader.py
    status: pending
  - id: quality
    content: Run ruff format + ruff check on changed files
    status: pending
  - id: re-audit
    content:
      'Mention to user: re-run auditor after accumulating new pipeline runs with
      new strategies to compare'
    status: pending
isProject: false
---

# Strategy Overhaul — templates/strategies.json

## What the Audit Proved

- **Mean reversion BUY works:** 60% win rate, +4.8% avg return (best
  risk-adjusted)
- **Golden cross BUY entries work:** 67% win rate, +8.6% avg return (when it
  fires BUY)
- **Momentum screening finds exhausted moves:** 6% win rate — screens for "has
  momentum" not "starting momentum"
- **Value Accumulation wins small, loses huge:** 65% win rate but -8.0% avg
  return — no stop discipline
- **SHORT SL/TP levels are set backwards by GPT** — grader trusts them blindly,
  producing garbage grades
- **Confidence calibration is broken 40-100%** — addressed separately (already
  changed)
- **Intraday Scalp is the most consistent** — 45% win rate, tight constraints,
  momentum-heavy

## Design Principles for New Strategies

1. **Hard stop discipline** — every strategy: `max_position_pct` capped at 4-5%,
   `min_risk_reward` >= 2.0
2. **Screen for beginning, not end** — momentum filters should catch early-stage
   moves (price_change_1m low-positive, not already up 20%+)
3. **Tight over loose** — `constraint_style: "tight"`, `max_tickers` <= 6
4. **Timeframe must match holding period** — no 4H charts for multi-week holds
5. **Dedicated short screening** — bearish setups need their own screening
   prompt and FMP filters
6. **TSX-first** — all strategies optimized for Canadian market dynamics (less
   liquidity, fewer analysts)

## New Strategy Templates (5 total)

### 1. TSX Quality Pullback (replaces Mean Reversion + Value Accumulation)

Combines what worked from both: find quality companies (Piotroski 5+, low debt)
that have pulled back 5-15% (not 25% — avoid falling knives) with technical
reversal signals. Tight position sizing.

Key changes from old Mean Reversion:

- `price_change_1m_min: -15.0` / `max: -3.0` (was -45% to -3%, now much tighter)
- `weight_momentum: 30` (was 25 for Mean Rev, 10 for Value Accum)
- `max_position_pct: 4.0`, `min_risk_reward: 2.5`
- `constraint_style: "tight"`, `max_tickers: 5`
- Daily chart timeframe for 3-10 day holds
- RSI 25-40 oversold zone (tighter than old 35 max)
- Requires volume confirmation on reversal

### 2. TSX Early Momentum (replaces Momentum Breakout)

Screen for stocks just beginning their move — not already up 20% in 6 months.
Look for the transition from base-building to breakout: low ADX rising, first
EMA stack forming, volume picking up from quiet base.

Key changes:

- `price_change_6m_min`: removed (was 20% — this was filtering for exhausted
  moves)
- `price_change_1m_min: 0.0` / `max: 10.0` (just starting to move, not extended)
- `price_change_3m_min: -5.0` / `max: 15.0` (was 10%+ required)
- ADX filter: `adx_min: 15, adx_max: 30` (trend forming, not already strong)
- RSI: `rsi_min: 50, rsi_max: 65` (bullish but not overbought)
- `constraint_style: "tight"`, `max_tickers: 5`
- `max_position_pct: 4.0`, `min_risk_reward: 2.5`

### 3. TSX Swing Breakout (replaces Golden Cross + BB Squeeze)

Keep the golden cross signal but tighten everything. Daily chart, 1-3 week
holds, require volume confirmation on the cross day, ADX trending up.

Key changes:

- `constraint_style: "tight"` (was "loose")
- `max_tickers: 5` (was 8)
- `max_position_pct: 4.0` (was 6%)
- `min_risk_reward: 2.0`
- Add `price_change_1m_min: 2.0` (some recent strength required)
- Volume filter tighter: `volume_min: 400000` (was 300k)
- `weight_momentum: 45` (increase from 40)
- Merge BB squeeze indicators in for setup variety

### 4. TSX Breakdown Short (new — dedicated bearish strategy)

Dedicated short strategy with bearish screening. Screen for stocks breaking
below key support, death cross (EMA 50 below 200), declining fundamentals,
analyst downgrades.

Key design:

- `screening_prompt`: focuses on bearish catalysts — earnings misses, guidance
  cuts, analyst downgrades, sector weakness, breaking below EMA 200
- `ta_focus`: death cross, RSI below 40 and falling, MACD negative histogram
  expanding, Supertrend red, volume on down days
- FMP filters: `price_change_1m_max: -5.0` (stock already declining),
  `price_change_3m_max: -10.0`
- `constraint_style: "tight"`, `max_tickers: 4`
- `max_position_pct: 3.0`, `min_risk_reward: 2.5` (smaller positions for shorts)
- `enable_debate: true`
- Short timeframes included for timing entries

### 5. Intraday Scalp (keep, minor tune)

Best-performing strategy on a risk-adjusted basis. Keep mostly as-is with minor
tightening:

- `max_tickers: 4` (was 5)
- `rvol_min: 2.5` (was 2.0 — require even more volume confirmation)
- Keep `enable_debate: false`, `weight_momentum: 60`

### Removed (not replaced)

- **Earnings Play** — 0% BUY win rate, TSX lacks the analyst ecosystem for
  event-driven plays
- **EMA Stack Momentum Intraday** — 0% BUY win rate, redundant with Intraday
  Scalp
- **EMA 21 Pullback Swing** — 50% win rate but +0.1% avg return, subsumed by
  Quality Pullback
- **VWAP Reversal Scalp** — only 4 trades, too niche, merge concepts into
  Intraday Scalp
- **Crypto Swing** — keep if crypto is still traded, cut if TSX-only focus
- **Crypto Intraday Scalp** — same

## Bug Fix: SHORT SL/TP Validation in Auditor

In `[auditor/grader.py](src/auditor/auditor/grader.py)`, the
`_grade_active_trade` method trusts GPT's SL/TP levels without validating them
against the trade direction. For SHORT trades, GPT sometimes sets stop_loss
below entry and take_profit above entry (as if it were a long), producing
inverted grades.

Fix: add a direction sanity check after loading GPT levels — if SL/TP are
backwards for the action, swap them or fall back to ATR.

## Files Changed

- `[templates/strategies.json](templates/strategies.json)` — full rewrite (9
  templates -> 5)
- `[src/auditor/auditor/grader.py](src/auditor/auditor/grader.py)` — SHORT SL/TP
  direction validation

## Crypto Decision

The plan above removes Crypto Swing and Crypto Intraday Scalp. If crypto should
stay, they can be kept as-is (they weren't in the audit losers). This needs
confirmation.
