"""Orchestrates train-judge cycles until the quality bar is met.

Runs the primary model training, judge evaluation, and iterative
improvement loop with configurable quality thresholds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import shap

from ml_training.judge.judge import JudgeSystem
from ml_training.judge.report import JudgeReport
from ml_training.models.calibration import ConformalPredictor, ProbabilityCalibrator
from ml_training.models.predictor import (
    DEFAULT_EMBARGO_WINDOW,
    DEFAULT_PURGE_WINDOW,
    PredictionModel,
    TrainingResult,
)
from ml_training.models.registry import ModelArtifact, ModelMetadata, ModelRegistry

logger = logging.getLogger(__name__)


FUNDAMENTAL_FEATURES = frozenset(
    {
        "pe_ratio",
        "pb_ratio",
        "ev_ebitda",
        "debt_equity",
        "roe",
        "net_margin",
        "revenue_growth",
        "piotroski_score",
        "altman_z",
        "analyst_target_upside",
        "insider_buy_ratio",
        "current_ratio",
        "dividend_yield",
        "roa",
        "composite_score",
    }
)


@dataclass
class TrainingRoundResult:
    """Results from a single training round."""

    round_num: int
    training_result: TrainingResult | None = None
    judge_report: JudgeReport | None = None
    artifact_path: str | None = None
    shap_importances: dict[str, float] | None = None


@dataclass
class TrainingLoopConfig:
    """Configuration for the training loop."""

    max_rounds: int = 5
    target_col: str = "direction_10d"
    return_col: str = "return_10d"
    n_boost_rounds: int = 500
    auto_promote: bool = False
    quality_bar: dict[str, float] | None = None
    classifier_params: dict[str, Any] | None = None
    strategy_type: str | None = None
    binary_mode: bool = False
    feature_prune_fraction: float = 0.20


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

        After round 1, if the model fails, low-importance features are
        pruned via SHAP analysis before subsequent rounds.

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

        working_dataset = self._apply_strategy_feature_mask(dataset)

        for round_num in range(1, self._config.max_rounds + 1):
            logger.info("=" * 60)
            logger.info("ROUND %d / %d", round_num, self._config.max_rounds)
            logger.info("=" * 60)

            result = self._run_round(working_dataset, round_num)
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

            if (
                round_num == 1
                and result.shap_importances
                and self._config.feature_prune_fraction > 0
            ):
                prune_frac = self._config.feature_prune_fraction
                overfit_gap = result.judge_report.insample_vs_oos_gap
                if overfit_gap > 0.15:
                    prune_frac = max(prune_frac, 0.35)
                    logger.info(
                        "High overfit gap (%.1f%%) — increasing prune fraction to %.0f%%",
                        overfit_gap * 100,
                        prune_frac * 100,
                    )
                working_dataset = self._prune_features(
                    working_dataset, result.shap_importances, prune_fraction=prune_frac
                )

        return self._rounds

    def _apply_strategy_feature_mask(self, dataset: pd.DataFrame) -> pd.DataFrame:
        """Drop feature groups known to be noise for certain strategy types.

        Uses substring matching because per-strategy training passes the
        strategy ID (e.g. ``ema_stack_momentum_intraday``) rather than
        the template's ``strategy_type`` field.
        """
        st = self._config.strategy_type or ""
        if "intraday" in st or "scalp" in st:
            drop = [c for c in FUNDAMENTAL_FEATURES if c in dataset.columns]
            if drop:
                logger.info("Strategy mask: dropping %d fundamental features for %s", len(drop), st)
                return dataset.drop(columns=drop)
        return dataset

    def _prune_features(
        self,
        dataset: pd.DataFrame,
        shap_importances: dict[str, float],
        prune_fraction: float | None = None,
    ) -> pd.DataFrame:
        """Drop the lowest-importance features based on SHAP values."""
        from ml_training.models.predictor import _identify_feature_columns

        frac = prune_fraction if prune_fraction is not None else self._config.feature_prune_fraction
        feature_cols = set(_identify_feature_columns(dataset))
        scored = {f: v for f, v in shap_importances.items() if f in feature_cols}
        if not scored:
            return dataset

        sorted_feats = sorted(scored.items(), key=lambda x: x[1])
        n_drop = max(1, int(len(sorted_feats) * frac))
        drop_cols = {f for f, _ in sorted_feats[:n_drop]}

        keep = [c for c in dataset.columns if c not in drop_cols]
        logger.info(
            "Pruned %d low-importance features for next round: %s",
            len(drop_cols),
            sorted(drop_cols),
        )
        return dataset[keep]

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
            classifier_params=self._config.classifier_params,
            binary_mode=self._config.binary_mode,
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

        judge_split = int(len(test_df) * 0.7)
        judge_df = test_df.iloc[:judge_split]
        cal_df = test_df.iloc[judge_split:]

        from ml_training.models.predictor import _prepare_features

        X_test_judge, _ = _prepare_features(judge_df, feature_cols)
        X_test_cal, _ = _prepare_features(cal_df, feature_cols)
        X_train, _ = _prepare_features(train_df, feature_cols)

        from sklearn.preprocessing import LabelEncoder

        le = LabelEncoder()
        if self._config.binary_mode:
            le.fit([0, 1])
            y_judge = judge_df[self._config.target_col].astype(int).values
            y_cal = cal_df[self._config.target_col].astype(int).values
        else:
            le.fit(["DOWN", "FLAT", "UP"])
            y_judge = le.transform(judge_df[self._config.target_col].values)
            y_cal = le.transform(cal_df[self._config.target_col].values)

        predictions = training_result.classifier.predict(X_test_judge)
        probabilities = training_result.classifier.predict_proba(X_test_judge)

        cal_probabilities = training_result.classifier.predict_proba(X_test_cal)

        shap_train: dict[str, float] | None = None
        shap_test: dict[str, float] | None = None
        shap_sample_size = 2000
        try:
            explainer = shap.TreeExplainer(training_result.classifier)

            X_test_sample = X_test_judge.sample(
                min(shap_sample_size, len(X_test_judge)), random_state=42
            )
            shap_values = explainer.shap_values(X_test_sample)
            if isinstance(shap_values, list):
                mean_abs = np.mean([np.abs(sv).mean(axis=0) for sv in shap_values], axis=0)
            else:
                mean_abs = np.abs(shap_values).mean(axis=0)
            mean_abs = np.asarray(mean_abs, dtype=float).ravel()
            shap_test = dict(zip(feature_cols, mean_abs.tolist()))

            X_train_sample = X_train.sample(min(shap_sample_size, len(X_train)), random_state=42)
            shap_values_train = explainer.shap_values(X_train_sample)
            if isinstance(shap_values_train, list):
                mean_abs_train = np.mean(
                    [np.abs(sv).mean(axis=0) for sv in shap_values_train], axis=0
                )
            else:
                mean_abs_train = np.abs(shap_values_train).mean(axis=0)
            mean_abs_train = np.asarray(mean_abs_train, dtype=float).ravel()
            shap_train = dict(zip(feature_cols, mean_abs_train.tolist()))
        except Exception:
            logger.warning("SHAP analysis failed, skipping importance drift check", exc_info=True)

        result.shap_importances = shap_test

        strategy_labels = (
            judge_df["strategy_type"].values if "strategy_type" in judge_df.columns else None
        )

        fold_details = [
            {
                "train_indices": fr.train_indices,
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
            true_labels=y_judge,
            feature_data=X_test_judge,
            training_data=X_train,
            fold_results=fold_details,
            train_accuracies=[fr.train_accuracy for fr in training_result.fold_results],
            test_accuracies=[fr.test_accuracy for fr in training_result.fold_results],
            strategy_labels=strategy_labels,
            shap_importances_train=shap_train,
            shap_importances_test=shap_test,
            dataset_size=len(dataset),
        )
        result.judge_report = judge_report

        calibrator = ProbabilityCalibrator()
        cal_result = calibrator.fit(cal_probabilities, y_cal)

        conformal = ConformalPredictor(target_coverage=0.90)
        conformal.fit(cal_result.calibrated_probs, y_cal)

        classifier_params_used = self._config.classifier_params or {}
        training_config = {
            "classifier_params": classifier_params_used,
            "n_boost_rounds": self._config.n_boost_rounds,
            "target_col": self._config.target_col,
            "return_col": self._config.return_col,
            "n_folds": len(training_result.fold_results),
            "purge_window": DEFAULT_PURGE_WINDOW,
            "embargo_window": DEFAULT_EMBARGO_WINDOW,
            "strategy_type": self._config.strategy_type,
            "dataset_size": len(dataset),
        }

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
                strategy_type=self._config.strategy_type,
                training_config=training_config,
                shap_importance=shap_test,
            ),
        )

        path = self._registry.save_artifact(artifact, strategy_type=self._config.strategy_type)
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
