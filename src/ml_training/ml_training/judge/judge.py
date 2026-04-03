"""Judge system orchestrator: runs all validation layers and produces a JudgeReport.

Coordinates the calibrator, conformal predictor, drift detector,
WFO validator, strategy auditor, and reliability meta-learner into
a single evaluation pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score

from ml_training.judge.drift_detector import DriftDetector
from ml_training.judge.report import JudgeReport, determine_verdict
from ml_training.judge.wfo_validator import WFOValidator
from ml_training.models.calibration import ConformalPredictor, ProbabilityCalibrator

logger = logging.getLogger(__name__)

MIN_STRATEGY_SAMPLES = 50


class JudgeSystem:
    """Multi-layered model validation system.

    Runs six independent validation layers:
    A. Calibrator (Platt/Venn-Abers)
    B. Conformal predictor (MAPIE)
    C. Drift monitor (PSI + KS + SHAP + ADWIN)
    D. WFO validator (CPCV + embargo + DSR)
    E. Strategy-level audit
    F. Reliability meta-learner (Logistic Regression)
    """

    def __init__(
        self,
        quality_bar: dict[str, float] | None = None,
        n_trials: int = 1,
    ) -> None:
        self._quality_bar = quality_bar
        self._calibrator = ProbabilityCalibrator()
        self._conformal = ConformalPredictor(target_coverage=0.90)
        self._drift_detector = DriftDetector()
        self._wfo_validator = WFOValidator(n_trials=n_trials)
        self._reliability_model: LogisticRegression | None = None

    def evaluate(
        self,
        model_version: str,
        predictions: np.ndarray,
        probabilities: np.ndarray,
        true_labels: np.ndarray,
        feature_data: pd.DataFrame,
        training_data: pd.DataFrame | None = None,
        fold_results: list[dict[str, Any]] | None = None,
        train_accuracies: list[float] | None = None,
        test_accuracies: list[float] | None = None,
        strategy_labels: np.ndarray | None = None,
        shap_importances_train: dict[str, float] | None = None,
        shap_importances_test: dict[str, float] | None = None,
        dataset_size: int | None = None,
    ) -> JudgeReport:
        """Run the complete judge evaluation pipeline.

        Args:
            model_version: Version string of the model being evaluated.
            predictions: Model's predicted class labels.
            probabilities: Raw probability matrix from the model.
            true_labels: Ground truth labels.
            feature_data: Feature DataFrame for the test set.
            training_data: Feature DataFrame from training (for drift detection).
            fold_results: CPCV fold details for WFO validation.
            train_accuracies: In-sample accuracy per fold.
            test_accuracies: Out-of-sample accuracy per fold.
            strategy_labels: Strategy type per sample.
            shap_importances_train: SHAP importances at training time.
            shap_importances_test: SHAP importances on test data.

        Returns:
            Complete JudgeReport with verdict and recommendations.
        """
        report = JudgeReport(model_version=model_version)

        # Layer A: Calibration
        logger.info("Layer A: Running probability calibration...")
        cal_result = self._calibrator.fit(probabilities, true_labels)
        report.ece = cal_result.ece
        report.brier_score = cal_result.brier_score
        calibrated_probs = cal_result.calibrated_probs

        # Layer B: Conformal prediction
        logger.info("Layer B: Running conformal prediction...")
        self._conformal.fit(calibrated_probs, true_labels)
        conformal_result = self._conformal.predict_sets(calibrated_probs)
        report.conformal_coverage_achieved = self._conformal.evaluate_coverage(
            conformal_result.prediction_sets, true_labels
        )

        # Layer C: Drift detection
        logger.info("Layer C: Running drift detection...")
        if training_data is not None:
            error_stream = (predictions != true_labels).astype(float)
            drift_report = self._drift_detector.detect(
                reference_data=training_data,
                current_data=feature_data,
                reference_shap_importances=shap_importances_train,
                current_shap_importances=shap_importances_test,
                error_stream=error_stream,
            )
            report.drift_status = drift_report.status
            report.psi_overall = drift_report.psi_overall
            report.ks_flagged_features = drift_report.ks_flagged_features
            report.shap_ndcg = drift_report.shap_ndcg

        # Layer D: WFO validation
        logger.info("Layer D: Running WFO validation...")
        if fold_results:
            wfo_result = self._wfo_validator.validate(
                fold_results=fold_results,
                train_accuracies=train_accuracies,
                test_accuracies=test_accuracies,
            )
            report.wfo_integrity = wfo_result.wfo_integrity
            report.purge_verified = wfo_result.purge_verified
            report.embargo_verified = wfo_result.embargo_verified
            report.overfit_risk = wfo_result.overfit_risk
            report.insample_vs_oos_gap = wfo_result.insample_vs_oos_gap
            report.deflated_sharpe_probability = wfo_result.deflated_sharpe_probability

        # Layer E: Strategy-level audit
        logger.info("Layer E: Running strategy audit...")
        report.overall_accuracy = float(accuracy_score(true_labels, predictions))
        report.accuracy_by_strategy = self._compute_strategy_accuracies(
            predictions, true_labels, strategy_labels
        )

        # Layer F: Reliability meta-learner
        logger.info("Layer F: Training reliability meta-learner...")
        report.reliability_model_accuracy = self._train_reliability_model(
            predictions,
            probabilities,
            conformal_result.reliability_scores,
            true_labels,
            strategy_labels,
            feature_data,
        )

        # Final verdict
        logger.info("Determining verdict...")
        determine_verdict(report, self._quality_bar, dataset_size=dataset_size)

        logger.info(
            "Judge verdict: %s (accuracy=%.1f%%, ECE=%.4f)",
            report.judge_verdict,
            report.overall_accuracy * 100,
            report.ece,
        )
        return report

    def _compute_strategy_accuracies(
        self,
        predictions: np.ndarray,
        true_labels: np.ndarray,
        strategy_labels: np.ndarray | None,
    ) -> dict[str, float]:
        """Compute per-strategy accuracy with minimum sample thresholds."""
        if strategy_labels is None:
            return {}

        accuracies: dict[str, float] = {}
        for strat in np.unique(strategy_labels):
            mask = strategy_labels == strat
            count = mask.sum()
            if count < MIN_STRATEGY_SAMPLES:
                logger.warning(
                    "Strategy %s has only %d test samples (minimum %d)",
                    strat,
                    count,
                    MIN_STRATEGY_SAMPLES,
                )
                continue
            accuracies[str(strat)] = float(accuracy_score(true_labels[mask], predictions[mask]))

        return accuracies

    def _train_reliability_model(
        self,
        predictions: np.ndarray,
        probabilities: np.ndarray,
        reliability_scores: np.ndarray,
        true_labels: np.ndarray,
        strategy_labels: np.ndarray | None,
        feature_data: pd.DataFrame,
    ) -> float:
        """Train a Logistic Regression meta-learner for per-prediction reliability.

        Predicts whether the primary model's prediction is correct,
        using the model's own outputs + context as features.

        Returns:
            Meta-learner accuracy on the same data (train accuracy, not generalized).
        """
        meta_features: list[np.ndarray] = [
            predictions.reshape(-1, 1).astype(float),
            probabilities,
            reliability_scores.reshape(-1, 1),
        ]

        for col in ["adx", "volume_ratio"]:
            if col in feature_data.columns:
                vals = feature_data[col].fillna(0).values.reshape(-1, 1)
                meta_features.append(vals)

        if strategy_labels is not None:
            from sklearn.preprocessing import LabelEncoder

            le = LabelEncoder()
            encoded = le.fit_transform(strategy_labels).reshape(-1, 1).astype(float)
            meta_features.append(encoded)

        X_meta = np.hstack(meta_features)
        y_meta = (predictions == true_labels).astype(int)

        n_classes = len(np.unique(y_meta))
        if n_classes < 2:
            accuracy = float(y_meta.mean()) if y_meta.sum() > 0 else 0.0
            logger.warning(
                "Reliability meta-learner skipped: only %d class in labels (accuracy=%.3f)",
                n_classes,
                accuracy,
            )
            return accuracy

        self._reliability_model = LogisticRegression(
            C=1.0,
            max_iter=1000,
            solver="lbfgs",
        )
        self._reliability_model.fit(X_meta, y_meta)

        meta_preds = self._reliability_model.predict(X_meta)
        accuracy = float(accuracy_score(y_meta, meta_preds))

        logger.info("Reliability meta-learner accuracy: %.3f", accuracy)
        return accuracy

    def predict_reliability(
        self,
        predictions: np.ndarray,
        probabilities: np.ndarray,
        reliability_scores: np.ndarray,
        feature_data: pd.DataFrame,
        strategy_labels: np.ndarray | None = None,
    ) -> np.ndarray:
        """Predict reliability scores for new predictions.

        Args:
            predictions: Model predictions.
            probabilities: Probability matrix.
            reliability_scores: Conformal reliability scores.
            feature_data: Feature DataFrame.
            strategy_labels: Strategy type labels.

        Returns:
            Reliability probability for each prediction.

        Raises:
            RuntimeError: If reliability model has not been trained.
        """
        if self._reliability_model is None:
            raise RuntimeError("Reliability model not trained. Call evaluate() first.")

        meta_features: list[np.ndarray] = [
            predictions.reshape(-1, 1).astype(float),
            probabilities,
            reliability_scores.reshape(-1, 1),
        ]

        for col in ["adx", "volume_ratio"]:
            if col in feature_data.columns:
                vals = feature_data[col].fillna(0).values.reshape(-1, 1)
                meta_features.append(vals)

        if strategy_labels is not None:
            from sklearn.preprocessing import LabelEncoder

            le = LabelEncoder()
            encoded = le.fit_transform(strategy_labels).reshape(-1, 1).astype(float)
            meta_features.append(encoded)

        X_meta = np.hstack(meta_features)
        return self._reliability_model.predict_proba(X_meta)[:, 1]
