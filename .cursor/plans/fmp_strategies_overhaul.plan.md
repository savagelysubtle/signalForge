---
name: ''
overview: ''
todos: []
isProject: false
---

# FMP Pre-Screener & Strategies Overhaul

**Problem:** Pipeline is producing too many `WATCH` recommendations — "setup
developing, not actionable yet" — across all TSX strategies. Users expect mostly
`BUY`/`HOLD`/`NO_TRADE` with `WATCH` as an edge case; instead `WATCH` has become
the default output. Root cause is not a single issue; it's a cascade of
key-format bugs, dead wiring, prompt bias, and screener filters that don't match
what the strategies actually trade.

**Scope:** `src/backend/services/fmp_service.py`,
`src/backend/pipeline/orchestrator.py`, `src/backend/pipeline/fmp_context.py`,
`src/backend/pipeline/stages/{claude,gemini,risk_post_filter}.py`,
`src/backend/pipeline/prompts/gpt_debate.py`, `src/backend/ml/pre_gpt.py`,
`templates/strategies.json`.

---

## SECTION A — The Showstopper (highest-priority bug)

### A1. Ticker key mismatch strips FMP context from every TSX ticker

**The data flow:**

1. FMP `/stable/company-screener` returns TSX listings with raw Yahoo suffix
   format: `SHOP.TO`, `ENB.TO`, `AGI.TO`. `FmpEnrichedStock.symbol = "SHOP.TO"`.
2. `orchestrator.py:494, 503`: `fmp_map = {s.symbol: s for s in fmp_candidates}`
   keys the dict by **raw** FMP symbols: `{"SHOP.TO": ..., "ENB.TO": ...}`.
3. `orchestrator.py:564, 619`: everything downstream is normalized via
   `normalize_ticker()`: `SHOP.TO` → `TSX:SHOP`. So
   `ticker_symbols = ["TSX:SHOP", "TSX:ENB", ...]`.
4. Every downstream consumer does `fmp_map.get(ticker)` / `ticker in fmp_map`
   with the **normalized** key against a **raw-keyed** dict. Lookup always fails
   for TSX.

**Cascade of consequences:**

| Consumer                                       | Location                         | Effect when lookup fails                                                                                                                                                         |
| ---------------------------------------------- | -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pre_filter_tickers`                           | `stages/risk_post_filter.py:59`  | Logs "may be valid ticker without FMP coverage" and passes all through — **pre-filter is a no-op for TSX**                                                                       |
| `risk_post_filter`                             | `stages/risk_post_filter.py:158` | Piotroski/Altman risk flags **never attached** to TSX tickers                                                                                                                    |
| `format_fmp_for_gemini`                        | `stages/gemini.py:187`           | Gemini sentiment runs **without** company/earnings/insider context                                                                                                               |
| `format_fmp_for_gpt`                           | `fmp_context.py:158`             | **Every TSX ticker gets "No FMP data available." in the GPT bull/bear/judge prompt.** No composite score, no Piotroski, no analyst target, no insider signal, no momentum data   |
| `build_ml_feature_dicts` → `run_pre_gpt_gates` | `ml/pre_gpt.py:38, 146`          | ML prior runs with empty FMP features for TSX → more uncertain predictions → triggers `ml_uncertainty_escalates_debate` → forces debate escalation → pushes judge toward `WATCH` |
| `_enrich_screening_fundamentals`               | `orchestrator.py:165-170`        | Works correctly — only consumer using `canonical_ticker_match_key`. Frontend cards show data but LLMs don't.                                                                     |

**Why this produces WATCH:** The judge receives Perplexity narrative, chart
images, and raw TA, but **zero quantitative backing** for TSX tickers. When
qualitative narrative is ambiguous, the judge picks the safe middle. Piotroski
7, Altman Z 4.2, insider net buying, +25% analyst upside — all present in the
data, all invisible to the judge. The anchor that could push a marginal chart
over the `BUY` line is systematically removed.

**Fix:** Key `fmp_map` by `canonical_ticker_match_key(s.symbol)` at construction
so it matches normalized keys.

```python
# orchestrator.py:494, 503
from utils.ticker import canonical_ticker_match_key
fmp_map = {canonical_ticker_match_key(normalize_ticker(s.symbol)): s for s in fmp_candidates}
```

All 6 downstream consumers then need to normalize their lookup ticker the same
way, or we pre-normalize `tickers` before the lookup in `format_fmp_for_gpt`,
`pre_filter_tickers`, `risk_post_filter`, `format_fmp_for_gemini`, and
`build_ml_feature_dicts`. Prefer fixing at source (fmp_map construction).

**Verification:** Add an integration test that runs `screen_and_enrich` on a TSX
strategy, then asserts `format_fmp_for_gpt(fmp_map, normalized_tickers)`
contains real composite scores, not "No FMP data available."

---

### A2. `format_fmp_for_claude` is dead code

`fmp_context.py:95` defines it. Zero callers anywhere in the codebase
(`stages/claude.py` has no references). Claude's vision stage reads charts
**without any FMP context at all**, for all stocks including US — no Piotroski,
no earnings date, no composite score context.

**Fix:** Wire it into `stages/claude.py` the same way `format_fmp_for_gemini`
flows into `stages/gemini.py:188`. Build a per-ticker `fmp_str` and include it
in the Claude chart-analysis user prompt alongside the image attachment.

---

### A3. `filter_by_rsi` has inverted logic AND zero callers

`fmp_service.py:916-923`:

```python
if strategy_type == "mean_reversion" and rsi < 30:
    logger.info("...rejecting ... oversold for mean-reversion")
    continue
