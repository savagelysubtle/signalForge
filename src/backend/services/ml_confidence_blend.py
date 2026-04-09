"""Post-ML-gate confidence adjustment: blend displayed confidence with ML uncertainty."""

from __future__ import annotations

import logging

from pipeline.schemas import Recommendation, SignalStrength

logger = logging.getLogger(__name__)


def _signal_strength_from_confidence(confidence: float) -> SignalStrength:
    if confidence >= 0.7:
        return SignalStrength.STRONG
    if confidence >= 0.5:
        return SignalStrength.MODERATE
    if confidence >= 0.3:
        return SignalStrength.WEAK
    return SignalStrength.NO_EDGE


def blend_confidence_with_ml(rec: Recommendation) -> None:
    """Downweight confidence when ML shows low edge or ambiguous conformal sets.

    Runs after the ML gate has set ``ml_probability``, ``ml_blocked``, and
    ``ml_conformal_set``. Mutates ``rec.confidence`` and appends to
    ``confidence_adjustment`` in place.

    Args:
        rec: Single recommendation with ML gate fields populated (or skipped).
    """
    if rec.ml_probability is None:
        return

    p = float(rec.ml_probability)
    n_set = len(rec.ml_conformal_set) if rec.ml_conformal_set else 0
    ambiguity = max(0.0, min(1.0, (n_set - 1) / 2.0)) if n_set else 0.0

    before = rec.confidence

    if rec.ml_blocked:
        capped = min(rec.confidence, max(0.12, p * 0.65 + 0.08))
        rec.confidence = max(0.05, min(1.0, capped))
        note = f"ML gate block: confidence capped ({before:.2f}->{rec.confidence:.2f}, p={p:.2f})"
    else:
        conviction = abs(p - 0.5) * 2.0
        base_mult = 0.65 + 0.35 * conviction
        amb_mult = 1.0 - 0.12 * ambiguity
        mult = base_mult * amb_mult
        rec.confidence = max(0.05, min(1.0, rec.confidence * mult))
        note = (
            f"ML uncertainty blend: x{mult:.2f} ({before:.2f}->{rec.confidence:.2f}, "
            f"p={p:.2f}, amb={ambiguity:.1f})"
        )

    existing = (rec.confidence_adjustment or "").strip()
    rec.confidence_adjustment = f"{existing} | {note}" if existing else note
    rec.signal_strength = _signal_strength_from_confidence(rec.confidence)

    logger.debug("ML confidence blend %s: %s", rec.ticker, note)
