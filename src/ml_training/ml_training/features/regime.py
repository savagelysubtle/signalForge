"""HMM-based market regime detection for ML training pipeline.

This module provides a Gaussian Hidden Markov Model to classify market states
(bear/neutral/bull) based on VIX volatility, market breadth, and momentum indicators.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import joblib
import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from numpy.typing import NDArray

try:
    from hmmlearn.hmm import GaussianHMM

    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False
    GaussianHMM = None


class RegimeDetector:
    """Market regime detector using Hidden Markov Model.

    Classifies market conditions into three regimes (bear/neutral/bull) based on:
    - VIX volatility returns
    - Market breadth (advance/decline ratio)
    - Price momentum (SPY 20-day returns)

    The HMM learns latent states from these features and reorders them so that
    state 0 = bear market (highest VIX), state 2 = bull market (lowest VIX).

    Attributes:
        n_regimes: Number of hidden states (default 3).
        random_state: Random seed for reproducibility.
        model: Fitted GaussianHMM instance (None until fit).
        state_order: Mapping from fitted states to semantic labels (None until fit).
    """

    def __init__(self, n_regimes: int = 3, random_state: int = 42) -> None:
        """Initialize regime detector.

        Args:
            n_regimes: Number of market regimes to detect (default 3).
            random_state: Random seed for HMM initialization.

        Raises:
            ImportError: If hmmlearn is not installed.
        """
        if not HMM_AVAILABLE:
            raise ImportError(
                "hmmlearn is required for regime detection. Install with: uv add hmmlearn"
            )

        self.n_regimes = n_regimes
        self.random_state = random_state
        self.model: GaussianHMM | None = None
        self.state_order: NDArray[np.int_] | None = None

    def fit(
        self,
        vix_returns: NDArray[np.float64],
        breadth: NDArray[np.float64],
        momentum: NDArray[np.float64],
    ) -> RegimeDetector:
        """Fit HMM to market regime features.

        Args:
            vix_returns: Daily VIX returns (volatility changes).
            breadth: Market breadth ratio (advancing / total stocks).
            momentum: Price momentum (e.g., SPY 20-day returns).

        Returns:
            Self, to allow method chaining.

        Raises:
            ValueError: If input arrays have different lengths or insufficient data.
        """
        if not (len(vix_returns) == len(breadth) == len(momentum)):
            raise ValueError("All feature arrays must have the same length")

        features = np.column_stack([vix_returns, breadth, momentum])

        features = self._handle_nan(features)

        if len(features) < self.n_regimes * 10:
            raise ValueError(
                f"Insufficient data: need at least {self.n_regimes * 10} samples, "
                f"got {len(features)}"
            )

        self.model = GaussianHMM(
            n_components=self.n_regimes,
            covariance_type="full",
            n_iter=100,
            random_state=self.random_state,
        )

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            self.model.fit(features)

        self._reorder_states_by_vix(features)

        return self

    def predict(self, features: NDArray[np.float64]) -> NDArray[np.int_]:
        """Predict regime labels for input features.

        Args:
            features: Feature matrix (n_samples, 3) with columns [vix_returns, breadth, momentum].

        Returns:
            Array of regime labels (0=bear, 1=neutral, 2=bull).

        Raises:
            RuntimeError: If model has not been fitted.
        """
        if self.model is None or self.state_order is None:
            raise RuntimeError("Model must be fitted before prediction")

        features = self._handle_nan(features)
        raw_states = self.model.predict(features)
        return self.state_order[raw_states]

    def predict_proba(self, features: NDArray[np.float64]) -> NDArray[np.float64]:
        """Predict regime probabilities for input features.

        Args:
            features: Feature matrix (n_samples, 3) with columns [vix_returns, breadth, momentum].

        Returns:
            Probability matrix (n_samples, n_regimes) where each row sums to 1.0.
            Columns correspond to [bear, neutral, bull] probabilities.

        Raises:
            RuntimeError: If model has not been fitted.
        """
        if self.model is None or self.state_order is None:
            raise RuntimeError("Model must be fitted before prediction")

        features = self._handle_nan(features)
        raw_probs = self.model.predict_proba(features)

        reordered_probs = np.zeros_like(raw_probs)
        for original_idx, semantic_idx in enumerate(self.state_order):
            reordered_probs[:, semantic_idx] = raw_probs[:, original_idx]

        return reordered_probs

    def regime_names(self) -> list[str]:
        """Get semantic names for regime labels.

        Returns:
            List of regime names corresponding to labels [0, 1, 2].
        """
        return ["bear", "neutral", "bull"]

    def save(self, path: Path) -> None:
        """Serialize detector to disk.

        Args:
            path: Output file path (e.g., 'regime_detector.joblib').

        Raises:
            RuntimeError: If model has not been fitted.
        """
        if self.model is None:
            raise RuntimeError("Cannot save unfitted model")

        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": self.model,
                "state_order": self.state_order,
                "n_regimes": self.n_regimes,
                "random_state": self.random_state,
            },
            path,
        )

    @classmethod
    def load(cls, path: Path) -> RegimeDetector:
        """Deserialize detector from disk.

        Args:
            path: Path to saved detector file.

        Returns:
            Loaded RegimeDetector instance.

        Raises:
            FileNotFoundError: If path does not exist.
            ImportError: If hmmlearn is not installed.
        """
        if not HMM_AVAILABLE:
            raise ImportError(
                "hmmlearn is required to load saved regime detector. Install with: uv add hmmlearn"
            )

        data = joblib.load(path)
        detector = cls(n_regimes=data["n_regimes"], random_state=data["random_state"])
        detector.model = data["model"]
        detector.state_order = data["state_order"]
        return detector

    def _handle_nan(self, features: NDArray[np.float64]) -> NDArray[np.float64]:
        """Handle NaN values by forward-filling then dropping remaining NaN.

        Args:
            features: Feature matrix potentially containing NaN.

        Returns:
            Cleaned feature matrix.
        """
        df = pd.DataFrame(features)
        df = df.ffill().dropna()
        return df.to_numpy()

    def _reorder_states_by_vix(self, features: NDArray[np.float64]) -> None:
        """Reorder HMM states so that state 0 = bear, state 2 = bull.

        Bear markets have high VIX returns (increasing volatility).
        Bull markets have low/negative VIX returns (decreasing volatility).

        Args:
            features: Feature matrix used for fitting (needed to compute state means).
        """
        if self.model is None:
            raise RuntimeError("Model must be fitted before reordering states")

        states = self.model.predict(features)
        vix_returns = features[:, 0]

        state_vix_means = []
        for state_id in range(self.n_regimes):
            mask = states == state_id
            if mask.sum() > 0:
                state_vix_means.append(vix_returns[mask].mean())
            else:
                state_vix_means.append(0.0)

        sorted_indices = np.argsort(state_vix_means)[::-1]
        self.state_order = np.empty(self.n_regimes, dtype=np.int_)
        for semantic_label, original_state in enumerate(sorted_indices):
            self.state_order[original_state] = semantic_label


def compute_regime_features(
    vix_prices: pd.DataFrame,
    spy_prices: pd.DataFrame,
    breadth_cache: dict[str, float],
) -> pd.DataFrame:
    """Compute input features for regime detection.

    Transforms raw VIX/SPY prices and breadth data into the three features
    needed by RegimeDetector: VIX returns, market breadth, and momentum.

    Args:
        vix_prices: DataFrame with columns ['date', 'close'] for VIX.
        spy_prices: DataFrame with columns ['date', 'close'] for SPY.
        breadth_cache: Dict mapping date strings (YYYY-MM-DD) to breadth ratios
            (advancing_stocks / total_stocks).

    Returns:
        DataFrame with columns ['date', 'vix_return', 'breadth', 'momentum'].
        Dates are aligned across all three features.

    Example:
        >>> vix_df = pd.DataFrame({'date': [...], 'close': [...]})
        >>> spy_df = pd.DataFrame({'date': [...], 'close': [...]})
        >>> breadth = {'2024-01-01': 0.65, '2024-01-02': 0.72, ...}
        >>> features = compute_regime_features(vix_df, spy_df, breadth)
    """
    vix_df = vix_prices.copy()
    vix_df["vix_return"] = vix_df["close"].pct_change()

    spy_df = spy_prices.copy()
    spy_df["spy_momentum"] = spy_df["close"].pct_change(periods=20)

    breadth_df = pd.DataFrame(
        list(breadth_cache.items()),
        columns=["date", "breadth"],
    )
    breadth_df["date"] = pd.to_datetime(breadth_df["date"])

    features = vix_df[["date", "vix_return"]].merge(breadth_df, on="date", how="inner")
    features = features.merge(
        spy_df[["date", "spy_momentum"]], on="date", how="inner", suffixes=("", "_spy")
    )

    features = features.rename(columns={"spy_momentum": "momentum"})
    features = features[["date", "vix_return", "breadth", "momentum"]]

    return features.dropna()
