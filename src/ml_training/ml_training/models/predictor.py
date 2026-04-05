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
    "num_leaves": 15,
    "max_depth": 5,
    "learning_rate": 0.05,
    "feature_fraction": 0.6,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "min_child_samples": 100,
    "reg_alpha": 0.1,
    "reg_lambda": 5.0,
    "is_unbalance": True,
    "verbose": -1,
    "n_jobs": -1,
    "seed": 42,
}

BINARY_CLASSIFIER_PARAMS: dict[str, Any] = {
    "objective": "binary",
    "metric": "binary_logloss",
    "boosting_type": "gbdt",
    "num_leaves": 15,
    "max_depth": 5,
    "learning_rate": 0.05,
    "feature_fraction": 0.6,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "min_child_samples": 100,
    "reg_alpha": 0.1,
    "reg_lambda": 5.0,
    "is_unbalance": True,
    "verbose": -1,
    "n_jobs": -1,
    "seed": 42,
}

REGRESSOR_PARAMS: dict[str, Any] = {
    "objective": "regression",
    "metric": "rmse",
    "boosting_type": "gbdt",
    "num_leaves": 15,
    "max_depth": 5,
    "learning_rate": 0.05,
    "feature_fraction": 0.6,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "min_child_samples": 100,
    "reg_alpha": 0.1,
    "reg_lambda": 5.0,
    "verbose": -1,
    "n_jobs": -1,
    "seed": 42,
}

DEFAULT_PURGE_WINDOW = 25
DEFAULT_EMBARGO_WINDOW = 10

N_ENSEMBLE_SEEDS = 7


@dataclass
class CPCVConfig:
    """Configuration for Combinatorial Purged Cross-Validation."""

    n_splits: int = 5
    purge_window: int = DEFAULT_PURGE_WINDOW
    embargo_window: int = DEFAULT_EMBARGO_WINDOW
    min_train_size: int = 500
    forward_horizon: int = 10


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
    train_indices: np.ndarray
    test_indices: np.ndarray
    test_true: np.ndarray
    feature_importances: np.ndarray
    best_iteration: int = 0


@dataclass
class TrainingResult:
    """Complete training results from all CPCV folds."""

    classifier: lgb.LGBMClassifier | None = None
    classifiers: list[lgb.LGBMClassifier] = field(default_factory=list)
    regressor: lgb.LGBMRegressor | None = None
    label_encoder: LabelEncoder | None = None
    feature_names: list[str] = field(default_factory=list)
    fold_results: list[FoldResult] = field(default_factory=list)
    overall_accuracy: float = 0.0
    accuracy_std: float = 0.0
    mean_brier_score: float = 0.0
    accuracy_by_strategy: dict[str, float] = field(default_factory=dict)
    overfit_gap: float = 0.0


def _identify_feature_columns(
    df: pd.DataFrame,
    model_mode: str = "shadow",
) -> list[str]:
    """Identify columns that should be used as features.

    Excludes metadata columns, target columns, and non-predictive columns.
    Uses prefix matching so any horizon (``return_Xd``, ``direction_Xd``)
    is automatically excluded.

    Args:
        df: Dataset DataFrame.
        model_mode: ``"independent"`` excludes LLM-derived features (for the
            gate model that runs before GPT).  ``"shadow"`` includes everything.
    """
    from ml_training.features.engineering import LLM_FEATURES

    exclude = {
        "ticker",
        "date",
        "strategy_id",
        "timeframe",
        "close",
        "max_favorable_excursion",
        "max_adverse_excursion",
        "stop_hit",
        "profitable",
        "triple_barrier_label",
        "barrier_type",
        "bars_to_barrier",
        "risk_reward_ratio",
    }
    if model_mode == "independent":
        exclude |= LLM_FEATURES

    cols = [
        c
        for c in df.columns
        if c not in exclude and not c.startswith("return_") and not c.startswith("direction_")
    ]

    if model_mode == "independent":
        leaked = frozenset(cols) & LLM_FEATURES
        if leaked:
            raise ValueError(f"Independent model must not use LLM features, found: {leaked}")

    return cols


