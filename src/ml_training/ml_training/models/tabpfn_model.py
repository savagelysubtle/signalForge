"""TabPFN v2 model wrapper with CPCV walk-forward optimization.

Uses TabPFN for classification and Ridge for regression, with the same
CPCV interface as PredictionModel for direct comparison.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import LabelEncoder

try:
    from tabpfn import TabPFNClassifier

    TABPFN_AVAILABLE = True
except ImportError:
    TABPFN_AVAILABLE = False

from ml_training.models.predictor import (
    CPCVConfig,
    FoldResult,
    _identify_feature_columns,
    _prepare_features,
    _purged_split,
)

logger = logging.getLogger(__name__)

DIRECTION_CLASSES = ["DOWN", "FLAT", "UP"]


class _TabPFNAdapter:
    """Adapter to make TabPFN compatible with LightGBM-style interface."""

    def __init__(self, model: Any) -> None:
        self._model = model
        self._feature_importances: np.ndarray | None = None

    def fit(
        self,
        X: pd.DataFrame | np.ndarray,
        y: np.ndarray,
        sample_weight: np.ndarray | None = None,
        categorical_feature: list[int] | None = None,
        eval_set: list[tuple[pd.DataFrame | np.ndarray, np.ndarray]] | None = None,
        callbacks: list[Any] | None = None,
    ) -> _TabPFNAdapter:
        X_arr = X.values if isinstance(X, pd.DataFrame) else X
        self._model.fit(X_arr, y)
        n_features = X_arr.shape[1]
        self._feature_importances = np.ones(n_features) / n_features
        return self

    def predict(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        X_arr = X.values if isinstance(X, pd.DataFrame) else X
        return self._model.predict(X_arr)

    def predict_proba(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        X_arr = X.values if isinstance(X, pd.DataFrame) else X
        return self._model.predict_proba(X_arr)

    @property
    def feature_importances_(self) -> np.ndarray:
        if self._feature_importances is None:
            raise RuntimeError("Model not fitted")
        return self._feature_importances

    @property
    def best_iteration_(self) -> int:
        return 1


@dataclass
class TabPFNTrainingResult:
    """Training results for TabPFN model."""

    classifier: _TabPFNAdapter | None = None
    classifiers: list[_TabPFNAdapter] = field(default_factory=list)
    regressor: Ridge | None = None
    label_encoder: LabelEncoder | None = None
    feature_names: list[str] = field(default_factory=list)
    fold_results: list[FoldResult] = field(default_factory=list)
    overall_accuracy: float = 0.0
    accuracy_std: float = 0.0
    mean_brier_score: float = 0.0
    accuracy_by_strategy: dict[str, float] = field(default_factory=dict)
    overfit_gap: float = 0.0


class TabPFNModel:
    """TabPFN prediction model with CPCV training and evaluation.

    Uses TabPFN for direction classification and Ridge for return regression,
    matching the PredictionModel interface for direct comparison.
    """

    def __init__(
        self,
        target_col: str = "direction_10d",
        return_col: str = "return_10d",
        cpcv_config: CPCVConfig | None = None,
        binary_mode: bool = False,
    ) -> None:
        if not TABPFN_AVAILABLE:
            raise ImportError("tabpfn package not installed. Install with: pip install tabpfn")
        self._target_col = target_col
        self._return_col = return_col
        self._cpcv = cpcv_config or CPCVConfig()
        self._binary_mode = binary_mode
        self._result: TabPFNTrainingResult | None = None

    def train(self, df: pd.DataFrame, n_rounds: int = 500) -> TabPFNTrainingResult:
        """Train the model using CPCV walk-forward optimization.

        Args:
            df: Full training dataset with features and labels.
            n_rounds: Ignored for TabPFN (no boosting rounds).

        Returns:
            TabPFNTrainingResult with models, metrics, and fold details.
        """
        df = df.dropna(subset=[self._target_col]).sort_values("date").reset_index(drop=True)

        feature_cols = _identify_feature_columns(df)
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

            tabpfn_model = TabPFNClassifier(device="cpu", N_ensemble_configurations=8)
            clf = _TabPFNAdapter(tabpfn_model)
            clf.fit(X_train, y_train)

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
                best_iteration=1,
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
            return TabPFNTrainingResult()

        logger.info("Training final TabPFN model on 90%% of data...")
        split_n = int(len(X) * 0.9)
        X_fit = X.iloc[:split_n]
        y_fit = y_cls[:split_n]

        final_tabpfn = TabPFNClassifier(device="cpu", N_ensemble_configurations=8)
        final_clf = _TabPFNAdapter(final_tabpfn)
        final_clf.fit(X_fit, y_fit)

        final_reg = Ridge(alpha=1.0, random_state=42)
        final_reg.fit(X_fit, y_reg[:split_n])

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

        result = TabPFNTrainingResult(
            classifier=final_clf,
            classifiers=[final_clf],
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
        """Generate predictions from the trained TabPFN model.

        Args:
            X: Feature DataFrame (same columns as training).

        Returns:
            Tuple of (direction predictions, probabilities, return predictions).

        Raises:
            RuntimeError: If model has not been trained.
        """
        if self._result is None or self._result.classifier is None:
            raise RuntimeError("Model not trained. Call train() first.")

        dir_probs = self._result.classifier.predict_proba(X)
        dir_preds = np.argmax(dir_probs, axis=1)

        ret_preds = (
            self._result.regressor.predict(X) if self._result.regressor else np.zeros(len(X))
        )

        return dir_preds, dir_probs, ret_preds

    @property
    def result(self) -> TabPFNTrainingResult | None:
        return self._result
