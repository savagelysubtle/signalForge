"""Round-trip integration test: train -> save -> load -> predict.

Catches the exact NaN-collapse bug where training uses features that are
unavailable at inference, producing identical predictions for all inputs.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))


def _make_synthetic_dataset(n: int = 500) -> pd.DataFrame:
    """Create a minimal synthetic dataset with known-different features."""
    rng = np.random.default_rng(42)
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "ticker": rng.choice(["AAPL", "MSFT", "GOOG"], n),
            "close": rng.uniform(100, 300, n),
            "strategy_type": "swing",
            "rsi_14": rng.uniform(20, 80, n),
            "adx": rng.uniform(10, 50, n),
            "macd_histogram": rng.normal(0, 0.5, n),
            "volume_ratio": rng.uniform(0.5, 3.0, n),
            "momentum_score": rng.uniform(-0.5, 0.5, n),
            "price_vs_ema_21": rng.normal(0, 2, n),
            "atr_pct": rng.uniform(0.5, 3.0, n),
            "market_regime": rng.choice(["trending_bull", "ranging", "trending_bear"], n),
            "primary_signal": rng.choice(["bullish", "bearish", "neutral"], n),
            "signal_strength": rng.uniform(0, 1, n),
            "day_of_week": rng.integers(0, 7, n),
            "month": rng.integers(1, 13, n),
            "triple_barrier_label": rng.integers(0, 2, n),
            "return_10d": rng.normal(0, 2, n),
        }
    )
    return df


class TestTrainToInference:
    """Verify the full train -> serialize -> load -> predict round trip."""

    def test_round_trip_produces_different_predictions(self):
        """Train a tiny model, save it, load it, and verify distinct predictions."""
        from ml_training.models.predictor import PredictionModel
        from ml_training.models.registry import ModelRegistry

        df = _make_synthetic_dataset()

        model = PredictionModel(
            target_col="triple_barrier_label",
            return_col="return_10d",
            binary_mode=True,
            model_mode="independent",
            inference_only=True,
        )
        result = model.train(df, n_rounds=10)
        assert result.classifier is not None, "Training failed to produce a classifier"
        assert len(result.feature_names) > 0, "No feature names in training result"

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ModelRegistry(artifacts_dir=Path(tmpdir))
            artifact_path = registry.save_artifact(
                classifier=result.classifier,
                regressor=result.regressor,
                label_encoder=result.label_encoder,
                feature_encoders=result.feature_encoders,
                feature_names=result.feature_names,
                strategy_type="swing",
                metrics={"test": True},
            )
            assert Path(artifact_path).exists(), "Artifact was not saved"

            import joblib
            from ml.inference import _to_float, build_feature_vector

            artifact = joblib.load(artifact_path)
            classifier = artifact.classifier
            feature_names = artifact.metadata.feature_names

            features_a = build_feature_vector(
                {
                    "rsi_14": 25.0,
                    "adx": 40.0,
                    "macd_histogram": 0.8,
                    "volume_ratio": 3.0,
                    "momentum_score": 0.7,
                    "price_vs_ema_21": 3.5,
                    "atr_pct": 1.2,
                },
                None,
                {
                    "strategy_type": "swing",
                    "market_regime": "trending_bull",
                    "day_of_week": 2,
                    "month": 4,
                },
            )
            features_b = build_feature_vector(
                {
                    "rsi_14": 75.0,
                    "adx": 12.0,
                    "macd_histogram": -0.6,
                    "volume_ratio": 0.4,
                    "momentum_score": -0.5,
                    "price_vs_ema_21": -4.0,
                    "atr_pct": 3.5,
                },
                None,
                {
                    "strategy_type": "swing",
                    "market_regime": "trending_bear",
                    "day_of_week": 2,
                    "month": 4,
                },
            )

            vec_a = [_to_float(features_a.get(n)) for n in feature_names]
            vec_b = [_to_float(features_b.get(n)) for n in feature_names]

            df_a = pd.DataFrame([vec_a], columns=feature_names)
            df_b = pd.DataFrame([vec_b], columns=feature_names)

            prob_a = classifier.predict_proba(df_a)[0]
            prob_b = classifier.predict_proba(df_b)[0]

            nan_count = sum(1 for v in vec_a if np.isnan(v))
            total = len(vec_a)

            assert nan_count < total * 0.5, (
                f"{nan_count}/{total} features are NaN -- model likely trained on "
                "features unavailable at inference"
            )

            assert not np.array_equal(prob_a, prob_b), (
                f"Identical predictions for very different inputs: "
                f"prob_a={prob_a}, prob_b={prob_b}. "
                "Model is not using the provided features."
            )

    def test_inference_only_excludes_training_features(self):
        """Verify --inference-only models don't include FFD/TSFresh/HMM features."""
        from ml_training.features.feature_spec import TRAINING_ONLY_NAMES, TRAINING_ONLY_PREFIXES
        from ml_training.models.predictor import PredictionModel

        df = _make_synthetic_dataset()
        df["ffd_close"] = np.random.default_rng(0).normal(0, 1, len(df))
        df["hmm_regime"] = 1

        model = PredictionModel(
            target_col="triple_barrier_label",
            return_col="return_10d",
            binary_mode=True,
            model_mode="independent",
            inference_only=True,
        )
        result = model.train(df, n_rounds=5)

        for name in result.feature_names:
            assert name not in TRAINING_ONLY_NAMES, (
                f"Training-only feature '{name}' found in inference-only model"
            )
            for prefix in TRAINING_ONLY_PREFIXES:
                assert not name.startswith(prefix), (
                    f"Training-only prefix feature '{name}' found in inference-only model"
                )