```

Mean reversion **wants** RSI < 30 — that's the entry signal. This function
rejects the exact setup it should keep. It's never called from
`screen_and_enrich` (grep confirms zero callers). Dead code with a latent bug.

**Fix:** Either delete entirely, or fix logic + wire into `screen_and_enrich` as
a real per-strategy RSI gate:

```python
# Correct logic:
if strategy_type in ("momentum", "momentum_breakout") and rsi > 75:
    continue  # reject overbought for momentum
if strategy_type == "mean_reversion" and rsi > 45:
    continue  # reject NOT-oversold for mean reversion (keep RSI < 35)
```

---

## SECTION B — Judge Prompt Biases Toward WATCH

### B1. "R:R < 2:1 → WATCH" is an explicit watch factory

`prompts/gpt_debate.py:362`:

> "Target R:R >= 2:1. If the chart structure does not support 2:1, use `WATCH`."

Combined with every strategy in `strategies.json` setting
`min_risk_reward: 2.0–2.5`, this creates a hard downgrade path. On a momentum
breakout where price has already run to resistance, next target is often 4-6%
away while stop is 3-5% below entry → R:R ≈ 1:1 to 1.5:1 → forced `WATCH`.

**Fix:** Soften to "flag low R:R as a risk factor, reduce position size, but
don't auto-downgrade if track agreement is high." Let the judge override on
conviction.

### B2. Confidence label mapping treats WATCH as the comfortable middle

`prompts/gpt_debate.py:313`:

```
- WATCH c3_slightly_low to c5_neutral: Setup developing, not actionable yet
- NO_TRADE c0_no_confidence to c2_low: No directional edge visible
```

`WATCH` is the "c3–c5" zone — literally the middle of the 0-10 confidence scale.
`NO_TRADE` requires the judge to commit to "no edge." `BUY`/`SHORT` need c6+.
**WATCH is the default for any ambiguous case** because it maps to the most
comfortable confidence range the LLM can claim.

**Fix:** Rebalance so WATCH maps to c2-c4 and BUY/SHORT can live at c5+ with
justification. Remove WATCH's "safe middle" status.

### B3. Framework is asymmetric: easy to escape to WATCH, hard to commit to BUY

No counter-rule says "if Claude's TA assessment is strong AND Gemini sentiment
is positive AND FMP composite > 70 → you must justify NOT issuing BUY." The
decision framework only has escape hatches, no affirmative BUY mandates.

**Fix:** Add an explicit BUY-mandate clause to `JUDGE_SYSTEM_PROMPT`, but
require that every BUY/SHORT signal includes a **conditional entry plan** —
never "buy at market now":

```
When all three tracks agree directionally (agreement_score >= 0.7), Claude's
technical assessment is bullish/bearish, and the FMP composite score is >= 70
OR no FMP data is available, you MUST issue BUY/SHORT unless you can name a
specific invalidation that applies NOW (not "might happen"). Converting a
high-agreement setup to WATCH requires a concrete blocker — not vague
uncertainty, but a named risk (e.g., earnings in 2 days, broken structure).

