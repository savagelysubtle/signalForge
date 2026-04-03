"""Outcome tracking for ML predictions (Karpathy Data Engine foundation).

Logs predictions with feature context, resolves actual outcomes by
checking price data N days later, and reports rolling accuracy metrics
per strategy, confidence bucket, and regime.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

PREDICTIONS_FILE = "predictions_log.parquet"
RESOLVED_FILE = "resolved_predictions.parquet"


@dataclass
class PredictionRecord:
    """A single logged prediction."""

    timestamp: str
    ticker: str
    strategy_type: str
    predicted_direction: str
    confidence: float
    model_version: str
    feature_vector_hash: str = ""
    resolved: bool = False
    actual_direction: str | None = None
    actual_return: float | None = None
    correct: bool | None = None


class OutcomeTracker:
    """Tracks predictions and resolves outcomes from price data.

    Stores predictions in a parquet log, then resolves them against
    actual price movements to measure real-world accuracy.

    Args:
        data_dir: Base data directory (e.g. ``data/raw``).
        horizon_days: Number of trading days to wait before resolving.
    """

    def __init__(self, data_dir: Path, horizon_days: int = 10) -> None:
        self._data_dir = data_dir
        self._horizon = horizon_days
        self._outcomes_dir = data_dir / "outcomes"
        self._outcomes_dir.mkdir(parents=True, exist_ok=True)
        self._predictions_path = self._outcomes_dir / PREDICTIONS_FILE
        self._resolved_path = self._outcomes_dir / RESOLVED_FILE

    def log_prediction(
        self,
        ticker: str,
        strategy_type: str,
        predicted_direction: str,
        confidence: float,
        model_version: str,
        feature_hash: str = "",
    ) -> None:
        """Log a new prediction for future outcome resolution.

        Args:
            ticker: Ticker symbol.
            strategy_type: Strategy type key.
            predicted_direction: UP/DOWN/FLAT prediction.
            confidence: Model confidence (0-1).
            model_version: Model version string.
            feature_hash: Optional hash of the feature vector.
        """
        record = {
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "strategy_type": strategy_type,
            "predicted_direction": predicted_direction,
            "confidence": confidence,
            "model_version": model_version,
            "feature_vector_hash": feature_hash,
            "resolved": False,
            "actual_direction": None,
            "actual_return": None,
            "correct": None,
        }

        existing = self._load_predictions()
        new_row = pd.DataFrame([record])
        combined = (
            pd.concat([existing, new_row], ignore_index=True) if not existing.empty else new_row
        )
        combined.to_parquet(self._predictions_path, index=False)

    def resolve_outcomes(self, price_loader: Any) -> ResolveResult:
        """Check unresolved predictions against actual price data.

        Args:
            price_loader: Object with ``load_prices(ticker, timeframe)`` method
                returning a DataFrame with ``date`` and ``close`` columns.

        Returns:
            ResolveResult with counts of newly resolved predictions.
        """
        df = self._load_predictions()
        if df.empty:
            return ResolveResult()

        unresolved = df[df["resolved"] == False]  # noqa: E712
        if unresolved.empty:
            logger.info("No unresolved predictions to process")
            return ResolveResult()

        newly_resolved = 0
        cutoff = datetime.now() - timedelta(days=self._horizon + 5)

        for idx, row in unresolved.iterrows():
            pred_date = pd.Timestamp(row["timestamp"])
            if pred_date > cutoff:
                continue

            prices = price_loader.load_prices(row["ticker"], "D")
            if prices.empty:
                continue

            prices["date"] = pd.to_datetime(prices["date"])
            after = prices[prices["date"] > pred_date]
            if len(after) < self._horizon:
                continue

            entry_price = prices[prices["date"] <= pred_date]["close"].iloc[-1]
            exit_price = after.iloc[self._horizon - 1]["close"]
            actual_return = (exit_price - entry_price) / entry_price

            if actual_return > 0.02:
                actual_dir = "UP"
            elif actual_return < -0.02:
                actual_dir = "DOWN"
            else:
                actual_dir = "FLAT"

            df.at[idx, "resolved"] = True
            df.at[idx, "actual_direction"] = actual_dir
            df.at[idx, "actual_return"] = float(actual_return)
            df.at[idx, "correct"] = row["predicted_direction"] == actual_dir
            newly_resolved += 1

        df.to_parquet(self._predictions_path, index=False)

        resolved = df[df["resolved"] == True]  # noqa: E712
        if not resolved.empty:
            resolved.to_parquet(self._resolved_path, index=False)

        logger.info("Resolved %d predictions", newly_resolved)
        return ResolveResult(
            total_unresolved=len(unresolved),
            newly_resolved=newly_resolved,
            remaining=len(unresolved) - newly_resolved,
        )

    def report(self) -> OutcomeReport:
        """Generate a rolling accuracy report from resolved predictions.

        Returns:
            OutcomeReport with accuracy breakdowns.
        """
        if not self._resolved_path.exists():
            return OutcomeReport()

        df = pd.read_parquet(self._resolved_path)
        if df.empty:
            return OutcomeReport()

        total = len(df)
        correct = int(df["correct"].sum())
        overall_acc = correct / total if total > 0 else 0.0

        by_strategy: dict[str, dict[str, Any]] = {}
        for st, group in df.groupby("strategy_type"):
            n = len(group)
            c = int(group["correct"].sum())
            by_strategy[str(st)] = {
                "total": n,
                "correct": c,
                "accuracy": c / n if n > 0 else 0.0,
            }

        by_confidence: dict[str, dict[str, Any]] = {}
        df["conf_bucket"] = pd.cut(
            df["confidence"],
            bins=[0, 0.4, 0.6, 0.8, 1.0],
            labels=["low", "medium", "high", "very_high"],
        )
        for bucket, group in df.groupby("conf_bucket", observed=True):
            n = len(group)
            c = int(group["correct"].sum())
            by_confidence[str(bucket)] = {
                "total": n,
                "correct": c,
                "accuracy": c / n if n > 0 else 0.0,
            }

        return OutcomeReport(
            total_predictions=total,
            total_correct=correct,
            overall_accuracy=overall_acc,
            accuracy_by_strategy=by_strategy,
            accuracy_by_confidence=by_confidence,
        )

    def _load_predictions(self) -> pd.DataFrame:
        if self._predictions_path.exists():
            return pd.read_parquet(self._predictions_path)
        return pd.DataFrame()


@dataclass
class ResolveResult:
    """Result of resolving outcomes."""

    total_unresolved: int = 0
    newly_resolved: int = 0
    remaining: int = 0


@dataclass
class OutcomeReport:
    """Rolling accuracy report from resolved predictions."""

    total_predictions: int = 0
    total_correct: int = 0
    overall_accuracy: float = 0.0
    accuracy_by_strategy: dict[str, dict[str, Any]] = field(default_factory=dict)
    accuracy_by_confidence: dict[str, dict[str, Any]] = field(default_factory=dict)

    def summary(self) -> str:
        """Generate human-readable summary."""
        if self.total_predictions == 0:
            return "No resolved predictions yet."

        lines = [
            f"Outcome Report: {self.total_predictions} resolved predictions",
            f"  Overall Accuracy: {self.overall_accuracy:.1%}"
            f" ({self.total_correct}/{self.total_predictions})",
            "",
            "  By Strategy:",
        ]
        for st, data in sorted(self.accuracy_by_strategy.items()):
            lines.append(f"    {st}: {data['accuracy']:.1%} ({data['correct']}/{data['total']})")

        lines.append("")
        lines.append("  By Confidence Bucket:")
        for bucket, data in sorted(self.accuracy_by_confidence.items()):
            lines.append(
                f"    {bucket}: {data['accuracy']:.1%} ({data['correct']}/{data['total']})"
            )

        return "\n".join(lines)
