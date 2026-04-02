"""Confidence calibration engine for the v2 pipeline.

Decomposes the GPT-assigned confidence into weighted sub-components,
then applies deterministic penalty rules based on numerical TA state,
track agreement, and historical pattern accuracy. The result replaces
the raw GPT confidence with a calibrated score and a position-sizing
hint (``SignalStrength``).

Auto-threshold rules (starting points -- Phase 6 feedback loop tunes over time):
  - EMA cross age > 5 candles on daily:    -0.15
  - RSI > 70 on bullish signal:            -0.10
  - RSI < 30 on bearish signal:            -0.10
  - ADX < 20 (no trend):                   -0.20 (trend-following only)
  - Volume < 0.8x average:                 -0.10
  - Tracks disagree:                       -0.15 per dissenting track
  - Historical pattern accuracy < 40%:     -0.20
"""

from __future__ import annotations

import logging
from typing import Any

from pipeline.schemas import (
    ConfidenceBreakdown,
    MultiTimeframeTechnical,
    Recommendation,
    RiskAssessment,
    SignalStrength,
    StrategyConfig,
    TrackAgreement,
)

logger = logging.getLogger(__name__)

# ── Trend-following strategy types (ADX < 20 penalty applies) ────────────
_TREND_FOLLOWING_TYPES = frozenset(
    {
        "swing",
        "momentum",
        "trend",
        "breakout",
        "position",
    }
)


def _classify_signal_strength(confidence: float) -> SignalStrength:
    """Map calibrated confidence to a position-sizing hint."""
    if confidence >= 0.7:
        return SignalStrength.STRONG
    if confidence >= 0.5:
        return SignalStrength.MODERATE
    if confidence >= 0.3:
        return SignalStrength.WEAK
    return SignalStrength.NO_EDGE


def _score_track_agreement(
    agreement: TrackAgreement | None,
) -> tuple[float, list[str]]:
    """Compute the track-agreement component (max 0.30).

    Returns:
        (score, list_of_penalties_applied)
    """
    penalties: list[str] = []
    if agreement is None:
        return 0.15, penalties

    base = agreement.agreement_score * 0.30

    dissenting = 0
    directions = [
        agreement.perplexity_direction,
        agreement.gemini_direction,
        agreement.claude_direction,
    ]
    majority = max(set(directions), key=directions.count) if directions else "neutral"
    for d in directions:
        if d != majority and d != "neutral":
            dissenting += 1

    penalty = dissenting * 0.15
    if penalty > 0:
        penalties.append(f"tracks_disagree: -{penalty:.2f} ({dissenting} dissenting)")
        base = max(0.0, base - penalty)

    return round(min(base, 0.30), 4), penalties


def _score_technical_strength(
    ta: MultiTimeframeTechnical | None,
    action: str,
) -> tuple[float, list[str]]:
    """Compute the technical-strength component (max 0.20).

    Uses momentum score and ADX from the primary timeframe.

    Returns:
        (score, list_of_penalties_applied)
    """
    penalties: list[str] = []
    if ta is None:
        return 0.10, penalties

    snap = ta.primary
    momentum = abs(snap.momentum_score)
    adx = snap.adx
    rsi_val = snap.rsi.current if snap.rsi else 50.0

    base = min(momentum * 0.10 + (adx / 100.0) * 0.10, 0.20)

    is_bullish = action in ("BUY",)
    is_bearish = action in ("SHORT",)

    if is_bullish and rsi_val > 70:
        penalties.append(f"rsi_overbought: -0.10 (RSI={rsi_val:.1f} on bullish)")
        base = max(0.0, base - 0.10)

    if is_bearish and rsi_val < 30:
        penalties.append(f"rsi_oversold: -0.10 (RSI={rsi_val:.1f} on bearish)")
        base = max(0.0, base - 0.10)

    return round(min(base, 0.20), 4), penalties


