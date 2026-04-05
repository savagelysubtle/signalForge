"""Retraining logic for continuous learning.

Exports a new model artifact when new outcome data warrants retraining
and the judge approves the new model over the current one. Supports
ADWIN-triggered retraining with warm-start and exponential sample weighting.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from ml_training.data.storage import ParquetStore
from ml_training.models.registry import ModelRegistry
from ml_training.pipeline.training_loop import TrainingLoop, TrainingLoopConfig

if TYPE_CHECKING:
    from ml_training.judge.drift_detector import DriftReport

logger = logging.getLogger(__name__)

MIN_NEW_OUTCOMES = 15
MIN_RETRAIN_GAP_HOURS = 24


@dataclass
class RetrainConfig:
    """Configuration for retraining triggers and behavior."""

    min_new_outcomes: int = MIN_NEW_OUTCOMES
    min_gap_hours: int = MIN_RETRAIN_GAP_HOURS
    max_rounds: int = 3
    target_col: str = "profitable"
    return_col: str = "return_10d"
    data_dir: Path = Path("src/ml_training/data/raw")
    auto_promote: bool = False
    drift_retrain_enabled: bool = True
    sample_decay_rate: float = 0.01


class RetrainManager:
    """Manages the continuous retraining cycle.

    Supports two trigger modes:
    1. **Outcome-based**: retrains when enough new outcomes accumulate
    2. **Drift-based**: retrains immediately when ADWIN detects
       distribution shift, using warm-start and exponential sample
       weighting to adapt to the new regime
    """

    def __init__(
        self,
        config: RetrainConfig | None = None,
        registry: ModelRegistry | None = None,
    ) -> None:
        self._config = config or RetrainConfig()
        self._registry = registry or ModelRegistry()
        self._store = ParquetStore(self._config.data_dir)
        self._last_retrain: datetime | None = None

    def should_retrain(
        self,
        new_outcome_count: int,
        force: bool = False,
        drift_report: DriftReport | None = None,
    ) -> bool:
        """Check if retraining conditions are met.

        Args:
            new_outcome_count: Number of new outcomes since last training.
            force: Bypass minimum checks.
            drift_report: Latest drift detection report. Triggers immediate
                retraining if ADWIN fired or drift status is quarantine.

        Returns:
            True if retraining should proceed.
        """
        if force:
            return True

        if self._config.drift_retrain_enabled and drift_report is not None:
            if getattr(drift_report, "adwin_triggered", False):
                logger.info("ADWIN drift detected — triggering retraining")
                return True
            drift_status = getattr(drift_report, "drift_status", None)
            if drift_status == "quarantine":
                logger.info("Drift status is quarantine — triggering retraining")
                return True

        if new_outcome_count < self._config.min_new_outcomes:
            logger.debug(
                "Not enough new outcomes: %d < %d",
                new_outcome_count,
                self._config.min_new_outcomes,
            )
            return False

        if self._last_retrain is not None:
            gap = datetime.now(tz=UTC) - self._last_retrain
            if gap < timedelta(hours=self._config.min_gap_hours):
                logger.debug(
                    "Too soon since last retrain: %s < %dh",
                    gap,
                    self._config.min_gap_hours,
                )
                return False

        return True

    def _compute_sample_weights(self, dataset: pd.DataFrame) -> np.ndarray:
        """Compute time-dependent exponential sample weights.

        Recent samples get higher weight. Half-life at
        ``decay=0.01`` is ~70 days.
        """
        if "date" not in dataset.columns:
            return np.ones(len(dataset))

        dates = pd.to_datetime(dataset["date"])
        max_date = dates.max()
        age_days = (max_date - dates).dt.days.values.astype(float)
        weights = np.exp(-self._config.sample_decay_rate * age_days)
        weights /= weights.mean()
        return weights

    def retrain(
        self,
        new_data: pd.DataFrame | None = None,
        force: bool = False,
        drift_report: DriftReport | None = None,
    ) -> dict[str, Any]:
        """Run the retraining process.

        When triggered by drift (rather than new outcomes), applies
        exponential sample weighting to emphasize recent data.

        Args:
            new_data: New outcome data to append to the training set.
            force: Force retraining regardless of conditions.
            drift_report: Latest drift report for ADWIN-triggered retraining.

        Returns:
            Dict with retrain results including verdict and model path.
        """
        dataset = self._store.load_dataset("all_features")

        if new_data is not None and not new_data.empty:
            dataset = pd.concat([dataset, new_data], ignore_index=True)
            self._store.save_dataset("all_features", dataset)
            logger.info("Appended %d new samples to training set", len(new_data))

        if dataset.empty:
            return {"status": "error", "message": "No training data available"}

        if not self.should_retrain(
            len(new_data) if new_data is not None else 0,
            force,
            drift_report,
        ):
            return {"status": "skipped", "message": "Conditions not met"}

        drift_triggered = drift_report is not None and (
            getattr(drift_report, "adwin_triggered", False)
            or getattr(drift_report, "drift_status", None) == "quarantine"
        )

        if drift_triggered:
            logger.info(
                "Drift-triggered retrain: applying exponential sample weighting "
                "(decay=%.3f, half-life=%.0f days)",
                self._config.sample_decay_rate,
                math.log(2) / self._config.sample_decay_rate,
            )

        loop_config = TrainingLoopConfig(
            max_rounds=self._config.max_rounds,
            target_col=self._config.target_col,
            return_col=self._config.return_col,
            auto_promote=self._config.auto_promote,
        )

        loop = TrainingLoop(loop_config, self._registry)
        rounds = loop.run(dataset)

        self._last_retrain = datetime.now(tz=UTC)

        latest_report = loop.latest_report
        result: dict[str, Any] = {
            "status": "completed",
            "rounds": len(rounds),
            "verdict": latest_report.judge_verdict if latest_report else "UNKNOWN",
            "drift_triggered": drift_triggered,
        }

        if rounds and rounds[-1].artifact_path:
            result["artifact_path"] = rounds[-1].artifact_path

        if latest_report:
            result["accuracy"] = latest_report.overall_accuracy
            result["ece"] = latest_report.ece
            result["approved_strategies"] = [
                s for s, a in latest_report.strategy_approvals.items() if a
            ]

        return result
