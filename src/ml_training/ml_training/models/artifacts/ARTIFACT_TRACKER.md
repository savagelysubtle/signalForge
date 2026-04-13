# SignalForge ML Artifact Tracker — v2

> Started 2026-04-12. Previous tracker: `archive/ARTIFACT_TRACKER_v1_pre_strategy_overhaul.md`

---

## Pipeline Changes (2026-04-12)

### Strategy Overhaul

Rationalized from 14+ strategies to 9 granular types. Dropped: EMA 21 Pullback,
EMA Stack Momentum Intraday, Opening Range Breakout, VWAP Reversal Scalp, and
generic `swing`/`intraday` buckets.

| Strategy Type | R:R | Horizon |
|---|---|---|
| `momentum_breakout` | 3.0:1 | 5 bars |
| `golden_cross_swing` | 2.5:1 | 10 bars |
| `bb_squeeze_breakout` | 1.5:1 | 5 bars |
| `mean_reversion` | 1.5:1 | 5 bars |
| `value_accumulation` | 1.33:1 | 40 bars |
| `earnings_play` | 2.5:1 | 5 bars |
| `intraday_scalp` | 1.2:1 | 5 bars |
| `crypto_swing` | 2.0:1 | 5 bars |
| `crypto_intraday_scalp` | 1.2:1 | 5 bars |

### Barrier Config Fixes

- Mean Reversion profit_mult 1.0→1.5 (R:R was broken at 0.67:1, now 1.5:1)
- All barrier config keys now match granular strategy types (were mismatched)
- Golden Cross horizon 5→10 bars, Value Accumulation 20→40 bars

### New Features (10)

`williams_r`, `bb_position`, `bb_width_percentile`, `squeeze_duration`,
`range_compression_20d`, `volume_surge`, `ema_50_200_cross_direction`,
`ema_50_200_cross_recency`, `rsi_divergence`, `oversold_duration`

Moved to inference-available: `bollinger_width`, `distance_from_20d_high`,
`distance_from_20d_low`

### Primary Signal Rewrite

`compute_primary_signal()` rewritten with unique logic per strategy (momentum
breakout uses 20d high breakout + volume surge, golden cross uses EMA 50/200
crossover, mean reversion uses RSI extremes + divergence, etc.)

### CLI: `--fresh` Flag

New flag on `train` command — clears `dead_features.json`, `tuned_params.json`,
archives old `.joblib`/`_meta.json`, auto-sets `--no-tuned`.

### Backend/Frontend Sync

Scanner rules, gate R:R, feature mapper, risk validator, frontend labels/colors
all updated for 9 granular strategy types.

### Artifact Subfolder Structure

Models now save to per-strategy subdirectories: `artifacts/combined/`,
`artifacts/momentum_breakout/`, etc. Baseline report scans all subdirs.
`--fresh` archives from subfolders and cleans up empty dirs.

### Default Independent Only

`--model-mode` default changed from `both` to `independent`. Shadow model
only trained on explicit `--model-mode shadow` or `--model-mode both`.

---

## Dataset (2026-04-12)

| Metric | Value |
|---|---|
| Total samples | 1,389,324 |
| Features (inference-only) | 48 used / 124 in dataset |
| Training split | 1,180,925 (85%) |
| Holdout split | 208,399 (15%) |
| Tickers | ~987 (434 TSX, 503 US, 50 crypto) |
| Timeframes | D, W, 4H, 1H, 15m |

---

## Run Log

### Run 1: Fresh Combined Baseline (2026-04-12)

**Command:** `train --fresh --inference-only --rounds 3`
**Artifact:** `combined/model_v1_20260412.joblib`

| Metric | Value |
|---|---|
| Mode | independent |
| Accuracy | 55.1% |
| Brier Score | 0.2499 |
| Overfit Gap | -2.2% |
| ECE | 0.0000 |
| Verdict | CONDITIONAL_PASS |
| Features used | 48 (0 with non-zero SHAP) |
| CV Folds | 8 |
| Boost rounds | 500 (best_iter=1 on all folds) |

