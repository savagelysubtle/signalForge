# SignalForge ML Artifact Tracker

> Auto-generated 2026-04-07. Last log update: 2026-04-08 (Optuna v4 snapshot). This document tracks
> model training runs, production deployments, and analysis findings across the
> ML pipeline.

---

## Changelog: pipeline optimization (code) vs latest on-disk artifacts

**What changed in the codebase (ML pipeline optimization — implemented in repo):**

| Area | Change | Files (high level) |
|---|---|---|
| Tuning objective | GT-Score / Optuna now maximizes **(1 − Brier)** on binary folds, **−log loss** on multiclass; grid search logging uses `mean_brier_skill` | `hyperparameter_tuning.py` |
| Sample weights | **Exponential temporal decay** layered on uniqueness weights; `CPCVConfig.decay_lambda` (default 0.05); Optuna searches `decay_lambda`, passes `sample_weight` in CV; tuned value stored as `_decay_lambda` (not a LightGBM arg) | `predictor.py`, `hyperparameter_tuning.py` |
| Cross-validation | Default **8** splits; tiers: n &lt; 5k → cap 3 folds; 5k–100k → cap 5; **purge cap** `n_samples // (effective_splits * 4)` | `predictor.py` |
| Production gate | **Kelly** sizing from per-strategy R:R; **regime** Kelly multiplier; optional **meta-labeler** blend (60/40) when `model_{strategy}_meta_active.joblib` exists | `gate.py`, `inference.py`, `schemas.py` |
| Meta-labeler artifacts | `ModelArtifact.meta_labeler`; training loop persists MetaLabeler when `meta_label=True` | `registry.py`, `training_loop.py` |

**Where the new tuning shows up in artifacts**

| Signal | Meaning |
|---|---|
| `training_config.classifier_params._decay_lambda` | Optuna-selected temporal decay (saved JSON / joblib). **Absent on older runs** (e.g. independent v3 tier). |
| `training_config.n_folds` | **Reported** fold count from the training round (often **5** for 5k–100k row datasets after the small/medium cap; **8** when the full split count is used). |

**Latest batch on disk** — highest `v*` per strategy, suffix `20260407` (same calendar date; newer files supersede v3 / v21–v37 tier). **Optuna + Brier-style objective + decay in CV** apply to artifacts that include `_decay_lambda`.

### Shadow models (2026-04-07, max version — post–Optuna refresh)

| Strategy | Ver | Acc | Brier | OFGap | Judge | n | Folds | decay_λ |
|---|---|---|---|---|---|---|---|---|
| bollinger_band_squeeze_breakout_swing | v30 | 0.5766 | 0.2413 | -0.0063 | CONDITIONAL_PASS | 57,141 | 5 | 0.0503 |
| crypto_intraday_scalp | v22 | 0.5626 | 0.2476 | -0.0090 | CONDITIONAL_PASS | 148,409 | 8 | 0.0131 |
| crypto_swing | v22 | 0.5480 | 0.2508 | -0.0191 | CONDITIONAL_PASS | 763,328 | 8 | 0.0081 |
| earnings_play | v27 | 0.6433 | 0.2293 | -0.0199 | CONDITIONAL_PASS | 84,888 | 5 | 0.0237 |
| ema_21_pullback_swing | v26 | 0.5797 | 0.2420 | -0.0136 | CONDITIONAL_PASS | 63,031 | 5 | 0.0398 |
| ema_50_200_golden_cross_swing | v35 | 0.5904 | 0.2381 | -0.0005 | CONDITIONAL_PASS | 49,685 | 5 | 0.0607 |
| ema_stack_momentum_intraday | v22 | 0.5728 | 0.2433 | 0.0255 | CONDITIONAL_PASS | 13,634 | 5 | 0.0581 |
| intraday | v22 | 0.5667 | 0.2458 | -0.0163 | CONDITIONAL_PASS | 45,093 | 5 | 0.1495 |
| intraday_scalp | v24 | 0.5499 | 0.2477 | -0.0051 | CONDITIONAL_PASS | 21,307 | 5 | 0.1270 |
| mean_reversion | v30 | 0.5611 | 0.2464 | 0.0150 | CONDITIONAL_PASS | 84,888 | 5 | 0.0582 |
| momentum_breakout | v33 | 0.5834 | 0.2435 | -0.0074 | CONDITIONAL_PASS | 40,354 | 5 | 0.1395 |
| swing | v38 | 0.5468 | 0.2477 | -0.0176 | CONDITIONAL_PASS | 210,211 | 8 | 0.0158 |
| value_accumulation | v25 | 0.6719 | 0.2218 | -0.0163 | CONDITIONAL_PASS | 128,329 | 8 | 0.0067 |
| vwap_reversal_scalp | v19 | 0.5732 | 0.2436 | 0.0165 | CONDITIONAL_PASS | 10,152 | 5 | 0.0059 |

### Independent / gate models (2026-04-07, **v4** tier)

