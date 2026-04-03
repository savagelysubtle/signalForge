"""JudgeReport generation, formatting, and recommendation engine.

Produces a comprehensive JudgeReport from all validation layers,
with actionable recommendations for model improvement.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass
class JudgeReport:
    """Complete judge evaluation report for a model version."""

    model_version: str = ""
    judge_verdict: Literal["PASS", "CONDITIONAL_PASS", "FAIL"] = "FAIL"

    # WFO integrity
    wfo_integrity: Literal["clean", "leakage_detected", "insufficient_folds"] = "clean"
    purge_verified: bool = True
    embargo_verified: bool = True
    overfit_risk: Literal["low", "medium", "high"] = "low"
    insample_vs_oos_gap: float = 0.0

    # Performance
    overall_accuracy: float = 0.0
    accuracy_by_strategy: dict[str, float] = field(default_factory=dict)
    brier_score: float = 1.0
    ece: float = 1.0
    information_coefficient: float = 0.0
    deflated_sharpe_probability: float = 0.0

    # Drift status
    psi_overall: float = 0.0
    ks_flagged_features: list[str] = field(default_factory=list)
    shap_ndcg: float = 1.0
    cbpe_estimated_accuracy: float | None = None
    drift_status: Literal["healthy", "warning", "caution", "quarantine"] = "healthy"

    # Approvals
    regime_coverage: list[str] = field(default_factory=list)
    regime_gaps: list[str] = field(default_factory=list)
    strategy_approvals: dict[str, bool] = field(default_factory=dict)
    reliability_model_accuracy: float = 0.0

    # Actionable
    recommendations: list[str] = field(default_factory=list)
    conformal_coverage_achieved: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def summary(self) -> str:
        """Generate a human-readable summary of the judge report."""
        lines = [
            f"Judge Report: {self.model_version}",
            f"  Verdict: {self.judge_verdict}",
            "",
            "  Performance:",
            f"    Accuracy: {self.overall_accuracy:.1%}",
            f"    Brier Score: {self.brier_score:.4f}",
            f"    ECE: {self.ece:.4f}",
            f"    IC: {self.information_coefficient:.4f}",
            f"    DSR Probability: {self.deflated_sharpe_probability:.1%}",
            "",
            "  WFO Integrity:",
            f"    Status: {self.wfo_integrity}",
            f"    Purge: {'OK' if self.purge_verified else 'FAILED'}",
            f"    Embargo: {'OK' if self.embargo_verified else 'FAILED'}",
            f"    Overfit Risk: {self.overfit_risk} (gap={self.insample_vs_oos_gap:.1%})",
            "",
            "  Drift:",
            f"    Status: {self.drift_status}",
            f"    PSI: {self.psi_overall:.4f}",
            f"    SHAP NDCG: {self.shap_ndcg:.4f}",
        ]

        if self.ks_flagged_features:
            lines.append(f"    KS Flagged: {', '.join(self.ks_flagged_features)}")

        lines.append("")
        lines.append("  Strategy Approvals:")
        for strat, approved in sorted(self.strategy_approvals.items()):
            acc = self.accuracy_by_strategy.get(strat, 0)
            status = "APPROVED" if approved else "REJECTED"
            lines.append(f"    {strat}: {status} ({acc:.1%})")

        if self.recommendations:
            lines.append("")
            lines.append("  Recommendations:")
            for rec in self.recommendations:
                lines.append(f"    - {rec}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Quality bar thresholds
# ---------------------------------------------------------------------------

DEFAULT_QUALITY_BAR = {
    "min_overall_accuracy": 0.48,
    "min_strategy_accuracy": 0.45,
    "max_calibration_error": 0.08,
    "max_overfit_gap": 0.10,
    "min_samples_per_strategy": 50,
    "min_reliability_accuracy": 0.60,
    "min_dsr_probability": 0.50,
}


MIN_WFO_DATASET_SIZE = 5000


def determine_verdict(
    report: JudgeReport,
    quality_bar: dict[str, float] | None = None,
    dataset_size: int | None = None,
) -> Literal["PASS", "CONDITIONAL_PASS", "FAIL"]:
    """Determine the final judge verdict based on quality thresholds.

    Args:
        report: Populated JudgeReport.
        quality_bar: Override quality thresholds.
        dataset_size: Number of rows in the training dataset. When below
            ``MIN_WFO_DATASET_SIZE``, WFO integrity failures are
            downgraded to partial failures (insufficient data for
            meaningful walk-forward validation).

    Returns:
        One of PASS, CONDITIONAL_PASS, or FAIL.
    """
    bar = quality_bar or DEFAULT_QUALITY_BAR
    failures: list[str] = []
    partial_failures: list[str] = []

    if report.wfo_integrity != "clean":
        if dataset_size is not None and dataset_size < MIN_WFO_DATASET_SIZE:
            partial_failures.append(
                f"WFO integrity: {report.wfo_integrity} (downgraded — only {dataset_size} rows)"
            )
        else:
            failures.append(f"WFO integrity: {report.wfo_integrity}")

    if report.drift_status == "quarantine":
        partial_failures.append("Drift status: quarantine (expected for train/test time split)")

    if report.overall_accuracy < bar["min_overall_accuracy"]:
        failures.append(
            f"Overall accuracy {report.overall_accuracy:.1%} < {bar['min_overall_accuracy']:.1%}"
        )

    if report.ece > bar["max_calibration_error"]:
        partial_failures.append(
            f"Calibration error {report.ece:.4f} > {bar['max_calibration_error']}"
        )

    max_overfit = bar.get("max_overfit_gap", 0.10)
    if report.insample_vs_oos_gap > max_overfit:
        failures.append(
            f"Overfit gap {report.insample_vs_oos_gap:.1%} > {max_overfit:.1%} threshold"
        )

    min_reliability = bar.get("min_reliability_accuracy", 0.60)
    if report.reliability_model_accuracy < min_reliability:
        partial_failures.append(
            f"Reliability model accuracy {report.reliability_model_accuracy:.1%}"
            f" < {min_reliability:.1%}"
        )

    min_dsr = bar.get("min_dsr_probability", 0.50)
    if report.deflated_sharpe_probability > 0 and report.deflated_sharpe_probability < min_dsr:
        partial_failures.append(
            f"DSR probability {report.deflated_sharpe_probability:.1%} < {min_dsr:.1%}"
        )

    strategy_approvals: dict[str, bool] = {}
    for strat, acc in report.accuracy_by_strategy.items():
        approved = acc >= bar["min_strategy_accuracy"]
        strategy_approvals[strat] = approved
        if not approved:
            partial_failures.append(f"{strat} accuracy {acc:.1%} below threshold")

    report.strategy_approvals = strategy_approvals

    if failures:
        report.judge_verdict = "FAIL"
        report.recommendations.extend(failures)
    elif partial_failures:
        report.judge_verdict = "CONDITIONAL_PASS"
        report.recommendations.extend(partial_failures)
    else:
        report.judge_verdict = "PASS"

    return report.judge_verdict
