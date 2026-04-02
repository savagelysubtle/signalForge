"""Walk-Forward Optimization validator: CPCV integrity, purge/embargo checks, DSR.

Validates the training process itself -- ensures no data leakage,
proper purging and embargo, acceptable overfit levels, and that
performance is statistically significant via Deflated Sharpe Ratio.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from scipy import stats as sp_stats

logger = logging.getLogger(__name__)

OVERFIT_GAP_LOW = 0.10
OVERFIT_GAP_MEDIUM = 0.15
DSR_THRESHOLD = 0.95


@dataclass
class WFOValidationResult:
    """Results from WFO/CPCV validation."""

    wfo_integrity: Literal["clean", "leakage_detected", "insufficient_folds"] = "clean"
    purge_verified: bool = True
    embargo_verified: bool = True
    overfit_risk: Literal["low", "medium", "high"] = "low"
    insample_vs_oos_gap: float = 0.0
    fold_accuracies: list[float] = field(default_factory=list)
    fold_variance: float = 0.0
    regime_coverage: list[str] = field(default_factory=list)
    regime_gaps: list[str] = field(default_factory=list)
    deflated_sharpe_probability: float = 0.0
    warnings: list[str] = field(default_factory=list)


def compute_deflated_sharpe_ratio(
    sharpe_ratio: float,
    n_observations: int,
    n_trials: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Compute the Deflated Sharpe Ratio probability.

    Corrects the observed Sharpe Ratio for:
    - Multiple testing (selection from n_trials)
    - Non-normal returns (skewness, excess kurtosis)

    Args:
        sharpe_ratio: Observed Sharpe Ratio.
        n_observations: Number of return observations.
        n_trials: Number of hyperparameter/model configurations tried.
        skewness: Skewness of returns.
        kurtosis: Kurtosis of returns (3.0 = normal).

    Returns:
        Probability (0-1) that the Sharpe Ratio is genuine. Target: > 0.95.
    """
    if n_observations <= 1 or n_trials <= 0:
        return 0.0

    euler_mascheroni = 0.5772156649
    expected_max_sr = (1 - euler_mascheroni) * sp_stats.norm.ppf(
        1 - 1 / n_trials
    ) + euler_mascheroni * sp_stats.norm.ppf(1 - 1 / (n_trials * np.e))

    excess_kurtosis = kurtosis - 3.0
    sr_std = np.sqrt(
        (1 - skewness * sharpe_ratio + (excess_kurtosis / 4) * sharpe_ratio**2)
        / (n_observations - 1)
    )

    if sr_std <= 0:
        return 1.0 if sharpe_ratio > expected_max_sr else 0.0

    z = (sharpe_ratio - expected_max_sr) / sr_std
    return float(sp_stats.norm.cdf(z))


