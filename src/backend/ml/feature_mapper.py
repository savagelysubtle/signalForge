"""Map live pipeline data to flat ML training feature names.

The ML models were trained on flat feature keys like ``rsi_14``,
``macd_histogram``, ``volume_ratio``, etc.  The live pipeline produces
nested Pydantic ``model_dump()`` dicts (``rsi.current``, ``macd.histogram``)
and separate FMP / regime dicts with different field names.

This module bridges ALL three data sources into a unified flat dict that
``build_feature_vector`` can consume directly.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Timeframe label mapping: TechnicalSnapshot.timeframe → model prefix
_TF_PREFIX: dict[str, str] = {
    "1h": "tf_1H",
    "1H": "tf_1H",
    "60": "tf_1H",
    "4h": "tf_4H",
    "4H": "tf_4H",
    "240": "tf_4H",
    "1d": "tf_D",
    "1D": "tf_D",
    "D": "tf_D",
    "daily": "tf_D",
    "1w": "tf_W",
    "1W": "tf_W",
    "W": "tf_W",
    "weekly": "tf_W",
}


def _map_single_snapshot(snapshot_dict: dict[str, Any]) -> dict[str, Any]:
    """Convert one ``TechnicalSnapshot.model_dump()`` to flat ML keys.

    Returns only the TA-derived features; context/FMP handled separately.
    """
    flat: dict[str, Any] = {}

    price = snapshot_dict.get("price_current")
    flat["price_current"] = price

    # RSI
    rsi = snapshot_dict.get("rsi")
    if isinstance(rsi, dict):
        flat["rsi_14"] = rsi.get("current")
        flat["rsi_zone"] = rsi.get("zone")

    # MACD
    macd = snapshot_dict.get("macd")
    if isinstance(macd, dict):
        flat["macd_histogram"] = macd.get("histogram")
        slope_raw = macd.get("histogram_slope")
        flat["macd_slope"] = 1.0 if slope_raw == "expanding" else -1.0 if slope_raw else 0.0

    # ADX / ATR
    flat["adx"] = snapshot_dict.get("adx")
    flat["atr_pct"] = snapshot_dict.get("atr_pct")

    # Volume
    vol = snapshot_dict.get("volume")
    if isinstance(vol, dict):
        flat["volume_ratio"] = vol.get("ratio")
        trend_raw = vol.get("trend")
        if trend_raw == "increasing":
            flat["volume_trend"] = 1.0
        elif trend_raw == "decreasing":
            flat["volume_trend"] = -1.0
        else:
            flat["volume_trend"] = 0.0

    # EMAs — price_vs_ema_*, ema_stack_score, ema_spread_pct
    emas_list = snapshot_dict.get("emas")
    if isinstance(emas_list, list) and price is not None and price > 0:
        ema_values: dict[int, float] = {}
        for ema in emas_list:
            if isinstance(ema, dict):
                period = ema.get("period")
                val = ema.get("current_value")
                if period is not None and val is not None:
                    ema_values[period] = val

        for p in (9, 21, 50, 200):
            if p in ema_values:
                flat[f"price_vs_ema_{p}"] = (price - ema_values[p]) / price

        stack_pairs = [(9, 21), (21, 50), (50, 200)]
        stack_score = 0.0
        stack_count = 0
        for fast, slow in stack_pairs:
            if fast in ema_values and slow in ema_values:
                stack_score += 1.0 if ema_values[fast] > ema_values[slow] else -1.0
                stack_count += 1
        flat["ema_stack_score"] = stack_score / max(stack_count, 1)

        sorted_periods = sorted(ema_values.keys())
        if len(sorted_periods) >= 2:
            shortest = ema_values[sorted_periods[0]]
            longest = ema_values[sorted_periods[-1]]
            if longest > 0:
                flat["ema_spread_pct"] = (shortest - longest) / longest

    # Momentum score
    flat["momentum_score"] = snapshot_dict.get("momentum_score")

    # Price range features from OHLC
    p_high = snapshot_dict.get("price_high")
    p_low = snapshot_dict.get("price_low")
    p_open = snapshot_dict.get("price_open")
    if p_high is not None and p_low is not None and price is not None and price > 0:
        flat["high_low_range"] = (p_high - p_low) / price
        if p_open is not None and p_open > 0:
            flat["gap_pct"] = (p_open - price) / price

    # Strategy-specific features -- pass through if present in snapshot
    for key in (
        "williams_r",
        "bb_position",
        "bb_width_percentile",
        "squeeze_duration",
        "range_compression_20d",
        "volume_surge",
        "ema_50_200_cross_direction",
        "ema_50_200_cross_recency",
        "rsi_divergence",
        "oversold_duration",
        "bollinger_width",
        "distance_from_20d_high",
        "distance_from_20d_low",
    ):
        val = snapshot_dict.get(key)
        if val is not None:
            flat[key] = val

    # Derive volume_surge from volume_ratio if not already present
    if "volume_surge" not in flat and "volume_ratio" in flat:
        vr = flat["volume_ratio"]
        if vr is not None:
            flat["volume_surge"] = 1.0 if vr > 1.5 else 0.0

    # Derive ema_50_200_cross_direction from EMAs if available
    if "ema_50_200_cross_direction" not in flat:
        emas_list = snapshot_dict.get("emas")
        if isinstance(emas_list, list) and price is not None:
            ema_vals: dict[int, float] = {}
            for ema in emas_list:
                if isinstance(ema, dict):
                    p = ema.get("period")
                    v = ema.get("current_value")
                    if p is not None and v is not None:
                        ema_vals[p] = v
            if 50 in ema_vals and 200 in ema_vals:
                flat["ema_50_200_cross_direction"] = 1.0 if ema_vals[50] > ema_vals[200] else -1.0

    return flat


def map_snapshot_to_flat_features(snapshot_dict: dict[str, Any]) -> dict[str, Any]:
    """Convert a ``TechnicalSnapshot.model_dump()`` to flat ML feature keys.

    Public API kept for backward compatibility. For multi-timeframe mapping,
    use ``map_multi_tf_to_features`` instead.
    """
    return _map_single_snapshot(snapshot_dict)


def map_multi_tf_to_features(multi_tf_dict: dict[str, Any]) -> dict[str, Any]:
    """Convert a ``MultiTimeframeTechnical.model_dump()`` to flat ML keys.

    Extracts primary timeframe features (unprefixed) plus secondary
    timeframe features with ``tf_{TF}_`` prefix matching trained models.

    Args:
        multi_tf_dict: Raw ``MultiTimeframeTechnical.model_dump()``.

    Returns:
        Flat feature dict with primary + secondary timeframe keys.
    """
    flat: dict[str, Any] = {}

    primary = multi_tf_dict.get("primary")
    if isinstance(primary, dict):
        flat.update(_map_single_snapshot(primary))

    for tf_list_key in ("additional", "short"):
        tf_list = multi_tf_dict.get(tf_list_key)
        if not isinstance(tf_list, list):
            continue
        for snap in tf_list:
            if not isinstance(snap, dict):
                continue
            tf_label = snap.get("timeframe", "")
            prefix = _TF_PREFIX.get(tf_label)
            if prefix is None:
                continue

            secondary = _map_single_snapshot(snap)
            for key in ("rsi_14", "price_vs_ema_200", "ema_stack_score", "momentum_score"):
                val = secondary.get(key)
                if val is not None:
                    flat[f"{prefix}_{key}"] = val

    return flat


# FMP field name → ML training feature name
_FMP_FIELD_MAP: dict[str, str] = {
    "pe_ratio": "pe_ratio",
    "pb_ratio": "pb_ratio",
    "ev_ebitda": "ev_ebitda",
    "debt_equity": "debt_equity",
    "roe": "roe",
    "roa": "roa",
    "net_profit_margin": "net_margin",
    "piotroski_score": "piotroski_score",
    "altman_z_score": "altman_z",
    "analyst_target_upside": "analyst_target_upside",
    "insider_buy_ratio": "insider_buy_ratio",
    "current_ratio": "current_ratio",
    "dividend_yield": "dividend_yield",
    "composite_score": "composite_score",
    "price_change_1d": "price_change_1d",
    "sector": "sector",
}

# Revenue growth lives on FmpEnrichedStock but under different possible names
_FMP_REVENUE_FIELDS = ("revenue_growth", "revenueGrowth", "revenue_growth_yoy")


def map_fmp_to_features(fmp_dict: dict[str, Any]) -> dict[str, Any]:
    """Normalize FMP ``model_dump()`` keys to ML training feature names.

    Only emits features that trained models actually use.
    """
    flat: dict[str, Any] = {}

    for fmp_key, ml_key in _FMP_FIELD_MAP.items():
        val = fmp_dict.get(fmp_key)
        if val is not None:
            flat[ml_key] = val

    for rev_key in _FMP_REVENUE_FIELDS:
        val = fmp_dict.get(rev_key)
        if val is not None:
            flat["revenue_growth"] = val
            break

    return flat


def build_context_features(
    strategy_type: str,
    regime_dict: dict[str, Any] | None,
    sector: str | None = None,
) -> dict[str, Any]:
    """Build the context feature dict expected by ML models.

    Adds temporal features (day_of_week, month) that the training pipeline
    computes but the live pipeline was previously omitting.
    """
    now = datetime.now(tz=UTC)
    ctx: dict[str, Any] = {
        "strategy_type": strategy_type,
        "day_of_week": now.weekday(),
        "month": now.month,
    }

    if regime_dict:
        ctx["market_regime"] = regime_dict.get("regime_type", "unknown")
        ctx["vix_level"] = regime_dict.get("vix_estimate")
        ctx["market_breadth_proxy"] = regime_dict.get("breadth_estimate")
    else:
        ctx["market_regime"] = "unknown"

    if sector:
        ctx["sector"] = sector

    return ctx
