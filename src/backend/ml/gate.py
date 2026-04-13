"""ML gate — independent model that runs before GPT output is finalized.

Uses a LightGBM model trained without any LLM-derived features so its
probability estimate is truly independent of GPT.  The gate adjusts
position sizing via Kelly criterion and can block recommendations that
the model assigns low probability to.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Any

from ml.inference import (
    build_feature_vector,
    ml_model_available,
    run_meta_prediction,
    run_prediction,
)
from ml.schemas import GateResult

logger = logging.getLogger(__name__)

# Per-strategy reward-to-risk ratios derived from training barrier configs.
# profit_mult / stop_mult — determines Kelly breakeven and optimal sizing.
_STRATEGY_RR: dict[str, float] = {
    "momentum_breakout": 3.0 / 1.0,
    "golden_cross_swing": 2.5 / 1.0,
    "bb_squeeze_breakout": 1.5 / 1.0,
    "mean_reversion": 1.5 / 1.0,
    "value_accumulation": 2.0 / 1.5,
    "earnings_play": 2.5 / 1.0,
    "intraday_scalp": 1.2 / 1.0,
    "crypto_swing": 2.0 / 1.0,
    "crypto_intraday_scalp": 1.2 / 1.0,
}
_DEFAULT_RR = 2.0
_MIN_KELLY = 0.05
_MAX_SIZE = 1.0

_REGIME_KELLY_MULT: dict[str, float] = {
    "bear": 0.5,
    "neutral": 1.0,
    "bull": 1.25,
    "unknown": 0.8,
}


def _kelly_size(prob: float, rr: float = _DEFAULT_RR) -> float:
    """Kelly criterion position sizing: f* = (b*p - q) / b.

    Args:
        prob: Predicted probability of a profitable trade.
        rr: Reward-to-risk ratio (profit_mult / stop_mult).

    Returns:
        Optimal fraction of capital to allocate, clamped to [0, _MAX_SIZE].
    """
    q = 1.0 - prob
    f_star = (rr * prob - q) / rr
    return max(0.0, min(f_star, _MAX_SIZE))


async def quick_score(
    ticker: str,
    strategy_type: str,
    ta_features: dict[str, float | None],
    regime_context: dict[str, Any] | None = None,
) -> float | None:
    """Lightweight ML scoring for the strategy scanner.

    Returns the model's probability estimate, or ``None`` if no model is
    available or prediction fails.
    """
    result = await run_ml_gate(ticker, strategy_type, ta_features, regime_context=regime_context)
    if result.reason in ("no_independent_model", "prediction_failed"):
        return None
    return result.ml_probability


async def run_ml_gate(
    ticker: str,
    strategy_type: str,
    ta_features: dict[str, float | None],
    fmp_features: dict[str, float | None] | None = None,
    regime_context: dict[str, Any] | None = None,
) -> GateResult:
    """Run the independent ML gate for a single ticker.

    Builds a feature vector from market-observable data only (no LLM
    outputs) and returns a sizing/block decision using Kelly criterion
    with regime-conditional modifiers and optional meta-labeler blending.

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

    from ml.feature_mapper import build_context_features

    sector = fmp_features.get("sector") if fmp_features else None
    context = build_context_features(strategy_type, regime_context, sector=sector)

    features = build_feature_vector(
        ta_features,
        fmp_features,
        context,
        llm_features=None,
    )

    prediction = await asyncio.to_thread(
        partial(run_prediction, ticker, strategy_type, features, mode="independent")
    )
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

    # --- Meta-labeler conviction blending ---
    meta_conviction: float | None = None
    meta_conv = await asyncio.to_thread(
        partial(run_meta_prediction, ticker, strategy_type, features)
    )
    if meta_conv is not None:
        meta_conviction = meta_conv
        prob = 0.6 * prob + 0.4 * meta_conviction

    # --- Kelly criterion sizing ---
    strategy_rr = _STRATEGY_RR.get(strategy_type, _DEFAULT_RR)
    kelly = _kelly_size(prob, rr=strategy_rr)

    # --- Regime-conditional modifier ---
    regime = regime_context.get("regime_type", "unknown") if regime_context else "unknown"
    regime_mult = _REGIME_KELLY_MULT.get(regime, 0.8)
    adjusted_kelly = kelly * regime_mult

    blocked = adjusted_kelly < _MIN_KELLY
    size_mult = min(adjusted_kelly, _MAX_SIZE) if not blocked else 0.0

    return GateResult(
        ticker=ticker,
        ml_probability=prob,
        predicted_direction=prediction.predicted_direction,
        size_multiplier=size_mult,
        blocked=blocked,
        conformal_set=prediction.prediction_set,
        reliability_score=prediction.reliability_score,
        model_version=prediction.model_version,
        meta_conviction=meta_conviction,
        reason="blocked" if blocked else "sized",
    )
