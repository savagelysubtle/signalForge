"""Map live TechnicalSnapshot dicts to flat ML training feature names.

The ML models were trained on flat feature keys like ``rsi_14``,
``macd_histogram``, ``volume_ratio``, etc.  The live pipeline produces
nested Pydantic ``model_dump()`` dicts (``rsi.current``, ``macd.histogram``).
This module bridges the two.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def map_snapshot_to_flat_features(snapshot_dict: dict[str, Any]) -> dict[str, Any]:
    """Convert a ``TechnicalSnapshot.model_dump()`` to flat ML feature keys.

    Args:
        snapshot_dict: Raw ``model_dump()`` output from a ``TechnicalSnapshot``.

    Returns:
        Dict with flat keys matching the ML training feature names.
        Missing features are omitted (LightGBM handles NaN natively).
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

    # EMAs — compute price_vs_ema_* and ema_stack_score
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

        # ema_stack_score: +1 for each pair where shorter > longer
        stack_pairs = [(9, 21), (21, 50), (50, 200)]
        stack_score = 0.0
        stack_count = 0
        for fast, slow in stack_pairs:
            if fast in ema_values and slow in ema_values:
                stack_score += 1.0 if ema_values[fast] > ema_values[slow] else -1.0
                stack_count += 1
        flat["ema_stack_score"] = stack_score / max(stack_count, 1)

        # ema_spread_pct: spread between shortest and longest available
        sorted_periods = sorted(ema_values.keys())
        if len(sorted_periods) >= 2:
            shortest = ema_values[sorted_periods[0]]
            longest = ema_values[sorted_periods[-1]]
            if longest > 0:
                flat["ema_spread_pct"] = (shortest - longest) / longest

    # Momentum score (direct field)
    flat["momentum_score"] = snapshot_dict.get("momentum_score")

    # Price range features from OHLC
    p_high = snapshot_dict.get("price_high")
    p_low = snapshot_dict.get("price_low")
    p_open = snapshot_dict.get("price_open")
    if p_high is not None and p_low is not None and price is not None and price > 0:
        flat["high_low_range"] = (p_high - p_low) / price
        if p_open is not None and p_open > 0:
            flat["gap_pct"] = (p_open - price) / price

    return flat