def _score_trend_alignment(
    ta: MultiTimeframeTechnical | None,
    config: StrategyConfig,
) -> tuple[float, list[str]]:
    """Compute the trend-alignment component (max 0.20).

    Uses multi-timeframe alignment and EMA cross age from primary TF.

    Returns:
        (score, list_of_penalties_applied)
    """
    penalties: list[str] = []
    if ta is None:
        return 0.10, penalties

    alignment_scores = {
        "aligned_bullish": 0.20,
        "aligned_bearish": 0.20,
        "divergent": 0.05,
    }
    base = alignment_scores.get(ta.timeframe_alignment, 0.05)

    snap = ta.primary
    if snap.ema_crosses:
        latest_cross = snap.ema_crosses[0]
        if latest_cross.candles_ago > 5:
            penalties.append(
                f"stale_ema_cross: -0.15 (cross {latest_cross.candles_ago} candles ago)"
            )
            base = max(0.0, base - 0.15)

    is_trend_strategy = config.strategy_type.lower() in _TREND_FOLLOWING_TYPES
    if is_trend_strategy and snap.adx < 20:
        penalties.append(f"low_adx_trend_strategy: -0.20 (ADX={snap.adx:.1f}, no trend)")
        base = max(0.0, base - 0.20)

    return round(min(base, 0.20), 4), penalties


def _score_historical_pattern(
    reflection_metrics: dict[str, Any] | None,
) -> tuple[float, list[str]]:
    """Compute the historical-pattern component (max 0.20).

    Uses pattern accuracy and confidence calibration from the reflection system.

    Returns:
        (score, list_of_penalties_applied)
    """
    penalties: list[str] = []
    if not reflection_metrics:
        return 0.10, penalties

    cal = reflection_metrics.get("confidence_calibration", {})
    pattern_stats = reflection_metrics.get("pattern_stats", {})

    base = 0.10

    if cal:
        high_wr = cal.get("high", {}).get("win_rate", 50)
        if high_wr > 60:
            base = 0.18
        elif high_wr > 50:
            base = 0.14

    worst_pattern_wr = 100.0
    for _name, stats in pattern_stats.items():
        total = stats.get("total", 0)
        if total >= 3:
            wr = stats.get("win_rate", 50)
            worst_pattern_wr = min(worst_pattern_wr, wr)

    if worst_pattern_wr < 40:
        penalties.append(
            f"weak_historical_pattern: -0.20 (worst pattern {worst_pattern_wr:.0f}% win rate)"
        )
        base = max(0.0, base - 0.20)

    return round(min(base, 0.20), 4), penalties


def _score_regime_fit(
    regime_context: str,
    config: StrategyConfig,
) -> tuple[float, list[str]]:
    """Compute the regime-fit component (max 0.10).

    Checks whether the current market regime suits the strategy type.

    Returns:
        (score, list_of_penalties_applied)
    """
    penalties: list[str] = []
    if not regime_context:
        return 0.05, penalties

    regime_lower = regime_context.lower()
    strategy_lower = config.strategy_type.lower()

    favorable_combos = {
        "trending": {"swing", "trend", "momentum", "breakout", "position"},
        "bullish": {"swing", "momentum", "breakout", "position"},
        "bearish": {"swing", "position"},
        "ranging": {"mean_reversion", "scalp", "range"},
        "volatile": {"scalp", "momentum", "breakout"},
    }

    score = 0.05
    for regime_keyword, good_strategies in favorable_combos.items():
        if regime_keyword in regime_lower and strategy_lower in good_strategies:
            score = 0.10
            break

    return round(score, 4), penalties


def _score_volume(
    ta: MultiTimeframeTechnical | None,
) -> tuple[float, list[str]]:
    """Check volume and return penalty if below 0.8x average.

    Returns:
        (penalty_amount, list_of_penalties_applied)
    """
    penalties: list[str] = []
    if ta is None:
        return 0.0, penalties

    vol = ta.primary.volume
    if vol is None:
        return 0.0, penalties

    ratio = vol.ratio
    if ratio < 0.8:
        penalties.append(f"low_volume: -0.10 (volume {ratio:.2f}x avg)")
        return 0.10, penalties

    return 0.0, penalties


