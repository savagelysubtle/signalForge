# SignalForge ML Training Pipeline

Standalone offline training system that produces LightGBM model artifacts for
SignalForge's live inference layer. This project pulls historical market data,
engineers strategy-aware features, trains gradient-boosted classifiers with
walk-forward validation, runs a multi-layered judge system, and exports
`.joblib` artifacts that the backend loads for prediction.

This codebase is **never deployed to production**. The backend
(`src/backend/ml/`) contains only the thin inference layer that loads the
exported artifacts.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   TRAINING PIPELINE (this project)              │
│                                                                 │
│  acquire ──► build-dataset ──► tune ──► train ──► promote       │
│    │              │              │         │          │          │
│  FMP/yfinance  Feature eng.  Optuna    LightGBM   Copy to      │
│  Binance       + labeling    search    + Judge     backend      │
│  ──► Parquet   ──► Parquet             ──► .joblib              │
└────────────────────────────────────────────┬────────────────────┘
                                             │
                              .joblib artifact drop-in
                                             │
                                             ▼
                          ┌──────────────────────────────┐
                          │  LIVE INFERENCE (src/backend) │
                          │  Load artifact → .predict()   │
                          └──────────────────────────────┘
```

## Quick Start

### Standard (GIL enabled)

```bash
cd src/ml_training

# Install dependencies
uv sync --all-groups --prerelease=allow

# 1. Pull historical data from FMP (requires FMP_API_KEY in .env)
uv run ml-train acquire --category all --lookback-days 5475 --timeframes D,4H,1H,15m,1m

# 2. Build strategy-aware feature datasets (--augment adds synthetic data for small strategies)
uv run ml-train build-dataset --augment

# 3. Validate the dataset
uv run ml-train validate

# 4. Train models with judge validation (binary profitable target is now default)
uv run ml-train train --rounds 3

# 5. Tune hyperparameters (Optuna Bayesian search with GT-Score objective)
uv run ml-train tune --method optuna --n-trials 50

# 6. Promote passing models to the backend
uv run ml-train promote
```

### Free-Threaded (Python 3.14t, GIL disabled -- recommended)

True multi-core parallelism for CPU-bound stages. See the
[Free-Threading](#free-threading-python-314) section for details.

```bash
cd src/ml_training

# One-time setup
uv python install 3.14t
uv sync --all-groups --python 3.14t --prerelease=allow

# 1. Acquire data (parallel Binance/yfinance downloads)
uv run --python 3.14t python -X gil=0 -m ml_training.pipeline.cli acquire --category all --lookback-days 5475 --timeframes W,D,4H,1H,15m,1m

# 2. Build datasets (parallel per-ticker feature engineering + augmentation)
uv run --python 3.14t python -X gil=0 -m ml_training.pipeline.cli build-dataset --augment

# 3. Validate
uv run --python 3.14t python -X gil=0 -m ml_training.pipeline.cli validate

# 4. Train (parallel per-strategy models, SHAP, calibration)
uv run --python 3.14t python -X gil=0 -m ml_training.pipeline.cli train --rounds 3

# 5. Tune (parallel Optuna trials with GT-Score objective)
uv run --python 3.14t python -X gil=0 -m ml_training.pipeline.cli tune --method optuna --n-trials 50

