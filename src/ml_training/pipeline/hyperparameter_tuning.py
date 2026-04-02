"""Automated hyperparameter search for LightGBM models.

Uses LightGBM's built-in cross-validation with time-series splits
to find optimal hyperparameters without overfitting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import LabelEncoder

from ml_training.models.predictor import CATEGORICAL_FEATURES, DIRECTION_CLASSES, _prepare_features

logger = logging.getLogger(__name__)


@dataclass
class HyperparameterSearchResult:
    """Results from a hyperparameter search."""

    best_params: dict[str, Any] = field(default_factory=dict)
    best_score: float = 0.0
    all_results: list[dict[str, Any]] = field(default_factory=list)
    n_trials: int = 0


PARAM_GRID: list[dict[str, Any]] = [
    {"num_leaves": 31, "learning_rate": 0.1, "min_child_samples": 20},
    {"num_leaves": 63, "learning_rate": 0.05, "min_child_samples": 20},
    {"num_leaves": 63, "learning_rate": 0.05, "min_child_samples": 50},
    {"num_leaves": 127, "learning_rate": 0.03, "min_child_samples": 30},
    {"num_leaves": 31, "learning_rate": 0.05, "feature_fraction": 0.7},
    {"num_leaves": 63, "learning_rate": 0.05, "feature_fraction": 0.6, "bagging_fraction": 0.7},
    {"num_leaves": 31, "learning_rate": 0.1, "min_child_samples": 50, "reg_alpha": 0.1},
    {"num_leaves": 63, "learning_rate": 0.03, "min_child_samples": 30, "reg_lambda": 0.1},
]


class HyperparameterTuner:
    """Grid search over LightGBM hyperparameters with time-series CV.

    Uses a predefined parameter grid (not random search) for
    reproducibility and interpretability.
    """

    def __init__(
        self,
        target_col: str = "direction_10d",
        n_cv_splits: int = 3,
        n_boost_rounds: int = 300,
        param_grid: list[dict[str, Any]] | None = None,
    ) -> None:
        self._target_col = target_col
        self._n_splits = n_cv_splits
        self._n_rounds = n_boost_rounds
        self._grid = param_grid or PARAM_GRID

    def search(self, dataset: pd.DataFrame) -> HyperparameterSearchResult:
        """Run hyperparameter search across the parameter grid.

        Args:
            dataset: Full training dataset with features and labels.

        Returns:
            HyperparameterSearchResult with best parameters and scores.
        """
        df = dataset.dropna(subset=[self._target_col]).sort_values("date").reset_index(drop=True)

        feature_cols = [
            c
            for c in df.columns
            if c
            not in {
                "ticker",
                "date",
                "strategy_id",
                "timeframe",
                "close",
                "return_5d",
                "return_10d",
                "return_20d",
                "direction_5d",
                "direction_10d",
                "direction_20d",
                "max_favorable_excursion",
                "max_adverse_excursion",
                "stop_hit",
            }
        ]

        X, _encoders = _prepare_features(df, feature_cols)
        le = LabelEncoder()
        le.fit(DIRECTION_CLASSES)
        y = le.transform(df[self._target_col].values)

        categorical_indices = [X.columns.get_loc(c) for c in CATEGORICAL_FEATURES if c in X.columns]

        tscv = TimeSeriesSplit(n_splits=self._n_splits)
        results: list[dict[str, Any]] = []
        best_score = -1.0
        best_params: dict[str, Any] = {}

        for i, params in enumerate(self._grid):
            full_params = {
                "objective": "multiclass",
                "num_class": 3,
                "metric": "multi_logloss",
                "boosting_type": "gbdt",
                "feature_fraction": 0.8,
                "bagging_fraction": 0.8,
                "bagging_freq": 5,
                "verbose": -1,
                "n_jobs": -1,
                "seed": 42,
                **params,
            }

            fold_scores: list[float] = []
            for train_idx, test_idx in tscv.split(X):
                X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
                y_train, y_test = y[train_idx], y[test_idx]

                clf = lgb.LGBMClassifier(**full_params, n_estimators=self._n_rounds)
                clf.fit(
                    X_train,
                    y_train,
                    categorical_feature=categorical_indices,
                    eval_set=[(X_test, y_test)],
                    callbacks=[lgb.log_evaluation(0), lgb.early_stopping(30, verbose=False)],
                )
                score = float(np.mean(clf.predict(X_test) == y_test))
                fold_scores.append(score)

            mean_score = float(np.mean(fold_scores))
            std_score = float(np.std(fold_scores))

            result = {
                "params": params,
                "mean_accuracy": mean_score,
                "std_accuracy": std_score,
                "fold_scores": fold_scores,
            }
            results.append(result)

            logger.info(
                "Config %d/%d: accuracy=%.3f±%.3f | %s",
                i + 1,
                len(self._grid),
                mean_score,
                std_score,
                params,
            )

            if mean_score > best_score:
                best_score = mean_score
                best_params = full_params

        return HyperparameterSearchResult(
            best_params=best_params,
            best_score=best_score,
            all_results=results,
            n_trials=len(self._grid),
        )
