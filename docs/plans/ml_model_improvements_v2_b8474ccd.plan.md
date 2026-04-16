---
name: ML model improvements v2
overview:
  'Four targeted code changes to improve ML model accuracy: scale feature
  pruning and model complexity with dataset size, fix Optuna search
  inconsistencies, and fix two bugs (dead feature double-counting, exception
  syntax).'
todos:
  - id: prune-scaling
    content:
      Scale feature pruning inversely with feature count + add 12-feature floor
      in training_loop.py
    status: completed
  - id: model-scaling
    content:
      Add _scale_default_params() in predictor.py to scale model complexity with
      dataset size
    status: completed
  - id: optuna-fixes
    content:
      Fix min_child_samples range, bagging_freq inconsistency, and default
      n_trials in hyperparameter_tuning.py
    status: completed
  - id: bug-fixes
    content:
      Fix dead feature double-counting and invalid exception syntax in
      training_loop.py
    status: completed
  - id: rebuild-retrain
    content: Fresh train, tune, tuned train, update ARTIFACT_TRACKER
    status: completed
isProject: false
---

# ML Model Quality Improvements v2

~~Fix 1 (lag/delta features) removed -- the production pipeline only provides a
single snapshot of indicators at inference time. Lag features computed during
training would create a train/serve mismatch since they can't be reproduced at
inference without adding historical data retrieval to the backend pipeline.~~

## Fix 1: Scale Feature Pruning with Feature Count

**Problem:** Flat 30% prune rate (line 79 of
[training_loop.py](src/ml_training/ml_training/pipeline/training_loop.py)) is
devastating for low-feature strategies. After fundamental masking,
non-fundamental strategies have ~22 features. Pruning 30% = 7 features dropped.
Strategies like momentum_breakout (11 active out of 27) lose features they need.

**File:**
[training_loop.py](src/ml_training/ml_training/pipeline/training_loop.py)

Modify `_prune_features()` (lines 400-432) to scale prune fraction and enforce a
minimum feature floor:

- In `_prune_features`, after computing `scored` (line 420), add adaptive
  scaling:
  - If `len(scored) <= 15`: cap `frac` at `0.15`
  - If `len(scored) <= 25`: cap `frac` at `0.20`
  - Otherwise: use configured `frac` (0.30)
- Add minimum feature floor:
  `n_drop = min(n_drop, max(0, len(sorted_feats) - 12))`

This ensures we never prune below 12 features and go lighter when features are
scarce.

---

## Fix 2: Scale Model Complexity with Dataset Size

**Problem:** `BINARY_CLASSIFIER_PARAMS` in
[predictor.py](src/ml_training/ml_training/models/predictor.py) (lines 45-62)
uses `num_leaves=15`, `max_depth=5`, `min_child_samples=100` for ALL strategies.
For crypto_swing's 653K samples, each leaf averages 43K samples -- the model is
severely underfitting. For intraday_scalp's 18K, defaults are fine.

**File:** [predictor.py](src/ml_training/ml_training/models/predictor.py)

Add a static method `_scale_default_params()` and call it in `train()` at line
362, only when no tuned params were provided (i.e., using defaults):

```python
@staticmethod
def _scale_default_params(params: dict[str, Any], n_samples: int) -> dict[str, Any]:
    params = params.copy()
    if n_samples > 200_000:
        params.setdefault("num_leaves", 31)
        params.setdefault("max_depth", 7)
        params.setdefault("min_child_samples", 300)
    elif n_samples > 50_000:
        params.setdefault("num_leaves", 23)
        params.setdefault("max_depth", 6)
        params.setdefault("min_child_samples", 150)
    return params
```

Use `setdefault` so tuned params are never overwritten -- this only fills in
defaults that haven't been explicitly set.

---

## Fix 4: Fix Optuna Search Inconsistencies

**Problem:** Three issues in
[hyperparameter_tuning.py](src/ml_training/ml_training/pipeline/hyperparameter_tuning.py):

1. `min_child_samples` range caps at 150 (line 426) regardless of dataset size.
   For 653K-sample crypto_swing, 150 is still tiny.
2. `bagging_freq=1` during search (line 429) but `bagging_freq=5` in saved
   params template (line ~485). Models train differently than they were
   evaluated.
3. Default `n_trials=30` (line 309) is lean for 11 hyperparameters.

**Fixes:**

- **Line 426:** Make `min_child_samples` range adaptive:
  `trial.suggest_int("min_child_samples", 20, max(150, n_samples // 2000))` --
  pass `n_samples` into the closure from `search_optuna` (it already has access
  to `X` at line 392, so `n_samples = len(X)`)
- **Line ~485:** Change `"bagging_freq": 5` to `"bagging_freq": 1` in the saved
  params template to match the search
- **Line 309:** Change default `n_trials` from `30` to `50`

---

## Fix 4: Bug Fixes (dead features + exception syntax)

Two bugs found during analysis:

**Bug A — Dead feature counter double-counts same strategy**

**File:**
[training_loop.py](src/ml_training/ml_training/pipeline/training_loop.py), line
207

Currently `strategy_counts[feat] = strategy_counts.get(feat, 0) + 1` increments
every time a strategy runs, even if the same strategy trained multiple times.
Should use a set of strategy names:

Change the data structure from `dict[str, int]` to `dict[str, set[str]]`
tracking which strategies had zero SHAP, and count `len(strategies_set) >= 8`
for confirmed dead.

**Bug B — Invalid exception syntax**

**File:**
[training_loop.py](src/ml_training/ml_training/pipeline/training_loop.py), line
202

`except json.JSONDecodeError, KeyError:` is invalid Python 3 syntax. Should be
`except (json.JSONDecodeError, KeyError):` with parentheses.

---

## After Fixes: Retrain and Compare

No dataset rebuild needed -- these fixes change how models are trained, not what
features are computed. Use the existing datasets:

```
train --fresh --inference-only --per-strategy --rounds 3   # baseline with fixes
tune --inference-only --per-strategy --n-trials 50         # optimize
train --inference-only --per-strategy --rounds 3           # tuned
```

Update ARTIFACT_TRACKER.md with Run 10 results and comparison to Run 9.
