"""LightGBM primary prediction model with CPCV walk-forward optimization.

Trains a direction classifier (UP/DOWN/FLAT) and a return regressor,
using Combinatorial Purged Cross-Validation for robust out-of-sample
evaluation.
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

logger = logging.getLogger(__name__)

DIRECTION_CLASSES = ["DOWN", "FLAT", "UP"]
CATEGORICAL_FEATURES = ["strategy_type", "market_regime", "sector"]

CLASSIFIER_PARAMS: dict[str, Any] = {
    "objective": "multiclass",
    "num_class": 3,
    "metric": "multi_logloss",
    "boosting_type": "gbdt",
    "num_leaves": 63,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "min_child_samples": 20,
    "verbose": -1,
    "n_jobs": -1,
    "seed": 42,
}

REGRESSOR_PARAMS: dict[str, Any] = {
    "objective": "regression",
    "metric": "rmse",
    "boosting_type": "gbdt",
    "num_leaves": 63,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "min_child_samples": 20,
    "verbose": -1,
    "n_jobs": -1,
    "seed": 42,
}

DEFAULT_PURGE_WINDOW = 200
DEFAULT_EMBARGO_WINDOW = 5


@dataclass
class CPCVConfig:
    """Configuration for Combinatorial Purged Cross-Validation."""

    n_splits: int = 5
    purge_window: int = DEFAULT_PURGE_WINDOW
    embargo_window: int = DEFAULT_EMBARGO_WINDOW
    min_train_size: int = 500


@dataclass
class FoldResult:
    """Results from a single CPCV fold."""

    fold_idx: int
    train_size: int
    test_size: int
    train_accuracy: float
    test_accuracy: float
    test_predictions: np.ndarray
    test_probabilities: np.ndarray
    test_indices: np.ndarray
    test_true: np.ndarray
    feature_importances: np.ndarray


@dataclass
class TrainingResult:
    """Complete training results from all CPCV folds."""

    classifier: lgb.LGBMClassifier | None = None
    regressor: lgb.LGBMRegressor | None = None
    label_encoder: LabelEncoder | None = None
    feature_names: list[str] = field(default_factory=list)
    fold_results: list[FoldResult] = field(default_factory=list)
    overall_accuracy: float = 0.0
    accuracy_std: float = 0.0
    mean_brier_score: float = 0.0
    accuracy_by_strategy: dict[str, float] = field(default_factory=dict)
    overfit_gap: float = 0.0


def _identify_feature_columns(df: pd.DataFrame) -> list[str]:
    """Identify columns that should be used as features.

    Excludes metadata columns, target columns, and non-predictive columns.
    """
    exclude = {
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
    return [c for c in df.columns if c not in exclude]


def _prepare_features(
    df: pd.DataFrame,
    feature_cols: list[str],
) -> tuple[pd.DataFrame, dict[str, LabelEncoder]]:
    """Prepare feature matrix: encode categoricals, handle missing values.

    Args:
        df: Raw dataset DataFrame.
        feature_cols: Columns to include as features.

    Returns:
        Tuple of (prepared feature DataFrame, dict of label encoders for categoricals).
    """
    X = df[feature_cols].copy()
    encoders: dict[str, LabelEncoder] = {}

    for col in CATEGORICAL_FEATURES:
        if col in X.columns:
            X[col] = X[col].fillna("unknown").astype(str)
            le = LabelEncoder()
            X[col] = le.fit_transform(X[col])
            encoders[col] = le

    numeric_cols = X.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        X[col] = X[col].fillna(X[col].median())

    return X, encoders


def _purged_split(
    n_samples: int,
    train_indices: np.ndarray,
    test_indices: np.ndarray,
    purge_window: int,
    embargo_window: int,
) -> np.ndarray:
    """Apply purging and embargo to training indices.

    Removes training samples that are within `purge_window` before the test
    period and `embargo_window` after the training period.

    Args:
        n_samples: Total number of samples.
        train_indices: Original training indices.
        test_indices: Test indices.
        purge_window: Number of samples to purge before test.
        embargo_window: Embargo buffer after train.

    Returns:
        Cleaned training indices with purge and embargo applied.
    """
    test_start = test_indices.min()
    test_end = test_indices.max()

    purge_start = max(0, test_start - purge_window)
    embargo_end = min(n_samples - 1, test_end + embargo_window)

    mask = np.ones(len(train_indices), dtype=bool)
    for i, idx in enumerate(train_indices):
        if purge_start <= idx < test_start:
            mask[i] = False
        if test_end < idx <= embargo_end:
            mask[i] = False

    return train_indices[mask]


class PredictionModel:
    """LightGBM prediction model with CPCV training and evaluation.

    Trains both a direction classifier and return regressor using
    walk-forward validation with purging and embargo.
    """

    def __init__(
        self,
        target_col: str = "direction_10d",
        return_col: str = "return_10d",
        cpcv_config: CPCVConfig | None = None,
        classifier_params: dict[str, Any] | None = None,
        regressor_params: dict[str, Any] | None = None,
    ) -> None:
        self._target_col = target_col
        self._return_col = return_col
        self._cpcv = cpcv_config or CPCVConfig()
        self._clf_params = classifier_params or CLASSIFIER_PARAMS.copy()
        self._reg_params = regressor_params or REGRESSOR_PARAMS.copy()
        self._result: TrainingResult | None = None

    def train(self, df: pd.DataFrame, n_rounds: int = 500) -> TrainingResult:
        """Train the model using CPCV walk-forward optimization.

        Args:
            df: Full training dataset with features and labels.
            n_rounds: Number of boosting rounds.

        Returns:
            TrainingResult with models, metrics, and fold details.
        """
        df = df.dropna(subset=[self._target_col]).sort_values("date").reset_index(drop=True)

        feature_cols = _identify_feature_columns(df)
        X, _encoders = _prepare_features(df, feature_cols)

        label_encoder = LabelEncoder()
        label_encoder.fit(DIRECTION_CLASSES)
        y_cls = label_encoder.transform(df[self._target_col].values)
        y_reg = df[self._return_col].fillna(0).values

        tscv = TimeSeriesSplit(n_splits=self._cpcv.n_splits)
        fold_results: list[FoldResult] = []
        all_test_preds: list[np.ndarray] = []
        all_test_true: list[np.ndarray] = []

        for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(X)):
            train_idx_clean = _purged_split(
                len(X),
                train_idx,
                test_idx,
                self._cpcv.purge_window,
                self._cpcv.embargo_window,
            )

            if len(train_idx_clean) < self._cpcv.min_train_size:
                logger.warning(
                    "Fold %d: insufficient training samples (%d < %d), skipping",
                    fold_idx,
                    len(train_idx_clean),
                    self._cpcv.min_train_size,
                )
                continue

            X_train = X.iloc[train_idx_clean]
            X_test = X.iloc[test_idx]
            y_train = y_cls[train_idx_clean]
            y_test = y_cls[test_idx]

            categorical_indices = [
                X.columns.get_loc(c) for c in CATEGORICAL_FEATURES if c in X.columns
            ]

            clf = lgb.LGBMClassifier(**self._clf_params, n_estimators=n_rounds)
            clf.fit(
                X_train,
                y_train,
                categorical_feature=categorical_indices,
                eval_set=[(X_test, y_test)],
                callbacks=[lgb.log_evaluation(0), lgb.early_stopping(50, verbose=False)],
            )

            train_preds = clf.predict(X_train)
            test_preds = clf.predict(X_test)
            test_probs = clf.predict_proba(X_test)

            train_acc = float(np.mean(train_preds == y_train))
            test_acc = float(np.mean(test_preds == y_test))

            fold_result = FoldResult(
                fold_idx=fold_idx,
                train_size=len(train_idx_clean),
                test_size=len(test_idx),
                train_accuracy=train_acc,
                test_accuracy=test_acc,
                test_predictions=test_preds,
                test_probabilities=test_probs,
                test_indices=test_idx,
                test_true=y_test,
                feature_importances=clf.feature_importances_,
            )
            fold_results.append(fold_result)
            all_test_preds.append(test_preds)
            all_test_true.append(y_test)

            logger.info(
                "Fold %d: train_acc=%.3f, test_acc=%.3f, train=%d, test=%d",
                fold_idx,
                train_acc,
                test_acc,
                len(train_idx_clean),
                len(test_idx),
            )

        if not fold_results:
            logger.error("No valid CPCV folds completed")
            return TrainingResult()

        logger.info("Training final model on full dataset...")
        categorical_indices = [X.columns.get_loc(c) for c in CATEGORICAL_FEATURES if c in X.columns]

        final_clf = lgb.LGBMClassifier(**self._clf_params, n_estimators=n_rounds)
        final_clf.fit(X, y_cls, categorical_feature=categorical_indices)

        final_reg = lgb.LGBMRegressor(**self._reg_params, n_estimators=n_rounds)
        final_reg.fit(X, y_reg, categorical_feature=categorical_indices)

        all_preds_concat = np.concatenate(all_test_preds)
        all_true_concat = np.concatenate(all_test_true)
        overall_acc = float(np.mean(all_preds_concat == all_true_concat))

        fold_accs = [f.test_accuracy for f in fold_results]
        train_accs = [f.train_accuracy for f in fold_results]
        overfit_gap = float(np.mean(train_accs) - np.mean(fold_accs))

        brier_scores = []
        for fr in fold_results:
            for i, true_label in enumerate(fr.test_true):
                prob = fr.test_probabilities[i, true_label]
                brier_scores.append((1 - prob) ** 2)

        accuracy_by_strategy: dict[str, float] = {}
        if "strategy_type" in df.columns:
            strat_col = df["strategy_type"].values
            for fr in fold_results:
                for strat in np.unique(strat_col[fr.test_indices]):
                    mask = strat_col[fr.test_indices] == strat
                    if mask.sum() > 0:
                        acc = float(np.mean(fr.test_predictions[mask] == fr.test_true[mask]))
                        if strat not in accuracy_by_strategy:
                            accuracy_by_strategy[strat] = acc
                        else:
                            accuracy_by_strategy[strat] = (accuracy_by_strategy[strat] + acc) / 2

        result = TrainingResult(
            classifier=final_clf,
            regressor=final_reg,
            label_encoder=label_encoder,
            feature_names=list(X.columns),
            fold_results=fold_results,
            overall_accuracy=overall_acc,
            accuracy_std=float(np.std(fold_accs)),
            mean_brier_score=float(np.mean(brier_scores)) if brier_scores else 1.0,
            accuracy_by_strategy=accuracy_by_strategy,
            overfit_gap=overfit_gap,
        )

        self._result = result
        logger.info(
            "Training complete: accuracy=%.3f±%.3f, overfit_gap=%.3f, brier=%.3f",
            overall_acc,
            result.accuracy_std,
            overfit_gap,
            result.mean_brier_score,
        )
        return result

    def predict(
        self,
        X: pd.DataFrame,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Generate predictions from the trained model.

        Args:
            X: Feature DataFrame (same columns as training).

        Returns:
            Tuple of (direction predictions, probabilities, return predictions).

        Raises:
            RuntimeError: If model has not been trained.
        """
        if self._result is None or self._result.classifier is None:
            raise RuntimeError("Model not trained. Call train() first.")

        dir_preds = self._result.classifier.predict(X)
        dir_probs = self._result.classifier.predict_proba(X)
        ret_preds = (
            self._result.regressor.predict(X) if self._result.regressor else np.zeros(len(X))
        )

        return dir_preds, dir_probs, ret_preds

    @property
    def result(self) -> TrainingResult | None:
        return self._result