| Strategy | Ver | Acc | Brier | OFGap | Judge | n | Folds | decay_λ |
|---|---|---|---|---|---|---|---|---|
| bollinger_band_squeeze_breakout_swing | v4 | 0.5766 | 0.2413 | -0.0063 | CONDITIONAL_PASS | 57,141 | 5 | 0.0503 |
| crypto_intraday_scalp | v4 | 0.5626 | 0.2476 | -0.0090 | CONDITIONAL_PASS | 148,409 | 8 | 0.0131 |
| crypto_swing | v4 | 0.5480 | 0.2508 | -0.0191 | CONDITIONAL_PASS | 763,328 | 8 | 0.0081 |
| earnings_play | v4 | 0.6433 | 0.2293 | -0.0199 | CONDITIONAL_PASS | 84,888 | 5 | 0.0237 |
| ema_21_pullback_swing | v4 | 0.5797 | 0.2420 | -0.0136 | CONDITIONAL_PASS | 63,031 | 5 | 0.0398 |
| ema_50_200_golden_cross_swing | v4 | 0.5904 | 0.2381 | -0.0005 | CONDITIONAL_PASS | 49,685 | 5 | 0.0607 |
| ema_stack_momentum_intraday | v4 | 0.5728 | 0.2433 | 0.0255 | CONDITIONAL_PASS | 13,634 | 5 | 0.0581 |
| intraday | v4 | 0.5667 | 0.2458 | -0.0163 | CONDITIONAL_PASS | 45,093 | 5 | 0.1495 |
| intraday_scalp | v4 | 0.5499 | 0.2477 | -0.0051 | CONDITIONAL_PASS | 21,307 | 5 | 0.1270 |
| mean_reversion | v4 | 0.5611 | 0.2464 | 0.0150 | CONDITIONAL_PASS | 84,888 | 5 | 0.0582 |
| momentum_breakout | v4 | 0.5834 | 0.2435 | -0.0074 | CONDITIONAL_PASS | 40,354 | 5 | 0.1395 |
| swing | v4 | 0.5468 | 0.2477 | -0.0176 | CONDITIONAL_PASS | 210,211 | 8 | 0.0158 |
| value_accumulation | v4 | 0.6719 | 0.2218 | -0.0163 | CONDITIONAL_PASS | 128,329 | 8 | 0.0067 |
| vwap_reversal_scalp | v4 | 0.5732 | 0.2436 | 0.0165 | CONDITIONAL_PASS | 10,152 | 5 | 0.0059 |

### Independent **v3 → v4** (same date folder; new Optuna + `_decay_lambda`)

| Strategy | Acc v3 | Acc v4 | Δ Acc | Brier v3 | Brier v4 | Δ Brier |
|---|---|---|---|---|---|---|
| bollinger_band_squeeze_breakout_swing | 0.5741 | 0.5766 | +0.0025 | 0.2437 | 0.2413 | -0.0024 |
| ema_21_pullback_swing | 0.5775 | 0.5797 | +0.0022 | 0.2421 | 0.2420 | -0.0001 |
| ema_50_200_golden_cross_swing | 0.5786 | 0.5904 | +0.0118 | 0.2429 | 0.2381 | -0.0048 |
| ema_stack_momentum_intraday | 0.5754 | 0.5728 | -0.0026 | 0.2428 | 0.2433 | +0.0004 |
| intraday_scalp | 0.5484 | 0.5499 | +0.0015 | 0.2477 | 0.2477 | ~0 |
| momentum_breakout | 0.5810 | 0.5834 | +0.0025 | 0.2437 | 0.2435 | -0.0002 |
| swing | 0.5433 | 0.5468 | +0.0035 | 0.2479 | 0.2477 | -0.0002 |
| vwap_reversal_scalp | 0.5746 | 0.5732 | -0.0014 | 0.2441 | 0.2436 | -0.0005 |
| crypto_intraday_scalp, crypto_swing, earnings_play, intraday, mean_reversion, value_accumulation | (unchanged acc to 4dp) | — | — | — | — |

**Readout:** Largest lift **ema_50_200_golden_cross_swing** (+1.18pp acc, -0.0048 Brier). Several strategies **unchanged** at 4 decimal places (Optuna may have landed near prior hyperparams). **Gate / Kelly** changes remain **out of band** for these tables — they affect live sizing only.

**Action:** Promote v4 independent + matching shadow after judge review; update production table above after `promote`.

---

## Upcoming: Inference-Only Retraining (2026-04-11)

### Problem Identified

All 19 production models produce **identical predictions for every ticker** at
live inference. Root cause: models were trained on ~64 features, but only ~29 are
available at inference time. The remaining ~35 features (TSFresh, FFD, HMM regime
probabilities, rolling price stats) are computed from historical time series
during training but cannot be reproduced from a single live `TechnicalSnapshot`.
At inference, these features are `NaN`, causing LightGBM to route all inputs down
the same default tree path regardless of actual TA values.

**Evidence:** `test_ml_gate.py` confirmed that 12 numeric features (RSI, ADX,
MACD histogram, volume ratio, momentum, EMA distances) were correctly mapped and
distinct across tickers, yet `run_prediction()` returned identical probabilities
(0.483826) for all inputs. Feature vector inspection showed 35/64 features as
`BOTH NaN`.

### What Changed (code)

| Area | Change | Files |
|---|---|---|
| Feature registry | Added `TRAINING_ONLY_FEATURES` frozenset (13 explicit features) + `TRAINING_ONLY_PREFIXES = ("tsf_",)` to catch ~30 TSFresh features by prefix. Added `is_training_only_feature()` helper. | `engineering.py` |
| Feature column filter | `_identify_feature_columns()` now accepts `inference_only=True` param that excludes all training-only features from the training dataset | `predictor.py` |
| Training loop | `TrainingLoopConfig.inference_only` field threaded to `PredictionModel` and `_prune_features()` | `training_loop.py` |
| Hyperparameter tuning | `HyperparameterTuner` accepts `inference_only` param, applied in both `search()` and `search_optuna()` | `hyperparameter_tuning.py` |
| CLI | `--inference-only` flag added to both `train` and `tune` subcommands | `cli.py` |
| Data acquisition defaults | Default timeframes now include `15m` and `W`; intraday lookback set to 183 days (6 months) | `acquisition.py`, `cli.py` |

