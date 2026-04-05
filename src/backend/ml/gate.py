"""ML gate — independent model that runs before GPT output is finalized.

Uses a LightGBM model trained without any LLM-derived features so its
probability estimate is truly independent of GPT.  The gate adjusts
position sizing and can block recommendations that the model assigns
low probability to.
"""

from __future__ import annotations

import logging
from typing import Any

from ml.inference import build_feature_vector, ml_model_available, run_prediction
from ml.schemas import GateResult

logger = logging.getLogger(__name__)

# Probability thresholds → position size multipliers.
# These should be tuned once 50+ resolved outcomes are available.
_SIZE_TIERS: list[tuple[float, float]] = [
    (0.65, 1.00),
    (0.58, 0.75),
    (0.52, 0.50),
]
_BLOCK_THRESHOLD = 0.52


async def run_ml_gate(
    ticker: str,
    strategy_type: str,
    ta_features: dict[str, float | None],
    fmp_features: dict[str, float | None] | None = None,
    regime_context: dict[str, Any] | None = None,
) -> GateResult:
    """Run the independent ML gate for a single ticker.

    Builds a feature vector from market-observable data only (no LLM
    outputs) and returns a sizing/block decision.

    Args:
        ticker: Ticker symbol.
        strategy_type: Strategy template type.
        ta_features: Technical analysis features from TechnicalSnapshot.
        fmp_features: FMP fundamental features (optional).
        regime_context: Dict with ``regime_type``, ``vix_estimate``, etc.

    Returns:
        GateResult with probability, size multiplier, and block decision.
    """
    if not ml_model_available(strategy_type, mode="independent"):
        return GateResult(
            ticker=ticker,
            ml_probability=0.0,
            predicted_direction="FLAT",
            size_multiplier=1.0,
            blocked=False,
            reason="no_independent_model",
        )

    context: dict[str, Any] = {
        "strategy_type": strategy_type,
        "market_regime": regime_context.get("regime_type", "unknown")
        if regime_context
        else "unknown",
        "vix_level": regime_context.get("vix_estimate") if regime_context else None,
    }

    features = build_feature_vector(
        ta_features,
        fmp_features,
        context,
        llm_features=None,
    )

    prediction = run_prediction(ticker, strategy_type, features, mode="independent")
    if prediction is None:
        return GateResult(
            ticker=ticker,
            ml_probability=0.0,
            predicted_direction="FLAT",
            size_multiplier=1.0,
            blocked=False,
            reason="prediction_failed",
        )

    prob = (
        prediction.probability_profitable
        if prediction.probability_profitable is not None
        else prediction.probability_up
    )

    size_mult = 0.0
    for threshold, mult in _SIZE_TIERS:
        if prob >= threshold:
            size_mult = mult
            break

    blocked = prob < _BLOCK_THRESHOLD

    return GateResult(
        ticker=ticker,
        ml_probability=prob,
        predicted_direction=prediction.predicted_direction,
        size_multiplier=size_mult,
        blocked=blocked,
        conformal_set=prediction.prediction_set,
        reliability_score=prediction.reliability_score,
        model_version=prediction.model_version,
        reason="blocked" if blocked else "sized",
    )
