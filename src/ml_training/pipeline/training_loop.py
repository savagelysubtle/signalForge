"""Orchestrates train-judge cycles until the quality bar is met.

Runs the primary model training, judge evaluation, and iterative
improvement loop with configurable quality thresholds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
import shap

from ml_training.judge.judge import JudgeSystem
from ml_training.judge.report import JudgeReport
from ml_training.models.calibration import ConformalPredictor, ProbabilityCalibrator
from ml_training.models.predictor import PredictionModel, TrainingResult
from ml_training.models.registry import ModelArtifact, ModelMetadata, ModelRegistry

logger = logging.getLogger(__name__)


@dataclass
class TrainingRoundResult:
    """Results from a single training round."""

    round_num: int
    training_result: TrainingResult | None = None
    judge_report: JudgeReport | None = None
    artifact_path: str | None = None


@dataclass
class TrainingLoopConfig:
    """Configuration for the training loop."""

    max_rounds: int = 5
    target_col: str = "direction_10d"
    return_col: str = "return_10d"
    n_boost_rounds: int = 500
    auto_promote: bool = False
    quality_bar: dict[str, float] | None = None


class TrainingLoop:
    """Orchestrates the train-judge cycle.

    Runs multiple rounds of training and evaluation, applying
    the judge system after each round to determine if the model
    meets the quality bar for promotion.
    """

    def __init__(
        self,
        config: TrainingLoopConfig | None = None,
        registry: ModelRegistry | None = None,
    ) -> None:
        self._config = config or TrainingLoopConfig()
        self._registry = registry or ModelRegistry()
        self._rounds: list[TrainingRoundResult] = []

    def run(self, dataset: pd.DataFrame) -> list[TrainingRoundResult]:
        """Execute the training loop.

        Args:
            dataset: Complete feature dataset with labels.

        Returns:
            List of TrainingRoundResult for each round.
        """
        logger.info(
            "Starting training loop: max_rounds=%d, target=%s",
            self._config.max_rounds,
            self._config.target_col,
        )

        for round_num in range(1, self._config.max_rounds + 1):
            logger.info("=" * 60)
            logger.info("ROUND %d / %d", round_num, self._config.max_rounds)
            logger.info("=" * 60)

            result = self._run_round(dataset, round_num)
            self._rounds.append(result)

            if result.judge_report is None:
                logger.error("Round %d: judge evaluation failed", round_num)
                continue

            verdict = result.judge_report.judge_verdict
            logger.info("Round %d verdict: %s", round_num, verdict)

            if verdict == "PASS":
                logger.info("Model PASSED judge evaluation!")
                if self._config.auto_promote and result.artifact_path:
                    from pathlib import Path

                    self._registry.promote_to_shadow(Path(result.artifact_path))
                    logger.info("Model promoted to shadow mode")
                break

            if verdict == "CONDITIONAL_PASS":
                logger.info(
                    "Model CONDITIONALLY PASSED. Approved strategies: %s",
                    result.judge_report.strategy_approvals,
                )
                break

            logger.info(
                "Round %d FAILED. Recommendations:\n%s",
                round_num,
                "\n".join(f"  - {r}" for r in result.judge_report.recommendations),
            )

        return self._rounds

    def _run_round(self, dataset: pd.DataFrame, round_num: int) -> TrainingRoundResult:
        """Execute a single training round.

        Args:
            dataset: Feature dataset.
            round_num: Current round number.

        Returns:
            TrainingRoundResult with model and judge evaluation.
        """
        result = TrainingRoundResult(round_num=round_num)

        model = PredictionModel(
            target_col=self._config.target_col,
            return_col=self._config.return_col,
        )

        training_result = model.train(dataset, n_rounds=self._config.n_boost_rounds)
        result.training_result = training_result

        if training_result.classifier is None:
            logger.error("Training produced no classifier")
            return result

        feature_cols = training_result.feature_names
        df_sorted = (
            dataset.dropna(subset=[self._config.target_col])
            .sort_values("date")
            .reset_index(drop=True)
        )

        split_idx = int(len(df_sorted) * 0.8)
        train_df = df_sorted.iloc[:split_idx]
        test_df = df_sorted.iloc[split_idx:]

        from ml_training.models.predictor import _prepare_features

        X_test, _ = _prepare_features(test_df, feature_cols)
        X_train, _ = _prepare_features(train_df, feature_cols)

        from sklearn.preprocessing import LabelEncoder

        le = LabelEncoder()
        le.fit(["DOWN", "FLAT", "UP"])
        y_test = le.transform(test_df[self._config.target_col].values)

        predictions = training_result.classifier.predict(X_test)
        probabilities = training_result.classifier.predict_proba(X_test)

        shap_train: dict[str, float] | None = None
        shap_test: dict[str, float] | None = None
        try:
            explainer = shap.TreeExplainer(training_result.classifier)
            shap_values = explainer.shap_values(X_test)
            if isinstance(shap_values, list):
                mean_abs = np.mean([np.abs(sv).mean(axis=0) for sv in shap_values], axis=0)
            else:
                mean_abs = np.abs(shap_values).mean(axis=0)
            shap_test = dict(zip(feature_cols, mean_abs))

            shap_values_train = explainer.shap_values(
                X_train.sample(min(500, len(X_train)), random_state=42)
            )
            if isinstance(shap_values_train, list):
                mean_abs_train = np.mean(
                    [np.abs(sv).mean(axis=0) for sv in shap_values_train], axis=0
                )
            else:
                mean_abs_train = np.abs(shap_values_train).mean(axis=0)
            shap_train = dict(zip(feature_cols, mean_abs_train))
        except Exception:
            logger.warning("SHAP analysis failed, skipping importance drift check")

        strategy_labels = (
            test_df["strategy_type"].values if "strategy_type" in test_df.columns else None
        )

        fold_details = [
            {
                "train_indices": fr.test_indices[:1],
                "test_indices": fr.test_indices,
            }
            for fr in training_result.fold_results
        ]

        judge = JudgeSystem(
            quality_bar=self._config.quality_bar,
            n_trials=round_num,
        )
        judge_report = judge.evaluate(
            model_version=f"v{round_num}",
            predictions=predictions,
            probabilities=probabilities,
            true_labels=y_test,
            feature_data=X_test,
            training_data=X_train,
            fold_results=fold_details,
            train_accuracies=[fr.train_accuracy for fr in training_result.fold_results],
            test_accuracies=[fr.test_accuracy for fr in training_result.fold_results],
            strategy_labels=strategy_labels,
            shap_importances_train=shap_train,
            shap_importances_test=shap_test,
        )
        result.judge_report = judge_report

        calibrator = ProbabilityCalibrator()
        cal_result = calibrator.fit(probabilities, y_test)

        conformal = ConformalPredictor(target_coverage=0.90)
        conformal.fit(cal_result.calibrated_probs, y_test)

        artifact = ModelArtifact(
            classifier=training_result.classifier,
            regressor=training_result.regressor,
            label_encoder=training_result.label_encoder,
            calibrator=calibrator,
            conformal=conformal,
            metadata=ModelMetadata(
                model_version=f"v{round_num}",
                training_date="",
                feature_names=feature_cols,
                metrics={
                    "overall_accuracy": training_result.overall_accuracy,
                    "brier_score": training_result.mean_brier_score,
                    "overfit_gap": training_result.overfit_gap,
                    "ece": cal_result.ece,
                },
                judge_verdict=judge_report.judge_verdict,
                approved_strategies=[s for s, a in judge_report.strategy_approvals.items() if a],
            ),
        )

        path = self._registry.save_artifact(artifact)
        result.artifact_path = str(path)

        return result

    @property
    def rounds(self) -> list[TrainingRoundResult]:
        return self._rounds

    @property
    def latest_report(self) -> JudgeReport | None:
        for r in reversed(self._rounds):
            if r.judge_report is not None:
                return r.judge_report
        return None