### Features Excluded by `--inference-only`

| Category | Features | Count | Reason |
|---|---|---|---|
| FFD | `ffd_close`, `ffd_return_1d` | 2 | Requires full price history for fractional differencing weights |
| HMM regime | `hmm_regime`, `hmm_regime_prob_{bear,neutral,bull}` | 4 | Requires fitted HMM on VIX/SPY/breadth time series |
| TSFresh | All `tsf_*` prefixed features | ~30 | Requires 20-bar rolling window of raw OHLCV |
| Rolling price stats | `price_change_5d`, `price_change_20d`, `bollinger_width`, `volatility_20d`, `distance_from_20d_high`, `distance_from_20d_low` | 6 | Require multi-day rolling windows |
| Cross-sectional | `sector_relative_strength` | 1 | Requires computing breadth across entire universe |

### Features Retained (~29 expected at inference)

| Category | Features | Count |
|---|---|---|
| Core TA | `rsi_14`, `rsi_zone`, `macd_histogram`, `macd_slope`, `adx`, `atr_pct`, `volume_ratio`, `volume_trend`, `momentum_score`, `price_vs_ema_{9,21,50,200}`, `ema_stack_score`, `ema_spread_pct`, `high_low_range`, `gap_pct`, `price_change_1d` | ~18 |
| FMP Fundamentals | `pe_ratio`, `pb_ratio`, `ev_ebitda`, `debt_equity`, `roe`, `net_margin`, `revenue_growth`, `piotroski_score`, `altman_z`, `analyst_target_upside`, `insider_buy_ratio`, `current_ratio`, `dividend_yield`, `roa`, `composite_score` | 15 |
| Context | `strategy_type`, `market_regime`, `sector`, `day_of_week`, `month`, `vix_level`, `market_breadth_proxy` | 7 |
| Primary signal | `primary_signal`, `signal_strength` | 2 |
| Multi-TF (live available) | `tf_{1H,4H,D}_rsi_14`, `tf_{1H,4H,D}_price_vs_ema_200`, etc. | varies |

### Data Refresh

Data acquired 2026-04-11: 987 tickers (434 TSX, 503 US, 50 crypto) across all
timeframes (D, W, 4H, 1H, 15m). Dataset rebuild with augmentation running.

### Training Plan

```bash
# Step 1: Tune with inference-only features
uv run --python 3.14t python -X gil=0 -m ml_training.pipeline.cli tune \
    --per-strategy --n-trials 50 --inference-only

# Step 2: Train with inference-only features
uv run --python 3.14t python -X gil=0 -m ml_training.pipeline.cli train \
    --per-strategy --rounds 3 --inference-only --model-mode independent

# Step 3: Promote passing models
uv run --python 3.14t python -X gil=0 -m ml_training.pipeline.cli promote
```

### Expected Outcome

Models will go from ~64 features (35 NaN at inference) to ~29 features (0 NaN at
inference). Every feature in the trained model will have a real value when making
live predictions. LightGBM will learn meaningful splits on RSI, ADX, MACD,
volume, EMA distances -- the features that actually differentiate tickers.

**Hypothesis:** Accuracy may be similar or slightly lower in cross-validation
(fewer features = less signal), but **live inference quality will be dramatically
better** because the model can actually discriminate between inputs. The current
production models are effectively returning a constant baseline.

### Results: Baseline Inference-Only Training (2026-04-11)

First training run with `--inference-only` flag. Default params (no tuning yet).
Dataset rebuilt same day with fresh data (987 tickers, D/W/4H/1H/15m).
New pipeline improvements active: temporal holdout (15%), min sample floor (15K),
dead feature pruning, feature-aware augmentation.

#### Shadow models (inference-only baseline, default params)