CRITICAL — BUY/SHORT signals are CONDITIONAL, not immediate:
Every BUY or SHORT must specify a tactical entry plan with:
  1. Entry trigger: the price action condition (e.g., "wait for pullback to
     $142 support zone and reversal candle" or "short on rejection at $185
     resistance with bearish engulfing")
  2. Entry price zone: specific level or range, not "current price"
  3. Invalidation level: where the setup fails (stop loss)
  4. Target level(s): where to take profit

The purpose is NOT to say "buy now" — it is to say "buy THIS stock at THIS
price WHEN this condition triggers." The user trades manually in TradingView
and needs a setup to wait for, not an instruction to chase. A BUY signal
that says "enter at current price" without a pullback/trigger condition is
as useless as a WATCH — it gives no edge.
```

---

## SECTION C — Scoring and Data-Integrity Holes

### C1. Missing data silently scores as median

`fmp_service.py:1427-1428`:

```python
if value is None:
    return 50.0
```

A TSX small-cap with **no Piotroski, no Altman, no analyst coverage, no insider
data, no fundamentals** scores `50/50/50/50` → composite `50`. That's better
than a real-data stock scoring `40` on one axis. **Data-poor names silently
outrank data-rich ones** in borderline cases. On TSX small-caps where FMP
coverage is thin, this is a serious noise injector.

**Fix:** Either penalize missing data (return 30 for None instead of 50), or
track a coverage count and tie-break in favor of data-rich names at sort time.

### C2. Post-filters pass on missing data

`fmp_service.py:1153-1245` — every check is structured as "if threshold AND
value AND fails → reject." Missing data is never a rejection. Documented as
intentional but combined with C1 it means `piotroski_min: 3` is a paper tiger on
TSX.

**Fix:** Add a `strict_filters: bool = False` flag on `FmpScreenerConfig`. When
true, missing data fails the filter. Turn on for high-conviction strategies like
Value Accumulation.

### C3. `price_change_6m` fetched but never scored

`fmp_service.py:1711`: `stock.price_change_6m = price_chg.sixMonth` — populated.
`_score_momentum` at line 1457 only uses `1d / 1m / 3m / rvol` — 6m is
**silently discarded**. For momentum strategies this is the most important
horizon.

**Fix:** Add `price_change_6m` to `_score_momentum` with weight equal to `3m`.

### C4. `free_float_pct` fetched but never used

`fmp_service.py:1693-1695`: share float is fetched per ticker when
`weight_momentum is not None` (always true). But `free_float_pct` is never read
by `_score_momentum`, `_score_quality`, or `_apply_post_filters`. Wasted API
call per ticker per run.

**Fix:** Either use `free_float_pct` as a quality multiplier (low float = higher
volatility penalty for scalp strategies) or remove the fetch.

### C5. Crypto composite scoring is mostly noise

`screen_crypto` at `fmp_service.py:1334` only populates `price_change_1d`,
`volume`, `rvol`, `market_cap`. Other momentum fields (1m, 3m, 6m), all
fundamentals, quality, sentiment are `None`. Per C1, all unset axes default
to 50. **Three of four scoring dimensions for crypto are pure noise.**

**Fix:** For crypto, zero out `weight_fundamental`, `weight_quality`,
`weight_sentiment` at config build time. Compute composite from momentum only.
Or fetch multi-period price changes via a separate crypto-specific endpoint if
available.

### C6. Percentile rank slightly biased

`fmp_service.py:1432`:
`rank = sum(1 for v in clean if v <= value) / len(clean) * 100` is the
cumulative ≤ rank. Ties all score the same (100 in a uniform pool). Minor but
compounds C1. Use the average rank formula for ties or `< value` then add
half-tie credit.

---

## SECTION D — Screener Design Holes

### D1. Schema can't express technical setups

`schemas.py:728-810` — `FmpScreenerConfig` has zero technical-indicator fields.
You can't write `ema_50_above_ema_200: True`, `rsi_daily_range: [55, 70]`,
`bb_width_pct_max: 20`, or `distance_from_52wk_high_pct_max: 5`. **The data
model itself prevents the screener from ever doing what the strategies
describe.**

**Fix:** Extend schema with a `technical_filters` nested model:

```python
class TechnicalFilters(BaseModel):
    ema_stack: Literal["bullish", "bearish", "none"] | None = None  # 9>21>50>200 or reverse
    ema_50_vs_200: Literal["golden_cross", "death_cross", "above", "below"] | None = None
    rsi_period: int = 14
    rsi_min: float | None = None
    rsi_max: float | None = None
    adx_min: float | None = None  # trend strength
    bb_width_percentile_max: float | None = None  # squeeze detection
    distance_from_52wk_high_pct_max: float | None = None
    distance_from_52wk_low_pct_min: float | None = None

class FmpScreenerConfig(BaseModel):
    ...existing fields...
    technical_filters: TechnicalFilters | None = None
```

Wire into `screen_and_enrich` by calling `fetch_technical_indicator` for each
surviving candidate after post-filter, computing pass/fail per the strategy's
`technical_filters`, and dropping failures before composite scoring. Accept the
extra API cost — it's the only way to match screener output to `ta_focus`.

### D2. Fallback amplifies bad pools

`orchestrator.py:617-620`: when Perplexity returns nothing, use top-N from FMP.
But "Perplexity returned nothing" often means the pool was weak. The fallback
pushes those weak names through the rest of the pipeline under a `fmp_fallback`
label.

**Fix:** Require `composite_score >= 60` for fallback. Otherwise abort with a
user-visible "pool too weak — try relaxing filters or different strategy" error.

### D3. `max_sector_concentration: 3` applied post-sort can drop good picks

`fmp_service.py:1927-1928`: sector cap runs AFTER `sort + limit`. In a small TSX
pool where 4-5 tech names occupy the top 10, you drop the 4th-best. Works
against pools where the strategy intentionally fishes in a hot sector during
sector rotation.

**Fix:** Apply sector cap **before** `limit` so we evaluate more candidates per
sector. Optionally: disable sector cap when regime is `sector_rotation`.

### D4. Regime adjuster only re-weights; doesn't re-filter

`fmp_service.py:1585-1617`: `apply_regime_weight_adjustments` only touches the 4
scoring weights. It doesn't relax/tighten filters, doesn't shift
country/exchange, doesn't add setup-type filters. In `trending_bull` the
universe should arguably expand beyond TSX-only; in `high_volatility`
post-filters should tighten.

**Fix:** Add `apply_regime_filter_adjustments` that mutates filter thresholds
(not just weights) based on regime. E.g., `high_volatility` → `roe_min += 3`,
`altman_z_min += 0.5`, `beta_max -= 0.5`.

### D5. Strategy-level filter misconfigurations in `strategies.json`

**Momentum Breakout** (`strategies.json:52-84`):

- `price_change_3m_min: 5.0` is flat, not momentum. Should be
  `price_change_6m_min: 20.0` + `price_change_3m_min: 10.0`.
- `price_change_1m_min: 0.0` is "not losing money," not "breaking out."
- `beta_min: 1.0` excludes MSFT/WMT-class trend leaders with beta < 1. Drop the
  floor.
- Remove `piotroski_min`, `altman_z_min`, `roe_min` — these are value metrics,
  not momentum.

**Bollinger Band Squeeze** (`strategies.json:219-247`):

- `price_change_1m_min: -20.0 / max: 12.0` is "anything that hasn't moved," not
  "compressed volatility."
- Needs a real BB-width filter (requires D1).

**EMA 50/200 Golden Cross** (`strategies.json:136-167`):

- No EMA comparison filter exists in config. Just `price_change_3m_min: 2.0`.
- Without D1's `ema_50_vs_200: "golden_cross"` filter, this strategy can never
  actually screen for its name.

**Earnings Play** (`strategies.json:463-485`):

- `min_earnings_beat_pct: 50.0` on a TSX-14-day window produces 2-5 forced
  picks.
- Lower to 30.0 or drop `min_earnings_beat_pct` entirely (let GPT weigh beat
  history).

**Mean Reversion** (`strategies.json:301-326`):

- `price_change_1m_min: -45.0 / max: -3.0` is a falling-knife filter.
- Needs an oversold RSI gate (requires D1 + A3 fix): `rsi_max: 35`.

**Intraday Scalp** (`strategies.json:539-559`):

- `price_change_1d_min: 0.5` is very weak. Should be `rvol_min: 2.0` +
  `price_change_1d_min: 1.5`.

**All strategies**:

- Drop `piotroski_min: 3`, `altman_z_min: 1.8`, `roe_min: 5.0` from non-value
  strategies. Keep only on Value Accumulation.

### D6. TSX universe is small (but stays as default)

All stock strategies default to `country: "CA"` + `exchange: "TSX"`. TSX has
~1,500 listings, ~200 liquid. After market-cap + quality floors → 30-80 names.
You'll see the same symbols repeatedly regardless of screening.

**NOTE:** CA/TSX defaults are **intentional and must remain the fallback**. We
are Canadian traders — when no exchange is specified or a strategy doesn't
override, the system must always default to Canadian markets.

**Fix:** Support an _optional_ universe list like `country: ["CA", "US"]` or
`exchange: ["TSX", "NASDAQ", "NYSE"]` for strategies that want broader reach.
Schema change plus FMP screener parameter handling (multiple calls, merge).
CA/TSX remains the default when the field is omitted or empty.

---

## SECTION E — Recommended Fix Order (Impact / Effort)

Ranked by **watch-rate reduction per hour of work**:

### Phase 1 — Critical (~1 hour total, massive watch-rate reduction)

1. **Fix ticker-key mismatch in `fmp_map` construction** (A1). One edit in
   `orchestrator.py:494, 503`. Re-enables entire FMP context pipeline for TSX.
   Likely the single biggest watch-rate drop. **~30 min including verification
   test.**
2. **Wire `format_fmp_for_claude` into `stages/claude.py`** (A2). Claude chart
   read starts seeing fundamentals. **~15 min.**
3. **Remove the "R:R 2:1 → WATCH" auto-downgrade** from
   `prompts/gpt_debate.py:362` (B1). Replace with "flag as risk factor." **~5
   min.**
4. **Rebalance confidence-label mapping** so WATCH → c2-c4, BUY/SHORT → c5+
   (B2). **~10 min.**

### Phase 2 — Strategy config cleanup (~30 min)

1. **Drop `piotroski_min`/`altman_z_min`/`roe_min` from momentum strategies**
   (D5). Edit `strategies.json` — remove from Momentum Breakout, BB Squeeze,
   Intraday Scalp, Earnings Play. Keep on Value Accumulation and Mean Reversion.
2. **Fix Momentum Breakout thresholds**: `price_change_6m_min: 20.0`,
   `price_change_3m_min: 10.0`, remove `beta_min: 1.0` (D5).
3. **Lower `min_earnings_beat_pct` to 30.0** on Earnings Play (D5).
4. **Require `composite_score >= 60` for FMP fallback** in
   `orchestrator.py:617-620` (D2).

### Phase 3 — Scoring integrity (~45 min)

1. **Use `price_change_6m` in `_score_momentum`** (C3). Single function edit.
2. **Penalize missing data in `_percentile_rank`** — return 30 not 50 (C1).
   Single function edit.
3. **Remove `free_float_pct` fetch or use it** (C4). Delete 3 lines in
   `_enrich_extended`.
4. **Delete dead `filter_by_rsi`** (A3). Or fix + wire properly (requires D1
   first).

### Phase 4 — Prompt hardening (~30 min)

1. **Add affirmative BUY mandate** to `JUDGE_SYSTEM_PROMPT` (B3).
   Counter-balance the existing WATCH escape hatches.

### Phase 5 — Schema extension (big lift, ~4 hours)

1. **Extend `FmpScreenerConfig` with `technical_filters`** (D1). Schema +
   `screen_and_enrich` wiring + per-strategy RSI/EMA/ADX gates. This is the only
   thing that closes the strategy-screener gap at the root. Requires
   `fetch_technical_indicator` per-candidate calls.
2. **Wire backfilled RSI/EMA/BB checks into strategies** (uses D1). Update all
   `strategies.json` entries to use `technical_filters`.

### Phase 6 — Universe expansion (~2 hours)

1. **Support optional multi-exchange `exchange: ["TSX", "NASDAQ"]`** (D6).
   Schema change + `screen_stocks` parallel calls + merge. CA/TSX stays as
   default fallback — only strategies that explicitly opt in get broader
   universes.
2. **Add regime-based filter adjustments** (D4). New
   `apply_regime_filter_adjustments` function.

### Phase 7 — Crypto fixes (~30 min)

1. **Zero out non-momentum weights for crypto** when `is_crypto=True` (C5).
   Single function edit in `screen_crypto` or `compute_composite_scores`.

---

## Success Metrics

After Phase 1 lands, watch a 2-day window:

- **Target**: WATCH rate drops from >50% to <30% of total recommendations.
- **Side check**: judge reasoning for BUY/SHORT should now cite specific FMP
  composite scores, Piotroski, analyst targets. If reasoning still says "limited
  fundamental data available" for TSX, the fix didn't land.
- **Regression check**: NO_TRADE rate shouldn't spike — that would indicate
  judge is now over-committing to no-edge calls. Expect NO_TRADE to stay flat.

Log the stage metadata field `fmp_candidates_count` alongside the judge's action
for each ticker in a dashboard. If `fmp_candidates_count > 0` but judge cites
"no fundamental data," the ticker-key fix is still broken somewhere.

---

## Files Touched (Phase 1-4)

- `src/backend/pipeline/orchestrator.py` — lines 494, 503 (A1); 617-620 (D2)
- `src/backend/pipeline/stages/claude.py` — new `format_fmp_for_claude` wiring
  (A2)
- `src/backend/pipeline/prompts/gpt_debate.py` — lines 362 (B1); 312-314 (B2);
  new BUY mandate (B3)
- `src/backend/services/fmp_service.py` — lines 1427-1433 (C1); 1457-1474 (C3);
  1693-1695 (C4); delete 881-927 (A3)
- `templates/strategies.json` — remove value floors from momentum strategies
  (D5); fix Momentum Breakout thresholds (D5); lower Earnings Play beat rate
  (D5)

## Files Touched (Phase 5-7)

- `src/backend/pipeline/schemas.py` — new `TechnicalFilters` model, extend
  `FmpScreenerConfig` (D1)
- `src/backend/services/fmp_service.py` — wire technical filters into
  `screen_and_enrich`, new regime filter adjuster (D1, D4); support
  multi-exchange in `screen_stocks` (D6); fix crypto weights (C5)
- `templates/strategies.json` — populate new `technical_filters` on every
  strategy (D1)