# 6. Promote
uv run --python 3.14t python -X gil=0 -m ml_training.pipeline.cli promote
```

## CLI Reference

All commands are invoked via `uv run ml-train <command>` or
`uv run python -m ml_training.pipeline.cli <command>`.

| Command            | Description                                                               | Key Flags                                                                                                           |
| ------------------ | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `acquire`          | Pull OHLCV + indicators + fundamentals from FMP, yfinance, Binance        | `--category {all,tsx,us,crypto}`, `--timeframes D,4H,1H,15m,1m`, `--lookback-days 5475`                             |
| `build-dataset`    | Strategy-aware feature extraction, labeling, FFD, triple barrier, TSFresh | `--data-dir`, `--augment`                                                                                           |
| `validate`         | Dataset quality checks (leakage, balance, counts)                         | `--data-dir`                                                                                                        |
| `tune`             | Hyperparameter search (GT-Score objective via grid or Optuna)             | `--n-trials N`, `--per-strategy`, `--strategy <key>`, `--method {grid,optuna}`                                      |
| `train`            | Train-judge loop until quality bar is met                                 | `--rounds N`, `--per-strategy`, `--three-class`, `--model {lgbm,tabpfn,ensemble}`, `--meta-label`, `--regime-split` |
| `verify`           | Verify acquired raw data quality (gaps, issues)                           | `--data-dir`                                                                                                        |
| `promote`          | Copy latest passing artifacts to backend inference path                   | —                                                                                                                   |
| `resolve-outcomes` | Match pending predictions against actual prices                           | `--horizon N`                                                                                                       |
| `report-outcomes`  | Print rolling accuracy dashboard                                          | `--data-dir`                                                                                                        |

Global flags: `-v` / `--verbose` for debug logging.

## Project Structure

```
src/ml_training/
├── pyproject.toml                           # uv project config, dependencies, ruff/ty settings
├── README.md                                # This file
├── data/
│   └── raw/                                 # Runtime data (gitignored Parquet + checkpoints)
│       ├── acquisition_checkpoint.json
│       ├── best_params.json                 # Global tuned hyperparameters
│       └── best_params_<strategy>.json      # Per-strategy tuned hyperparameters
└── ml_training/                             # Installable Python package
    ├── threading.py                         # Free-threading utilities (GIL detection, parallel_map)
    ├── data/
    │   ├── acquisition.py                   # FMP historical data puller (rate-limited, checkpointed)
    │   ├── augmentation.py                  # Synthetic data augmentation (jitter, SMOTE-like)
    │   ├── binance_provider.py              # Binance Vision CSV/zip downloads (threaded I/O)
    │   ├── yfinance_provider.py             # Bulk daily OHLCV via yfinance
    │   └── storage.py                       # ParquetStore: organized Parquet file I/O
    ├── features/
    │   ├── engineering.py                   # Feature extraction (technical + FFD + triple barrier + TSFresh)
    │   ├── dataset_builder.py               # Strategy replay, labeling, HMM regimes (threaded)
    │   ├── regime.py                        # HMM-based market regime detection
    │   └── validator.py                     # Pre-training dataset QA (leakage, balance, coverage)
    ├── models/
    │   ├── predictor.py                     # LightGBM classifier + regressor, CPCV splits
    │   ├── tabpfn_model.py                  # TabPFN v2 wrapper (optional)
    │   ├── ensemble.py                      # Stacked ensemble: LightGBM + CatBoost + XGBoost (optional)
    │   ├── meta_labeler.py                  # Meta-labeling architecture
    │   ├── calibration.py                   # Venn-ABERS / Platt / Isotonic + Mondrian conformal
    │   ├── registry.py                      # Model versioning, .joblib export, backend promotion
    │   └── artifacts/                       # Exported model files (.joblib, gitignored)
    │       └── model_*_meta.json            # Metadata sidecars for each trained model
    ├── judge/
    │   ├── judge.py                         # JudgeSystem: orchestrates all validation layers
    │   ├── drift_detector.py                # PSI, KS, SHAP drift, ADWIN, CBPE
    │   ├── wfo_validator.py                 # CPCV integrity, purge/embargo, Deflated Sharpe Ratio
    │   └── report.py                        # JudgeReport generation + verdict + recommendations
    └── pipeline/
        ├── cli.py                           # CLI entry point (argparse subcommands, GIL logging)
        ├── training_loop.py                 # Train/judge cycle (threaded SHAP)
        ├── hyperparameter_tuning.py         # LightGBM CV + Optuna search (threaded grid)
        ├── outcome_tracker.py               # Prediction logging and outcome resolution
        └── retrain.py                       # Continuous retraining policy (RetrainManager)
