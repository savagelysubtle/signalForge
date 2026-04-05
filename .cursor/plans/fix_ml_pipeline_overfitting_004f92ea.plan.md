---
name: Fix ML Pipeline Overfitting
overview:
  Fix 5 structural defects in the ML training pipeline that cause 13-38% overfit
  gaps across 10/15 failing strategies, then apply research-backed improvements
  to regularization, labeling, and ensembling -- all before introducing GPT
  features.
todos:
  - id: fix-final-model
    content:
      'P0: Fix final model -- add early stopping, use median best_iteration from
      CV folds, hold out 10% validation slice (predictor.py lines 373-380)'
    status: completed
  - id: fix-purge-embargo
    content:
      'P0: Fix purge/embargo -- reduce DEFAULT_PURGE_WINDOW to 25,
      DEFAULT_EMBARGO_WINDOW to 10, add forward_horizon to CPCVConfig
      (predictor.py lines 82-83)'
    status: completed
  - id: fix-imputation
    content:
      'P0: Fix median imputation look-ahead -- _prepare_features must compute
      medians only from training indices (predictor.py lines 181-184)'
    status: completed
  - id: fix-retry-loop
    content:
      'P1: Make training loop rounds 2-5 apply different adjustments each round
      instead of repeating identical training (training_loop.py lines 155-171)'
    status: completed
  - id: harden-lgbm-defaults
    content:
      'P2: Tighten LightGBM defaults -- num_leaves=15, max_depth=5,
      min_child_samples=100, reg_lambda=5.0 (predictor.py lines 25-62)'
    status: completed
  - id: tighten-optuna
    content:
      'P2: Narrow Optuna search space -- num_leaves [7,31], max_depth [3,6],
      min_child_samples [50,300], reg_lambda [1.0,50.0]
      (hyperparameter_tuning.py lines 344-355)'
    status: completed
  - id: replace-grid-config
    content:
      'P2: Replace overly complex grid config 7 (num_leaves=63) with
      conservative DART config (hyperparameter_tuning.py lines 95-101)'
    status: completed
  - id: sample-weights
    content:
      'P3: Implement sample weighting by label uniqueness for overlapping
      forward returns (predictor.py new function)'
    status: completed
  - id: feature-neutralization
    content:
      'P3: Add cross-sectional z-score feature normalization per date to prevent
      ticker memorization (engineering.py + dataset_builder.py)'
    status: completed
  - id: seed-ensemble
    content:
      'P4: Implement 7-seed ensemble for final model -- average predict_proba
      across seeds (predictor.py lines 373-380)'
    status: completed
  - id: rebuild-retrain
    content:
      'P5: Rebuild datasets, re-tune with --n-trials 50, retrain all strategies,
      compare overfit gaps'
    status: in_progress
isProject: false
---

# Fix ML Pipeline Overfitting

## Problem Statement

10 of 15 strategy models FAIL with 13-38% overfit gaps. Five previous
improvement plans are all marked "completed" yet models still fail. Root cause
analysis reveals structural bugs in the training code that no amount of
parameter tuning can fix.

## Phase 1: Critical Bug Fixes (must do first)

These are code defects, not tuning choices. They directly cause inflated metrics
and must be fixed before any other work is meaningful.

### 1A. Final model trains on ALL data with no early stopping

**File:** [predictor.py](src/ml_training/ml_training/models/predictor.py) lines
376-380

The CV folds correctly use early stopping (`patience=50`, line 333), but the
final saved model trains on 100% of data with NO `eval_set` and NO early
stopping. It runs the full 500 boosting rounds, memorizing the entire dataset.

```python
# CURRENT (broken) - lines 376-380
final_clf = lgb.LGBMClassifier(**self._clf_params, n_estimators=n_rounds)
final_clf.fit(X, y_cls, categorical_feature=categorical_indices)
```

**Fix:** Use the median best iteration from CV folds as `n_estimators` for the
final model. Hold out a small validation slice (last 10%) for early stopping on
the final fit.

```python
# Compute median best_iteration from folds
best_iters = [fr.best_iteration for fr in fold_results if fr.best_iteration]
final_n = int(np.median(best_iters)) if best_iters else n_rounds

# Hold out last 10% for early stopping
split_n = int(len(X) * 0.9)
X_fit, X_val = X.iloc[:split_n], X.iloc[split_n:]
y_fit, y_val = y_cls[:split_n], y_cls[split_n:]

final_clf = lgb.LGBMClassifier(**self._clf_params, n_estimators=final_n)
final_clf.fit(
    X_fit, y_fit,
    categorical_feature=categorical_indices,
    eval_set=[(X_val, y_val)],
    callbacks=[lgb.early_stopping(50, verbose=False)],
)
```