| Strategy | Ver | Acc | Brier | OFGap | Judge | n | Feats | Active | Top SHAP |
|---|---|---|---|---|---|---|---|---|---|
| bollinger_band_squeeze_breakout_swing | v31 | 56.3% | 0.2453 | -3.2% | COND_PASS | 50,843 | 31 | 12 | month, market_breadth_proxy, atr_pct |
| crypto_intraday_scalp | v23 | 56.1% | 0.2463 | -0.8% | COND_PASS | 126,147 | 27 | 3 | market_breadth_proxy, day_of_week, price_change_1d |
| crypto_swing | v25 | 52.3% | 0.2553 | +0.1% | FAIL | 653,074 | 1 | 0 | (collapsed to 1 feature) |
| earnings_play | v28 | 64.3% | 0.2309 | -2.8% | COND_PASS | 72,154 | 31 | 5 | tf_D_rsi_14, momentum_score, price_vs_ema_200 |
| ema_21_pullback_swing | v27 | 56.0% | 0.2453 | -3.1% | COND_PASS | 56,310 | 31 | 4 | atr_pct, month, market_breadth_proxy |
| ema_50_200_golden_cross_swing | v36 | 54.6% | 0.2454 | -1.1% | COND_PASS | 44,113 | 31 | 5 | month, atr_pct, tf_4H_momentum_score |
| intraday | v23 | 56.7% | 0.2456 | -1.8% | COND_PASS | 38,612 | 9 | 4 | tf_1H_momentum_score, tf_1H_rsi_14, tf_1H_price_vs_ema_200 |
| intraday_scalp | v25 | 54.5% | 0.2481 | -1.2% | COND_PASS | 18,110 | 5 | 2 | market_breadth_proxy, atr_pct |
| mean_reversion | v31 | 55.6% | 0.2471 | +2.8% | COND_PASS | 72,154 | 7 | 3 | market_breadth_proxy, tf_D_price_vs_ema_200, atr_pct |
| momentum_breakout | v34 | 55.0% | 0.2460 | -1.4% | COND_PASS | 35,520 | 6 | 3 | market_breadth_proxy, tf_4H_momentum_score, tf_4H_price_vs_ema_200 |
| swing | v39 | 54.0% | 0.2476 | -0.8% | COND_PASS | 186,788 | 4 | 3 | market_breadth_proxy, tf_4H_price_vs_ema_200, atr_pct |
| value_accumulation | v26 | 66.9% | 0.2214 | -1.5% | PASS | 109,079 | 21 | 2 | market_breadth_proxy, atr_pct |

#### Independent models (inference-only baseline, default params)

| Strategy | Ver | Acc | Brier | OFGap | Judge | n | Feats | Active |
|---|---|---|---|---|---|---|---|---|
| bollinger_band_squeeze_breakout_swing | v5 | 56.3% | 0.2453 | -3.2% | COND_PASS | 50,843 | 31 | 12 |
| crypto_intraday_scalp | v5 | 56.1% | 0.2463 | -0.8% | COND_PASS | 126,147 | 27 | 3 |
| crypto_swing | v7 | 52.3% | 0.2553 | +0.1% | FAIL | 653,074 | 3 | 0 |
| earnings_play | v5 | 64.3% | 0.2309 | -2.8% | COND_PASS | 72,154 | 31 | 5 |
| ema_21_pullback_swing | v5 | 56.0% | 0.2453 | -3.1% | COND_PASS | 56,310 | 31 | 4 |
| ema_50_200_golden_cross_swing | v5 | 54.6% | 0.2454 | -1.1% | COND_PASS | 44,113 | 31 | 5 |
| intraday | v5 | 56.7% | 0.2455 | -1.8% | COND_PASS | 38,612 | 20 | 7 |
| intraday_scalp | v5 | 54.9% | 0.2476 | -0.6% | COND_PASS | 18,110 | 16 | 10 |
| mean_reversion | v5 | 55.4% | 0.2472 | +2.9% | COND_PASS | 72,154 | 9 | 4 |
| momentum_breakout | v5 | 55.0% | 0.2459 | -1.3% | COND_PASS | 35,520 | 7 | 3 |
| swing | v5 | 54.1% | 0.2478 | -0.7% | COND_PASS | 186,788 | 7 | 3 |
| value_accumulation | v5 | 66.9% | 0.2214 | -1.5% | PASS | 109,079 | 21 | 2 |

#### Baseline Summary

- **24 models** total (12 shadow + 12 independent). No `vwap_reversal_scalp` or `ema_stack_momentum_intraday` in this run (may have been below sample floor or not in dataset).
- **2 PASS** (value_accumulation), **20 CONDITIONAL_PASS**, **2 FAIL** (crypto_swing)
- **Accuracy range:** 52.3% – 66.9% (mean 56.9%)
- **Feature usage:** Only 29% of features have non-zero SHAP on average
- `market_breadth_proxy` and `atr_pct` are the most consistently useful features across all strategies
- No holdout metrics populated (holdout split implemented but not yet evaluated -- will appear after next training run with updated code)
- **Next step:** Tune with `--inference-only --per-strategy --n-trials 50` then retrain

#### Baseline vs Prior Production (Apr 7 tuned)

| Strategy | Prod Acc | Baseline Acc | Delta | Notes |
|---|---|---|---|---|
| bollinger_band_squeeze | 57.7% | 56.3% | -1.4% | Prod had tuned params |
| crypto_intraday_scalp | 56.3% | 56.1% | -0.2% | Near-identical |
| crypto_swing | 54.8% | 52.3% | -2.5% | Both struggling |
| earnings_play | 64.3% | 64.3% | 0.0% | Identical |
| ema_21_pullback_swing | 58.0% | 56.0% | -2.0% | Prod had tuned params |
| ema_50_200_golden_cross | 59.0% | 54.6% | -4.4% | Biggest drop -- needs tuning |
| intraday | 56.7% | 56.7% | 0.0% | Identical |
| intraday_scalp | 55.0% | 54.5% | -0.5% | Close |
| mean_reversion | 56.1% | 55.6% | -0.5% | Close |
| momentum_breakout | 58.3% | 55.0% | -3.3% | Needs tuning |
| swing | 54.7% | 54.0% | -0.7% | Close |
| value_accumulation | 67.2% | 66.9% | -0.3% | Near-identical, only PASS |

**Takeaway:** Baseline inference-only models (default params, no tuning) are 0-4% behind the prior tuned production models. Expected -- not yet tuned. But SHAP already shows heavy reliance on macro features (`market_breadth_proxy`, `atr_pct`) over per-ticker TA features.

---

