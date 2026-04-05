"""Meta-labeling: binary filter for primary strategy signals.

A meta-labeler is a binary classifier that predicts whether a signal from a
primary strategy will be profitable. It operates on the subset of rows where
the primary strategy fired a signal (signal != 0), rather than the full dataset.

This allows the model to focus on discriminating good signals from bad signals,
rather than generating signals itself.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ml_training.models.predictor import (
    CPCVConfig,
    PredictionModel,
    TrainingResult,
)

logger = logging.getLogger(__name__)

MIN_SIGNAL_SAMPLES = 30


def _small_dataset_params(n_samples: int) -> dict:
    """LightGBM parameters tuned for very small meta-label datasets."""
    return {
        "objective": "binary",
        "metric": "binary_logloss",
        "boosting_type": "gbdt",
        "is_unbalance": True,
        "verbose": -1,
        "n_jobs": -1,
        "seed": 42,
        "num_leaves": 4,
        "max_depth": 2,
        "learning_rate": 0.05,
        "min_child_samples": max(3, n_samples // 10),
        "feature_fraction": 0.4,
        "bagging_fraction": 0.8,
        "bagging_freq": 3,
        "reg_alpha": 5.0,
        "reg_lambda": 10.0,
        "min_gain_to_split": 1.0,
    }


class MetaLabeler:
    """Binary classifier for filtering primary strategy signals.

    Trains a model to predict whether signals from a primary strategy will be
    profitable. Operates only on rows where the primary strategy fired a signal,
    not the full dataset.

    Example:
        >>> labeler = MetaLabeler(target_col="profitable", return_col="return_10d")
        >>> result = labeler.train(df, signal_col="strategy_signal")
        >>> conviction = labeler.predict_conviction(new_data)
    """

    def __init__(
        self,
        target_col: str = "profitable",
        return_col: str = "return_10d",
        cpcv_config: object | None = None,
        classifier_params: dict | None = None,
    ) -> None:
        """Initialize meta-labeler.

        Args:
            target_col: Binary target column (1 = profitable, 0 = not profitable).
            return_col: Forward return column for regressor training.
            cpcv_config: Optional CPCVConfig for cross-validation settings.
            classifier_params: Optional LightGBM binary classifier parameters.
        """
        self._target_col = target_col
        self._return_col = return_col
        self._cpcv_config = cpcv_config
        self._classifier_params = classifier_params
        self._model: PredictionModel | None = None

    def train(
        self,
        df: pd.DataFrame,
        signal_col: str = "primary_signal",
        n_rounds: int = 500,
    ) -> TrainingResult:
        """Train meta-labeler on signals from a primary strategy.

        Filters to rows where signal_col != 0 (strategy fired a signal), then
        trains a binary classifier to predict whether those signals will be
        profitable.

        Args:
            df: Full dataset with features, signals, and labels.
            signal_col: Column containing primary strategy signals (0 = no signal).
            n_rounds: Number of boosting rounds.

        Returns:
            TrainingResult with model, metrics, and fold details. Returns empty
            TrainingResult if insufficient signal samples.
        """
        signal_mask = df[signal_col] != 0
        signal_df = df[signal_mask].copy()

        logger.info(
            "Meta-labeling: %d/%d rows with signals (%.1f%%)",
            len(signal_df),
            len(df),
            100.0 * len(signal_df) / len(df) if len(df) > 0 else 0.0,
        )

        if len(signal_df) < MIN_SIGNAL_SAMPLES:
            logger.warning(
                "Insufficient signal samples for meta-labeling: %d < %d. "
                "Returning empty TrainingResult.",
                len(signal_df),
                MIN_SIGNAL_SAMPLES,
            )
            return TrainingResult()

        n = len(signal_df)
        if n < 200:
            cpcv = CPCVConfig(
                n_splits=2,
                purge_window=max(2, n // 20),
                embargo_window=max(1, n // 30),
                min_train_size=max(15, n // 4),
                forward_horizon=5,
            )
            params = _small_dataset_params(n)
            logger.info(
                "Small meta-label dataset (%d samples): using 2-fold CV, "
                "min_child_samples=%d, max_depth=2",
                n,
                params["min_child_samples"],
            )
        else:
            cpcv = self._cpcv_config
            params = self._classifier_params

        self._model = PredictionModel(
            target_col=self._target_col,
            return_col=self._return_col,
            cpcv_config=cpcv,
            classifier_params=params,
            binary_mode=True,
        )

        logger.info("Training meta-labeler on %d signal samples...", len(signal_df))
        result = self._model.train(signal_df, n_rounds=n_rounds)

        if result.overall_accuracy > 0:
            logger.info(
                "Meta-labeler training complete: accuracy=%.3f±%.3f, overfit_gap=%.3f",
                result.overall_accuracy,
                result.accuracy_std,
                result.overfit_gap,
            )

        return result

    def predict(
        self,
        X: pd.DataFrame,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Generate predictions from trained meta-labeler.

        Args:
            X: Feature DataFrame (same columns as training).

        Returns:
            Tuple of (binary predictions, probabilities, return predictions).

        Raises:
            RuntimeError: If model has not been trained.
        """
        if self._model is None:
            raise RuntimeError("Meta-labeler has not been trained yet")
        return self._model.predict(X)

    def predict_conviction(self, X: pd.DataFrame) -> np.ndarray:
        """Predict conviction score for position sizing.

        Returns the probability that a signal will be profitable (class 1).
        Higher conviction suggests larger position size.

        Args:
            X: Feature DataFrame (same columns as training).

        Returns:
            Array of conviction scores [0.0, 1.0], one per sample.

        Raises:
            RuntimeError: If model has not been trained.
        """
        _, probs, _ = self.predict(X)
        return probs[:, 1]

    @property
    def result(self) -> TrainingResult | None:
        """Access the underlying training result."""
        return self._model.result if self._model else None
