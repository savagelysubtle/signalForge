---
name: Strategy Overhaul and Features
overview: Archive the current broken strategies.json (13 strategies with dead barrier configs and missing features), replace with 9 real strategies using granular strategy_type keys, fix the barrier config mismatch, add strategy-specific ML features, and update all downstream references (scanner, gate, frontend, feature_spec).
todos:
  - id: archive-strategies
    content: Archive current strategies.json to templates/archive/strategies_v1.json. Create fresh strategies.json with 9 strategies using granular strategy_type keys.
    status: completed
  - id: fix-barrier-configs
    content: Fix STRATEGY_BARRIER_CONFIG, _HORIZON_MAP, FFD_D_BY_STRATEGY to use granular strategy_type keys. Fix Mean Reversion R:R from 0.67:1 to 1.0:1 (profit_mult 1.5). Update _infer_strategy_type().
    status: completed
  - id: fix-primary-signal
    content: Rewrite compute_primary_signal() with real strategy-specific logic for each of the 9 strategies (golden cross uses 50/200 not 9/21, squeeze detects BB compression, earnings uses pre-earnings momentum not constant signal).
    status: completed
  - id: add-strategy-features
    content: "Add strategy-specific ML features: williams_r, bb_position, range_compression_20d, volume_surge, ema_50_200_cross_recency, ema_50_200_cross_direction, bb_width_percentile, squeeze_duration, rsi_divergence, oversold_duration."
    status: completed
  - id: update-feature-spec
    content: Register all new features in feature_spec.py. Move distance_from_20d_high/low and bollinger_width from training-only to inference-available.
    status: completed
  - id: update-backend
    content: Update strategy_scanner.py (remove dropped strategies, update mappings), gate.py (R:R dict), test_ml_gate.py (replace vwap references), feature_mapper.py (new feature mappings).
    status: completed
  - id: update-frontend
    content: Update ScannerResultsGrid.tsx (labels/colors) and resolveScannerStrategy.ts (hint map) to remove dropped strategies.
    status: completed
  - id: rebuild-retrain
    content: Rebuild dataset with new features, train with --inference-only, run baseline_report.py to verify strategy-specific features now have non-zero SHAP importance.
    status: completed
isProject: false
---

# Strategy Overhaul: Real Strategies with Real Features

## Problem Statement

The ML training pipeline has 13 strategies but only 5 actual signal paths. Key
failures:

- **10 of 15 barrier configs are dead code** -- `strategy_type` in
strategies.json uses coarse buckets (`swing`, `intraday`) but
`STRATEGY_BARRIER_CONFIG` has granular keys (`momentum_breakout`,
`bollinger_band_squeeze_breakout`) that never match
- **Zero strategy-specific features** -- all strategies get identical generic TA
features
- **4 strategies are clones** of swing with the same signal (EMA 9 vs 21)
- **Core indicators missing** -- VWAP, Williams %R, Supertrend, crossover
recency, squeeze detection, RSI divergence are listed as chart_indicators but
never computed as ML features

## Strategy Decisions

**KEEP (9 strategies):**


| Strategy                | New strategy_type       | Current                       | Barrier Fix                             |
| ----------------------- | ----------------------- | ----------------------------- | --------------------------------------- |
| Momentum Breakout       | `momentum_breakout`     | `swing` (wrong)               | 3.0:1 (was getting 2.0:1)               |
| EMA 50/200 Golden Cross | `golden_cross_swing`    | `swing` (wrong)               | 2.5:1 (was getting 2.0:1)               |
| Bollinger Band Squeeze  | `bb_squeeze_breakout`   | `swing` (wrong)               | 1.5:1 (was getting 2.0:1)               |
| Mean Reversion          | `mean_reversion`        | correct                       | Fix to 1.5:1 TP (was 1.0:1, underwater) |
| Value Accumulation      | `value_accumulation`    | `value` (dead code)           | 1.33:1 (was getting default 2.0:1)      |
| Earnings Play           | `earnings_play`         | `event` (dead code)           | 2.5:1 (was getting default 2.0:1)       |
| Intraday Scalp          | `intraday_scalp`        | `intraday` (dead code)        | 1.2:1 (was getting 1.5:1)               |
| Crypto Swing            | `crypto_swing`          | correct                       | 2.0:1 (correct)                         |
| Crypto Intraday Scalp   | `crypto_intraday_scalp` | `crypto_intraday` (dead code) | 1.2:1 (was getting 1.5:1)               |


**DROP (4 strategies) -- archive only:**