This requires adding `best_iteration` to the `FoldResult` dataclass and
capturing `clf.best_iteration_` after each fold fit.

### 1B. Purge window is massively too large

**File:** [predictor.py](src/ml_training/ml_training/models/predictor.py) lines
82-83

`DEFAULT_PURGE_WINDOW = 200` strips 200 rows at every fold boundary. For daily
data with 10-20 day forward returns, this wastes ~40% of data per boundary. The
adaptive formula on line 287 (`max(20, n_samples//500)`) produces 22 for an 11K
dataset, which is better but should be tied to the forward return horizon, not
an arbitrary ratio.

**Fix:** Make purge proportional to forward horizon. The embargo should be ~50%
of the forward horizon.

```python
DEFAULT_PURGE_WINDOW = 25   # ~1 month of trading days, overridden per-strategy
DEFAULT_EMBARGO_WINDOW = 10  # half of a typical 20-day forward return
```

Also add a `forward_horizon` parameter to `CPCVConfig` so the pipeline can
compute `purge = max(forward_horizon, max_feature_lookback)` dynamically. Wire
this from the strategy's horizon map in
[dataset_builder.py](src/ml_training/ml_training/features/dataset_builder.py)
`_HORIZON_MAP` (lines 40-57).

### 1C. Median imputation leaks future data

**File:** [predictor.py](src/ml_training/ml_training/models/predictor.py) lines
181-184

```python
# CURRENT - computes median on FULL column (including future rows)
median = X[col].median()
X[col] = X[col].fillna(median if pd.notna(median) else 0.0)
```

**Fix:** `_prepare_features` must accept a `fit_mask` (training indices) and
compute medians only from training rows. Apply those medians to fill both train
and test. This prevents look-ahead bias through imputation.

### 1D. Training loop rounds 2-5 are no-ops

**File:**
[training_loop.py](src/ml_training/ml_training/pipeline/training_loop.py) lines
155-171

Feature pruning only happens after round 1 (`round_num == 1`). Rounds 2-5
retrain with identical data, features, and params, producing the same result.

**Fix:** Make each retry round apply a meaningful adjustment:

- Round 2: prune features (current behavior, keep)
- Round 3: increase `reg_lambda` by 2x and `min_child_samples` by 1.5x
- Round 4: switch to DART boosting
- Round 5: reduce `num_leaves` to 15 and `max_depth` to 4

This gives the retry loop actual exploratory power instead of repeating the same
training.

---

## Phase 2: Stronger Regularization Defaults

Once the structural bugs are fixed, tighten the defaults for noisy financial
data.

### 2A. LightGBM parameter hardening

**File:** [predictor.py](src/ml_training/ml_training/models/predictor.py) lines
25-62

Update both `CLASSIFIER_PARAMS` and `BINARY_CLASSIFIER_PARAMS`:

- `num_leaves`: 31 -> **15** (halve tree complexity for noisy data)
- `max_depth`: 8 -> **5** (shallower trees generalize better)
- `min_child_samples`: 30 -> **100** (~1% of 11K rows per leaf)
- `feature_fraction`: 0.8 -> **0.6** (more aggressive feature subsampling)
- `reg_lambda`: 1.0 -> **5.0** (much stronger L2 regularization)
- `bagging_freq`: 5 -> **1** (subsample every iteration)

### 2B. Tighten Optuna search space

**File:**
[hyperparameter_tuning.py](src/ml_training/ml_training/pipeline/hyperparameter_tuning.py)
lines 344-355

Narrow ranges to prevent Optuna from finding overfit configs:

- `num_leaves`: [15, 63] -> **[7, 31]**
- `max_depth`: [3, 10] -> **[3, 6]**
- `min_child_samples`: [30, 150] -> **[50, 300]**
- `reg_lambda`: [0.01, 10.0] -> **[1.0, 50.0]**
- `feature_fraction`: [0.5, 0.9] -> **[0.3, 0.7]**

Also add `min_gain_to_split` lower bound of 0.01 (currently starts at 0.0).

### 2C. Remove grid config 7 (overly complex)

**File:**
[hyperparameter_tuning.py](src/ml_training/ml_training/pipeline/hyperparameter_tuning.py)
lines 95-101

Config index 6 has `num_leaves=63, max_depth=8` which is far too complex for
noisy financial data. Replace it with a conservative DART config:

```python
{
    "boosting_type": "dart",
    "num_leaves": 15,
    "max_depth": 4,
    "learning_rate": 0.03,
    "min_child_samples": 100,
    "drop_rate": 0.1,
    "reg_lambda": 5.0,
},
```

---

## Phase 3: Sample Weighting and Feature Neutralization

