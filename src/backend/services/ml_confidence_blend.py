"""Post-ML-gate confidence adjustment: symmetric agreement/disagreement blend.

Replaces the old one-way penalty model with a bounded symmetric adjuster.
When ML agrees with the trade thesis, confidence gets a mild boost; when
ML disagrees, confidence gets a mild cut. Extreme ML blocking still caps
confidence, but less aggressively.

Signal strength is NOT reassigned here — the orchestrator re-applies signal
strength after all confidence modifications are complete.

ML role separation (prevents double-counting):
  - ML adjusts ``confidence`` here (agreement/disagreement signal)
  - ML blocks at extreme low edge via ``ml_blocked`` (safety valve)
  - Position sizing reads ``win_probability`` (which already has ML input
    from boosters), not raw ``ml_probability`` again
"""

from __future__ import annotations

import logging

from pipeline.schemas import Recommendation

logger = logging.getLogger(__name__)

_ML_AGREE_BOOST = 0.05
_ML_DISAGREE_CUT = 0.05
_ML_BLOCK_CAP = 0.30
_MAX_ML_ADJUSTMENT = 0.08


def blend_confidence_with_ml(rec: Recommendation) -> None:
    """Apply symmetric ML agreement/disagreement adjustment to confidence.

    Replaces the old one-way downweighting. When ML strongly agrees with
    the directional thesis, confidence gets a bounded boost. When ML
    disagrees, confidence gets a bounded cut. ML blocking caps confidence
    but never crushes it below 0.20.

    Args:
        rec: Single recommendation with ML gate fields populated (or skipped).
    """
    if rec.ml_probability is None:
        return

    p = float(rec.ml_probability)
    before = rec.confidence

    if rec.ml_blocked:
        capped = min(rec.confidence, max(0.20, _ML_BLOCK_CAP))
        rec.confidence = max(0.05, min(1.0, capped))
        note = f"ML gate block: confidence capped ({before:.2f}->{rec.confidence:.2f}, p={p:.2f})"
    else:
        is_bullish_trade = rec.action in ("BUY",)
        ml_agrees = (is_bullish_trade and p > 0.55) or (not is_bullish_trade and p < 0.45)
        ml_disagrees = (is_bullish_trade and p < 0.40) or (not is_bullish_trade and p > 0.60)

        conviction = abs(p - 0.5) * 2.0

        if ml_agrees:
            boost = min(conviction * _ML_AGREE_BOOST, _MAX_ML_ADJUSTMENT)
            rec.confidence = min(1.0, rec.confidence + boost)
            note = f"ML agrees: +{boost:.3f} ({before:.2f}->{rec.confidence:.2f}, p={p:.2f})"
        elif ml_disagrees:
            cut = min(conviction * _ML_DISAGREE_CUT, _MAX_ML_ADJUSTMENT)
            rec.confidence = max(0.10, rec.confidence - cut)
            note = f"ML disagrees: -{cut:.3f} ({before:.2f}->{rec.confidence:.2f}, p={p:.2f})"
        else:
            note = f"ML neutral: no adjustment ({before:.2f}, p={p:.2f})"

    existing = (rec.confidence_adjustment or "").strip()
    rec.confidence_adjustment = f"{existing} | {note}" if existing else note

    logger.debug("ML confidence blend %s: %s", rec.ticker, note)
