"""Probability calibration and conformal prediction.

Provides Platt scaling for probability calibration and MAPIE
conformal prediction for reliability sets. Upgrade path to
Venn-Abers calibration via crepes library.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss

logger = logging.getLogger(__name__)


@dataclass
class CalibrationResult:
    """Results from probability calibration."""

    calibrated_probs: np.ndarray
    ece: float = 0.0
    brier_score: float = 0.0
    log_loss_val: float = 0.0
    method: str = "platt"


@dataclass
class ConformalResult:
    """Results from conformal prediction."""

    prediction_sets: list[list[str]]
    reliability_scores: np.ndarray
    coverage: float = 0.0


class ProbabilityCalibrator:
    """Calibrates raw model probabilities using Platt scaling.

    Raw LightGBM probabilities are often miscalibrated. This applies
    a learned logistic mapping to improve calibration.
    """

    def __init__(self, method: str = "sigmoid") -> None:
        self._method = method
        self._calibrator: LogisticRegression | None = None
        self._n_classes: int = 3

    def fit(
        self,
        raw_probs: np.ndarray,
        true_labels: np.ndarray,
    ) -> CalibrationResult:
        """Fit the calibrator on validation predictions.

        Args:
            raw_probs: Raw probability matrix from the classifier (n_samples, n_classes).
            true_labels: True class labels (integer-encoded).

        Returns:
            CalibrationResult with calibrated probabilities and quality metrics.
        """
        self._n_classes = raw_probs.shape[1]

        self._calibrator = LogisticRegression(
            C=1.0,
            max_iter=1000,
            solver="lbfgs",
        )
        self._calibrator.fit(raw_probs, true_labels)

        calibrated = self._calibrator.predict_proba(raw_probs)
        calibrated = calibrated / calibrated.sum(axis=1, keepdims=True)

        ece = self._compute_ece(calibrated, true_labels)
        brier = self._compute_multiclass_brier(calibrated, true_labels)
        ll = float(log_loss(true_labels, calibrated))

        result = CalibrationResult(
            calibrated_probs=calibrated,
            ece=ece,
            brier_score=brier,
            log_loss_val=ll,
            method=self._method,
        )

        logger.info(
            "Calibration complete: ECE=%.4f, Brier=%.4f, LogLoss=%.4f",
            ece,
            brier,
            ll,
        )
        return result

    def calibrate(self, raw_probs: np.ndarray) -> np.ndarray:
        """Apply calibration to new probability predictions.

        Args:
            raw_probs: Raw probability matrix (n_samples, n_classes).

        Returns:
            Calibrated probability matrix.

        Raises:
            RuntimeError: If calibrator has not been fit.
        """
        if self._calibrator is None:
            raise RuntimeError("Calibrator not fit. Call fit() first.")

        calibrated = self._calibrator.predict_proba(raw_probs)
        return calibrated / calibrated.sum(axis=1, keepdims=True)

    def _compute_ece(
        self,
        probs: np.ndarray,
        true_labels: np.ndarray,
        n_bins: int = 10,
    ) -> float:
        """Compute Expected Calibration Error.

        ECE measures the gap between predicted confidence and actual accuracy
        across confidence bins.

        Args:
            probs: Predicted probability matrix.
            true_labels: True labels.
            n_bins: Number of confidence bins.

        Returns:
            ECE value (lower is better, target < 0.05).
        """
        confidences = np.max(probs, axis=1)
        predictions = np.argmax(probs, axis=1)
        correctness = predictions == true_labels

        bin_boundaries = np.linspace(0, 1, n_bins + 1)
        ece = 0.0
        total = len(confidences)

        for i in range(n_bins):
            mask = (confidences > bin_boundaries[i]) & (confidences <= bin_boundaries[i + 1])
            count = mask.sum()
            if count == 0:
                continue
            avg_confidence = confidences[mask].mean()
            avg_accuracy = correctness[mask].mean()
            ece += (count / total) * abs(avg_accuracy - avg_confidence)

        return float(ece)

    def _compute_multiclass_brier(
        self,
        probs: np.ndarray,
        true_labels: np.ndarray,
    ) -> float:
        """Compute multi-class Brier score."""
        one_hot = np.zeros_like(probs)
        one_hot[np.arange(len(true_labels)), true_labels] = 1
        return float(np.mean(np.sum((probs - one_hot) ** 2, axis=1)))


class ConformalPredictor:
    """Conformal prediction sets with coverage guarantees.

    Produces prediction sets where the true label is guaranteed to be
    included with a specified probability (e.g., 90%). Set size indicates
    model uncertainty.
    """

    def __init__(
        self,
        target_coverage: float = 0.90,
        class_names: list[str] | None = None,
    ) -> None:
        self._target_coverage = target_coverage
        self._class_names = class_names or ["DOWN", "FLAT", "UP"]
        self._threshold: float | None = None

    def fit(
        self,
        probs: np.ndarray,
        true_labels: np.ndarray,
    ) -> float:
        """Calibrate the conformal threshold on validation data.

        Uses the split conformal method: find the threshold on nonconformity
        scores that achieves the target coverage.

        Args:
            probs: Calibrated probability matrix (n_samples, n_classes).
            true_labels: True labels (integer-encoded).

        Returns:
            The calibrated threshold value.
        """
        nonconformity_scores = 1 - probs[np.arange(len(true_labels)), true_labels]

        n = len(nonconformity_scores)
        quantile_level = np.ceil((n + 1) * self._target_coverage) / n
        quantile_level = min(quantile_level, 1.0)
        self._threshold = float(np.quantile(nonconformity_scores, quantile_level))

        logger.info(
            "Conformal threshold=%.4f for %.0f%% coverage",
            self._threshold,
            self._target_coverage * 100,
        )
        return self._threshold

    def predict_sets(self, probs: np.ndarray) -> ConformalResult:
        """Generate prediction sets with coverage guarantees.

        Args:
            probs: Calibrated probability matrix (n_samples, n_classes).

        Returns:
            ConformalResult with prediction sets and reliability scores.

        Raises:
            RuntimeError: If conformal threshold has not been calibrated.
        """
        if self._threshold is None:
            raise RuntimeError("Conformal predictor not calibrated. Call fit() first.")

        prediction_sets: list[list[str]] = []
        for row in probs:
            pset = [
                self._class_names[j] for j in range(len(row)) if (1 - row[j]) <= self._threshold
            ]
            if not pset:
                pset = [self._class_names[int(np.argmax(row))]]
            prediction_sets.append(pset)

        reliability_scores = np.array([1.0 / len(ps) for ps in prediction_sets])

        return ConformalResult(
            prediction_sets=prediction_sets,
            reliability_scores=reliability_scores,
        )

    def evaluate_coverage(
        self,
        prediction_sets: list[list[str]],
        true_labels: np.ndarray,
    ) -> float:
        """Evaluate empirical coverage of prediction sets.

        Args:
            prediction_sets: List of prediction sets.
            true_labels: True labels (integer-encoded).

        Returns:
            Fraction of true labels contained in their prediction sets.
        """
        covered = 0
        for ps, true_label in zip(prediction_sets, true_labels):
            true_name = self._class_names[true_label]
            if true_name in ps:
                covered += 1
        coverage = covered / len(true_labels) if true_labels.size > 0 else 0.0
        return float(coverage)
