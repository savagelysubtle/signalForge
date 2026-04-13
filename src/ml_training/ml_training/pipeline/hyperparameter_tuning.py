"""Automated hyperparameter search for LightGBM models.

Uses LightGBM's built-in cross-validation with time-series splits
to find optimal hyperparameters without overfitting.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import LabelEncoder

from ml_training.models.predictor import (
    CATEGORICAL_FEATURES,
    DEFAULT_EMBARGO_WINDOW,
    DEFAULT_PURGE_WINDOW,
    DIRECTION_CLASSES,
    _identify_feature_columns,
    _prepare_features,
    _purged_split,
    compute_sample_weights,
)
from ml_training.threading import balanced_lgb_njobs, optimal_workers

logger = logging.getLogger(__name__)


@dataclass
class HyperparameterSearchResult:
    """Results from a hyperparameter search."""

    best_params: dict[str, Any] = field(default_factory=dict)
    best_score: float = 0.0
    all_results: list[dict[str, Any]] = field(default_factory=list)
    n_trials: int = 0


PARAM_GRID: list[dict[str, Any]] = [
    {
        "num_leaves": 15,
        "max_depth": 5,
        "learning_rate": 0.05,
        "min_child_samples": 50,
        "reg_lambda": 1.0,
    },
    {
        "num_leaves": 31,
        "max_depth": 8,
        "learning_rate": 0.05,
        "min_child_samples": 30,
        "reg_lambda": 1.0,
    },
    {
        "num_leaves": 31,
        "max_depth": 6,
        "learning_rate": 0.1,
        "min_child_samples": 50,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
    },
    {
        "num_leaves": 31,
        "max_depth": 8,
        "learning_rate": 0.03,
        "min_child_samples": 30,
        "reg_alpha": 0.5,
        "reg_lambda": 2.0,
    },
    {
        "num_leaves": 15,
        "max_depth": 5,
        "learning_rate": 0.05,
        "min_child_samples": 80,
        "feature_fraction": 0.6,
        "reg_lambda": 2.0,
    },
    {
        "num_leaves": 31,
        "max_depth": 6,
        "learning_rate": 0.05,
        "min_child_samples": 50,
        "feature_fraction": 0.6,
        "bagging_fraction": 0.7,
        "reg_lambda": 1.0,
    },
    {
        "boosting_type": "dart",
        "num_leaves": 15,
        "max_depth": 4,
        "learning_rate": 0.03,
        "min_child_samples": 100,
        "drop_rate": 0.1,
        "reg_lambda": 5.0,
    },
    {
        "num_leaves": 15,
        "max_depth": 4,
        "learning_rate": 0.05,
        "min_child_samples": 100,
        "reg_lambda": 5.0,
    },
]


class HyperparameterTuner:
    """Grid search over LightGBM hyperparameters with time-series CV.

    Uses a predefined parameter grid (not random search) for
    reproducibility and interpretability.
    """

    def __init__(
        self,
        target_col: str = "direction_10d",
        n_cv_splits: int = 8,
        n_boost_rounds: int = 300,
        param_grid: list[dict[str, Any]] | None = None,
        purge_window: int = DEFAULT_PURGE_WINDOW,
        embargo_window: int = DEFAULT_EMBARGO_WINDOW,
        binary_mode: bool = False,
        inference_only: bool = False,
    ) -> None:
        self._target_col = target_col
        self._n_splits = n_cv_splits
        self._n_rounds = n_boost_rounds
        self._grid = param_grid or PARAM_GRID
        self._purge_window = purge_window
        self._embargo_window = embargo_window
        self._binary_mode = binary_mode
        self._inference_only = inference_only

    def search(self, dataset: pd.DataFrame) -> HyperparameterSearchResult:
        """Run hyperparameter search across the parameter grid.

        Grid configs are evaluated in parallel when free-threading is
        active.  Each config's ``n_jobs`` is balanced to avoid OpenMP
        oversubscription.

        Args:
            dataset: Full training dataset with features and labels.

        Returns:
            HyperparameterSearchResult with best parameters and scores.
        """
        df = dataset.dropna(subset=[self._target_col]).sort_values("date").reset_index(drop=True)

        feature_cols = _identify_feature_columns(df, inference_only=self._inference_only)

        X, _encoders = _prepare_features(df, feature_cols)
        if self._binary_mode:
            le = LabelEncoder()
            le.fit([0, 1])
            y = df[self._target_col].astype(int).values
        else:
            le = LabelEncoder()
            le.fit(DIRECTION_CLASSES)
            y = le.transform(df[self._target_col].values)

        categorical_indices = [X.columns.get_loc(c) for c in CATEGORICAL_FEATURES if c in X.columns]

        n_samples = len(X)
        workers = optimal_workers("cpu")
        per_model_njobs = balanced_lgb_njobs(workers) if workers > 1 else -1

        if self._binary_mode:
            base_obj, base_metric = "binary", "binary_logloss"
        else:
            base_obj, base_metric = "multiclass", "multi_logloss"

        def _evaluate_config(params: dict[str, Any]) -> dict[str, Any]:
            """Evaluate one hyperparameter config across CV folds."""
            full_params: dict[str, Any] = {
                "objective": base_obj,
                "metric": base_metric,
                "boosting_type": "gbdt",
                "feature_fraction": 0.8,
                "bagging_fraction": 0.8,
                "bagging_freq": 5,
                "is_unbalance": True,
                "verbose": -1,
                "n_jobs": per_model_njobs,
                "seed": 42,
                **params,
            }
            if not self._binary_mode:
                full_params.setdefault("num_class", 3)

            tscv = TimeSeriesSplit(n_splits=self._n_splits)
            fold_scores: list[float] = []
            fold_train_scores: list[float] = []

            for raw_train_idx, test_idx in tscv.split(X):
                train_idx = _purged_split(
                    n_samples,
                    raw_train_idx,
                    test_idx,
                    self._purge_window,
                    self._embargo_window,
                )
                X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
                y_train, y_test = y[train_idx], y[test_idx]

                clf = lgb.LGBMClassifier(**full_params, n_estimators=self._n_rounds)
                clf.fit(
                    X_train,
                    y_train,
                    categorical_feature=categorical_indices,
                    eval_set=[(X_test, y_test)],
                    callbacks=[lgb.log_evaluation(0), lgb.early_stopping(50, verbose=False)],
                )
                if self._binary_mode:
                    te_bs = float(brier_score_loss(y_test, clf.predict_proba(X_test)[:, 1]))
                    tr_bs = float(brier_score_loss(y_train, clf.predict_proba(X_train)[:, 1]))
                    base_rate = float(np.mean(y_test))
                    bs_ref = base_rate * (1.0 - base_rate)
                    fold_scores.append(1.0 - (te_bs / bs_ref) if bs_ref > 1e-9 else 0.0)
                    fold_train_scores.append(1.0 - (tr_bs / bs_ref) if bs_ref > 1e-9 else 0.0)
                else:
                    te_ll = float(log_loss(y_test, clf.predict_proba(X_test)))
                    tr_ll = float(log_loss(y_train, clf.predict_proba(X_train)))
                    class_dist = np.bincount(y_test, minlength=3).astype(float) / len(y_test)
                    naive_ll = -float(np.sum(class_dist * np.log(np.clip(class_dist, 1e-15, 1.0))))
                    fold_scores.append(1.0 - (te_ll / naive_ll) if naive_ll > 1e-9 else 0.0)
                    fold_train_scores.append(1.0 - (tr_ll / naive_ll) if naive_ll > 1e-9 else 0.0)

            mean_score = float(np.mean(fold_scores))
            std_score = float(np.std(fold_scores))
            mean_train = float(np.mean(fold_train_scores))
            overfit_gap = max(mean_train - mean_score, 0.0)
            fold_variance = float(np.var(fold_scores))
            consistency_penalty = fold_variance * 3.0
            composite = mean_score - 1.0 * overfit_gap - consistency_penalty

            return {
                "params": params,
                "full_params": full_params,
                "mean_brier_skill": mean_score,
                "std_brier_skill": std_score,
                "overfit_gap": overfit_gap,
                "fold_variance": fold_variance,
                "composite_score": composite,
                "fold_scores": fold_scores,
            }

        if workers > 1:
            logger.info(
                "Parallel grid search: %d configs across %d threads (n_jobs=%d per model)",
                len(self._grid),
                workers,
                per_model_njobs,
            )
            results: list[dict[str, Any]] = []
            with ThreadPoolExecutor(max_workers=workers) as pool:
                future_to_idx = {
                    pool.submit(_evaluate_config, p): i for i, p in enumerate(self._grid)
                }
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    result = future.result()
                    results.append(result)
                    logger.info(
                        "Config %d/%d: brier_skill=%.3f±%.3f gap=%.3f composite=%.3f | %s",
                        idx + 1,
                        len(self._grid),
                        result["mean_brier_skill"],
                        result["std_brier_skill"],
                        result["overfit_gap"],
                        result["composite_score"],
                        result["params"],
                    )
        else:
            results = []
            for i, params in enumerate(self._grid):
                result = _evaluate_config(params)
                results.append(result)
                logger.info(
                    "Config %d/%d: brier_skill=%.3f±%.3f gap=%.3f composite=%.3f | %s",
                    i + 1,
                    len(self._grid),
                    result["mean_brier_skill"],
                    result["std_brier_skill"],
                    result["overfit_gap"],
                    result["composite_score"],
                    result["params"],
                )

        best = max(results, key=lambda r: r["composite_score"])

        return HyperparameterSearchResult(
            best_params=best["full_params"],
            best_score=best["composite_score"],
            all_results=[{k: v for k, v in r.items() if k != "full_params"} for r in results],
            n_trials=len(self._grid),
        )

    def search_optuna(
        self,
        dataset: pd.DataFrame,
        n_trials: int = 50,
    ) -> HyperparameterSearchResult:
        """Bayesian hyperparameter search using Optuna TPE sampler.

        Falls back to grid search if optuna is not installed.

        Args:
            dataset: Full training dataset with features and labels.
            n_trials: Number of Optuna trials to run.

        Returns:
            HyperparameterSearchResult with best parameters.
        """
        try:
            import optuna
        except ImportError:
            logger.warning("optuna not installed, falling back to grid search")
            return self.search(dataset)

        optuna.logging.set_verbosity(optuna.logging.WARNING)

        df = dataset.dropna(subset=[self._target_col]).sort_values("date").reset_index(drop=True)
        feature_cols = _identify_feature_columns(df, inference_only=self._inference_only)

        X, _encoders = _prepare_features(df, feature_cols)
        if self._binary_mode:
            le = LabelEncoder()
            le.fit([0, 1])
            y = df[self._target_col].astype(int).values
        else:
            le = LabelEncoder()
            le.fit(DIRECTION_CLASSES)
            y = le.transform(df[self._target_col].values)
        categorical_indices = [X.columns.get_loc(c) for c in CATEGORICAL_FEATURES if c in X.columns]
        n_samples = len(X)
        tscv = TimeSeriesSplit(n_splits=self._n_splits)

        if self._binary_mode:
            obj_name, obj_metric = "binary", "binary_logloss"
        else:
            obj_name, obj_metric = "multiclass", "multi_logloss"

        workers = min(optimal_workers("cpu"), 4)
        per_model_njobs = balanced_lgb_njobs(workers) if workers > 1 else -1
        splits = list(tscv.split(X))

        logger.info(
            "Optuna search: %d trials, %d parallel folds, n_jobs=%d per model",
            n_trials,
            workers,
            per_model_njobs,
        )

        purge_window = self._purge_window
        embargo_window = self._embargo_window
        n_rounds = self._n_rounds
        binary_mode = self._binary_mode

        def _eval_fold(
            fold_args: tuple[np.ndarray, np.ndarray, dict[str, Any], np.ndarray],
        ) -> tuple[float, float, int]:
            """Evaluate one CV fold.  Returns (test_bss, train_bss, best_iter)."""
            raw_train_idx, test_idx, params, sample_weights = fold_args
            train_idx = _purged_split(
                n_samples,
                raw_train_idx,
                test_idx,
                purge_window,
                embargo_window,
            )
            X_tr, X_te = X.iloc[train_idx], X.iloc[test_idx]
            y_tr, y_te = y[train_idx], y[test_idx]
            w_tr = sample_weights[train_idx]

            clf = lgb.LGBMClassifier(**params, n_estimators=n_rounds)
            clf.fit(
                X_tr,
                y_tr,
                sample_weight=w_tr,
                categorical_feature=categorical_indices,
                eval_set=[(X_te, y_te)],
                callbacks=[lgb.log_evaluation(0), lgb.early_stopping(50, verbose=False)],
            )
            best_iter = getattr(clf, "best_iteration_", n_rounds)

            if binary_mode:
                te_bs = float(brier_score_loss(y_te, clf.predict_proba(X_te)[:, 1]))
                tr_bs = float(brier_score_loss(y_tr, clf.predict_proba(X_tr)[:, 1]))
                base_rate = float(np.mean(y_te))
                bs_ref = base_rate * (1.0 - base_rate)
                te_bss = 1.0 - (te_bs / bs_ref) if bs_ref > 1e-9 else 0.0
                tr_bss = 1.0 - (tr_bs / bs_ref) if bs_ref > 1e-9 else 0.0
            else:
                te_ll = float(log_loss(y_te, clf.predict_proba(X_te)))
                tr_ll = float(log_loss(y_tr, clf.predict_proba(X_tr)))
                class_dist = np.bincount(y_te, minlength=3).astype(float) / len(y_te)
                naive_ll = -float(np.sum(class_dist * np.log(np.clip(class_dist, 1e-15, 1.0))))
                te_bss = 1.0 - (te_ll / naive_ll) if naive_ll > 1e-9 else 0.0
                tr_bss = 1.0 - (tr_ll / naive_ll) if naive_ll > 1e-9 else 0.0
            return te_bss, tr_bss, best_iter

        def objective(trial: optuna.Trial) -> float:
            params: dict[str, Any] = {
                "objective": obj_name,
                "metric": obj_metric,
                "boosting_type": "gbdt",
                "is_unbalance": True,
                "verbose": -1,
                "n_jobs": per_model_njobs,
                "seed": 42,
            }
            if not self._binary_mode:
                params["num_class"] = 3
            params.update(
                {
                    "num_leaves": trial.suggest_int("num_leaves", 15, 63),
                    "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
                    "min_child_samples": trial.suggest_int(
                        "min_child_samples", 20, max(150, n_samples // 2000)
                    ),
                    "feature_fraction": trial.suggest_float("feature_fraction", 0.4, 0.8),
                    "bagging_fraction": trial.suggest_float("bagging_fraction", 0.6, 0.9),
                    "bagging_freq": 1,
                    "reg_alpha": trial.suggest_float("reg_alpha", 0.01, 5.0, log=True),
                    "reg_lambda": trial.suggest_float("reg_lambda", 0.1, 10.0, log=True),
                    "max_depth": trial.suggest_int("max_depth", 4, 8),
                    "min_gain_to_split": trial.suggest_float(
                        "min_gain_to_split", 0.001, 0.1, log=True
                    ),
                }
            )
            decay_lambda = trial.suggest_float("decay_lambda", 0.0, 0.15)
            sample_weights = compute_sample_weights(
                n_samples, horizon=10, decay_lambda=decay_lambda
            )

            fold_args = [
                (raw_train_idx, test_idx, params, sample_weights)
                for raw_train_idx, test_idx in splits
            ]

            if workers > 1:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    results = list(pool.map(_eval_fold, fold_args))
            else:
                results = [_eval_fold(fa) for fa in fold_args]

            fold_test_scores = [r[0] for r in results]
            fold_train_scores = [r[1] for r in results]
            fold_iters = [r[2] for r in results]

            mean_test = float(np.mean(fold_test_scores))
            mean_train = float(np.mean(fold_train_scores))
            gap = max(mean_train - mean_test, 0.0)
            fold_variance = float(np.var(fold_test_scores))

            median_iter = float(np.median(fold_iters))
            if median_iter <= 1:
                learning_penalty = 0.3
            elif median_iter <= 3:
                learning_penalty = 0.1
            else:
                learning_penalty = 0.0

            return mean_test - 1.0 * gap - 3.0 * fold_variance - learning_penalty

        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler())
        study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

        best_trial = study.best_trial
        lgb_params = {k: v for k, v in best_trial.params.items() if k != "decay_lambda"}
        best_full_params: dict[str, Any] = {
            "objective": obj_name,
            "metric": obj_metric,
            "boosting_type": "gbdt",
            "is_unbalance": True,
            "verbose": -1,
            "n_jobs": -1,
            "seed": 42,
            "bagging_freq": 1,
            **lgb_params,
        }
        if not self._binary_mode:
            best_full_params["num_class"] = 3

        logger.info(
            "Optuna best: composite=%.4f after %d trials (decay_lambda=%.3f) | %s",
            best_trial.value,
            n_trials,
            best_trial.params.get("decay_lambda", 0.0),
            best_trial.params,
        )

        best_full_params["_decay_lambda"] = best_trial.params.get("decay_lambda", 0.0)

        return HyperparameterSearchResult(
            best_params=best_full_params,
            best_score=best_trial.value or 0.0,
            all_results=[
                {"trial": t.number, "value": t.value, "params": t.params} for t in study.trials
            ],
            n_trials=n_trials,
        )

    @staticmethod
    def save_best_params(
        result: HyperparameterSearchResult,
        data_dir: Path,
        strategy_type: str | None = None,
    ) -> Path:
        """Save best hyperparameters to JSON for the train command to pick up.

        Args:
            result: Tuning search result.
            data_dir: Base data directory (e.g. data/raw).
            strategy_type: If provided, saves as ``best_params_{strategy_type}.json``.

        Returns:
            Path to the saved JSON file.
        """
        filename = f"best_params_{strategy_type}.json" if strategy_type else "best_params.json"
        path = data_dir / filename
        payload = {
            "best_params": result.best_params,
            "best_score": result.best_score,
            "n_trials": result.n_trials,
            "strategy_type": strategy_type,
        }
        path.write_text(json.dumps(payload, indent=2))
        logger.info("Saved best params to %s (score=%.4f)", path, result.best_score)
        return path


def load_tuned_params(
    data_dir: Path,
    strategy_type: str | None = None,
) -> dict[str, Any] | None:
    """Load previously tuned hyperparameters from JSON.

    Args:
        data_dir: Base data directory containing best_params.json.
        strategy_type: If provided, loads ``best_params_{strategy_type}.json``.

    Returns:
        Dict of LightGBM params, or None if no tuning results exist.
    """
    if strategy_type:
        path = data_dir / f"best_params_{strategy_type}.json"
    else:
        path = data_dir / "best_params.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    logger.info(
        "Loaded tuned params from %s (score=%.4f, %d trials)",
        path,
        payload.get("best_score", 0),
        payload.get("n_trials", 0),
    )
    return payload.get("best_params")
