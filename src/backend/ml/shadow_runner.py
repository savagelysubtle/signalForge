"""Shadow mode orchestration and logging.

Runs ML predictions alongside GPT without affecting visible output.
Logs both predictions for later comparison.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, cast

from database.connection import get_db
from ml.inference import build_feature_vector, ml_model_available, run_prediction
from ml.schemas import MLPrediction, ShadowStats

logger = logging.getLogger(__name__)


async def run_ml_shadow(
    run_id: str,
    recommendations: list[dict[str, Any]],
    ta_snapshots: dict[str, dict[str, Any]] | None = None,
    fmp_data: dict[str, dict[str, Any]] | None = None,
    regime_context: dict[str, Any] | None = None,
    strategy_type: str = "swing",
    user_id: str = "",
) -> list[MLPrediction]:
    """Run ML predictions in shadow mode for comparison with GPT.

    Args:
        run_id: Pipeline run ID.
        recommendations: GPT recommendations list.
        ta_snapshots: Technical analysis snapshots per ticker.
        fmp_data: FMP enrichment data per ticker.
        regime_context: Market regime context.
        strategy_type: Strategy type from config.
        user_id: User ID for RLS.

    Returns:
        List of ML predictions for each recommendation.
    """
    if not ml_model_available(strategy_type):
        logger.warning("No ML model available for %s, skipping shadow predictions", strategy_type)
        return []

    predictions: list[MLPrediction] = []
    insert_rows: list[dict[str, Any]] = []

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
            "market_regime": regime_context.get("regime_type", "unknown")
            if regime_context
            else "unknown",
            "vix_level": regime_context.get("vix_estimate") if regime_context else None,
        }

        action = rec.get("action", "")
        confidence = rec.get("confidence", 0)
        entry_price = rec.get("entry_price")
        stop_loss = rec.get("stop_loss")
        take_profit = rec.get("take_profit")

        action_map = {"BUY": 1, "SHORT": -1, "HOLD": 0, "NO_TRADE": 0, "WATCH": 0}
        sl_dist = None
        tp_dist = None
        if entry_price and entry_price > 0:
            if stop_loss and stop_loss > 0:
                sl_dist = abs(entry_price - stop_loss) / entry_price * 100
            if take_profit and take_profit > 0:
                tp_dist = abs(take_profit - entry_price) / entry_price * 100

        llm_feats: dict[str, float | None] = {
            "llm_action_encoded": float(action_map.get(action, 0)),
            "llm_confidence": float(confidence) if confidence else None,
            "llm_rr_ratio": float(rec.get("risk_reward_ratio", 0))
            if rec.get("risk_reward_ratio")
            else None,
            "llm_sl_distance_pct": sl_dist,
            "llm_tp_distance_pct": tp_dist,
            "llm_key_factor_count": float(len(rec.get("key_factors", []))),
            "llm_warning_count": float(len(rec.get("warnings", []))),
        }

        features = build_feature_vector(ta_features, fund_features, context, llm_feats)
        prediction = run_prediction(ticker, strategy_type, features)

        if prediction is not None:
            predictions.append(prediction)
            insert_rows.append(
                {
                    "id": uuid.uuid4().hex,
                    "user_id": user_id,
                    "run_id": run_id,
                    "ticker": ticker,
                    "strategy_type": strategy_type,
                    "prediction_date": "now()",
                    "ml_prediction": prediction.model_dump(),
                    "ml_direction": prediction.predicted_direction,
                    "ml_confidence": prediction.probability_profitable
                    if prediction.probability_profitable is not None
                    else prediction.probability_up,
                    "ml_reliability": prediction.reliability_score,
                    "gpt_prediction": {
                        "action": rec.get("action", ""),
                        "confidence": rec.get("confidence", 0),
                    },
                    "gpt_action": rec.get("action", ""),
                    "gpt_confidence": rec.get("confidence", 0),
                    "model_version": prediction.model_version,
                }
            )

    if insert_rows:
        try:
            client = await get_db()
            _chunk = 100
            for i in range(0, len(insert_rows), _chunk):
                await (
                    client.table("ml_shadow_predictions")
                    .insert(insert_rows[i : i + _chunk])
                    .execute()
                )
        except Exception:
            logger.exception("Failed to batch store shadow predictions")

    if predictions:
        logger.info(
            "Shadow predictions: %d/%d tickers",
            len(predictions),
            len(recommendations),
        )

    return predictions


async def get_shadow_stats(user_id: str) -> ShadowStats:
    """Get aggregated shadow mode statistics.

    Args:
        user_id: User ID for RLS filtering.

    Returns:
        ShadowStats with comparison metrics.
    """
    try:
        client = await get_db()
        result = (
            await client.table("ml_shadow_predictions")
            .select("actual_direction,ml_correct,gpt_correct,ml_direction,gpt_action,model_version")
            .eq("user_id", user_id)
            .execute()
        )
        rows = cast(list[dict[str, Any]], result.data or [])
    except Exception:
        logger.exception("Failed to fetch shadow stats")
        return ShadowStats()

    if not rows:
        return ShadowStats()

    total = len(rows)
    with_outcomes = [r for r in rows if r.get("actual_direction") is not None]
    ml_correct_count = sum(1 for r in with_outcomes if r.get("ml_correct"))
    gpt_correct_count = sum(1 for r in with_outcomes if r.get("gpt_correct"))

    agreed = sum(1 for r in rows if r.get("ml_direction") == r.get("gpt_action"))

    disagreements_with_outcomes = [
        r for r in with_outcomes if r.get("ml_direction") != r.get("gpt_action")
    ]
    ml_wins = sum(
        1 for r in disagreements_with_outcomes if r.get("ml_correct") and not r.get("gpt_correct")
    )
    gpt_wins = sum(
        1 for r in disagreements_with_outcomes if r.get("gpt_correct") and not r.get("ml_correct")
    )

    model_version = rows[0].get("model_version", "") if rows else ""

    return ShadowStats(
        total_predictions=total,
        predictions_with_outcomes=len(with_outcomes),
        ml_accuracy=ml_correct_count / len(with_outcomes) if with_outcomes else None,
        gpt_accuracy=gpt_correct_count / len(with_outcomes) if with_outcomes else None,
        agreement_rate=agreed / total if total > 0 else 0,
        ml_wins_on_disagreement=ml_wins,
        gpt_wins_on_disagreement=gpt_wins,
        model_version=model_version,
    )
