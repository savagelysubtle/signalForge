"""Drift detection: PSI, KS test, SHAP importance drift, ADWIN.

Five independent drift signals that detect when the model's operating
environment has changed enough to warrant attention or retraining.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

PSI_HEALTHY = 0.1
PSI_WARNING = 0.2
PSI_CAUTION = 0.4
KS_SIGNIFICANCE = 0.05
SHAP_NDCG_HEALTHY = 0.95
SHAP_NDCG_WARNING = 0.90

DriftStatus = Literal["healthy", "warning", "caution", "quarantine"]


@dataclass
class DriftReport:
    """Combined drift detection results from all methods."""

    status: DriftStatus = "healthy"
    psi_overall: float = 0.0
    psi_by_feature: dict[str, float] = field(default_factory=dict)
    ks_flagged_features: list[str] = field(default_factory=list)
    ks_p_values: dict[str, float] = field(default_factory=dict)
    shap_ndcg: float = 1.0
    shap_importance_drift: dict[str, float] = field(default_factory=dict)
    adwin_triggered: bool = False
    adwin_drift_point: int | None = None
    cbpe_estimated_accuracy: float | None = None
    recommendations: list[str] = field(default_factory=list)


def compute_psi(
    reference: np.ndarray,
    current: np.ndarray,
    n_bins: int = 10,
) -> float:
    """Compute Population Stability Index between two distributions.

    PSI measures how much a distribution has shifted from a reference.
    Higher values indicate more drift.

    Args:
        reference: Reference (training) distribution values.
        current: Current (production) distribution values.
        n_bins: Number of bins for discretization.

    Returns:
        PSI value. 0-0.1=stable, 0.1-0.2=warning, 0.2+=significant.
    """
    eps = 1e-6

    breakpoints = np.linspace(
        min(reference.min(), current.min()) - eps,
        max(reference.max(), current.max()) + eps,
        n_bins + 1,
    )

    ref_counts = np.histogram(reference, bins=breakpoints)[0] + eps
    cur_counts = np.histogram(current, bins=breakpoints)[0] + eps

    ref_pct = ref_counts / ref_counts.sum()
    cur_pct = cur_counts / cur_counts.sum()

    psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
    return max(psi, 0.0)


def compute_ks_test(
    reference: np.ndarray,
    current: np.ndarray,
) -> tuple[float, float]:
    """Run Kolmogorov-Smirnov test for per-feature drift.

    Args:
        reference: Reference distribution values.
        current: Current distribution values.

    Returns:
        Tuple of (KS statistic, p-value).
    """
    stat, p_value = stats.ks_2samp(reference, current)
    return float(stat), float(p_value)


def compute_ndcg(
    reference_ranking: list[str],
    current_ranking: list[str],
    k: int | None = None,
) -> float:
    """Compute NDCG for SHAP feature importance ranking similarity.

    Measures how well the current feature importance ranking matches
    the reference ranking. 1.0 = identical ranking.

    Args:
        reference_ranking: Feature names ordered by importance (training time).
        current_ranking: Feature names ordered by importance (current).
        k: Top-k features to consider. Defaults to all.

    Returns:
        NDCG score between 0 and 1.
    """
    if not reference_ranking or not current_ranking:
        return 1.0

    k = k or len(reference_ranking)
    n = min(k, len(reference_ranking), len(current_ranking))

    ref_relevance = {name: n - i for i, name in enumerate(reference_ranking[:n])}

    dcg = 0.0
    for i, name in enumerate(current_ranking[:n]):
        rel = ref_relevance.get(name, 0)
        dcg += rel / np.log2(i + 2)

    idcg = 0.0
    for i, name in enumerate(reference_ranking[:n]):
        rel = ref_relevance.get(name, 0)
        idcg += rel / np.log2(i + 2)

    return float(dcg / idcg) if idcg > 0 else 0.0


class DriftDetector:
    """Multi-method drift detection system.

    Runs PSI, KS test, SHAP importance drift, and ADWIN to produce
    an overall drift status with per-method details.
    """

    def __init__(
        self,
        critical_features: list[str] | None = None,
    ) -> None:
        self._critical_features = critical_features or [
            "rsi_14",
            "adx",
            "volume_ratio",
            "vix_level",
            "momentum_score",
        ]
        self._adwin_detectors: dict[str, Any] = {}

    def detect(
        self,
        reference_data: pd.DataFrame,
        current_data: pd.DataFrame,
        reference_shap_importances: dict[str, float] | None = None,
        current_shap_importances: dict[str, float] | None = None,
        error_stream: np.ndarray | None = None,
    ) -> DriftReport:
        """Run all drift detection methods.

        Args:
            reference_data: Training feature data.
            current_data: Current/test feature data.
            reference_shap_importances: SHAP importances at training time.
            current_shap_importances: SHAP importances on current data.
            error_stream: Stream of prediction errors for ADWIN.

        Returns:
            DriftReport with combined results from all methods.
        """
        report = DriftReport()

        self._run_psi(reference_data, current_data, report)
        self._run_ks_tests(reference_data, current_data, report)
        self._run_shap_drift(reference_shap_importances, current_shap_importances, report)
        self._run_adwin(error_stream, report)
        self._determine_status(report)

        return report

    def _run_psi(
        self,
        reference: pd.DataFrame,
        current: pd.DataFrame,
        report: DriftReport,
    ) -> None:
        """Compute PSI for each numeric feature."""
        numeric_cols = reference.select_dtypes(include=[np.number]).columns
        common_cols = [c for c in numeric_cols if c in current.columns]

        psi_values: dict[str, float] = {}
        for col in common_cols:
            ref_vals = reference[col].dropna().values
            cur_vals = current[col].dropna().values
            if len(ref_vals) < 10 or len(cur_vals) < 10:
                continue
            psi_values[col] = compute_psi(ref_vals, cur_vals)

        report.psi_by_feature = psi_values
        report.psi_overall = float(np.mean(list(psi_values.values()))) if psi_values else 0.0

    def _run_ks_tests(
        self,
        reference: pd.DataFrame,
        current: pd.DataFrame,
        report: DriftReport,
    ) -> None:
        """Run KS tests on critical features."""
        for feat in self._critical_features:
            if feat not in reference.columns or feat not in current.columns:
                continue

            ref_vals = reference[feat].dropna().values
            cur_vals = current[feat].dropna().values
            if len(ref_vals) < 10 or len(cur_vals) < 10:
                continue

            _stat, p_val = compute_ks_test(ref_vals, cur_vals)
            report.ks_p_values[feat] = p_val

            if p_val < KS_SIGNIFICANCE:
                report.ks_flagged_features.append(feat)

    def _run_shap_drift(
        self,
        ref_importances: dict[str, float] | None,
        cur_importances: dict[str, float] | None,
        report: DriftReport,
    ) -> None:
        """Detect SHAP feature importance drift via NDCG."""
        if not ref_importances or not cur_importances:
            report.shap_ndcg = 1.0
            return

        ref_ranking = sorted(ref_importances, key=ref_importances.get, reverse=True)
        cur_ranking = sorted(cur_importances, key=cur_importances.get, reverse=True)

        report.shap_ndcg = compute_ndcg(ref_ranking, cur_ranking)

        report.shap_importance_drift = {}
        for feat in ref_importances:
            ref_val = ref_importances.get(feat, 0)
            cur_val = cur_importances.get(feat, 0)
            if ref_val > 0:
                report.shap_importance_drift[feat] = abs(cur_val - ref_val) / ref_val

    def _run_adwin(
        self,
        error_stream: np.ndarray | None,
        report: DriftReport,
    ) -> None:
        """Run ADWIN online drift detection on prediction errors."""
        if error_stream is None or len(error_stream) < 10:
            return

        try:
            from river.drift import ADWIN

            detector = ADWIN()
            for i, err in enumerate(error_stream):
                detector.update(float(err))
                if detector.drift_detected:
                    report.adwin_triggered = True
                    report.adwin_drift_point = i
                    break
        except ImportError:
            logger.debug("river not installed, skipping ADWIN drift detection")

    def _determine_status(self, report: DriftReport) -> None:
        """Determine overall drift status from individual signals."""
        if (
            report.adwin_triggered
            or report.psi_overall > PSI_CAUTION
            or report.shap_ndcg < SHAP_NDCG_WARNING
        ):
            report.status = "quarantine"
            report.recommendations.append("Stop predictions and retrain immediately")
        elif report.psi_overall > PSI_WARNING or report.shap_ndcg < SHAP_NDCG_HEALTHY:
            report.status = "caution"
            report.recommendations.append("Reduce confidence on predictions; schedule retraining")
        elif report.psi_overall > PSI_HEALTHY or report.ks_flagged_features:
            report.status = "warning"
            report.recommendations.append("Monitor closely; log but continue predictions")
            if report.ks_flagged_features:
                report.recommendations.append(
                    f"Flagged features: {', '.join(report.ks_flagged_features)}"
                )
        else:
            report.status = "healthy"
