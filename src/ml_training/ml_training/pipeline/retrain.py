"""Retraining logic for continuous learning.

Exports a new model artifact when new outcome data warrants retraining
and the judge approves the new model over the current one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from ml_training.data.storage import ParquetStore
from ml_training.models.registry import ModelRegistry
from ml_training.pipeline.training_loop import TrainingLoop, TrainingLoopConfig

logger = logging.getLogger(__name__)

MIN_NEW_OUTCOMES = 15
MIN_RETRAIN_GAP_HOURS = 24


@dataclass
class RetrainConfig:
    """Configuration for retraining triggers and behavior."""

    min_new_outcomes: int = MIN_NEW_OUTCOMES
    min_gap_hours: int = MIN_RETRAIN_GAP_HOURS
    max_rounds: int = 3
    target_col: str = "direction_10d"
    return_col: str = "return_10d"
    data_dir: Path = Path("src/ml_training/data/raw")
    auto_promote: bool = False


class RetrainManager:
    """Manages the continuous retraining cycle.

    Checks whether retraining is warranted based on new outcome count
    and time since last training, then runs the training loop and
    compares the new model against the current one.
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
    ) -> bool:
        """Check if retraining conditions are met.

        Args:
            new_outcome_count: Number of new outcomes since last training.
            force: Bypass minimum checks.

        Returns:
            True if retraining should proceed.
        """
        if force:
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

    def retrain(
        self,
        new_data: pd.DataFrame | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Run the retraining process.

        Args:
            new_data: New outcome data to append to the training set.
                If None, uses the existing stored dataset.
            force: Force retraining regardless of conditions.

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

        if not self.should_retrain(len(new_data) if new_data is not None else 0, force):
            return {"status": "skipped", "message": "Conditions not met"}

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