class WFOValidator:
    """Validates the Walk-Forward Optimization process.

    Checks data leakage, overfit levels, regime coverage, and
    statistical significance of performance.
    """

    def __init__(
        self,
        purge_window: int = 200,
        embargo_window: int = 5,
        n_trials: int = 1,
    ) -> None:
        self._purge_window = purge_window
        self._embargo_window = embargo_window
        self._n_trials = n_trials

    def validate(
        self,
        fold_results: list[dict[str, Any]],
        train_accuracies: list[float] | None = None,
        test_accuracies: list[float] | None = None,
        fold_returns: list[np.ndarray] | None = None,
        regime_labels: list[str] | None = None,
    ) -> WFOValidationResult:
        """Run all WFO validation checks.

        Args:
            fold_results: List of dicts with fold details (train_indices, test_indices, etc.).
            train_accuracies: In-sample accuracy per fold.
            test_accuracies: Out-of-sample accuracy per fold.
            fold_returns: Per-fold return series for DSR computation.
            regime_labels: Market regime labels per fold.

        Returns:
            WFOValidationResult with all checks.
        """
        result = WFOValidationResult()

        if len(fold_results) < 3:
            result.wfo_integrity = "insufficient_folds"
            result.warnings.append(f"Only {len(fold_results)} folds (minimum 3 recommended)")

        self._check_leakage(fold_results, result)
        self._check_overfit(train_accuracies, test_accuracies, result)
        self._check_regime_coverage(regime_labels, result)
        self._compute_dsr(test_accuracies, fold_returns, result)

        return result

    def _check_leakage(
        self,
        fold_results: list[dict[str, Any]],
        result: WFOValidationResult,
    ) -> None:
        """Verify purging and embargo are correctly applied."""
        for i, fold in enumerate(fold_results):
            train_idx = fold.get("train_indices")
            test_idx = fold.get("test_indices")

            if train_idx is None or test_idx is None:
                continue

            train_idx = np.asarray(train_idx)
            test_idx = np.asarray(test_idx)

            if len(train_idx) == 0 or len(test_idx) == 0:
                continue

            train_max = train_idx.max()
            test_min = test_idx.min()
            gap = test_min - train_max

            if gap < 1:
                result.wfo_integrity = "leakage_detected"
                result.purge_verified = False
                result.warnings.append(f"Fold {i}: train/test overlap detected (gap={gap})")

            if gap < self._embargo_window:
                result.embargo_verified = False
                result.warnings.append(
                    f"Fold {i}: embargo too small (gap={gap}, required={self._embargo_window})"
                )

            purge_violations = np.sum(
                (train_idx >= test_min - self._purge_window) & (train_idx < test_min)
            )
            if purge_violations > 0:
                result.purge_verified = False
                result.warnings.append(
                    f"Fold {i}: {purge_violations} training samples within purge window"
                )

    def _check_overfit(
        self,
        train_accs: list[float] | None,
        test_accs: list[float] | None,
        result: WFOValidationResult,
    ) -> None:
        """Check for overfitting by comparing in-sample vs out-of-sample."""
        if not train_accs or not test_accs:
            return

        result.fold_accuracies = test_accs
        result.fold_variance = float(np.var(test_accs))

        mean_train = float(np.mean(train_accs))
        mean_test = float(np.mean(test_accs))
        gap = mean_train - mean_test
        result.insample_vs_oos_gap = gap

        if gap > OVERFIT_GAP_MEDIUM:
            result.overfit_risk = "high"
            result.warnings.append(f"High overfit risk: gap={gap:.1%}")
        elif gap > OVERFIT_GAP_LOW:
            result.overfit_risk = "medium"
            result.warnings.append(f"Medium overfit risk: gap={gap:.1%}")
        else:
            result.overfit_risk = "low"

    def _check_regime_coverage(
        self,
        regime_labels: list[str] | None,
        result: WFOValidationResult,
    ) -> None:
        """Verify test folds span different market regimes."""
        all_regimes = {"bull", "bear", "ranging", "high_vol", "low_vol"}

        if not regime_labels:
            result.regime_gaps = list(all_regimes)
            result.warnings.append("No regime labels available for coverage check")
            return

        covered = set(regime_labels)
        result.regime_coverage = sorted(covered)
        result.regime_gaps = sorted(all_regimes - covered)

        if result.regime_gaps:
            result.warnings.append(f"Untested market regimes: {', '.join(result.regime_gaps)}")

    def _compute_dsr(
        self,
        test_accs: list[float] | None,
        fold_returns: list[np.ndarray] | None,
        result: WFOValidationResult,
    ) -> None:
        """Compute Deflated Sharpe Ratio."""
        if fold_returns and any(len(r) > 0 for r in fold_returns):
            all_returns = np.concatenate([r for r in fold_returns if len(r) > 0])
            if len(all_returns) > 1:
                sharpe = (
                    float(all_returns.mean() / all_returns.std()) if all_returns.std() > 0 else 0.0
                )
                skew = float(sp_stats.skew(all_returns))
                kurt = float(sp_stats.kurtosis(all_returns) + 3)
                result.deflated_sharpe_probability = compute_deflated_sharpe_ratio(
                    sharpe, len(all_returns), self._n_trials, skew, kurt
                )
                return

        if test_accs and len(test_accs) >= 2:
            arr = np.array(test_accs)
            if arr.std() > 0:
                pseudo_sharpe = float((arr.mean() - 0.5) / arr.std())
                result.deflated_sharpe_probability = compute_deflated_sharpe_ratio(
                    pseudo_sharpe, len(arr), self._n_trials
                )
