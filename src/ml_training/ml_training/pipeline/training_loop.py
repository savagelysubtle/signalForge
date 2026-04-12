"""Orchestrates train-judge cycles until the quality bar is met.

Runs the primary model training, judge evaluation, and iterative
improvement loop with configurable quality thresholds.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
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
)
from ml_training.models.registry import ModelArtifact, ModelMetadata, ModelRegistry
from ml_training.threading import optimal_workers

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

MIN_STRATEGY_SAMPLES = 15_000


@dataclass
class TrainingRoundResult:
    """Results from a single training round."""

    round_num: int
    training_result: Any = None
    judge_report: JudgeReport | None = None
    artifact_path: str | None = None
    shap_importances: dict[str, float] | None = None


@dataclass
class TrainingLoopConfig:
    """Configuration for the training loop."""

    max_rounds: int = 5
    target_col: str = "triple_barrier_label"
    return_col: str = "return_10d"
    n_boost_rounds: int = 500
    auto_promote: bool = False
    quality_bar: dict[str, float] | None = None
    classifier_params: dict[str, Any] | None = None
    strategy_type: str | None = None
    binary_mode: bool = True
    feature_prune_fraction: float = 0.30
    model_type: str = "lgbm"
    meta_label: bool = False
    model_mode: str = "shadow"
    inference_only: bool = False


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

        Reserves the final 15% of data (by date) as a strict temporal holdout
        for post-training validation.

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

        dataset, self._holdout = self._split_temporal_holdout(dataset)

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

            if verdict in ("PASS", "CONDITIONAL_PASS"):
                holdout_metrics = self._evaluate_holdout(result)
                if holdout_metrics and result.artifact_path:
                    self._append_holdout_to_metadata(result.artifact_path, holdout_metrics)

                if verdict == "PASS":
                    logger.info("Model PASSED judge evaluation!")
                    if self._config.auto_promote and result.artifact_path:
                        from pathlib import Path

                        self._registry.promote_to_shadow(Path(result.artifact_path))
                        logger.info("Model promoted to shadow mode")
                else:
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

            working_dataset = self._apply_round_adjustments(round_num, result, working_dataset)

        self._update_dead_features()
        return self._rounds

    def _update_dead_features(self) -> None:
        """Auto-update dead_features.json with features that had zero SHAP across all rounds."""
        all_shap: dict[str, list[float]] = {}
        for r in self._rounds:
            if r.shap_importances:
                for feat, importance in r.shap_importances.items():
                    all_shap.setdefault(feat, []).append(abs(importance))

        if not all_shap:
            return

        dead = sorted(
            feat
            for feat, values in all_shap.items()
            if all(v == 0.0 for v in values) and len(values) >= 1
        )

        if not dead:
            return

        import json
        from pathlib import Path

        dead_path = Path(__file__).resolve().parents[2] / "data" / "raw" / "dead_features.json"
        strategy_counts: dict[str, int] = {}
        if dead_path.exists():
            try:
                data = json.loads(dead_path.read_text())
                strategy_counts = data.get("strategy_zero_count", {})
            except json.JSONDecodeError, KeyError:
                pass

        strategy_label = self._config.strategy_type or "combined"
        for feat in dead:
            strategy_counts[feat] = strategy_counts.get(feat, 0) + 1

        confirmed_dead = sorted(feat for feat, count in strategy_counts.items() if count >= 8)

        dead_path.parent.mkdir(parents=True, exist_ok=True)
        dead_path.write_text(
            json.dumps(
                {
                    "dead_features": confirmed_dead,
                    "strategy_zero_count": strategy_counts,
                    "last_updated_by": strategy_label,
                },
                indent=2,
            )
        )
        logger.info(
            "Updated dead_features.json: %d confirmed dead, %d tracked",
            len(confirmed_dead),
            len(strategy_counts),
        )

    def _apply_round_adjustments(
        self,
        round_num: int,
        result: TrainingRoundResult,
        working_dataset: pd.DataFrame,
    ) -> pd.DataFrame:
        """Apply round-specific adjustments so retries explore different configs.

        Round 1 failure -> prune low-SHAP features (round 2 trains pruned).
        Round 2 failure -> double ``reg_lambda``, increase ``min_child_samples``.
        Round 3 failure -> switch boosting to DART with dropout.
        Round 4 failure -> reduce tree complexity to minimum viable.

        Returns the (possibly pruned) working dataset.
        """
        if round_num == 1 and result.shap_importances and self._config.feature_prune_fraction > 0:
            prune_frac = self._config.feature_prune_fraction
            overfit_gap = result.judge_report.insample_vs_oos_gap if result.judge_report else 0.0
            if overfit_gap > 0.12:
                prune_frac = max(prune_frac, 0.40)
                logger.info(
                    "High overfit gap (%.1f%%) — increasing prune fraction to %.0f%%",
                    overfit_gap * 100,
                    prune_frac * 100,
                )
            working_dataset = self._prune_features(
                working_dataset, result.shap_importances, prune_fraction=prune_frac
            )

        params = self._config.classifier_params
        if params is None:
            params = {}
            self._config.classifier_params = params

        if round_num == 2:
            old_lambda = params.get("reg_lambda", 5.0)
            old_min_child = params.get("min_child_samples", 100)
            params["reg_lambda"] = old_lambda * 2
            params["min_child_samples"] = int(old_min_child * 1.5)
            logger.info(
                "Round 3 adjustment: reg_lambda=%.1f, min_child_samples=%d",
                params["reg_lambda"],
                params["min_child_samples"],
            )

        elif round_num == 3:
            params["boosting_type"] = "dart"
            params["drop_rate"] = 0.1
            params["max_drop"] = 50
            params["skip_drop"] = 0.5
            logger.info("Round 4 adjustment: switched to DART boosting")

        elif round_num == 4:
            params["num_leaves"] = 15
            params["max_depth"] = 4
            params["min_child_samples"] = 200
            logger.info("Round 5 adjustment: minimum viable tree complexity")

        return working_dataset

    _HOLDOUT_FRACTION = 0.15

    def _split_temporal_holdout(self, dataset: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Reserve the final fraction of data (by date) as a strict temporal holdout.

        Returns:
            (training_set, holdout_set)
        """
        if "date" not in dataset.columns or len(dataset) < 100:
            return dataset, pd.DataFrame()

        sorted_df = dataset.sort_values("date").reset_index(drop=True)
        split_idx = int(len(sorted_df) * (1 - self._HOLDOUT_FRACTION))
        train = sorted_df.iloc[:split_idx].copy()
        holdout = sorted_df.iloc[split_idx:].copy()

        logger.info(
            "Temporal holdout split: %d train, %d holdout (%.0f%%)",
            len(train),
            len(holdout),
            self._HOLDOUT_FRACTION * 100,
        )
        return train, holdout

    def _evaluate_holdout(self, result: TrainingRoundResult) -> dict[str, float]:
        """Run the trained model against the temporal holdout set.

        Returns holdout metrics dict (accuracy, brier_score, calibration_error).
        """
        holdout = getattr(self, "_holdout", pd.DataFrame())
        if holdout.empty or result.training_result is None:
            return {}

        from sklearn.metrics import accuracy_score, brier_score_loss

        from ml_training.models.predictor import _identify_feature_columns

        try:
            feature_cols = _identify_feature_columns(
                holdout,
                model_mode=self._config.model_mode,
                inference_only=self._config.inference_only,
            )
            X = holdout[feature_cols]
            y = holdout[self._config.target_col]

            classifier = result.training_result.classifier
            y_pred = classifier.predict(X)
            y_proba = classifier.predict_proba(X)

            acc = accuracy_score(y, y_pred)
            is_binary = y_proba.shape[1] == 2
            brier = brier_score_loss(y, y_proba[:, 1]) if is_binary else float("nan")
            calibration_error = abs(y_proba[:, 1].mean() - y.mean()) if is_binary else float("nan")

            metrics = {
                "holdout_accuracy": round(acc, 4),
                "holdout_brier_score": round(brier, 4),
                "holdout_calibration_error": round(calibration_error, 4),
                "holdout_samples": len(holdout),
            }
            logger.info(
                "Holdout metrics: accuracy=%.3f, brier=%.4f, cal_error=%.4f",
                acc,
                brier,
                calibration_error,
            )
            return metrics
        except Exception:
            logger.warning("Holdout evaluation failed", exc_info=True)
            return {}

    @staticmethod
    def _append_holdout_to_metadata(artifact_path: str, holdout_metrics: dict[str, float]) -> None:
        """Merge holdout metrics into the artifact's _meta.json file."""
        import json
        from pathlib import Path

        meta_path = (
            Path(artifact_path).with_suffix("").with_name(Path(artifact_path).stem + "_meta.json")
        )
        if not meta_path.exists():
            return
        try:
            meta = json.loads(meta_path.read_text())
            meta.setdefault("metrics", {}).update(holdout_metrics)
            meta["holdout_metrics"] = holdout_metrics
            meta_path.write_text(json.dumps(meta, indent=2))
        except Exception:
            logger.warning("Failed to write holdout metrics to %s", meta_path, exc_info=True)

    def _apply_strategy_feature_mask(self, dataset: pd.DataFrame) -> pd.DataFrame:
        """Drop fundamental features for all strategies except value-oriented ones.

        Fundamental features (PE ratio, ROE, etc.) are static per-ticker and
        change at most quarterly.  SHAP analysis shows these act as ticker
        fingerprints that enable memorization rather than learning directional
        patterns.  Only ``value`` strategies have a theoretical basis for
        keeping them.
        """
        st = self._config.strategy_type or ""
        if "value" not in st:
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
        feature_cols = set(
            _identify_feature_columns(
                dataset,
                model_mode=self._config.model_mode,
                inference_only=self._config.inference_only,
            )
        )
        scored = {f: v for f, v in shap_importances.items() if f in feature_cols}
        if not scored:
            return dataset

        protected = {"primary_signal", "signal_strength"}
        sorted_feats = sorted(scored.items(), key=lambda x: x[1])
        n_drop = max(1, int(len(sorted_feats) * frac))
        drop_cols = {f for f, _ in sorted_feats[:n_drop]} - protected

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

        if self._config.meta_label:
            from ml_training.models.meta_labeler import MetaLabeler

            model = MetaLabeler(
                target_col=self._config.target_col,
                return_col=self._config.return_col,
                classifier_params=self._config.classifier_params,
            )
            training_result = model.train(
                dataset, signal_col="primary_signal", n_rounds=self._config.n_boost_rounds
            )
        elif self._config.model_type == "tabpfn":
            from ml_training.models.tabpfn_model import TabPFNModel

            model = TabPFNModel(
                target_col=self._config.target_col,
                return_col=self._config.return_col,
                binary_mode=self._config.binary_mode,
            )
            training_result = model.train(dataset, n_rounds=self._config.n_boost_rounds)
        elif self._config.model_type == "ensemble":
            from ml_training.models.ensemble import StackedEnsembleModel

            model = StackedEnsembleModel(
                target_col=self._config.target_col,
                return_col=self._config.return_col,
                classifier_params=self._config.classifier_params,
                binary_mode=self._config.binary_mode,
            )
            training_result = model.train(dataset, n_rounds=self._config.n_boost_rounds)
        else:
            model = PredictionModel(
                target_col=self._config.target_col,
                return_col=self._config.return_col,
                classifier_params=self._config.classifier_params,
                binary_mode=self._config.binary_mode,
                model_mode=self._config.model_mode,
                inference_only=self._config.inference_only,
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
            X_train_sample = X_train.sample(min(shap_sample_size, len(X_train)), random_state=42)

            def _shap_importances(X_sample: pd.DataFrame) -> dict[str, float]:
                sv = explainer.shap_values(X_sample)
                if isinstance(sv, list):
                    mean_abs = np.mean([np.abs(s).mean(axis=0) for s in sv], axis=0)
                else:
                    mean_abs = np.abs(sv).mean(axis=0)
                mean_abs = np.asarray(mean_abs, dtype=float).ravel()
                return dict(zip(feature_cols, mean_abs.tolist()))

            workers = optimal_workers("cpu")
            if workers > 1:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    fut_test = pool.submit(_shap_importances, X_test_sample)
                    fut_train = pool.submit(_shap_importances, X_train_sample)
                    shap_test = fut_test.result()
                    shap_train = fut_train.result()
            else:
                shap_test = _shap_importances(X_test_sample)
                shap_train = _shap_importances(X_train_sample)
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

        calibrator = ProbabilityCalibrator(method="venn_abers")
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
            "model_mode": self._config.model_mode,
            "dataset_size": len(dataset),
        }

        artifact = ModelArtifact(
            classifier=training_result.classifier,
            regressor=training_result.regressor,
            label_encoder=training_result.label_encoder,
            calibrator=calibrator,
            conformal=conformal,
            meta_labeler=model if self._config.meta_label else None,
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

        save_key = self._config.strategy_type
        if self._config.model_mode == "independent" and save_key:
            save_key = f"{save_key}_independent"
        path = self._registry.save_artifact(artifact, strategy_type=save_key)
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