- EMA 21 Pullback Swing (clone of swing strategies)
- EMA Stack Momentum Intraday (below sample floor, no unique features)
- Opening Range Breakout (below sample floor, no ORB features)
- VWAP Reversal Scalp (no VWAP features, below sample floor)

---

## Phase 0: Archive and Clean strategies.json

- Move `templates/strategies.json` to `templates/archive/strategies_v1.json`
- Create new `templates/strategies.json` with 9 strategies
- Change each strategy's `strategy_type` to the granular key (see table above)
- Everything else in each strategy object stays the same (screening_prompt,
chart_indicators, ta_focus, fmp_screener, etc.)

---

## Phase 1: Fix Barrier Config Key Mismatch

All changes in
[src/ml_training/ml_training/features/engineering.py](src/ml_training/ml_training/features/engineering.py):

- `**STRATEGY_BARRIER_CONFIG`: Clean up to match the 9 new granular keys
exactly. Remove dead entries (`ema_21_pullback`, `ema_stack_momentum`,
`vwap_reversal_scalp`, `intraday`, `crypto_intraday`). Fix Mean Reversion to
`profit_mult: 1.5` (was 1.0, giving 0.67:1 R:R which is underwater at 55.6%
accuracy).
- `**FFD_D_BY_STRATEGY`: Update keys to match new granular types.

In
[src/ml_training/ml_training/features/dataset_builder.py](src/ml_training/ml_training/features/dataset_builder.py):

- `**_HORIZON_MAP`: Replace coarse keys with granular keys:
  - `("momentum_breakout", "D"): 5`
  - `("golden_cross_swing", "D"): 10` (was 5, too short for 1-4 week holds)
  - `("bb_squeeze_breakout", "D"): 7`
  - `("mean_reversion", "4H"): 10` (keep)
  - `("value_accumulation", "4H"): 40` (was 20, too short for 2-8 week holds)
  - `("earnings_play", "4H"): 10` (keep)
  - `("intraday_scalp", "4H"): 3` (keep)
  - `("crypto_swing", "D"): 5` (keep)
  - `("crypto_intraday_scalp", "4H"): 6`
- `**_infer_strategy_type()`: Update to return granular types

---

## Phase 2: Fix compute_primary_signal()

In
[src/ml_training/ml_training/features/engineering.py](src/ml_training/ml_training/features/engineering.py),
rewrite `compute_primary_signal()` with strategy-specific logic:

- `**momentum_breakout`: 20-day high breakout + volume surge (close > 20d high
AND volume_ratio > 1.5)
- `**golden_cross_swing`: EMA 50 vs 200 crossover direction (not EMA 9 vs 21)
- `**bb_squeeze_breakout`: Bollinger bandwidth at 20-day minimum AND price
breakout above upper band
- `**mean_reversion`: RSI < 30 with price near 20-day low (keep existing RSI
logic, add price proximity)
- `**value_accumulation`: 20-day return < -5% AND composite_score > median (add
fundamental filter)
- `**earnings_play`: Replace constant signal=1 with pre-earnings momentum
(close > EMA 50 AND volume declining 5d)
- `**intraday_scalp`: 5-bar high breakout + volume surge (keep existing, add
volume filter)
- `**crypto_swing`: EMA 50 vs 200 (same as golden_cross_swing, appropriate for
crypto)
- `**crypto_intraday_scalp`: 5-bar high breakout (same as intraday)

---

## Phase 3: Add Strategy-Specific ML Features

New features to add in `compute_technical_features()` in
[src/ml_training/ml_training/features/engineering.py](src/ml_training/ml_training/features/engineering.py):

**Universally useful (benefits multiple strategies):**

- `williams_r` -- Williams %R oscillator (needed by 6 strategies). Formula:
`(highest_high_14 - close) / (highest_high_14 - lowest_low_14) * -100`
- `bb_position` -- Position within Bollinger Bands as 0-1 scale. Formula:
`(close - lower_band) / (upper_band - lower_band)`. Needed by squeeze,
mean_rev, value

**Momentum/Breakout features (momentum_breakout, bb_squeeze):**

- `range_compression_20d` -- Ratio of current 5-day range to 20-day range.
Detects coiling/compression before breakout
- `volume_surge` -- Boolean-ish: volume_ratio > 1.5 as 1.0 else 0.0. Clean
breakout confirmation
- `distance_from_20d_high` already exists (training-only) -- move to
inference_available=True

**Crossover features (golden_cross, crypto_swing):**