### Results: Tuned + Trained Inference-Only (2026-04-11, post-Optuna)

Tuned with `--inference-only --per-strategy --n-trials 50`, then retrained with
tuned params. Same dataset as baseline.

#### Shadow models (tuned inference-only)

| Strategy | Ver | Acc | Brier | OFGap | Judge | Feats | Active | vs Baseline |
|---|---|---|---|---|---|---|---|---|
| bollinger_band_squeeze_breakout_swing | v32 | 55.7% | 0.2469 | -2.1% | COND_PASS | 2 | 1 | **-0.6%** |
| crypto_intraday_scalp | v24 | 56.2% | 0.2464 | -0.9% | COND_PASS | 1 | 1 | +0.1% |
| crypto_swing | v25 | 52.3% | 0.2553 | +0.1% | FAIL | 1 | 0 | 0.0% |
| earnings_play | v29 | 64.3% | 0.2310 | -2.8% | COND_PASS | 5 | 2 | 0.0% |
| ema_21_pullback_swing | v28 | 55.2% | 0.2473 | -1.6% | COND_PASS | 1 | 1 | **-0.8%** |
| ema_50_200_golden_cross_swing | v37 | 54.1% | 0.2469 | -0.6% | COND_PASS | 1 | 1 | **-0.5%** |
| intraday | v24 | 56.7% | 0.2457 | -1.8% | COND_PASS | 4 | 1 | 0.0% |
| intraday_scalp | v25 | 54.5% | 0.2481 | -1.2% | COND_PASS | 5 | 2 | 0.0% (same model) |
| mean_reversion | v32 | 56.0% | 0.2469 | +2.2% | COND_PASS | 3 | 1 | **+0.4%** |
| momentum_breakout | v34 | 55.0% | 0.2460 | -1.4% | COND_PASS | 6 | 3 | 0.0% (same model) |
| swing | v39 | 54.0% | 0.2476 | -0.8% | COND_PASS | 4 | 3 | 0.0% (same model) |
| value_accumulation | v27 | 66.9% | 0.2214 | -1.5% | PASS | 17 | 1 | 0.0% |

#### Feature Collapse After Tuning

| Strategy | Baseline Features | Tuned Features | Baseline Active | Tuned Active | Sole Survivor |
|---|---|---|---|---|---|
| bollinger_band_squeeze | 31 | 2 | 12 | 1 | `market_breadth_proxy` |
| crypto_intraday_scalp | 27 | 1 | 3 | 1 | `market_breadth_proxy` |
| ema_21_pullback_swing | 31 | 1 | 4 | 1 | `market_breadth_proxy` |
| ema_50_200_golden_cross | 31 | 1 | 5 | 1 | `market_breadth_proxy` |
| intraday | 9 | 4 | 4 | 1 | `tf_1H_rsi_14` |
| mean_reversion | 7 | 3 | 3 | 1 | `tf_D_rsi_14` |
| value_accumulation | 21 | 17 | 2 | 1 | `tf_D_rsi_14` |
| earnings_play | 31 | 5 | 5 | 2 | `market_breadth_proxy` + `tf_D_momentum_score` |
| momentum_breakout | 6 | 6 | 3 | 3 | (unchanged -- same model) |
| swing | 4 | 4 | 3 | 3 | (unchanged -- same model) |

### Critical Finding: Market-Breadth Dominance Problem

**What happened:** Tuning + SHAP pruning aggressively collapsed most models to
a single feature: `market_breadth_proxy`. This feature measures the % of the
stock universe above its 200-day EMA -- it is **the same value for every ticker
on a given day**. Models that only use market-level features will produce
**identical predictions for all tickers**, which is the exact same end result as
the NaN collapse problem we set out to fix.

**Why this matters:**

