"""Dataset quality validation for ML training.

Checks for future leakage, distribution anomalies, class balance,
and minimum sample requirements before any model touches the data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_SAMPLES_PER_STRATEGY = 200
IDEAL_SAMPLES_PER_STRATEGY = 500
LEAKAGE_LOOKBACK_FEATURES = ["return_5d", "return_10d", "return_20d"]
DIRECTION_COLS = ["direction_5d", "direction_10d", "direction_20d"]


@dataclass
class ValidationReport:
    """Results of dataset validation."""

    is_valid: bool = True
    total_samples: int = 0
    total_features: int = 0
    strategy_counts: dict[str, int] = field(default_factory=dict)
    class_balance: dict[str, dict[str, int]] = field(default_factory=dict)
    leakage_warnings: list[str] = field(default_factory=list)
    distribution_warnings: list[str] = field(default_factory=list)
    missing_data_warnings: list[str] = field(default_factory=list)
    sample_warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    @property
    def all_warnings(self) -> list[str]:
        return (
            self.leakage_warnings
            + self.distribution_warnings
            + self.missing_data_warnings
            + self.sample_warnings
        )

    def summary(self) -> str:
        status = "PASS" if self.is_valid else "FAIL"
        lines = [
            f"Dataset Validation: {status}",
            f"  Samples: {self.total_samples}",
            f"  Features: {self.total_features}",
            f"  Strategies: {len(self.strategy_counts)}",
        ]
        for strat, count in sorted(self.strategy_counts.items()):
            lines.append(f"    {strat}: {count} samples")
        if self.all_warnings:
            lines.append(f"  Warnings ({len(self.all_warnings)}):")
            for w in self.all_warnings:
                lines.append(f"    - {w}")
        if self.recommendations:
            lines.append("  Recommendations:")
            for r in self.recommendations:
                lines.append(f"    - {r}")
        return "\n".join(lines)


class DatasetValidator:
    """Validates ML training datasets for quality and correctness."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def validate(self) -> ValidationReport:
        """Run all validation checks.

        Returns:
            ValidationReport with pass/fail status and detailed findings.
        """
        report = ValidationReport(
            total_samples=len(self._df),
            total_features=len(self._df.columns),
        )

        if self._df.empty:
            report.is_valid = False
            report.sample_warnings.append("Dataset is empty")
            return report

        self._check_strategy_counts(report)
        self._check_class_balance(report)
        self._check_leakage(report)
        self._check_distributions(report)
        self._check_missing_data(report)
        self._generate_recommendations(report)

        return report

    def _check_strategy_counts(self, report: ValidationReport) -> None:
        """Verify minimum sample counts per strategy type."""
        if "strategy_type" not in self._df.columns:
            report.sample_warnings.append("No strategy_type column found")
            report.is_valid = False
            return

        counts = self._df["strategy_type"].value_counts().to_dict()
        report.strategy_counts = counts

        for strat, count in counts.items():
            if count < MIN_SAMPLES_PER_STRATEGY:
                report.sample_warnings.append(
                    f"{strat}: only {count} samples (minimum {MIN_SAMPLES_PER_STRATEGY})"
                )
                report.is_valid = False
            elif count < IDEAL_SAMPLES_PER_STRATEGY:
                report.sample_warnings.append(
                    f"{strat}: {count} samples (ideal is {IDEAL_SAMPLES_PER_STRATEGY}+)"
                )

    def _check_class_balance(self, report: ValidationReport) -> None:
        """Check direction class balance per strategy."""
        for col in DIRECTION_COLS:
            if col not in self._df.columns:
                continue

            balance: dict[str, dict[str, int]] = {}
            for strat in self._df["strategy_type"].unique():
                strat_mask = self._df["strategy_type"] == strat
                value_counts = self._df.loc[strat_mask, col].value_counts().to_dict()
                balance[str(strat)] = {str(k): int(v) for k, v in value_counts.items()}

                total = sum(value_counts.values())
                if total > 0:
                    up_pct = value_counts.get("UP", 0) / total * 100
                    if up_pct > 70 or up_pct < 30:
                        report.distribution_warnings.append(
                            f"{strat}/{col}: class imbalance -- UP={up_pct:.0f}% "
                            f"(possible bull market bias)"
                        )

            report.class_balance[col] = balance

    def _check_leakage(self, report: ValidationReport) -> None:
        """Check for potential future leakage in features.

        Verifies that return/direction columns in the feature set aren't
        accidentally included as training features.
        """
        if "date" in self._df.columns and "ticker" in self._df.columns:
            grouped = self._df.sort_values("date").groupby("ticker")
            for _ticker, group in grouped:
                if len(group) < 2:
                    continue
                dates = group["date"].values
                diffs = np.diff(dates)
                negative = diffs < np.timedelta64(0, "D")
                if negative.any():
                    report.leakage_warnings.append(f"Non-chronological dates detected in {_ticker}")
                    report.is_valid = False
                    break

    def _check_distributions(self, report: ValidationReport) -> None:
        """Check feature distributions for anomalies."""
        numeric_cols = self._df.select_dtypes(include=[np.number]).columns

        for col in numeric_cols:
            values = self._df[col].dropna()
            if len(values) < 10:
                continue

            if values.std() == 0:
                report.distribution_warnings.append(f"{col}: zero variance (constant feature)")
                continue

            z_scores = np.abs((values - values.mean()) / values.std())
            extreme_pct = (z_scores > 10).sum() / len(values) * 100
            if extreme_pct > 1:
                report.distribution_warnings.append(
                    f"{col}: {extreme_pct:.1f}% extreme outliers (|z| > 10)"
                )

    def _check_missing_data(self, report: ValidationReport) -> None:
        """Check for excessive missing values."""
        for col in self._df.columns:
            missing_pct = self._df[col].isna().sum() / len(self._df) * 100
            if missing_pct > 50:
                report.missing_data_warnings.append(f"{col}: {missing_pct:.0f}% missing values")
            elif missing_pct > 20:
                report.missing_data_warnings.append(
                    f"{col}: {missing_pct:.0f}% missing (consider imputation)"
                )

    def _generate_recommendations(self, report: ValidationReport) -> None:
        """Generate actionable recommendations from validation findings."""
        for strat, count in report.strategy_counts.items():
            if count < MIN_SAMPLES_PER_STRATEGY:
                report.recommendations.append(
                    f"Add more {strat} data (need {MIN_SAMPLES_PER_STRATEGY - count}+ more samples)"
                )

        if report.distribution_warnings:
            report.recommendations.append("Consider winsorizing extreme outliers before training")

        if any("class imbalance" in w for w in report.distribution_warnings):
            report.recommendations.append(
                "Include bear market periods in data to reduce directional bias"
            )