**Approved strategies:** all 9 (bb_squeeze_breakout, crypto_intraday_scalp,
crypto_swing, earnings_play, golden_cross_swing, intraday_scalp,
mean_reversion, momentum_breakout, value_accumulation)

**Notes:**
- Default LightGBM params, no tuning applied
- Trees stop at iteration 1 — learning rate too conservative for this dataset
- All SHAP importances are 0.0 (trees too shallow to produce meaningful splits)
- Holdout eval fails (object dtype issue, see Known Issues #1)
- Training time: ~42s (independent only)

### Run 2: Optuna Tune 50 Trials — Broken GT-Score (2026-04-12)

**Command:** `tune --inference-only --n-trials 50`
**Result:** Best composite=0.7577 — but produced same best_iter=1 models

The old GT-Score objective (`raw_brier_skill - 2*gap - 5*variance`) gave
do-nothing models a free 0.75 baseline. Optuna converged on extreme
regularization: `reg_lambda=24`, `min_gain_to_split=0.22`, preventing any
meaningful splits. Training with these params produced identical 55.1% accuracy.

### GT-Score Fix (2026-04-12)

Three bugs fixed in `hyperparameter_tuning.py` and `predictor.py`:

1. **Scoring: Raw Brier → Brier Skill Score (BSS)**
   - Old: `1 - brier_score_loss()` → naive model scores 0.75
   - New: `1 - (BS_model / BS_naive)` → naive model scores 0.0
2. **Composite formula reworked**
   - Old: `mean_test - 2*gap - 5*variance` (rewarded underfitting via negative gap)
   - New: `mean_test - 1*max(gap,0) - 3*variance - learning_penalty`
   - Learning penalty: -0.3 if median best_iter≤1, -0.1 if ≤3, 0 otherwise
3. **`_decay_lambda` param leak fixed**
   - `_decay_lambda` was stored in classifier_params → passed to LGBMClassifier
     as invalid kwarg, silently corrupting param state
   - Now popped from params and applied to CPCVConfig sample weights instead
   - Training sample weights used hardcoded `decay_lambda=0.05` instead of
     the tuned value — now uses the tuned value

**Search space widened** to prevent over-regularization:
`num_leaves` 7-31→15-63, `learning_rate` 0.005-0.05→0.01-0.1,
`min_child_samples` 50-300→20-150, `reg_lambda` 1-50→0.1-10,
`min_gain_to_split` 0.01-1.0→0.001-0.1, `max_depth` 3-6→4-8

### Run 3: Optuna Tune 50 Trials — Fixed GT-Score (2026-04-12)

**Command:** `tune --inference-only --n-trials 50`
**Best composite:** -0.0010 (BSS scale; naive=0.0)
**Duration:** ~10.5 min

Best params found:
| Param | Old (broken) | New (fixed) |
|---|---|---|
| `num_leaves` | 30 | 54 |
| `learning_rate` | 0.006 | 0.016 |
| `min_child_samples` | 187 | 137 |
| `reg_alpha` | 1.53 | 0.61 |
| `reg_lambda` | 24.0 | 0.46 |
| `max_depth` | 4 | 7 |
| `min_gain_to_split` | 0.22 | 0.001 |
| `_decay_lambda` | 0.006 | 0.002 |

### Run 4: Tuned Training — Fixed GT-Score (2026-04-12)

**Command:** `train --inference-only --rounds 3`
**Artifact:** `combined/model_v4_20260412.joblib`

| Metric | Run 1 (untuned) | Run 4 (tuned+fixed) | Delta |
|---|---|---|---|
| Mode | independent | independent | — |
| Accuracy | 55.1% | **56.0%** | +0.9pp |
| Brier Score | 0.2499 | **0.2451** | -0.005 |
| Overfit Gap | -2.2% | **-0.3%** | healthier |
| ECE | 0.0000 | **0.0017** | actual calibration |
| Verdict | CONDITIONAL_PASS | **PASS** | upgraded |
| Active features | 0 | **35** | model learns |
| Ensemble rounds | 1 | **30** | real ensemble |
| best_iter range | 1 (all folds) | **1-142** | trees grow |

**Top SHAP features (v4):**
`tf_D_rsi_14=0.012`, `market_breadth_proxy=0.010`, `strategy_type=0.008`,
`month=0.008`, `vix_level=0.007`, `price_vs_ema_200=0.006`,
`market_regime=0.003`, `atr_pct=0.002`, `day_of_week=0.002`,
`squeeze_duration=0.002`

**Notes:**
- First PASS verdict on combined model
- Model differentiates strategies (`strategy_type` SHAP=0.008)
- Macro features matter: `vix_level`, `market_breadth_proxy`, `month`
- Technical features contribute: `tf_D_rsi_14`, `price_vs_ema_200`, `atr_pct`
- Holdout eval still fails (Known Issue #1)

### Run 5: Per-Strategy Baselines — Untuned (2026-04-12)

**Command:** `train --fresh --inference-only --per-strategy --rounds 3`

| Strategy | Acc | Brier | Gap | Verdict | Active Feats | Samples |
|---|---|---|---|---|---|---|
| earnings_play | 65.9% | 0.2242 | -2.7% | COND_PASS | 6 | 72,154 |
| golden_cross_swing | 63.4% | 0.2331 | -4.6% | COND_PASS | 9 | 44,113 |
| mean_reversion | 60.9% | 0.2365 | -0.8% | COND_PASS | 18 | 72,154 |
| value_accumulation | 58.5% | 0.2430 | -1.8% | PASS | 6 | 108,805 |
| momentum_breakout | 58.0% | 0.2442 | -3.3% | PASS | 11 | 35,520 |
| bb_squeeze_breakout | 55.6% | 0.2457 | -2.3% | COND_PASS | 23 | 50,843 |
| intraday_scalp | 53.7% | 0.2488 | +0.5% | COND_PASS | 19 | 18,110 |
| crypto_intraday_scalp | 52.7% | 0.2490 | -1.1% | COND_PASS | 9 | 126,147 |
| crypto_swing | 52.4% | 0.2552 | +0.0% | FAIL | 12 | 653,074 |

**Mean accuracy: 57.9%** (vs 56.0% combined). All models use features (6-23 active).

### Run 6: Per-Strategy Optuna Tune 50 Trials (2026-04-12)

**Command:** `tune --inference-only --per-strategy --n-trials 50`

| Strategy | Best BSS | Duration |
|---|---|---|
| earnings_play | **+0.0120** | ~5 min |
| mean_reversion | **+0.0106** | ~5 min |
| crypto_swing | +0.0002 | ~9 min |
| value_accumulation | -0.0020 | ~5 min |
| intraday_scalp | -0.0046 | ~3 min |
| crypto_intraday_scalp | -0.0047 | ~4 min |
| bb_squeeze_breakout | -0.0080 | ~3 min |
| momentum_breakout | -0.0102 | ~3 min |
| golden_cross_swing | -0.0149 | ~3 min |

Two strategies achieved positive BSS (earnings_play, mean_reversion).

### Run 7: Per-Strategy Tuned Training (2026-04-12)

**Command:** `train --inference-only --per-strategy --rounds 3`

| Strategy | Untuned | Tuned | Delta | Verdict |
|---|---|---|---|---|
| earnings_play | 65.9% | **67.2%** | +1.3pp | COND_PASS |
| golden_cross_swing | 63.4% | **63.6%** | +0.2pp | COND_PASS |
| mean_reversion | 60.9% | **62.0%** | +1.1pp | COND_PASS |
| value_accumulation | 58.5% | **59.6%** | +1.1pp | COND_PASS |
| momentum_breakout | 58.0% | **58.0%** | +0.0pp | COND_PASS |
| crypto_swing | 52.4% | **55.0%** | +2.6pp | COND_PASS |
| bb_squeeze_breakout | 55.6% | 54.9% | -0.7pp | COND_PASS |
| crypto_intraday_scalp | 52.7% | **53.8%** | +1.1pp | COND_PASS |
| intraday_scalp | 53.7% | 53.5% | -0.2pp | COND_PASS |

**Mean accuracy: 58.6%** (up from 57.9% untuned). Tuning improved 7 of 9 strategies.
Biggest gains: crypto_swing +2.6pp, earnings_play +1.3pp, mean_reversion +1.1pp.

**Top SHAP features across strategies:**
- `tf_D_rsi_14` dominates earnings_play (0.110) and mean_reversion (0.067)
- `month` is universally important (seasonal patterns)
- `market_breadth_proxy` drives earnings_play and crypto_intraday_scalp
- `bollinger_width` and `atr_pct` drive volatility strategies (bb_squeeze, golden_cross)
- `momentum_score` appears in mean_reversion and value_accumulation

### Pipeline Fixes Before Run 8 (2026-04-12)

Three targeted fixes applied before re-training:

1. **Re-enabled fundamental features for earnings_play + golden_cross_swing**
   - `_apply_strategy_feature_mask()` was dropping all 15 fundamental features
     unless strategy name contained `"value"`. Now uses explicit allowlist:
     `{value_accumulation, earnings_play, golden_cross_swing}`.
   - earnings_play gets 59→88 features (vs Run 7: 44 features, fundamentals stripped)

2. **Fixed intraday_scalp data pipeline**
   - `_HORIZON_MAP`: `("intraday_scalp", "4H"): 3→8` (12h→32h, ~1.5 trading days)
   - `_HORIZON_MAP`: `("crypto_intraday_scalp", "4H"): 6→8` for consistency
   - Added `"additional_timeframes": ["D"]` to both scalp templates in
     `strategies.json` — unlocks `tf_D_rsi_14`, `tf_D_price_vs_ema_200`, etc.
   - intraday_scalp features: 92→110, crypto_intraday_scalp: 92→110

3. **Made `primary_signal` numeric instead of categorical**
   - Was `FeatureType.CATEGORICAL` despite values `{-1, 0, 1}` having ordinal meaning
   - Changed to `FeatureType.NUMERIC` with `min_val=-1, max_val=1`
   - LightGBM can now split on thresholds (`signal > -0.5`) not just equality

### Run 8: Per-Strategy Fresh Training with Fixes (2026-04-12)

**Command:** `build-dataset --augment` then `train --fresh --inference-only --per-strategy --rounds 3`
**Dataset:** 1,389,324 samples, 122 features, 9 strategies

| Strategy | Run 7 | Run 8 | Delta | Verdict | Active Feats | Samples |
|---|---|---|---|---|---|---|
| earnings_play | 67.2% | **65.8%** | -1.4pp | COND_PASS | 8 | 72,154 |
| golden_cross_swing | 63.6% | **63.4%** | -0.2pp | COND_PASS | 9 | 44,113 |
| mean_reversion | 62.0% | **60.9%** | -1.1pp | COND_PASS | 18 | 72,154 |
| intraday_scalp | 53.5% | **61.3%** | **+7.8pp** | FAIL* | 28 | 18,110 |
| momentum_breakout | 58.0% | **58.0%** | +0.0pp | PASS | 8 | 35,520 |
| value_accumulation | 59.6% | **58.6%** | -1.0pp | COND_PASS | 7 | 108,805 |
| bb_squeeze_breakout | 54.9% | **55.6%** | +0.7pp | COND_PASS | 35 | 50,843 |
| crypto_intraday_scalp | 53.8% | **55.4%** | +1.6pp | COND_PASS | 6 | 126,147 |
| crypto_swing | 55.0% | **52.3%** | -2.7pp | FAIL | 13 | 653,074 |

**Mean accuracy: 59.0%** (vs 58.6% Run 7). Mixed results — explained below.

**Key observations:**
- **intraday_scalp: massive +7.8pp gain** (53.5→61.3%). The wider horizon (3→8 bars)
  and `tf_D_*` features transformed this strategy. `tf_D_rsi_14` is now its #1
  feature (SHAP=0.413). Verdict is FAIL due to +14.1% overfit gap — needs tuning
  with stronger regularization.
- **crypto_intraday_scalp: +1.6pp** from daily timeframe features
- **bb_squeeze_breakout: +0.7pp**, feature count jumped 23→35
- **earnings_play: -1.4pp** — this is untuned fresh model vs Run 7's tuned model.
  With tuning, should recover and likely improve with fundamentals restored.
- **crypto_swing: -2.7pp** — fresh untuned vs Run 7 tuned. Needs per-strategy tuning.
- Other strategies within noise range for untuned vs tuned comparison.

**Top SHAP features:**
- `tf_D_rsi_14` now dominates intraday_scalp (0.413!) and mean_reversion (0.050)
- `bollinger_width` leads bb_squeeze_breakout (0.052)
- `market_breadth_proxy` leads crypto_intraday_scalp, earnings_play, mean_reversion
- `price_vs_ema_50` contributes to earnings_play (0.010)

**Next steps:** Per-strategy Optuna tuning to optimize the new feature sets.
Intraday_scalp especially needs tuning to reduce its 14% overfit gap.

### Run 9: Per-Strategy Optuna Tune + Tuned Training (2026-04-13)

**Tune command:** `tune --inference-only --per-strategy --n-trials 50`
**Train command:** `train --inference-only --per-strategy --rounds 3`
**Duration:** Tune ~11.5 min, Train ~51s

**Tuning BSS scores:**

| Strategy | Run 6 BSS | Run 9 BSS | Delta |
|---|---|---|---|
| earnings_play | +0.0120 | **+0.0146** | +0.0026 |
| mean_reversion | +0.0106 | **+0.0084** | -0.0022 |
| crypto_intraday_scalp | -0.0047 | **+0.0059** | +0.0106 |
| intraday_scalp | -0.0046 | **+0.0045** | +0.0091 |
| crypto_swing | +0.0002 | **-0.0005** | -0.0007 |
| value_accumulation | -0.0020 | **-0.0025** | -0.0005 |
| bb_squeeze_breakout | -0.0080 | **-0.0087** | -0.0007 |
| momentum_breakout | -0.0102 | **-0.0102** | +0.0000 |
| golden_cross_swing | -0.0149 | **-0.0160** | -0.0011 |

4 strategies now have positive BSS (vs 2 in Run 6). The two scalp strategies
flipped from negative to positive after horizon + multi-TF fixes.

**Tuned training results (Run 9 vs Run 8 untuned vs Run 7 tuned):**

| Strategy | Run 7 Tuned | Run 8 Untuned | Run 9 Tuned | R9 vs R8 | R9 vs R7 | Verdict |
|---|---|---|---|---|---|---|
| earnings_play | 67.2% | 65.8% | **66.9%** | +1.1pp | -0.3pp | COND_PASS |
| golden_cross_swing | 63.6% | 63.4% | **63.7%** | +0.3pp | +0.1pp | PASS |
| mean_reversion | 62.0% | 60.9% | **62.3%** | +1.4pp | +0.3pp | COND_PASS |
| value_accumulation | 59.6% | 58.6% | **59.3%** | +0.7pp | -0.3pp | COND_PASS |
| bb_squeeze_breakout | 54.9% | 55.6% | **56.1%** | +0.5pp | +1.2pp | COND_PASS |
| crypto_intraday_scalp | 53.8% | 55.4% | **58.5%** | **+3.1pp** | **+4.7pp** | COND_PASS |
| momentum_breakout | 58.0% | 58.0% | **57.8%** | -0.2pp | -0.2pp | COND_PASS |
| intraday_scalp | 53.5% | 61.3% | **57.5%** | -3.8pp | **+4.0pp** | COND_PASS |
| crypto_swing | 55.0% | 52.3% | **54.7%** | +2.4pp | -0.3pp | COND_PASS |

**Mean accuracy: 59.6%** (vs 59.0% Run 8, 58.6% Run 7). Best overall mean yet.

**Key observations:**
- **crypto_intraday_scalp: biggest winner at 58.5%** (+4.7pp vs Run 7). Tuning
  unlocked the new daily TF features — `tf_D_rsi_14` (SHAP=0.075) now drives it.
  Feature usage jumped from 6→33 active features.
- **intraday_scalp: 57.5%** (+4.0pp vs Run 7). Tuning tamed the +14.1% overfit gap
  from Run 8 down to +0.2% — much healthier. Accuracy dropped vs untuned (61.3%)
  but the overfitting was unsustainable; 57.5% with near-zero gap is more reliable.
- **bb_squeeze_breakout: 56.1%** (+1.2pp vs Run 7 best). New all-time high.
- **golden_cross_swing: 63.7% PASS** — only PASS verdict. Healthy -4.0% gap.
- **Feature usage: 64% mean** (vs 37% in Run 8). Tuning activated many more features.
- **All 9 strategies COND_PASS or better** — no FAILs (vs 2 FAILs in Run 8).
- **Overfit gaps all healthy** — worst is crypto_intraday_scalp at +3.9% (vs 14.1%
  for intraday_scalp in Run 8). Tuning regularized effectively.

**Top SHAP features across strategies:**
- `tf_D_rsi_14` dominates earnings_play (0.106), mean_reversion (0.099),
  crypto_intraday_scalp (0.075), value_accumulation (0.037)
- `market_breadth_proxy` key for crypto_intraday_scalp (0.066), mean_reversion
  (0.063), earnings_play (0.049), value_accumulation (0.041)
- `momentum_score` drives mean_reversion (0.059), earnings_play (0.049)
- `price_vs_ema_200` drives earnings_play (0.064)
- `ema_spread_pct` newly important for value_accumulation (0.037)
- `tf_D_momentum_score` leads intraday_scalp (0.017)

### Pipeline Fixes Before Run 10 (2026-04-13)

Four targeted improvements to model training and tuning:

1. **Adaptive feature pruning** — `_prune_features()` now scales prune fraction
   inversely with feature count (30% for 25+ features, 20% for 15-25, 15% for
   ≤15) and enforces a 12-feature minimum floor. Prevents pruning spiral on
   low-feature strategies.

2. **Dataset-scaled model complexity** — New `_scale_default_params()` in
   `PredictionModel`. For >200K samples: `num_leaves=31, max_depth=7,
   min_child_samples=300`. For >50K: `num_leaves=23, max_depth=6,
   min_child_samples=150`. Only applies when using default (untuned) params.

3. **Optuna search fixes** — `min_child_samples` range now adaptive:
   `[20, max(150, n_samples//2000)]`. `bagging_freq=5→1` in saved params
   template to match search. Default `n_trials` 30→50.

4. **Bug fixes** — Dead feature counter changed from `dict[str, int]` to
   `dict[str, list[str]]` tracking strategy names (prevents double-counting).
   Exception syntax `except JSONDecodeError, KeyError` → `except (...):`.

### Run 10: Per-Strategy Tuned Training with v2 Fixes (2026-04-13)

**Tune command:** `tune --inference-only --per-strategy --n-trials 50`
**Train command:** `train --inference-only --per-strategy --rounds 3`

**Tuning BSS scores (Run 10 vs Run 9):**

| Strategy | Run 9 BSS | Run 10 BSS | Delta |
|---|---|---|---|
| crypto_intraday_scalp | +0.0059 | **+0.0111** | +0.0052 |
| mean_reversion | +0.0084 | **+0.0099** | +0.0015 |
| earnings_play | +0.0146 | **+0.0097** | -0.0049 |
| intraday_scalp | +0.0045 | **+0.0018** | -0.0027 |
| crypto_swing | -0.0005 | **+0.0003** | +0.0008 |
| value_accumulation | -0.0025 | **-0.0015** | +0.0010 |
| bb_squeeze_breakout | -0.0087 | **-0.0082** | +0.0005 |
| momentum_breakout | -0.0102 | **-0.0099** | +0.0003 |
| golden_cross_swing | -0.0160 | **-0.0156** | +0.0004 |

5 strategies improved BSS, crypto_swing flipped to positive. Adaptive
`min_child_samples` range particularly helped crypto_intraday_scalp (+0.0052).

**Tuned training results (Run 10 vs Run 9):**

| Strategy | Run 9 | Run 10 | Delta | Verdict | Active Feats | Samples |
|---|---|---|---|---|---|---|
| earnings_play | 66.9% | **66.1%** | -0.8pp | COND_PASS | 21 | 72,154 |
| golden_cross_swing | 63.7% | **63.6%** | -0.1pp | PASS | 9 | 44,113 |
| mean_reversion | 62.3% | **61.9%** | -0.4pp | COND_PASS | 18 | 72,154 |
| crypto_intraday_scalp | 58.5% | **61.6%** | **+3.1pp** | COND_PASS | 32 | 126,147 |
| value_accumulation | 59.3% | **59.3%** | +0.0pp | COND_PASS | 27 | 108,805 |
| momentum_breakout | 57.8% | **58.2%** | +0.4pp | COND_PASS | 16 | 35,520 |
| intraday_scalp | 57.5% | **57.5%** | +0.0pp | COND_PASS | 18 | 18,110 |
| bb_squeeze_breakout | 56.1% | **55.1%** | -1.0pp | COND_PASS | 30 | 50,843 |
| crypto_swing | 54.7% | **54.7%** | +0.0pp | COND_PASS | 7 | 653,074 |

**Mean accuracy: 59.8%** (vs 59.6% Run 9). Best mean overall.

**Key observations:**
- **crypto_intraday_scalp: +3.1pp** — biggest winner. Adaptive `min_child_samples`
  let Optuna explore higher regularization for this 126K-sample dataset. Feature
  usage jumped to 32 active. `tf_D_rsi_14` dominates (SHAP=0.263).
- **All 9 strategies COND_PASS or better** — zero FAILs for second consecutive run.
- **All overfit gaps healthy** — worst is crypto_intraday_scalp at +5.7%, improved
  from the rampant 14.1% seen in Run 8. Pruning floor prevents feature starvation.
- **momentum_breakout: +0.4pp** — pruning fix preserved features it needs.
- **Feature usage: 55% mean** — still solid with more features surviving pruning.

**Top SHAP features:**
- `tf_D_rsi_14` dominates crypto_intraday_scalp (0.263), intraday_scalp (0.063),
  value_accumulation (0.050)
- `atr_pct` leads bb_squeeze_breakout (0.059) and golden_cross_swing (0.007)
- `market_breadth_proxy` drives value_accumulation (0.059)
- `ema_spread_pct` newly important for value_accumulation (0.058)

---

## Known Issues

| # | Issue | Status |
|---|---|---|
| 1 | Holdout eval dtype error (object cols: strategy_type, analyst_target_upside, insider_buy_ratio, market_regime, sector, tf_D_ema_stack_score) | Open |
| 2 | GT-Score tuning objective rewarded "do nothing" models | **Fixed** — BSS scoring + learning penalty + search space widened |
| 3 | `_decay_lambda` leaked into LGBMClassifier as invalid param | **Fixed** — popped and applied to sample weights |
| 4 | Baseline report shows stale per-strategy models from pre-overhaul runs | **Fixed** — excluded `archive/` from rglob scan |
| 5 | Dead feature counter double-counted same strategy | **Fixed** — uses strategy name sets instead of int counter |
| 6 | Invalid `except` syntax (comma instead of tuple) in dead feature tracking | **Fixed** — `except (JSONDecodeError, KeyError):` |
| 7 | `bagging_freq` mismatch between Optuna search (1) and saved params (5) | **Fixed** — saved params now use `bagging_freq=1` |
