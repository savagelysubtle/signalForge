# SignalForge ML Artifact Tracker

> Auto-generated 2026-04-07. This document tracks all model training runs,
> production deployments, and analysis findings across the ML pipeline.

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
| Training 2026-04-07 shadow | 28 |
| Training 2026-04-07 independent | 28 |
| Training 2026-04-05 shadow | 136 |
| **Total artifacts** | **436** |
| Judge PASS | 5 (1.1%) |
| Judge CONDITIONAL_PASS | 186 (42.7%) |
| Judge FAIL | 245 (56.2%) |