- `ema_50_200_cross_recency` -- Bars since EMA 50 crossed EMA 200 (0 = cross
today, capped at 60). Critical for golden cross timing
- `ema_50_200_cross_direction` -- +1 if golden cross (50 > 200), -1 if death
cross

**Squeeze features (bb_squeeze):**

- `bb_width_percentile` -- Percentile rank of current bollinger_width vs last
100 days (0-1). Low value = squeeze
- `squeeze_duration` -- Consecutive days with bb_width below its 20-day average

**Reversal features (mean_reversion, value_accumulation):**

- `rsi_divergence` -- Simplified: price making new 14-day low but RSI NOT making
new 14-day low = +1 (bullish divergence), opposite = -1
- `oversold_duration` -- Consecutive bars with RSI < 35

**All new features registered in
[src/ml_training/ml_training/features/feature_spec.py](src/ml_training/ml_training/features/feature_spec.py)**
with `inference_available=True`, appropriate bounds, and types.

---

## Phase 4: Update Backend References

**[src/backend/services/strategy_scanner.py](src/backend/services/strategy_scanner.py):**

- Remove scanner rules for dropped strategies: `ema_21_pullback`,
`ema_stack_momentum`, `opening_range_breakout`, `vwap_reversal_scalp`
- Update `REGIME_ACTIVE_STRATEGIES` to remove dropped entries
- Update `_STRATEGY_TO_MODEL` mappings for new granular strategy_type keys
- Update `_TEMPLATE_TO_SCANNER_RULES` to map each granular type to its own
scanner rules (no more shared `swing` bucket)
- Update `_get_matched_rules` to remove dropped strategies

**[src/backend/ml/gate.py](src/backend/ml/gate.py):**

- Update `_STRATEGY_RR` dict to use new granular keys and correct R:R values
- Remove entries for dropped strategies

**[src/backend/tests/test_ml_gate.py](src/backend/tests/test_ml_gate.py):**

- Replace `vwap_reversal_scalp` test references with a kept strategy (e.g.,
`intraday_scalp`)

---

## Phase 5: Update Frontend References

**[src/frontend/src/components/search/ScannerResultsGrid.tsx](src/frontend/src/components/search/ScannerResultsGrid.tsx):**

- Remove `STRATEGY_LABELS` and `STRATEGY_COLORS` entries for dropped strategies
- Add entries for any new granular keys

**[src/frontend/src/lib/resolveScannerStrategy.ts](src/frontend/src/lib/resolveScannerStrategy.ts):**

- Update `SCANNER_RULE_TO_NAME_HINT` to remove dropped strategies

---

## Phase 6: Update Feature Spec + Inference

**[src/ml_training/ml_training/features/feature_spec.py](src/ml_training/ml_training/features/feature_spec.py):**

- Add all new features from Phase 3 to `_TA_FEATURES` with correct bounds and
`inference_available=True`
- Move `distance_from_20d_high` and `distance_from_20d_low` from training-only
to inference-available (they're just price comparisons, available live)
- Move `bollinger_width` from training-only to inference-available (can be
computed from live data)

**[src/backend/ml/feature_mapper.py](src/backend/ml/feature_mapper.py):**

- Add mappings for new features so the backend can populate them from
`TechnicalSnapshot` at inference time

---

## Phase 7: Rebuild Dataset + Retrain

```bash
cd src/ml_training
uv run --python 3.14t python -X gil=0 -m ml_training.pipeline.cli build-dataset --augment
uv run --python 3.14t python -X gil=0 -m ml_training.pipeline.cli train --inference-only --rounds 3
```

- Verify each strategy now has unique features with non-zero SHAP importance
- Run baseline_report.py to compare vs previous run
- Expect: models that differentiate tickers because they now have
strategy-specific features beyond market_breadth_proxy

---

## Files Modified (Summary)

- `templates/strategies.json` -- archived and recreated (9 strategies, granular
types)
- `src/ml_training/ml_training/features/engineering.py` -- barrier config,
primary signal, new features
- `src/ml_training/ml_training/features/dataset_builder.py` -- horizon map,
infer_strategy_type
- `src/ml_training/ml_training/features/feature_spec.py` -- new feature specs
- `src/backend/services/strategy_scanner.py` -- scanner rules, regime map,
template mapping
- `src/backend/ml/gate.py` -- R:R dict
- `src/backend/ml/feature_mapper.py` -- new feature mappings
- `src/backend/tests/test_ml_gate.py` -- test strategy references
- `src/frontend/src/components/search/ScannerResultsGrid.tsx` -- labels, colors
- `src/frontend/src/lib/resolveScannerStrategy.ts` -- hint map

