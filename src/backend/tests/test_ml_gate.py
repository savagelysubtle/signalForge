"""Test ML gate produces distinct probabilities for different TA inputs.

Verifies end-to-end: TechnicalSnapshot → feature mapper → ML model → prediction.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml_training"))


from ml.feature_mapper import build_context_features, map_fmp_to_features, map_multi_tf_to_features
from ml.inference import _to_float, build_feature_vector, ml_model_available, run_prediction
from ml.pre_gpt import build_ml_feature_dicts, run_pre_gpt_gates
from pipeline.schemas import (
    EMASnapshot,
    MACDSnapshot,
    MultiTimeframeTechnical,
    RegimeOutput,
    RSISnapshot,
    TechnicalSnapshot,
    VolumeSnapshot,
)


def _make_snapshot(
    ticker: str,
    price: float,
    rsi: float,
    adx: float,
    macd_hist: float,
    vol_ratio: float,
    momentum: float,
) -> MultiTimeframeTechnical:
    """Build a synthetic MultiTimeframeTechnical with distinct values."""
    return MultiTimeframeTechnical(
        ticker=ticker,
        primary=TechnicalSnapshot(
            ticker=ticker,
            timeframe="5m",
            timestamp="2026-04-11T10:00:00",
            price_current=price,
            price_open=price * 0.99,
            price_high=price * 1.02,
            price_low=price * 0.97,
            rsi=RSISnapshot(current=rsi, previous=rsi - 2, trend="rising", zone="neutral"),
            macd=MACDSnapshot(
                macd_line=0.15,
                signal_line=0.10,
                histogram=macd_hist,
                histogram_slope="expanding" if macd_hist > 0 else "contracting",
                signal_cross="above",
            ),
            adx=adx,
            atr=price * 0.015,
            atr_pct=1.5,
            volume=VolumeSnapshot(
                current=150000, avg_20=100000, ratio=vol_ratio, trend="increasing"
            ),
            emas=[
                EMASnapshot(
                    period=9,
                    current_value=price * 1.005,
                    previous_value=price * 1.003,
                ),
                EMASnapshot(
                    period=21,
                    current_value=price * 0.998,
                    previous_value=price * 0.996,
                ),
                EMASnapshot(
                    period=50,
                    current_value=price * 0.985,
                    previous_value=price * 0.983,
                ),
                EMASnapshot(
                    period=200,
                    current_value=price * 0.960,
                    previous_value=price * 0.958,
                ),
            ],
            momentum_score=momentum,
        ),
    )


REGIME = RegimeOutput(
    regime_type="trending_bull", vix_estimate="normal", breadth_estimate="moderate"
)


class TestFeatureMapper:
    """Verify the mapper produces correct, distinct features."""

    def test_primary_features_extracted(self):
        snap = _make_snapshot("TEST:A", 50.0, 45.2, 25.3, 0.05, 1.5, 0.35)
        features = map_multi_tf_to_features(snap.model_dump())

        assert features["rsi_14"] == 45.2
        assert features["adx"] == 25.3
        assert features["macd_histogram"] == 0.05
        assert features["volume_ratio"] == 1.5
        assert features["momentum_score"] == 0.35

    def test_different_tickers_produce_different_features(self):
        snap_a = _make_snapshot("TEST:A", 50.0, 45.2, 25.3, 0.05, 1.5, 0.35)
        snap_b = _make_snapshot("TEST:B", 10.0, 62.8, 18.1, -0.12, 0.8, -0.15)

        feats_a = map_multi_tf_to_features(snap_a.model_dump())
        feats_b = map_multi_tf_to_features(snap_b.model_dump())

        assert feats_a["rsi_14"] != feats_b["rsi_14"]
        assert feats_a["adx"] != feats_b["adx"]
        assert feats_a["macd_histogram"] != feats_b["macd_histogram"]

    def test_fmp_field_name_mapping(self):
        raw_fmp = {
            "net_profit_margin": 0.08,
            "altman_z_score": 3.2,
            "piotroski_score": 7,
            "price_change_1d": -0.5,
        }
        mapped = map_fmp_to_features(raw_fmp)

        assert mapped["net_margin"] == 0.08
        assert mapped["altman_z"] == 3.2
        assert mapped["piotroski_score"] == 7
        assert mapped["price_change_1d"] == -0.5

    def test_context_includes_temporal(self):
        ctx = build_context_features("intraday_scalp", None)
        assert "day_of_week" in ctx
        assert "month" in ctx
        assert 0 <= ctx["day_of_week"] <= 6
        assert 1 <= ctx["month"] <= 12


class TestFeatureVectorIntegrity:
    """Verify the feature vector reaching the model has correct numeric values."""

    def test_feature_vector_has_distinct_numerics(self):
        snap_a = _make_snapshot("TEST:A", 50.0, 45.2, 25.3, 0.05, 1.5, 0.35)
        snap_b = _make_snapshot("TEST:B", 10.0, 62.8, 18.1, -0.12, 0.8, -0.15)

        ta_a = map_multi_tf_to_features(snap_a.model_dump())
        ta_b = map_multi_tf_to_features(snap_b.model_dump())

        ctx = build_context_features(
            "intraday_scalp",
            {"regime_type": "trending_bull", "vix_estimate": 18.5, "breadth_estimate": 0.55},
        )

        vec_a = build_feature_vector(ta_a, None, ctx)
        vec_b = build_feature_vector(ta_b, None, ctx)

        assert _to_float(vec_a["rsi_14"]) == 45.2
        assert _to_float(vec_b["rsi_14"]) == 62.8
        assert _to_float(vec_a["adx"]) == 25.3
        assert _to_float(vec_b["adx"]) == 18.1


@pytest.mark.skipif(
    not ml_model_available("intraday_scalp", mode="independent"),
    reason="No intraday_scalp model artifact available",
)
class TestMLPredictionDivergence:
    """Verify the ML model produces different outputs for different inputs."""

    def test_raw_prediction_diverges(self):
        """Feed two very different feature sets and check predictions differ.

        NOTE: Will FAIL until models are retrained with inference-only features.
        Current models depend on TSFresh/FFD/HMM features unavailable at inference.
        """
        import numpy as np

        snap_a = _make_snapshot("TEST:A", 50.0, 25.0, 35.0, 0.50, 3.0, 0.80)
        snap_b = _make_snapshot("TEST:B", 10.0, 75.0, 12.0, -0.40, 0.3, -0.70)

        ta_a = map_multi_tf_to_features(snap_a.model_dump())
        ta_b = map_multi_tf_to_features(snap_b.model_dump())

        ctx = build_context_features(
            "intraday_scalp",
            {"regime_type": "trending_bull", "vix_estimate": 18.5, "breadth_estimate": 0.55},
        )

        vec_a = build_feature_vector(ta_a, None, ctx)
        vec_b = build_feature_vector(ta_b, None, ctx)

        pred_a = run_prediction("TEST:A", "intraday_scalp", vec_a, mode="independent")
        pred_b = run_prediction("TEST:B", "intraday_scalp", vec_b, mode="independent")

        assert pred_a is not None, "Model returned None for TEST:A"
        assert pred_b is not None, "Model returned None for TEST:B"

        prob_a = pred_a.probability_profitable or pred_a.probability_up
        prob_b = pred_b.probability_profitable or pred_b.probability_up

        print(f"\nTEST:A prob={prob_a:.6f} (RSI=25, ADX=35, MACD=+0.50, Vol=3.0x)")
        print(f"TEST:B prob={prob_b:.6f} (RSI=75, ADX=12, MACD=-0.40, Vol=0.3x)")
        print(f"Delta: {abs(prob_a - prob_b):.6f}")

        # Inspect what model actually received
        from ml.inference import _get_model

        model = _get_model("intraday_scalp", mode="independent")
        feat_names = model["feature_names"]

        print(f"\nFeature vector comparison ({len(feat_names)} features):")
        for name in feat_names:
            va = _to_float(vec_a.get(name))
            vb = _to_float(vec_b.get(name))
            nan_a = np.isnan(va)
            nan_b = np.isnan(vb)
            if nan_a and nan_b:
                status = "BOTH NaN"
            elif va != vb:
                status = f"DIFFERS: {va} vs {vb}"
            else:
                status = f"SAME: {va}"
            print(f"  {name:30s} {status}")

        if prob_a == prob_b:
            pytest.fail(
                f"Model returned identical probabilities {prob_a:.6f} for very different inputs. "
                "This suggests the model ignores the provided features."
            )

    @pytest.mark.asyncio
    async def test_gate_produces_distinct_probabilities(self):
        """End-to-end: build_ml_feature_dicts → run_pre_gpt_gates → distinct results.

        NOTE: This test will FAIL until models are retrained with only
        inference-available features. Current models use TSFresh/FFD/HMM
        features that are NaN at inference, causing identical tree paths.
        """
        snapshots = [
            _make_snapshot("TEST:A", 50.0, 25.0, 35.0, 0.50, 3.0, 0.80),
            _make_snapshot("TEST:B", 10.0, 75.0, 12.0, -0.40, 0.3, -0.70),
            _make_snapshot("TEST:C", 200.0, 50.0, 22.0, 0.01, 1.0, 0.00),
        ]
        ta_pre, fmp_pre, regime_pre = build_ml_feature_dicts(snapshots, None, REGIME)
        results = await run_pre_gpt_gates(
            ["TEST:A", "TEST:B", "TEST:C"],
            "intraday_scalp",
            ta_pre,
            fmp_pre,
            regime_pre,
        )

        probs = {t: g.ml_probability for t, g in results.items()}
        print(f"\nGate results: {probs}")

        unique_probs = set(probs.values())
        if len(unique_probs) == 1:
            pytest.fail(
                f"All 3 tickers got identical probability {unique_probs.pop():.6f}. "
                "The model is not using per-ticker features — retrain with "
                "inference-available features only."
            )