def calibrate_recommendation(
    rec: Recommendation,
    ta: MultiTimeframeTechnical | None,
    config: StrategyConfig,
    regime_context: str = "",
    reflection_metrics: dict[str, Any] | None = None,
    risk_assessment: RiskAssessment | None = None,
) -> Recommendation:
    """Apply structured confidence calibration to a single recommendation.

    Preserves the original GPT confidence in ``raw_gpt_confidence``, then
    replaces ``confidence`` with the calibrated score and sets
    ``confidence_breakdown`` and ``signal_strength``.

    Args:
        rec: The GPT-produced recommendation.
        ta: Multi-timeframe technical data for this ticker (may be None).
        config: Strategy configuration.
        regime_context: Current regime classification string.
        reflection_metrics: Pre-computed metrics from the reflection system.
        risk_assessment: Deterministic risk assessment for this ticker.

    Returns:
        The same ``Recommendation`` with calibrated confidence fields set.
    """
    if rec.action in ("NO_TRADE", "HOLD"):
        rec.raw_gpt_confidence = rec.confidence
        rec.signal_strength = _classify_signal_strength(rec.confidence)
        return rec

    all_penalties: list[str] = []

    track_score, p = _score_track_agreement(rec.track_agreement)
    all_penalties.extend(p)

    tech_score, p = _score_technical_strength(ta, rec.action)
    all_penalties.extend(p)

    trend_score, p = _score_trend_alignment(ta, config)
    all_penalties.extend(p)

    hist_score, p = _score_historical_pattern(reflection_metrics)
    all_penalties.extend(p)

    regime_score, p = _score_regime_fit(regime_context, config)
    all_penalties.extend(p)

    vol_penalty, p = _score_volume(ta)
    all_penalties.extend(p)

    raw_total = track_score + tech_score + trend_score + hist_score + regime_score
    calibrated = max(0.0, min(1.0, raw_total - vol_penalty))

    if risk_assessment and not risk_assessment.risk_approved:
        risk_penalty = (1.0 - risk_assessment.risk_score) * 0.15
        all_penalties.append(f"risk_disapproved: -{risk_penalty:.2f}")
        calibrated = max(0.0, calibrated - risk_penalty)

    breakdown = ConfidenceBreakdown(
        track_agreement=track_score,
        technical_strength=tech_score,
        trend_alignment=trend_score,
        historical_pattern=hist_score,
        regime_fit=regime_score,
        total=round(calibrated, 4),
        penalties_applied=all_penalties,
    )

    rec.raw_gpt_confidence = rec.confidence
    rec.confidence = round(calibrated, 4)
    rec.confidence_breakdown = breakdown
    rec.signal_strength = _classify_signal_strength(calibrated)

    if all_penalties:
        penalty_summary = "; ".join(all_penalties)
        existing = rec.confidence_adjustment
        if existing:
            rec.confidence_adjustment = f"{existing} | Calibration: {penalty_summary}"
        else:
            rec.confidence_adjustment = f"Calibration: {penalty_summary}"

    logger.info(
        "Calibrated %s: GPT=%.2f → calibrated=%.4f (%s)",
        rec.ticker,
        rec.raw_gpt_confidence,
        calibrated,
        rec.signal_strength,
    )

    return rec


def calibrate_recommendations(
    recommendations: list[Recommendation],
    ta_snapshots: list[MultiTimeframeTechnical] | None,
    config: StrategyConfig,
    regime_context: str = "",
    reflection_metrics: dict[str, Any] | None = None,
    risk_assessments: list[RiskAssessment] | None = None,
) -> list[Recommendation]:
    """Apply calibration to all recommendations in a pipeline run.

    Builds ticker-keyed lookups for TA and risk data, then delegates
    to ``calibrate_recommendation()`` for each ticker.

    Args:
        recommendations: GPT-produced recommendations.
        ta_snapshots: Per-ticker multi-timeframe TA (may be None).
        config: Strategy configuration.
        regime_context: Current regime classification string.
        reflection_metrics: Pre-computed metrics from the reflection system.
        risk_assessments: Per-ticker risk assessments (may be None).

    Returns:
        The same list with calibrated confidence fields set on each.
    """
    ta_map: dict[str, MultiTimeframeTechnical] = {}
    if ta_snapshots:
        for snap in ta_snapshots:
            ta_map[snap.ticker.upper()] = snap

    risk_map: dict[str, RiskAssessment] = {}
    if risk_assessments:
        for ra in risk_assessments:
            risk_map[ra.ticker.upper()] = ra

    for rec in recommendations:
        ticker_key = rec.ticker.upper()
        calibrate_recommendation(
            rec,
            ta=ta_map.get(ticker_key),
            config=config,
            regime_context=regime_context,
            reflection_metrics=reflection_metrics,
            risk_assessment=risk_map.get(ticker_key),
        )

    return recommendations
