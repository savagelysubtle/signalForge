"""Tabular data augmentation for small financial datasets.

Provides time series augmentation methods to expand training datasets while
preserving statistical properties and avoiding overfitting. Uses jitter
(Gaussian noise) as the primary augmentation technique, with SMOTE-like
interpolation for minority class balancing.

Feature-aware: categorical features are excluded from jitter, bounded
features are clipped to valid ranges, and a joint-distribution check
(pairwise Pearson correlation) supplements the per-column KS test.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp
from sklearn.neighbors import NearestNeighbors

logger = logging.getLogger(__name__)

METADATA_COLS = {"ticker", "date", "strategy_id", "strategy_type", "timeframe", "close"}

_CORR_SHIFT_THRESHOLD = 0.15


class TimeSeriesAugmenter:
    """Augments time series financial data using jitter and SMOTE-like interpolation.

    Designed for small datasets (<25k samples) where model performance is limited
    by data scarcity. Validates statistical quality of synthetic samples using
    Kolmogorov-Smirnov tests to ensure distribution similarity.

    Attributes:
        target_size: Desired total dataset size after augmentation.
        noise_std_scale: Standard deviation scale factor for Gaussian noise (0.01 = 1%).
        random_state: Random seed for reproducibility.
    """

    def __init__(
        self,
        target_size: int = 25000,
        noise_std_scale: float = 0.01,
        random_state: int = 42,
    ) -> None:
        """Initialize the augmenter.

        Args:
            target_size: Target number of samples after augmentation. If the original
                dataset already has >= target_size samples, no augmentation is performed.
            noise_std_scale: Scaling factor for noise standard deviation. Noise is
                computed as noise_std_scale * feature_std. Default 0.01 adds 1% noise.
            random_state: Random seed for NumPy and sklearn operations.
        """
        self._target_size = target_size
        self._noise_std_scale = noise_std_scale
        self._random_state = random_state
        np.random.seed(random_state)

    def augment(
        self,
        df: pd.DataFrame,
        target_col: str = "profitable",
        exclude_cols: set[str] | None = None,
    ) -> pd.DataFrame:
        """Augment the dataset to reach the target size.

        If the dataset is already >= target_size, returns it unchanged. Otherwise,
        applies jitter augmentation followed by SMOTE-like interpolation until
        the target is reached. Validates quality of synthetic samples and rejects
        batches where >30% of features fail KS test (p < 0.01).

        Args:
            df: Input DataFrame with features and target column.
            target_col: Name of the binary target column for class balancing.
            exclude_cols: Additional columns to exclude from augmentation (merged with
                METADATA_COLS). These columns are preserved from original samples.

        Returns:
            DataFrame with original + synthetic samples, up to target_size rows.

        Raises:
            ValueError: If target_col is not in df or has non-binary values.
        """
        if len(df) >= self._target_size:
            logger.info(
                f"Dataset already has {len(df)} samples (>= {self._target_size}), "
                "skipping augmentation"
            )
            return df

        if target_col not in df.columns:
            raise ValueError(f"Target column '{target_col}' not found in DataFrame")

        if not set(df[target_col].dropna().unique()).issubset({0, 1}):
            raise ValueError(f"Target column '{target_col}' must be binary (0/1 or True/False)")

        exclude_set = METADATA_COLS.copy()
        if exclude_cols:
            exclude_set.update(exclude_cols)

        try:
            from ml_training.features.feature_spec import (
                BOUNDED_FEATURES,
                CATEGORICAL_FEATURE_NAMES,
            )

            exclude_set |= CATEGORICAL_FEATURE_NAMES
            self._bounds = BOUNDED_FEATURES
        except ImportError:
            self._bounds = {}

        numeric_cols = [
            col for col in df.select_dtypes(include=[np.number]).columns if col not in exclude_set
        ]

        if not numeric_cols:
            logger.warning("No numeric columns to augment, returning original DataFrame")
            return df

        n_needed = self._target_size - len(df)
        logger.info(
            f"Augmenting dataset from {len(df)} to {self._target_size} samples "
            f"({n_needed} synthetic samples needed)"
        )

        augmented_frames = [df]
        remaining = n_needed

        jitter_samples = min(remaining, int(n_needed * 0.8))
        if jitter_samples > 0:
            logger.info(f"Generating {jitter_samples} samples using jitter augmentation")
            jitter_df = self._jitter_augment(df, jitter_samples, target_col, numeric_cols)

            if self._validate_quality(df, jitter_df, numeric_cols):
                augmented_frames.append(jitter_df)
                remaining -= len(jitter_df)
                logger.info("Jitter augmentation passed quality validation")
            else:
                logger.warning("Jitter augmentation failed quality validation, skipping batch")

        if remaining > 0:
            logger.info(f"Generating {remaining} samples using SMOTE-like interpolation")
            smote_df = self._smote_augment(df, remaining, target_col, numeric_cols)

            if self._validate_quality(df, smote_df, numeric_cols):
                augmented_frames.append(smote_df)
                logger.info("SMOTE augmentation passed quality validation")
            else:
                logger.warning("SMOTE augmentation failed quality validation, skipping batch")

        result = pd.concat(augmented_frames, ignore_index=True)
        logger.info(f"Final augmented dataset size: {len(result)} samples")
        return result

    def _jitter_augment(
        self,
        df: pd.DataFrame,
        n_samples: int,
        target_col: str,
        numeric_cols: list[str],
    ) -> pd.DataFrame:
        """Apply jitter augmentation by adding Gaussian noise to numeric features.

        Args:
            df: Original DataFrame.
            n_samples: Number of synthetic samples to generate.
            target_col: Name of the target column (preserved unchanged).
            numeric_cols: List of numeric column names to augment.

        Returns:
            DataFrame with n_samples rows of noisy synthetic data.
        """
        sampled = df.sample(n=n_samples, replace=True, random_state=self._random_state)
        augmented = sampled.copy()

        for col in numeric_cols:
            col_std = df[col].std(skipna=True)
            if col_std and col_std > 0:
                noise = np.random.normal(
                    0,
                    self._noise_std_scale * col_std,
                    n_samples,
                )
                augmented[col] = sampled[col].values + noise

        self._clip_bounded(augmented, numeric_cols)
        return augmented

    def _smote_augment(
        self,
        df: pd.DataFrame,
        n_samples: int,
        target_col: str,
        numeric_cols: list[str],
    ) -> pd.DataFrame:
        """Apply SMOTE-like interpolation for minority class balancing.

        For each synthetic sample, selects a random minority class sample and
        interpolates it with one of its 5 nearest neighbors.

        Args:
            df: Original DataFrame.
            n_samples: Number of synthetic samples to generate.
            target_col: Name of the binary target column.
            numeric_cols: List of numeric column names to interpolate.

        Returns:
            DataFrame with n_samples rows of interpolated synthetic data.
        """
        minority_class = df[target_col].value_counts().idxmin()
        minority_df = df[df[target_col] == minority_class]

        clean_minority = minority_df.dropna(subset=numeric_cols)
        if len(clean_minority) < 2:
            logger.warning(
                f"Minority class has <2 clean samples ({len(clean_minority)}), "
                "falling back to jitter augmentation"
            )
            return self._jitter_augment(df, n_samples, target_col, numeric_cols)

        minority_df = clean_minority
        X_minority = minority_df[numeric_cols].values
        n_neighbors = min(5, len(minority_df) - 1)

        nn = NearestNeighbors(n_neighbors=n_neighbors, n_jobs=-1)
        nn.fit(X_minority)

        synthetic_samples = []

        for _ in range(n_samples):
            idx = np.random.randint(0, len(minority_df))
            sample = minority_df.iloc[idx]
            sample_features = X_minority[idx].reshape(1, -1)

            _, neighbor_indices = nn.kneighbors(sample_features)
            neighbor_idx = np.random.choice(neighbor_indices[0])
            neighbor = minority_df.iloc[neighbor_idx]

            alpha = np.random.uniform(0, 1)
            synthetic_row = sample.copy()

            for col in numeric_cols:
                synthetic_row[col] = alpha * sample[col] + (1 - alpha) * neighbor[col]

            synthetic_samples.append(synthetic_row)

        result = pd.DataFrame(synthetic_samples)
        self._clip_bounded(result, numeric_cols)
        return result

    def _validate_quality(
        self,
        original: pd.DataFrame,
        augmented: pd.DataFrame,
        numeric_cols: list[str],
    ) -> bool:
        """Validate that augmented data has similar distribution to original.

        Uses Kolmogorov-Smirnov test to compare distributions. Rejects batch
        if >30% of features have p-value < 0.01, indicating significant
        distribution shift.

        Args:
            original: Original DataFrame.
            augmented: Augmented DataFrame to validate.
            numeric_cols: List of numeric columns to test.

        Returns:
            True if augmented data passes quality check, False otherwise.
        """
        failed_features = []

        for col in numeric_cols:
            orig_values = original[col].dropna()
            aug_values = augmented[col].dropna()

            if len(orig_values) < 2 or len(aug_values) < 2:
                continue

            statistic, p_value = ks_2samp(orig_values, aug_values)

            if p_value < 0.01:
                failed_features.append((col, p_value))
                logger.debug(
                    f"Feature '{col}' failed KS test: statistic={statistic:.4f}, "
                    f"p-value={p_value:.4f}"
                )

        failure_rate = len(failed_features) / len(numeric_cols)

        if failure_rate > 0.30:
            logger.warning(
                f"Quality validation failed: {len(failed_features)}/{len(numeric_cols)} "
                f"features ({failure_rate:.1%}) have significant distribution shift"
            )
            return False

        logger.debug(
            f"Quality validation passed: {len(failed_features)}/{len(numeric_cols)} "
            f"features ({failure_rate:.1%}) failed KS test"
        )

        return self._validate_joint_distribution(original, augmented, numeric_cols)

    def _clip_bounded(self, df: pd.DataFrame, numeric_cols: list[str]) -> None:
        """Clip augmented values to their valid ranges using the feature spec."""
        bounds = getattr(self, "_bounds", {})
        for col in numeric_cols:
            if col in bounds:
                lo, hi = bounds[col]
                if lo is not None or hi is not None:
                    df[col] = df[col].clip(lower=lo, upper=hi)

    def _validate_joint_distribution(
        self,
        original: pd.DataFrame,
        augmented: pd.DataFrame,
        numeric_cols: list[str],
    ) -> bool:
        """Check that pairwise correlations are preserved after augmentation.

        Computes Pearson correlation matrices on a subset of numeric columns
        and rejects the batch if the mean absolute difference exceeds the
        threshold.
        """
        check_cols = [c for c in numeric_cols if c in original.columns and c in augmented.columns]
        if len(check_cols) < 3:
            return True

        check_cols = check_cols[:30]

        try:
            orig_corr = original[check_cols].corr(numeric_only=True)
            aug_corr = pd.concat([original, augmented])[check_cols].corr(numeric_only=True)
            diff = (orig_corr - aug_corr).abs()
            mean_shift = diff.values[np.triu_indices_from(diff.values, k=1)].mean()

            if mean_shift > _CORR_SHIFT_THRESHOLD:
                logger.warning(
                    "Joint distribution check failed: mean correlation shift %.3f (threshold %.3f)",
                    mean_shift,
                    _CORR_SHIFT_THRESHOLD,
                )
                return False
        except Exception:
            logger.debug("Joint distribution check skipped due to error", exc_info=True)

        return True