### 3A. Sample weighting by label uniqueness

**New function in:**
[predictor.py](src/ml_training/ml_training/models/predictor.py)

With 10-day forward returns, consecutive rows share 9 of 10 bars, creating
highly autocorrelated labels. Weight each sample by its average uniqueness
(Lopez de Prado Ch. 4):

```python
def compute_sample_weights(dates: pd.Series, horizon: int) -> np.ndarray:
    """Weight samples by label uniqueness to correct for overlapping returns."""
    n = len(dates)
    weights = np.ones(n)
    for i in range(n):
        overlap_count = sum(1 for j in range(max(0, i - horizon), min(n, i + horizon + 1))
                          if j != i)
        weights[i] = 1.0 / (1 + overlap_count)
    return weights / weights.mean()  # normalize to mean=1
```

Pass as `sample_weight` to `clf.fit()`.

### 3B. Cross-sectional feature normalization

**File:**
[features/engineering.py](src/ml_training/ml_training/features/engineering.py)

Add a post-processing step that z-score normalizes numeric features within each
date (cross-sectional normalization). This prevents the model from learning
"AAPL's RSI is usually around 60" and forces it to learn "this stock's RSI is
high relative to peers today":

```python
def neutralize_features(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    """Z-score normalize features within each date to remove ticker identity."""
    for col in feature_cols:
        if col not in CATEGORICAL_FEATURES:
            df[col] = df.groupby("date")[col].transform(
                lambda x: (x - x.mean()) / (x.std() + 1e-8) if len(x) > 1 else 0.0
            )
    return df
```

Call this in
[dataset_builder.py](src/ml_training/ml_training/features/dataset_builder.py)
after feature computation but before saving the dataset.

---

## Phase 4: Seed Ensemble (free win)

### 4A. Multi-seed final model

**File:** [predictor.py](src/ml_training/ml_training/models/predictor.py) lines
373-380

Instead of training one final model with `seed=42`, train 5-10 models with
different seeds and average `predict_proba`. This typically reduces overfit gap
by 2-5% with zero complexity cost:

```python
N_SEEDS = 7
final_models = []
for seed in range(N_SEEDS):
    params = {**self._clf_params, "seed": seed, "feature_fraction_seed": seed}
    clf = lgb.LGBMClassifier(**params, n_estimators=final_n)
    clf.fit(X_fit, y_fit, ...)
    final_models.append(clf)
# Store list; predict() averages predict_proba across all models
```

Update the `TrainingResult` dataclass to hold
`classifiers: list[lgb.LGBMClassifier]` and modify `predict()` to average
probabilities.

---

## Phase 5: Validate and Rebuild

### 5A. Rebuild all datasets

After feature neutralization is added (Phase 3B), all datasets must be rebuilt:

```bash
uv run ml-train build-dataset
```

### 5B. Re-tune with new defaults

With tighter parameter ranges and fixed purge/embargo:

```bash
uv run ml-train tune --n-trials 50 --per-strategy
```

### 5C. Retrain and evaluate

```bash
uv run ml-train train --rounds 5 --per-strategy
```

### 5D. Compare results

Check model metadata files to verify:

- Overfit gaps reduced from 13-38% to target <15%
- No fundamental features in non-value model `feature_names`
- `training_config.n_boost_rounds` reflects early-stopped iteration count
- Binary mode active for per-strategy models

---

## Files Modified

- [predictor.py](src/ml_training/ml_training/models/predictor.py) -- final model
  early stopping, purge/embargo defaults, sample weights, seed ensemble,
  imputation fix
- [training_loop.py](src/ml_training/ml_training/pipeline/training_loop.py) --
  meaningful retry adjustments per round
- [hyperparameter_tuning.py](src/ml_training/ml_training/pipeline/hyperparameter_tuning.py)
  -- tighter Optuna space, replace overfit grid config
- [features/engineering.py](src/ml_training/ml_training/features/engineering.py)
  -- cross-sectional feature normalization function
- [features/dataset_builder.py](src/ml_training/ml_training/features/dataset_builder.py)
  -- wire neutralization, pass horizon to training config

## Expected Outcomes

- Phase 1 (bug fixes): Overfit gaps drop from 13-38% to honest numbers (likely
  5-20%). True OOS accuracy may drop, but numbers will be real.
- Phase 2 (regularization): Further 3-8% gap reduction from constrained trees.
- Phase 3 (weighting/neutralization): Removes ticker memorization path, another
  3-5% gap reduction.
- Phase 4 (ensemble): Free 2-5% gap reduction from seed diversity.
- Combined target: Get 8+ of 15 strategies to CONDITIONAL_PASS with <15% overfit
  gaps, up from current 5/15.
