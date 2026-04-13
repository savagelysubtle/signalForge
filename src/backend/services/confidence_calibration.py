"""Confidence calibration engine v2 — prior + boosters + penalties.

Replaces the old GPT-blend model with a regime-aware prior + evidence
update architecture. The system now works as:

  1. Start from ``prior_base_rate`` (strategy x regime x direction)
  2. Apply positive AND negative evidence boosters (capped individually
     at ±0.08, total cap ±0.15)
  3. Produce ``setup_quality_score`` and ``win_probability``
  4. Signal strength derived from calibrated ``win_probability``
  5. Confidence floors still rescue when tracks agree

The old 60/40 GPT/TA blend is retained as a compatibility path and will
be removed once the v2 shadow validation confirms improvement.
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
from services.prior_service import get_prior
from services.prior_service import is_loaded as priors_loaded

logger = logging.getLogger(__name__)

# ── Booster caps ─────────────────────────────────────────────────────────
_MAX_SINGLE_BOOST = 0.08
_MAX_TOTAL_BOOST = 0.15
_MIN_WIN_PROB = 0.20
_MAX_WIN_PROB = 0.80

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


def _classify_signal_strength(
    confidence: float,
    regime_context: str = "",
) -> SignalStrength:
    """Map calibrated confidence to a position-sizing hint.

    Thresholds shift based on market regime: bullish regimes lower the bar
    (more signals are actionable), bearish regimes raise it.
    """
    regime_lower = regime_context.lower() if regime_context else ""

    if "bull" in regime_lower or "trending_bull" in regime_lower:
        strong, moderate, weak = 0.65, 0.45, 0.25
    elif "bear" in regime_lower or "trending_bear" in regime_lower:
        strong, moderate, weak = 0.75, 0.55, 0.35
    else:
        strong, moderate, weak = 0.70, 0.50, 0.30

    if confidence >= strong:
        return SignalStrength.STRONG
    if confidence >= moderate:
        return SignalStrength.MODERATE
    if confidence >= weak:
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


def _compute_evidence_boosters(
    ta: MultiTimeframeTechnical | None,
    rec: Recommendation,
    config: StrategyConfig,
    regime_context: str = "",
) -> tuple[float, list[str]]:
    """Compute positive and negative evidence boosters from TA data.

    Returns:
        (net_boost capped to ±MAX_TOTAL_BOOST, list of driver descriptions)
    """
    drivers: list[str] = []
    boosts: list[float] = []

    if ta is None:
        return 0.0, drivers

    snap = ta.primary
    is_bullish = rec.action in ("BUY",)
    is_bearish = rec.action in ("SHORT",)

    # ── Positive boosters ────────────────────────────────────────────

    # 1. High RVOL (volume confirmation)
    if snap.volume and snap.volume.ratio >= 2.0:
        b = min(0.06, _MAX_SINGLE_BOOST)
        boosts.append(b)
        drivers.append(f"Strong RVOL ({snap.volume.ratio:.1f}x) +{b:.0%}")
    elif snap.volume and snap.volume.ratio >= 1.5:
        b = min(0.03, _MAX_SINGLE_BOOST)
        boosts.append(b)
        drivers.append(f"Above-avg volume ({snap.volume.ratio:.1f}x) +{b:.0%}")

    # 2. ADX strength (trend strategies)
    if snap.adx >= 30 and config.strategy_type in _TREND_FOLLOWING_TYPES:
        b = min(0.05, _MAX_SINGLE_BOOST)
        boosts.append(b)
        drivers.append(f"Strong ADX ({snap.adx:.0f}) +{b:.0%}")
    elif snap.adx >= 25 and config.strategy_type in _TREND_FOLLOWING_TYPES:
        b = min(0.03, _MAX_SINGLE_BOOST)
        boosts.append(b)
        drivers.append(f"Trending ADX ({snap.adx:.0f}) +{b:.0%}")

    # 3. Multi-timeframe alignment
    if ta.timeframe_alignment == "aligned_bullish" and is_bullish:
        b = min(0.07, _MAX_SINGLE_BOOST)
        boosts.append(b)
        drivers.append(f"Multi-TF bullish alignment +{b:.0%}")
    elif ta.timeframe_alignment == "aligned_bearish" and is_bearish:
        b = min(0.07, _MAX_SINGLE_BOOST)
        boosts.append(b)
        drivers.append(f"Multi-TF bearish alignment +{b:.0%}")

    # 4. RSI in momentum zone (not extreme)
    rsi_val = snap.rsi.current if snap.rsi else 50.0
    if (is_bullish and 50 <= rsi_val <= 65) or (is_bearish and 35 <= rsi_val <= 50):
        b = min(0.03, _MAX_SINGLE_BOOST)
        boosts.append(b)
        drivers.append(f"RSI momentum zone ({rsi_val:.0f}) +{b:.0%}")

    # 5. Clean risk geometry (entry/stop/TP all present with good R:R)
    if (
        rec.entry_price is not None
        and rec.stop_loss is not None
        and rec.take_profit is not None
        and rec.risk_reward_ratio is not None
        and rec.risk_reward_ratio >= 2.5
    ):
        b = min(0.04, _MAX_SINGLE_BOOST)
        boosts.append(b)
        drivers.append(f"Clean R:R ({rec.risk_reward_ratio:.1f}:1) +{b:.0%}")

    # ── Negative boosters ────────────────────────────────────────────

    # 6. Low RVOL
    if snap.volume and snap.volume.ratio < 0.5:
        b = max(-0.05, -_MAX_SINGLE_BOOST)
        boosts.append(b)
        drivers.append(f"Very low volume ({snap.volume.ratio:.1f}x) {b:+.0%}")
    elif snap.volume and snap.volume.ratio < 0.8:
        b = max(-0.03, -_MAX_SINGLE_BOOST)
        boosts.append(b)
        drivers.append(f"Below-avg volume ({snap.volume.ratio:.1f}x) {b:+.0%}")

    # 7. Weak ADX (trendless)
    if snap.adx < 15 and config.strategy_type in _TREND_FOLLOWING_TYPES:
        b = max(-0.06, -_MAX_SINGLE_BOOST)
        boosts.append(b)
        drivers.append(f"Weak ADX ({snap.adx:.0f}) {b:+.0%}")

    # 8. Overbought RSI on bullish / oversold on bearish
    if is_bullish and rsi_val > 75:
        b = max(-0.05, -_MAX_SINGLE_BOOST)
        boosts.append(b)
        drivers.append(f"RSI overbought ({rsi_val:.0f}) {b:+.0%}")
    elif is_bearish and rsi_val < 25:
        b = max(-0.05, -_MAX_SINGLE_BOOST)
        boosts.append(b)
        drivers.append(f"RSI oversold ({rsi_val:.0f}) {b:+.0%}")

    # 9. Stale EMA cross
    if snap.ema_crosses:
        latest = snap.ema_crosses[0]
        if latest.candles_ago > 8:
            b = max(-0.04, -_MAX_SINGLE_BOOST)
            boosts.append(b)
            drivers.append(f"Stale EMA cross ({latest.candles_ago} candles ago) {b:+.0%}")

    # Cap total
    net = sum(boosts)
    net = max(-_MAX_TOTAL_BOOST, min(_MAX_TOTAL_BOOST, net))

    return round(net, 4), drivers


def calibrate_recommendation(
    rec: Recommendation,
    ta: MultiTimeframeTechnical | None,
    config: StrategyConfig,
    regime_context: str = "",
    reflection_metrics: dict[str, Any] | None = None,
    risk_assessment: RiskAssessment | None = None,
) -> Recommendation:
    """Apply v2 confidence calibration to a single recommendation.

    Architecture: ``prior_base_rate + evidence_boosters → win_probability``.
    Also computes the legacy ``confidence`` via the old 60/40 blend for
    backward compatibility until shadow validation confirms v2 is better.

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
        rec.signal_strength = _classify_signal_strength(rec.confidence, regime_context)
        return rec

    all_penalties: list[str] = []

    # ── Legacy sub-component scores (kept for backward compat) ──────
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
        risk_penalty = (1.0 - risk_assessment.risk_score) * 0.07
        all_penalties.append(f"risk_disapproved: -{risk_penalty:.2f}")
        calibrated = max(0.0, calibrated - risk_penalty)

    # ── v2: Prior + Evidence Boosters → win_probability ─────────────
    direction = "long" if rec.action == "BUY" else "short"
    regime_key = ""
    if regime_context:
        rl = regime_context.lower()
        if "bull" in rl:
            regime_key = "normal"
        elif "bear" in rl or "volatile" in rl or "fear" in rl:
            regime_key = "high_volatility"
        else:
            regime_key = "normal"

    prior = get_prior(config.strategy_type, regime_key, direction) if priors_loaded() else 0.50
    rec.prior_base_rate = round(prior, 4)

    net_boost, boost_drivers = _compute_evidence_boosters(ta, rec, config, regime_context)
    rec.setup_quality_score = round(net_boost, 4)
    rec.confidence_drivers = boost_drivers

    win_prob = prior + net_boost
    win_prob = max(_MIN_WIN_PROB, min(_MAX_WIN_PROB, win_prob))
    rec.win_probability = round(win_prob, 4)

    # ── ML agreement label (set later by ML blend, placeholder here) ──
    ml_agreement: str = "unavailable"
    if rec.ml_probability is not None:
        p = float(rec.ml_probability)
        if abs(p - win_prob) < 0.10:
            ml_agreement = "neutral"
        elif (p > 0.55 and win_prob > 0.50) or (p < 0.45 and win_prob < 0.50):
            ml_agreement = "agree"
        else:
            ml_agreement = "disagree"

    breakdown = ConfidenceBreakdown(
        prior_base_rate=rec.prior_base_rate,
        setup_quality_score=rec.setup_quality_score,
        ml_agreement=ml_agreement,
        llm_conviction=rec.llm_conviction,
        win_probability=rec.win_probability,
        confidence_drivers=boost_drivers,
        penalties_applied=all_penalties,
    )

    rec.raw_gpt_confidence = rec.confidence

    # ── Legacy blend (60% GPT + 40% calibrated) ────────────────────
    blended = 0.6 * rec.confidence + 0.4 * calibrated
    blended = round(max(0.0, min(1.0, blended)), 4)

    # Confidence floor: prevent excessive reduction when tracks agree
    agreement_score = rec.track_agreement.agreement_score if rec.track_agreement else 0.0
    if agreement_score >= 0.8 and blended < 0.55:
        all_penalties.append(f"floor_applied: {blended:.4f}->0.55 (3/3 tracks agree)")
        logger.info(
            "Confidence floor 0.55 applied for %s (agreement=%.2f)", rec.ticker, agreement_score
        )
        blended = 0.55
    elif agreement_score >= 0.5 and blended < 0.45:
        all_penalties.append(f"floor_applied: {blended:.4f}->0.45 (2/3 tracks agree)")
        logger.info(
            "Confidence floor 0.45 applied for %s (agreement=%.2f)", rec.ticker, agreement_score
        )
        blended = 0.45

    rec.confidence = blended

    # Shadow v2: store the prior-based win_probability as confidence_v2
    rec.confidence_v2 = rec.win_probability

    rec.confidence_breakdown = breakdown
    rec.signal_strength = _classify_signal_strength(blended, regime_context)

    if all_penalties:
        penalty_summary = "; ".join(all_penalties)
        existing = rec.confidence_adjustment
        if existing:
            rec.confidence_adjustment = f"{existing} | Calibration: {penalty_summary}"
        else:
            rec.confidence_adjustment = f"Calibration: {penalty_summary}"

    logger.info(
        "Calibrated %s: GPT=%.2f → TA=%.4f → blended=%.4f | v2: prior=%.3f + boost=%.3f → wp=%.3f (%s)",
        rec.ticker,
        rec.raw_gpt_confidence,
        calibrated,
        blended,
        prior,
        net_boost,
        win_prob,
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
