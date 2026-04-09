"""Empirical calibration curve from historical GPT confidence vs outcomes.

Builds a mapping from GPT raw confidence buckets to actual win rates,
enabling data-driven confidence adjustment. Falls back to the fixed
40/60 blend when insufficient data (<50 outcomes).

The curve uses isotonic regression (monotonic calibration) when
scikit-learn is available, otherwise uses simple bucket averaging.
"""

from __future__ import annotations

import logging
from typing import Any

from database.connection import get_db

logger = logging.getLogger(__name__)

MIN_OUTCOMES_FOR_CURVE = 50
_BUCKET_EDGES = [0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]


async def compute_calibration_curve(
    user_id: str = "",
) -> dict[str, Any] | None:
    """Build a calibration curve from decisions + outcomes + recommendations.

    Joins decisions -> recommendations (for raw_gpt_confidence) and
    decisions -> outcomes (for win/loss), then bins and computes
    actual win rate per confidence bucket.

    Args:
        user_id: Scope to a specific user. Empty for all users.

    Returns:
        Calibration data dict with ``buckets``, ``total_outcomes``,
        ``isotonic_available``, and optionally ``isotonic_mapping``.
        Returns None if insufficient data.
    """
    client = await get_db()

    query = client.table("decisions").select("recommendation_id, user_id")
    if user_id:
        query = query.eq("user_id", user_id)
    dec_resp = await query.execute()
    decisions = dec_resp.data or []

    if not decisions:
        return None

    rec_ids = list({d["recommendation_id"] for d in decisions})
    if not rec_ids:
        return None

    rec_resp = (
        await client.table("recommendations")
        .select("id, confidence, raw_gpt_confidence, action")
        .in_("id", rec_ids)
        .execute()
    )
    rec_map = {r["id"]: r for r in (rec_resp.data or [])}

    out_query = client.table("outcomes").select("recommendation_id, profitable, pnl_percent")
    if user_id:
        out_query = out_query.eq("user_id", user_id)
    out_resp = await out_query.execute()
    outcomes = out_resp.data or []

    pairs: list[tuple[float, bool]] = []
    for o in outcomes:
        rec = rec_map.get(o["recommendation_id"])
        if not rec:
            continue

        confidence = rec.get("raw_gpt_confidence") or rec.get("confidence")
        if confidence is None:
            continue

        profitable = o.get("profitable")
        if profitable is None:
            pnl = o.get("pnl_percent")
            if pnl is not None:
                profitable = pnl > 0
            else:
                continue

        pairs.append((float(confidence), bool(profitable)))

    if len(pairs) < MIN_OUTCOMES_FOR_CURVE:
        logger.info(
            "Calibration curve: only %d outcomes (need %d), skipping",
            len(pairs),
            MIN_OUTCOMES_FOR_CURVE,
        )
        return None

    buckets = _compute_buckets(pairs)
    result: dict[str, Any] = {
        "total_outcomes": len(pairs),
        "overall_win_rate": round(sum(1 for _, w in pairs if w) / len(pairs) * 100, 1),
        "buckets": buckets,
        "isotonic_available": False,
    }

    isotonic = _fit_isotonic(pairs)
    if isotonic is not None:
        result["isotonic_available"] = True
        result["isotonic_mapping"] = isotonic

    return result


def _compute_buckets(
    pairs: list[tuple[float, bool]],
) -> list[dict[str, Any]]:
    """Bin confidence/outcome pairs into buckets with win rates."""
    bucket_data: list[dict[str, Any]] = []

    for i in range(len(_BUCKET_EDGES) - 1):
        lo = _BUCKET_EDGES[i]
        hi = _BUCKET_EDGES[i + 1]
        in_bucket = [(c, w) for c, w in pairs if lo <= c < hi]

        if not in_bucket:
            bucket_data.append(
                {"range": f"{lo:.1f}-{hi:.1f}", "count": 0, "wins": 0, "win_rate": None}
            )
            continue

        wins = sum(1 for _, w in in_bucket if w)
        bucket_data.append(
            {
                "range": f"{lo:.1f}-{hi:.1f}",
                "count": len(in_bucket),
                "wins": wins,
                "win_rate": round(wins / len(in_bucket) * 100, 1),
                "avg_confidence": round(sum(c for c, _ in in_bucket) / len(in_bucket), 3),
            }
        )

    return bucket_data


def _fit_isotonic(
    pairs: list[tuple[float, bool]],
) -> list[dict[str, float]] | None:
    """Fit isotonic regression (monotonic calibration) if sklearn available.

    Returns a list of (confidence, calibrated_probability) mapping points,
    or None if sklearn is not installed.
    """
    try:
        from sklearn.isotonic import IsotonicRegression
    except ImportError:
        logger.debug("scikit-learn not available, skipping isotonic regression")
        return None

    confidences = [c for c, _ in pairs]
    wins = [1.0 if w else 0.0 for _, w in pairs]

    ir = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    ir.fit(confidences, wins)

    sample_points = [round(x * 0.05, 2) for x in range(1, 21)]
    calibrated = ir.predict(sample_points)

    return [
        {"confidence": c, "calibrated": round(float(p), 4)}
        for c, p in zip(sample_points, calibrated, strict=False)
    ]
