"""ML-powered confidence calibration service.

Replaces the deterministic confidence_calibration.py with ML model
inference when a trained model is available. Falls back to the
existing deterministic calibration when no model is loaded.
"""

from __future__ import annotations

import logging
from typing import Any

from ml.inference import build_feature_vector, ml_model_available, run_prediction

logger = logging.getLogger(__name__)


async def calibrate_with_ml(
    recommendations: list[dict[str, Any]],
    ta_snapshots: dict[str, dict[str, Any]] | None = None,
    fmp_data: dict[str, dict[str, Any]] | None = None,
    strategy_type: str = "swing",
    regime_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Apply ML-based confidence calibration to recommendations.

    When a trained ML model is available, uses the model's calibrated
    probabilities to adjust the confidence score on each recommendation.
    Otherwise returns recommendations unchanged.

    Args:
        recommendations: List of recommendation dicts from GPT.
        ta_snapshots: Technical analysis features per ticker.
        fmp_data: Fundamental data per ticker.
        strategy_type: Strategy template type.
        regime_context: Market regime context.

    Returns:
        Updated recommendations with ML-calibrated confidence.
    """
    if not ml_model_available():
        return recommendations

    for rec in recommendations:
        ticker = rec.get("ticker", "")
        if not ticker:
            continue

        ta_features: dict[str, float | None] = {}
        if ta_snapshots and ticker in ta_snapshots:
            ta_features = ta_snapshots[ticker]

        fund_features: dict[str, float | None] = {}
        if fmp_data and ticker in fmp_data:
            fund_features = fmp_data[ticker]

        context = {
            "strategy_type": strategy_type,
            "market_regime": (
                regime_context.get("regime_type", "unknown") if regime_context else "unknown"
            ),
            "vix_level": regime_context.get("vix_estimate") if regime_context else None,
        }

        features = build_feature_vector(ta_features, fund_features, context)
        prediction = run_prediction(ticker, strategy_type, features)

        if prediction is None:
            continue

        rec["ml_confidence"] = prediction.probability_up
        rec["ml_direction"] = prediction.predicted_direction
        rec["ml_reliability"] = prediction.reliability_score
        rec["ml_prediction_set"] = prediction.prediction_set
        rec["ml_predicted_return"] = prediction.predicted_return_pct

        action = rec.get("action", "")
        gpt_confidence = rec.get("confidence", 0.5)

        if action in ("BUY", "WATCH") and prediction.predicted_direction == "UP":
            rec["confidence"] = gpt_confidence * 0.6 + prediction.probability_up * 0.4
        elif action in ("SHORT",) and prediction.predicted_direction == "DOWN":
            rec["confidence"] = gpt_confidence * 0.6 + prediction.probability_down * 0.4
        elif prediction.predicted_direction != _action_to_direction(action):
            rec["confidence"] = gpt_confidence * 0.7
            if "warnings" not in rec:
                rec["warnings"] = []
            rec["warnings"].append(
                f"ML model disagrees: predicts {prediction.predicted_direction} "
                f"(reliability={prediction.reliability_score:.2f})"
            )

        rec["confidence_breakdown"] = {
            "gpt_base": gpt_confidence,
            "ml_calibrated": prediction.probability_up,
            "ml_reliability": prediction.reliability_score,
            "prediction_set_size": len(prediction.prediction_set),
        }

    return recommendations


def _action_to_direction(action: str) -> str:
    """Map GPT action to expected direction."""
    mapping = {
        "BUY": "UP",
        "WATCH": "UP",
        "SHORT": "DOWN",
        "HOLD": "FLAT",
        "NO_TRADE": "FLAT",
    }
    return mapping.get(action, "FLAT")