```

## Data Flow

```
FMP API / yfinance / Binance
        │
        ▼
   data/raw/prices/*.parquet          Raw OHLCV candles
   data/raw/indicators/*.parquet      Technical indicator series
   data/raw/fundamentals/*.parquet    Quarterly fundamentals
        │
        ▼  (build-dataset)
   data/datasets/all_features.parquet          Combined training dataset
   data/datasets/<strategy>_features.parquet   Per-strategy datasets
        │
        ▼  (train)
   ml_training/models/artifacts/
     model_<strategy>_v<N>_<date>.joblib       Trained model bundle
     model_<strategy>_v<N>_<date>_meta.json    Metadata sidecar
        │
        ▼  (promote)
   src/backend/ml/artifacts/model_active.joblib
```

## Model Details

**Primary model:** LightGBM gradient boosting (classifier for direction,
regressor for expected return). Native categorical feature support, handles
missing values, small artifacts (~2-5 MB), millisecond CPU inference.

**Validation:** Combinatorial Purged Cross-Validation (CPCV) with embargo --
prevents lookahead bias from indicator lookback windows and serial
autocorrelation. Produces a distribution of out-of-sample results, not a single
number.

**Calibration:** Venn-ABERS (default) for calibrated probability intervals with
finite-sample guarantees, Platt scaling and Isotonic Regression also available.
Mondrian conformal prediction provides per-strategy conditional coverage.

**Training modes:**

- `--per-strategy` trains separate models per strategy type (swing, momentum,
  earnings_play, etc.)
- Default trains a combined model with `strategy_type` as a categorical feature
- Binary `profitable` target is now the default (use `--three-class` for the old
  UP/DOWN/FLAT direction classification)
- `--model tabpfn` uses TabPFN v2 (zero-tuning transformer, requires `tabpfn`)
- `--model ensemble` uses a stacked ensemble of LightGBM + CatBoost + XGBoost
  (requires `catboost` and `xgboost`)
- `--meta-label` trains only on data where a primary signal fired
- `--regime-split` trains separate models per HMM-detected market regime

## Judge System

Six independent validation layers, each deliberately simpler than what it
judges:

| Layer          | What It Checks                                             | Tool                            |
| -------------- | ---------------------------------------------------------- | ------------------------------- |
| Calibrator     | Probability calibration quality (ECE, Brier)               | Platt / Venn-Abers              |
| Conformal      | Prediction set coverage guarantees                         | MAPIE                           |
| Drift Monitor  | Feature distribution shift, concept drift                  | PSI, KS, SHAP importance, ADWIN |
| WFO Validator  | CPCV integrity, purge/embargo, overfit detection           | Pure statistics + DSR           |
| Strategy Audit | Per-strategy accuracy with sample thresholds               | Accuracy checks                 |
| Reliability    | Meta-learner predicting "will this prediction be correct?" | Logistic Regression             |

**Verdicts:** `PASS` (promote to shadow), `CONDITIONAL_PASS` (approve subset of
strategies), `FAIL` (retrain with adjustments).

## Environment Variables

| Variable      | Required            | Description                     |
| ------------- | ------------------- | ------------------------------- |
| `FMP_API_KEY` | Yes (for `acquire`) | Financial Modeling Prep API key |

The CLI automatically loads `.env` from the project root or parent directories.
You can also pass `--api-key` directly to the `acquire` command.

## Dependencies

Core: `lightgbm`, `scikit-learn`, `joblib`, `pandas`, `numpy`, `pyarrow`,
`httpx`, `pydantic`, `shap`, `mapie`, `scipy`, `tqdm`, `yfinance`, `optuna`,
`hmmlearn`, `tsfresh`, `crepes`

Optional (no pre-built wheels for Python 3.14t yet — code has graceful
`ImportError` fallbacks):

- `catboost`, `xgboost` — needed for `--model ensemble`
- `tabpfn` — needed for `--model tabpfn`
- `river` — needed for ADWIN drift-triggered retraining

Dev: `ruff`, `ty`

## Free-Threading (Python 3.14+)

The pipeline exploits Python 3.14's free-threading (PEP 703 / PEP 779) to
parallelise CPU-bound work via `ThreadPoolExecutor`. When the GIL is disabled,
threads achieve true multi-core parallelism with zero serialisation overhead —
DataFrames and model objects stay in shared memory instead of being pickled
across process boundaries.

**All parallelism is opt-in and gracefully degrades.** When the GIL is active
(default build), CPU-bound code paths fall back to sequential execution.
I/O-bound paths (Binance downloads) always use threads since the GIL is released
during I/O anyway.

### Where it helps

| Area                       | Mechanism                         | Est. Speedup |
| -------------------------- | --------------------------------- | ------------ |
| Dataset building (tickers) | `ThreadPoolExecutor` per ticker   | 4-8x         |
| Hyperparameter grid search | Parallel grid configs             | 3-6x         |
| Per-strategy training      | Concurrent strategy models        | 3-4x         |
| SHAP analysis              | Two parallel `shap_values` calls  | ~2x          |
| Indicator computation      | Parallel ticker x timeframe pairs | 3-5x         |
| Binance downloads          | Parallel HTTP downloads (I/O)     | 5-10x        |

### How to enable

**Important:** The standard `python 3.14` build has the GIL compiled in and
cannot disable it at runtime. You need the separate free-threaded build,
identified by the `t` suffix (`3.14t`):

```bash
# Install the free-threaded interpreter variant (note the 't' suffix)
uv python install 3.14t

# Sync with free-threaded interpreter
uv sync --all-groups --python 3.14t --prerelease=allow

# Run with GIL disabled
uv run --python 3.14t python -X gil=0 -m ml_training.pipeline.cli train
# Or via environment variable:
PYTHON_GIL=0 uv run --python 3.14t ml-train train
```

Without the `t` suffix, you're on the standard build and the CLI will report:

```
Python 3.14.0 — GIL enabled (run with PYTHON_GIL=0 to enable free-threading)
```

With the free-threaded build and `-X gil=0`:

```
Python 3.14.0 — free-threading ACTIVE (GIL disabled)
```

The pipeline works correctly in both modes — it simply falls back to sequential
execution for CPU-bound work when the GIL is active. I/O-bound parallelism
(Binance downloads) uses threads regardless since the GIL is released during
I/O.

### Module

See `ml_training/threading.py` for the utility functions:

- `is_free_threaded()` — check if the GIL is disabled
- `optimal_workers(task_type)` — auto-detect worker count
- `parallel_map(fn, items)` — parallel map with sequential fallback
- `balanced_lgb_njobs(n)` — avoid OpenMP oversubscription

## Code Quality

```bash
cd src/ml_training
uv run ruff format               # Format
uv run ruff check --fix           # Lint + auto-fix
uv run ty check                   # Type check
```

## Relationship to Backend

The training pipeline can import shared code from the backend (schemas, FMP
service) via Python path configuration, but **the backend never imports from
`ml_training`**. The only interface between them is the `.joblib` artifact file
that `promote` copies to `src/backend/ml/artifacts/`.

## References

- Lopez de Prado -- _Advances in Financial Machine Learning_ (2018) -- CPCV,
  purging, embargo, Deflated Sharpe Ratio
- van der Laan et al. (2025) -- _Generalized Venn and Venn-Abers Calibration_
  (ICML 2025)
- Kaya et al. (2025) -- _Conformal Prediction for Reliable Stock Selections_
  (ICML Workshop)

## License

AGPL v3.0 -- see repository root.
