"""Probability calibration and conformal prediction.

Provides Platt scaling, isotonic regression, and Venn-ABERS calibration.
Conformal prediction supports both split conformal and Mondrian
conformal (per-strategy conditional coverage).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from sklearn.isotonic import IsotonicRegression
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
    calibration_interval_width: float | None = None


@dataclass
class ConformalResult:
    """Results from conformal prediction."""

    prediction_sets: list[list[str]]
    reliability_scores: np.ndarray
    coverage: float = 0.0


class ProbabilityCalibrator:
    """Calibrates raw model probabilities.

    Supports three methods:
    - ``sigmoid`` (Platt scaling): logistic regression on raw probs
    - ``isotonic``: non-parametric monotone calibration
    - ``venn_abers``: produces calibrated probability intervals with
      finite-sample guarantees via the ``crepes`` library
    """

    def __init__(self, method: str = "sigmoid") -> None:
        self._method = method
        self._calibrator: LogisticRegression | None = None
        self._isotonic_calibrators: list[IsotonicRegression] | None = None
        self._venn_abers_calibrator: object | None = None
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
        interval_width = None

        if self._method == "venn_abers":
            calibrated, interval_width = self._fit_venn_abers(raw_probs, true_labels)
        elif self._method == "isotonic":
            calibrated = self._fit_isotonic(raw_probs, true_labels)
        else:
            calibrated = self._fit_sigmoid(raw_probs, true_labels)

        calibrated = calibrated / calibrated.sum(axis=1, keepdims=True)

        ece = self._compute_ece(calibrated, true_labels)
        brier = self._compute_multiclass_brier(calibrated, true_labels)

        unique_classes = np.unique(true_labels)
        ll = 0.0 if len(unique_classes) < 2 else float(log_loss(true_labels, calibrated))

        result = CalibrationResult(
            calibrated_probs=calibrated,
            ece=ece,
            brier_score=brier,
            log_loss_val=ll,
            method=self._method,
            calibration_interval_width=interval_width,
        )

        logger.info(
            "Calibration complete (%s): ECE=%.4f, Brier=%.4f, LogLoss=%.4f%s",
            self._method,
            ece,
            brier,
            ll,
            f", interval_width={interval_width:.4f}" if interval_width is not None else "",
        )
        return result

    def _fit_sigmoid(self, raw_probs: np.ndarray, true_labels: np.ndarray) -> np.ndarray:
        """Platt scaling via logistic regression."""
        self._calibrator = LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs")
        self._calibrator.fit(raw_probs, true_labels)
        return self._calibrator.predict_proba(raw_probs)

    def _fit_isotonic(self, raw_probs: np.ndarray, true_labels: np.ndarray) -> np.ndarray:
        """Per-class isotonic regression calibration."""
        self._isotonic_calibrators = []
        calibrated = np.zeros_like(raw_probs)

        for cls in range(self._n_classes):
            binary_true = (true_labels == cls).astype(float)
            iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
            iso.fit(raw_probs[:, cls], binary_true)
            self._isotonic_calibrators.append(iso)
            calibrated[:, cls] = iso.predict(raw_probs[:, cls])

        return calibrated

    def _fit_venn_abers(
        self, raw_probs: np.ndarray, true_labels: np.ndarray
    ) -> tuple[np.ndarray, float]:
        """Venn-ABERS calibration via crepes library.

        Falls back to isotonic if crepes is not available.
        """
        unique_classes = np.unique(true_labels)
        if len(unique_classes) < 2:
            logger.warning(
                "Only one class in calibration data (class=%s), "
                "falling back to isotonic calibration",
                unique_classes[0],
            )
            calibrated = self._fit_isotonic(raw_probs, true_labels)
            return calibrated, None

        try:
            from crepes import WrapClassifier

            self._venn_abers_calibrator = WrapClassifier(LogisticRegression(max_iter=1000))
            self._venn_abers_calibrator.fit(raw_probs, true_labels)
            cal_result = self._venn_abers_calibrator.predict_proba(raw_probs)

            if isinstance(cal_result, tuple) and len(cal_result) == 2:
                p_low, p_high = cal_result
                calibrated = (p_low + p_high) / 2
                interval_width = float(np.mean(p_high - p_low))
            else:
                calibrated = np.asarray(cal_result)
                interval_width = 0.0

            if calibrated.ndim == 1:
                calibrated = np.column_stack([1 - calibrated, calibrated])

            return calibrated, interval_width

        except ImportError:
            logger.warning("crepes not available, falling back to isotonic calibration")
            calibrated = self._fit_isotonic(raw_probs, true_labels)
            return calibrated, None

    def calibrate(self, raw_probs: np.ndarray) -> np.ndarray:
        """Apply calibration to new probability predictions.

        Args:
            raw_probs: Raw probability matrix (n_samples, n_classes).

        Returns:
            Calibrated probability matrix.

        Raises:
            RuntimeError: If calibrator has not been fit.
        """
        if self._method == "isotonic" and self._isotonic_calibrators is not None:
            calibrated = np.zeros_like(raw_probs)
            for cls, iso in enumerate(self._isotonic_calibrators):
                calibrated[:, cls] = iso.predict(raw_probs[:, cls])
            calibrated = calibrated / calibrated.sum(axis=1, keepdims=True)
            return calibrated

        if self._method == "venn_abers" and self._venn_abers_calibrator is not None:
            cal_result = self._venn_abers_calibrator.predict_proba(raw_probs)
            if isinstance(cal_result, tuple) and len(cal_result) == 2:
                calibrated = (cal_result[0] + cal_result[1]) / 2
            else:
                calibrated = np.asarray(cal_result)
            if calibrated.ndim == 1:
                calibrated = np.column_stack([1 - calibrated, calibrated])
            return calibrated / calibrated.sum(axis=1, keepdims=True)

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
        """Compute Expected Calibration Error."""
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

    Supports both split conformal (global threshold) and Mondrian
    conformal (per-strategy thresholds for conditional coverage).
    """

    def __init__(
        self,
        target_coverage: float = 0.90,
        class_names: list[str] | None = None,
    ) -> None:
        self._target_coverage = target_coverage
        self._class_names = class_names or ["DOWN", "FLAT", "UP"]
        self._threshold: float | None = None
        self._mondrian_thresholds: dict[str, float] | None = None

    def fit(
        self,
        probs: np.ndarray,
        true_labels: np.ndarray,
        strategy_labels: np.ndarray | None = None,
    ) -> float:
        """Calibrate the conformal threshold on validation data.

        When ``strategy_labels`` are provided, uses Mondrian conformal
        prediction to fit separate thresholds per strategy for
        conditional coverage guarantees.

        Args:
            probs: Calibrated probability matrix (n_samples, n_classes).
            true_labels: True labels (integer-encoded).
            strategy_labels: Per-sample strategy type labels for Mondrian conformal.

        Returns:
            The global calibrated threshold value.
        """
        nonconformity_scores = 1 - probs[np.arange(len(true_labels)), true_labels]

        n = len(nonconformity_scores)
        quantile_level = np.ceil((n + 1) * self._target_coverage) / n
        quantile_level = min(quantile_level, 1.0)
        self._threshold = float(np.quantile(nonconformity_scores, quantile_level))

        if strategy_labels is not None:
            self._mondrian_thresholds = {}
            unique_strategies = np.unique(strategy_labels)
            for strat in unique_strategies:
                strat_mask = strategy_labels == strat
                strat_scores = nonconformity_scores[strat_mask]
                if len(strat_scores) < 10:
                    self._mondrian_thresholds[str(strat)] = self._threshold
                    continue
                n_s = len(strat_scores)
                q_s = np.ceil((n_s + 1) * self._target_coverage) / n_s
                q_s = min(q_s, 1.0)
                self._mondrian_thresholds[str(strat)] = float(np.quantile(strat_scores, q_s))
            logger.info(
                "Mondrian conformal: %d strategy-specific thresholds",
                len(self._mondrian_thresholds),
            )

        logger.info(
            "Conformal threshold=%.4f for %.0f%% coverage",
            self._threshold,
            self._target_coverage * 100,
        )
        return self._threshold

    def predict_sets(
        self,
        probs: np.ndarray,
        strategy_labels: np.ndarray | None = None,
    ) -> ConformalResult:
        """Generate prediction sets with coverage guarantees.

        Args:
            probs: Calibrated probability matrix (n_samples, n_classes).
            strategy_labels: Per-sample strategy labels for Mondrian conformal.

        Returns:
            ConformalResult with prediction sets and reliability scores.

        Raises:
            RuntimeError: If conformal threshold has not been calibrated.
        """
        if self._threshold is None:
            raise RuntimeError("Conformal predictor not calibrated. Call fit() first.")

        prediction_sets: list[list[str]] = []
        for i, row in enumerate(probs):
            threshold = self._threshold
            if strategy_labels is not None and self._mondrian_thresholds is not None:
                strat = str(strategy_labels[i])
                threshold = self._mondrian_thresholds.get(strat, self._threshold)

            pset = [self._class_names[j] for j in range(len(row)) if (1 - row[j]) <= threshold]
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