| Problem | Old Models (NaN) | New Models (Inference-Only) |
|---|---|---|
| Root cause | 35/64 features NaN at inference | Models pruned to 1 macro feature |
| Symptom | Identical predictions per ticker | Identical predictions per ticker |
| Cross-validation accuracy | 55-67% | 52-67% |
| Per-ticker differentiation | None | None (market_breadth_proxy doesn't vary) |

The `--inference-only` fix was **necessary** (removed the NaN problem) but
**not sufficient** (exposed that per-ticker TA features are not surviving SHAP
pruning). The training loop prunes 30% of features on round 1 failure, and the
models converge to macro features because they provide a small but consistent
baseline accuracy that per-ticker TA features can't beat individually.

### Root Cause Hypotheses

| # | Hypothesis | Evidence | Test |
|---|---|---|---|
| 1 | **SHAP pruning too aggressive** | 30% prune fraction kills weak-but-useful features after just 1 round | Disable pruning, train with all features, check if predictions diverge |
| 2 | **Triple barrier horizon washes out TA** | 10-day horizon with 2:1 R:R too noisy for daily TA to predict | Try shorter horizons (5d) or different labeling |
| 3 | **Features need interactions** | Raw RSI=45 isn't predictive, but RSI>50 + MACD positive might be | Add cross-feature interaction columns |
| 4 | **Market breadth really is the dominant signal** | SHAP is correct -- macro regime matters more than individual TA | Accept simpler model, focus ML effort on regime detection |

**Next step:** Experiment with disabling SHAP pruning (`feature_prune_fraction=0`)
to see if a full-feature model produces distinct per-ticker predictions, even at
cost of slightly lower accuracy. This isolates hypothesis #1 from #2-#4.

#### Live inference validation (post-promote)

| Test | Expected | Actual |
|---|---|---|
| `test_raw_prediction_diverges` | Different probs for RSI=25 vs RSI=75 | — |
| `test_gate_produces_distinct_probabilities` | 3 tickers get 3 different probs | — |
| Live pipeline run: distinct `ml_probability` per ticker | All unique | — |

---

## Current Production Models (deployed)

These are the `*_active.joblib` artifacts in `src/backend/ml/artifacts/`.

| Strategy | Ver | Acc | Brier | OFGap | ECE | Judge | Samples | Feats | 0-SHAP |
|---|---|---|---|---|---|---|---|---|---|
| bollinger_band_squeeze_breakout_swing | v26 | 0.5930 | 0.2402 | 0.0074 | 0.0156 | COND_PASS | 55,626 | 48 | 2 |
| crypto_intraday | v12 | 0.4166 | 0.4362 | 0.0390 | 0.0172 | COND_PASS | 21,793 | 32 | 2 |
| crypto_intraday_scalp | v18 | 0.5848 | 0.2429 | -0.0129 | 0.0000 | COND_PASS | 148,409 | 60 | 44 |
| crypto_swing | v18 | 0.6293 | 0.2215 | 0.0632 | 0.0099 | **PASS** | 757,536 | 48 | 2 |
| earnings_play | v23 | 0.6478 | 0.2287 | -0.0265 | 0.0111 | COND_PASS | 84,888 | 44 | 7 |
| ema_21_pullback_swing | v22 | 0.5962 | 0.2386 | 0.0090 | 0.0143 | COND_PASS | 61,098 | 48 | 6 |
| ema_50_200_golden_cross_swing | v31 | 0.5845 | 0.2399 | 0.0573 | 0.0277 | COND_PASS | 48,456 | 48 | 10 |
| ema_stack_momentum_intraday | v18 | 0.6081 | 0.2375 | 0.0209 | 0.0001 | COND_PASS | 13,485 | 64 | 10 |
| event | v16 | 0.4048 | 0.4278 | 0.2667 | 0.0219 | **FAIL** | 11,388 | 34 | 1 |
| intraday | v18 | 0.5888 | 0.2418 | -0.0059 | 0.0000 | COND_PASS | 44,807 | 64 | 52 |
| intraday_scalp | v20 | 0.5519 | 0.2473 | -0.0073 | 0.0000 | COND_PASS | 21,307 | 60 | 34 |
| mean_reversion | v26 | 0.6478 | 0.2289 | -0.0265 | 0.0000 | COND_PASS | 84,888 | 48 | 42 |
| momentum_breakout | v29 | 0.5912 | 0.2414 | 0.0113 | 0.0000 | COND_PASS | 39,310 | 48 | 9 |
| opening_range_breakout | v8 | 0.5037 | 0.3921 | 0.2130 | 0.0374 | **FAIL** | 3,570 | 41 | 0 |
| swing | v34 | 0.6037 | 0.2369 | 0.0351 | 0.0215 | COND_PASS | 204,490 | 48 | 2 |
| value_accumulation | v21 | 0.6738 | 0.2177 | -0.0159 | 0.0491 | COND_PASS | 128,329 | 63 | 44 |
| value | v16 | 0.3649 | 0.4388 | 0.1284 | 0.0241 | **FAIL** | 18,907 | 36 | 9 |
| vwap_reversal_scalp | v15 | 0.6026 | 0.2390 | 0.0260 | 0.0000 | COND_PASS | 10,015 | 64 | 35 |

**Production summary:** 19 models. 1 PASS, 15 CONDITIONAL_PASS, 3 FAIL.
Best performers: `value_accumulation` (67.4%), `earnings_play` (64.8%), `crypto_swing` (62.9%).
Weakest: `value` (36.5%), `event` (40.5%), `crypto_intraday` (41.7%) -- these need attention.

---

## Latest Training Run: 2026-04-07 (shadow models)

Tuned with Optuna on existing dataset. **Decision: NOT promoted** -- inconsistent
improvement over production; several strategies showed feature collapse.

| Strategy | v1 Acc | v2 Acc | Delta vs Prod | Brier | OFGap | 0-SHAP (v2) | Notes |
|---|---|---|---|---|---|---|---|
| bollinger_band_squeeze | 0.5872 / 0.5936 | +0.0006 | 0.2396 | 0.0416 | 7 | Stable |
| crypto_intraday_scalp | 0.5651 / 0.5649 | -0.0199 | 0.2458 | -0.0121 | 27 | **Regressed**, feature collapse |
| crypto_swing | 0.6354 / 0.6388 | +0.0095 | 0.2179 | 0.0620 | 3 | **Improved** |
| earnings_play | 0.6478 / 0.6478 | 0.0000 | 0.2290 | -0.0265 | 40 | Same acc, severe collapse in v25 |
| ema_21_pullback | 0.5962 / 0.5961 | -0.0001 | 0.2366 | 0.0460 | 4 | Stable |
| ema_50_200_golden_cross | 0.5802 / 0.5805 | -0.0040 | 0.2400 | 0.0592 | 5 | Stable but worse than prod |
| ema_stack_momentum | 0.5720 / 0.5728 | -0.0353 | 0.2437 | 0.0224 | 11 | **Regressed** from 0.6081 |
| intraday | 0.5683 / 0.5641 | -0.0247 | 0.2451 | 0.0128 | 56 | **Severe collapse** in v20 |
| intraday_scalp | 0.5419 / 0.5471 | -0.0048 | 0.2480 | 0.0128 | 29 | Feature collapse |
| mean_reversion | 0.5953 / 0.6001 | -0.0477 | 0.2374 | 0.0582 | 16 | **Regressed** from 0.6478 |
| momentum_breakout | 0.5854 / 0.5963 | +0.0051 | 0.2426 | 0.0312 | 6 | Slight improvement |
| swing | 0.5922 / 0.5755 | -0.0282 | 0.2403 | 0.0641 | 3 | **Regressed** |
| value_accumulation | 0.6761 / 0.6733 | -0.0005 | 0.2201 | -0.0162 | 57 | Stable but extreme collapse |
| vwap_reversal_scalp | 0.5724 / 0.5725 | -0.0301 | 0.2445 | 0.0230 | 19 | **Regressed** from 0.6026 |

---

## Feature Collapse Analysis (2026-04-07)

Features consistently showing zero SHAP across multiple strategies -- candidates
for removal or investigation.

### Universally dead features (zero SHAP in 10+ strategies)

| Feature | Strategies with 0-SHAP | Likely Cause |
|---|---|---|
| `ffd_return_1d` | 14/14 | FFD may be over-differencing at d=0.4 |
| `hmm_regime` | 12/14 | Encoded as feature, should be gate modifier instead |
| `ema_stack_score` | 10/14 | Redundant with individual EMA distances |
| `tf_4H_ema_stack_score` | 12/14 | Weak signal on secondary timeframe |
| `tf_W_ema_stack_score` | 12/14 | Weak signal on secondary timeframe |
| `primary_signal` | 9/14 | By design (model already trains on signal subset) |
| `signal_strength` | 8/14 | Same as above |
| `rsi_zone` | 7/14 | Redundant with raw `rsi_14` |
| `market_regime` | 7/14 | Redundant with `hmm_regime` |
| `gap_pct` | 8/14 | Low signal for non-intraday strategies |

### Trivially zero (expected by design)

| Feature | Reason |
|---|---|
| `strategy_type` | Model is per-strategy, so this is constant |
| `sector` | Same rationale for crypto strategies |

### Strategies with severe feature collapse (50%+ features at zero)

| Strategy | Total Feats | Zero-SHAP | % Dead | Verdict |
|---|---|---|---|---|
| value_accumulation v23 | 63 | 57 | 90.5% | Over-regularized |
| intraday v20 | 64 | 56 | 87.5% | Over-regularized |
| intraday_scalp v21 | 60 | 43 | 71.7% | Over-regularized |
| earnings_play v25 | 44 | 40 | 90.9% | Over-regularized |
| vwap_reversal_scalp v16 | 64 | 31 | 48.4% | Borderline |

---

## Training History Timeline

| Date | Run Type | Key Changes | Outcome |
|---|---|---|---|
| 2026-04-05 | Full train (7yr data) | Multiple rounds per strategy, 3-5 fold CPCV | Current production models promoted |
| 2026-04-07 (run 1) | Optuna tune | Attempted 15yr lookback expansion | Mixed results, NOT promoted |
| 2026-04-07 (run 2) | Optuna tune | Same data, different trial count | Feature collapse on several strategies |
| 2026-04-07 | Train + Optuna (late) | Shadow **v30–v38**, independent **v4**; `_decay_lambda` in `classifier_params`; Brier-oriented Optuna CV | See “Latest batch” + v3→v4 delta tables |
| 2026-04-08 | Code + artifacts | Repo gate/training changes; training artifacts on `20260407` now include tuned decay | Compare v4 vs production before promote |
| 2026-04-11 | **Inference-only baseline** | `--inference-only` flag, fresh data (D/W/4H/1H/15m), 15% temporal holdout, min sample floor (15K), dead feature pruning, feature-aware augmentation, `feature_spec.py` canonical registry, `_meta.json` promoted with models | Baseline: mean 56.9% acc, 29% feature usage |
| 2026-04-11 | **Inference-only tuned** | Optuna 50 trials per strategy + retrain with tuned params | **Feature collapse:** most models pruned to 1-3 features. `market_breadth_proxy` dominates. Models produce identical per-ticker predictions (same symptom as NaN problem). Accuracy ≈ baseline (no improvement). **NOT promoted.** |

---

## Production vs Latest Delta Summary

| Strategy | Prod Acc | Latest Best | Delta | Winner |
|---|---|---|---|---|
| bollinger_band_squeeze | 0.5930 | 0.5936 | +0.06% | Latest (marginal) |
| crypto_intraday_scalp | 0.5848 | 0.5651 | -1.97% | **Production** |
| crypto_swing | 0.6293 | 0.6388 | +0.95% | Latest |
| earnings_play | 0.6478 | 0.6478 | 0.00% | Tie |
| ema_21_pullback | 0.5962 | 0.5962 | 0.00% | Tie |
| ema_50_200_golden_cross | 0.5845 | 0.5805 | -0.40% | **Production** |
| ema_stack_momentum | 0.6081 | 0.5728 | -3.53% | **Production** |
| intraday | 0.5888 | 0.5683 | -2.05% | **Production** |
| intraday_scalp | 0.5519 | 0.5471 | -0.48% | **Production** |
| mean_reversion | 0.6478 | 0.6001 | -4.77% | **Production** |
| momentum_breakout | 0.5912 | 0.5963 | +0.51% | Latest |
| swing | 0.6037 | 0.5922 | -1.15% | **Production** |
| value_accumulation | 0.6738 | 0.6761 | +0.23% | Latest (marginal) |
| vwap_reversal_scalp | 0.6026 | 0.5725 | -3.01% | **Production** |

**Verdict:** Production wins on 8/14 strategies. Latest only clearly better on `crypto_swing` and `momentum_breakout`. Keeping production models.

---

## Identified Pipeline Issues (from analysis)

These are the systemic issues identified through artifact analysis. See
`ml_pipeline_optimization` plan for implementation details.

| # | Issue | Evidence from Artifacts | Planned Fix |
|---|---|---|---|
| 1 | GT-Score optimizes accuracy, gate uses probability magnitudes | Brier scores cluster at 0.24 regardless of accuracy variation | Switch to Brier-score objective |
| 2 | Meta-labeler trained but not used in production | `primary_signal` has 0 SHAP because model already filters on it | Wire meta-labeler into gate |
| 3 | No temporal decay in sample weights | 15yr data didn't improve over 7yr despite more samples | Add exponential decay weighting |
| 4 | Gate thresholds (0.52/0.58/0.65) are arbitrary | At 2:1 R:R, breakeven = 33.3% -- blocking +EV trades | Kelly-optimal thresholds |
| 5 | HMM regime as feature has zero SHAP universally | `hmm_regime` = 0 SHAP in 12/14 strategies | Move to gate modifier |
| 6 | Only 3-5 CV folds, noisy variance estimate | `fold_variance * 5.0` penalty is unreliable with 3 folds | Increase to 8 folds |

---

## Metric Definitions

| Metric | Range | Good | Description |
|---|---|---|---|
| **Acc** (Accuracy) | 0-1 | >0.55 | Overall prediction accuracy |
| **Brier** (Brier Score) | 0-1 | <0.24 | Mean squared probability error (lower = better calibration) |
| **OFGap** (Overfit Gap) | -inf to inf | <0.10 | Train acc - test acc (negative = underfit, high positive = overfit) |
| **ECE** (Expected Calibration Error) | 0-1 | <0.08 | How well probabilities match observed frequencies |
| **0-SHAP** | 0-N | <10% of features | Features with exactly zero SHAP importance |
| **Judge** | PASS/COND/FAIL | PASS | Multi-layer validation verdict |

---

## Strategy Barrier Configs (R:R ratios)

These define the triple-barrier labeling for each strategy and affect Kelly sizing.

| Strategy | Profit Mult | Stop Mult | Effective R:R |
|---|---|---|---|
| mean_reversion | 1.0 | 1.5 | 0.67:1 |
| momentum_breakout | 3.0 | 1.0 | 3.0:1 |
| swing | 2.0 | 1.0 | 2.0:1 |
| earnings_play | 2.5 | 1.0 | 2.5:1 |
| value_accumulation | 2.0 | 1.5 | 1.33:1 |
| bollinger_band_squeeze | 1.5 | 1.0 | 1.5:1 |
| intraday_scalp | 1.2 | 1.0 | 1.2:1 |
| vwap_reversal_scalp | 1.0 | 1.0 | 1.0:1 |
| ema_21_pullback | 2.0 | 1.0 | 2.0:1 |
| ema_50_200_golden_cross | 2.5 | 1.0 | 2.5:1 |
| ema_stack_momentum | 2.0 | 1.0 | 2.0:1 |
| crypto_swing | 2.0 | 1.0 | 2.0:1 |
| crypto_intraday | 1.5 | 1.0 | 1.5:1 |
| crypto_intraday_scalp | 1.2 | 1.0 | 1.2:1 |
| intraday | 1.5 | 1.0 | 1.5:1 |

---

## Kelly Breakeven Thresholds (by R:R)

At each R:R ratio, this is the minimum accuracy needed for positive expected value.

| R:R | Breakeven Accuracy | Current Gate (0.52) Wastes? |
|---|---|---|
| 3.0:1 | 25.0% | Yes -- blocking 25-52% range |
| 2.5:1 | 28.6% | Yes -- blocking 29-52% range |
| 2.0:1 | 33.3% | Yes -- blocking 33-52% range |
| 1.5:1 | 40.0% | Yes -- blocking 40-52% range |
| 1.33:1 | 42.9% | Yes -- blocking 43-52% range |
| 1.2:1 | 45.5% | Yes -- blocking 46-52% range |
| 1.0:1 | 50.0% | Marginal waste at 50-52% |
| 0.67:1 | 60.0% | No -- 0.52 threshold is too low for this R:R |

---

## Artifact File Inventory

| Category | Count |
|---|---|
| Production (`*_active.joblib`) | 19 |
| Training 2026-04-11 inf-only tuned (shadow) | 12 |
| Training 2026-04-11 inf-only tuned (independent) | 12 |
| Training 2026-04-11 inf-only baseline (shadow) | 12 |
| Training 2026-04-11 inf-only baseline (independent) | 12 |
| Training 2026-04-07 shadow | 28 |
| Training 2026-04-07 independent | 28 |
| Training 2026-04-05 shadow | 136 |
| **Total artifacts** | **~484** |
| Judge PASS | 7 (~1.4%) |
| Judge CONDITIONAL_PASS | 226 (~46.7%) |
| Judge FAIL | 251 (~51.9%) |