def _prepare_features(
    df: pd.DataFrame,
    feature_cols: list[str],
    fit_indices: np.ndarray | None = None,
) -> tuple[pd.DataFrame, dict[str, LabelEncoder]]:
    """Prepare feature matrix: encode categoricals, handle missing values.

    Args:
        df: Raw dataset DataFrame.
        feature_cols: Columns to include as features.
        fit_indices: If provided, compute imputation medians only from these
            rows to prevent look-ahead bias.  When ``None`` all rows are used
            (backward-compatible for non-training callers).

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

    non_cat = [c for c in X.columns if c not in CATEGORICAL_FEATURES]
    for col in non_cat:
        X[col] = pd.to_numeric(X[col], errors="coerce")

    fit_slice = X.iloc[fit_indices] if fit_indices is not None else X
    numeric_cols = X.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        median = fit_slice[col].median()
        X[col] = X[col].fillna(median if pd.notna(median) else 0.0)

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


def compute_sample_weights(n_samples: int, horizon: int) -> np.ndarray:
    """Weight samples by label uniqueness to correct for overlapping returns.

    With *horizon*-bar forward returns, consecutive samples share most of
    their forward window.  This assigns lower weight to samples surrounded
    by many overlapping neighbours (Lopez de Prado, Ch. 4).
    """
    weights = np.empty(n_samples, dtype=np.float64)
    for i in range(n_samples):
        lo = max(0, i - horizon)
        hi = min(n_samples, i + horizon + 1)
        weights[i] = 1.0 / (hi - lo)
    weights /= weights.mean()
    return weights


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
        binary_mode: bool = False,
        model_mode: str = "shadow",
    ) -> None:
        self._target_col = target_col
        self._return_col = return_col
        self._cpcv = cpcv_config or CPCVConfig()
        self._binary_mode = binary_mode
        self._model_mode = model_mode
        if binary_mode:
            self._clf_params = classifier_params or BINARY_CLASSIFIER_PARAMS.copy()
        else:
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

        feature_cols = _identify_feature_columns(df, model_mode=self._model_mode)
        X, _encoders = _prepare_features(df, feature_cols)

        if self._binary_mode:
            label_encoder = LabelEncoder()
            label_encoder.fit([0, 1])
            y_cls = df[self._target_col].astype(int).values
        else:
            label_encoder = LabelEncoder()
            label_encoder.fit(DIRECTION_CLASSES)
            y_cls = label_encoder.transform(df[self._target_col].values)

        return_col = self._return_col if self._return_col in df.columns else None
        y_reg = df[return_col].fillna(0).values if return_col else np.zeros(len(df))

        sample_weights = compute_sample_weights(len(X), self._cpcv.forward_horizon)

        n_samples = len(X)
        effective_splits = self._cpcv.n_splits
        effective_purge = max(self._cpcv.purge_window, self._cpcv.forward_horizon)
        effective_embargo = max(self._cpcv.embargo_window, self._cpcv.forward_horizon // 2)

        if n_samples < 100_000:
            effective_splits = min(self._cpcv.n_splits, 3)
            effective_purge = min(effective_purge, max(20, n_samples // 500))
            logger.info(
                "Small dataset (%d rows): n_splits=%d, purge=%d, embargo=%d",
                n_samples,
                effective_splits,
                effective_purge,
                effective_embargo,
            )

        tscv = TimeSeriesSplit(n_splits=effective_splits)
        fold_results: list[FoldResult] = []
        all_test_preds: list[np.ndarray] = []
        all_test_true: list[np.ndarray] = []

        for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(X)):
            train_idx_clean = _purged_split(
                n_samples,
                train_idx,
                test_idx,
                effective_purge,
                effective_embargo,
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
            w_train = sample_weights[train_idx_clean]

            categorical_indices = [
                X.columns.get_loc(c) for c in CATEGORICAL_FEATURES if c in X.columns
            ]

            clf = lgb.LGBMClassifier(**self._clf_params, n_estimators=n_rounds)
            clf.fit(
                X_train,
                y_train,
                sample_weight=w_train,
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
                train_indices=train_idx_clean,
                test_indices=test_idx,
                test_true=y_test,
                feature_importances=clf.feature_importances_,
                best_iteration=getattr(clf, "best_iteration_", n_rounds),
            )
            fold_results.append(fold_result)
            all_test_preds.append(test_preds)
            all_test_true.append(y_test)

            logger.info(
                "Fold %d: train_acc=%.3f, test_acc=%.3f, best_iter=%d, train=%d, test=%d",
                fold_idx,
                train_acc,
                test_acc,
                fold_result.best_iteration,
                len(train_idx_clean),
                len(test_idx),
            )

        if not fold_results:
            logger.error("No valid CPCV folds completed")
            return TrainingResult()

        # --- Final model: early-stopped seed ensemble ---
        best_iters = [fr.best_iteration for fr in fold_results if fr.best_iteration > 0]
        final_n = int(np.median(best_iters)) if best_iters else n_rounds
        logger.info(
            "Training final ensemble (%d seeds, %d rounds from CV median)...",
            N_ENSEMBLE_SEEDS,
            final_n,
        )

        categorical_indices = [X.columns.get_loc(c) for c in CATEGORICAL_FEATURES if c in X.columns]

        # Hold out last 10% for early stopping on the final fit
        split_n = int(len(X) * 0.9)
        X_fit, X_val = X.iloc[:split_n], X.iloc[split_n:]
        y_fit, y_val = y_cls[:split_n], y_cls[split_n:]
        w_fit = sample_weights[:split_n]

        final_classifiers: list[lgb.LGBMClassifier] = []
        for seed in range(N_ENSEMBLE_SEEDS):
            seed_params = {
                **self._clf_params,
                "seed": seed,
                "feature_fraction_seed": seed,
            }
            clf = lgb.LGBMClassifier(**seed_params, n_estimators=final_n)
            clf.fit(
                X_fit,
                y_fit,
                sample_weight=w_fit,
                categorical_feature=categorical_indices,
                eval_set=[(X_val, y_val)],
                callbacks=[lgb.log_evaluation(0), lgb.early_stopping(50, verbose=False)],
            )
            final_classifiers.append(clf)

        primary_clf = final_classifiers[0]

        reg_params = {**self._reg_params, "seed": 0}
        final_reg = lgb.LGBMRegressor(**reg_params, n_estimators=final_n)
        final_reg.fit(
            X_fit,
            y_reg[:split_n],
            sample_weight=w_fit,
            categorical_feature=categorical_indices,
            eval_set=[(X_val, y_reg[split_n:])],
            callbacks=[lgb.log_evaluation(0), lgb.early_stopping(50, verbose=False)],
        )

        # --- Aggregate metrics ---
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
                strat_counts: dict[str, list[float]] = {}
                for strat in np.unique(strat_col[fr.test_indices]):
                    mask = strat_col[fr.test_indices] == strat
                    if mask.sum() > 0:
                        acc = float(np.mean(fr.test_predictions[mask] == fr.test_true[mask]))
                        strat_counts.setdefault(strat, []).append(acc)
                for strat, accs in strat_counts.items():
                    if strat in accuracy_by_strategy:
                        accuracy_by_strategy[strat] = (
                            accuracy_by_strategy[strat] + float(np.mean(accs))
                        ) / 2
                    else:
                        accuracy_by_strategy[strat] = float(np.mean(accs))

        result = TrainingResult(
            classifier=primary_clf,
            classifiers=final_classifiers,
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
            "Training complete: accuracy=%.3f±%.3f, overfit_gap=%.3f, brier=%.3f, "
            "ensemble=%d models, final_n=%d",
            overall_acc,
            result.accuracy_std,
            overfit_gap,
            result.mean_brier_score,
            len(final_classifiers),
            final_n,
        )
        return result

    def predict(
        self,
        X: pd.DataFrame,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Generate predictions from the trained model ensemble.

        Averages ``predict_proba`` across all seed models for more stable
        probability estimates, then derives class predictions from the
        averaged probabilities.

        Args:
            X: Feature DataFrame (same columns as training).

        Returns:
            Tuple of (direction predictions, probabilities, return predictions).

        Raises:
            RuntimeError: If model has not been trained.
        """
        if self._result is None or self._result.classifier is None:
            raise RuntimeError("Model not trained. Call train() first.")

        classifiers = self._result.classifiers or [self._result.classifier]
        probs_list = [clf.predict_proba(X) for clf in classifiers]
        dir_probs = np.mean(probs_list, axis=0)
        dir_preds = np.argmax(dir_probs, axis=1)

        ret_preds = (
            self._result.regressor.predict(X) if self._result.regressor else np.zeros(len(X))
        )

        return dir_preds, dir_probs, ret_preds

    @property
    def result(self) -> TrainingResult | None:
        return self._result
