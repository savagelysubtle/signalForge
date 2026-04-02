"""Feature extraction from raw historical data.

Transforms raw OHLCV + indicator + fundamental data into the standardized
feature vector used by the ML model. Mirrors the live pipeline's
TechnicalSnapshot computation so training and inference use identical features.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

EMA_PERIODS = [9, 21, 50, 200]


def compute_technical_features(
    prices: pd.DataFrame,
    indicators: pd.DataFrame,
) -> pd.DataFrame:
    """Compute technical features for each row in the price DataFrame.

    Merges indicator data with price data on the date column and computes
    derived features matching the live TechnicalSnapshot.

    Args:
        prices: OHLCV DataFrame with columns: date, open, high, low, close, volume.
        indicators: Merged indicator DataFrame with date + indicator columns.

    Returns:
        DataFrame with one row per date and ~25 technical feature columns.
    """
    if prices.empty:
        return pd.DataFrame()

    df = prices.copy()
    df["date"] = pd.to_datetime(df["date"])

    if not indicators.empty:
        indicators = indicators.copy()
        indicators["date"] = pd.to_datetime(indicators["date"])
        df = pd.merge(df, indicators, on="date", how="left")

    features = pd.DataFrame({"date": df["date"]})

    for period in EMA_PERIODS:
        ema_col = f"ema_{period}"
        if ema_col in df.columns:
            features[f"price_vs_ema_{period}"] = (
                (df["close"] - df[ema_col]) / df[ema_col] * 100
            ).replace([np.inf, -np.inf], np.nan)
        else:
            features[f"price_vs_ema_{period}"] = np.nan

    features["ema_stack_score"] = _compute_ema_stack_score(df)
    features["ema_spread_pct"] = _compute_ema_spread(df)

    if "rsi" in df.columns:
        features["rsi_14"] = df["rsi"]
        features["rsi_zone"] = df["rsi"].apply(_rsi_zone_encode)
    else:
        features["rsi_14"] = np.nan
        features["rsi_zone"] = 0.0

    if "macd" in df.columns:
        features["macd_histogram"] = df.get("macd_histogram", df.get("macd", np.nan))
    else:
        features["macd_histogram"] = np.nan

    if "macd_signal" in df.columns and "macd" in df.columns:
        features["macd_slope"] = (df["macd"] - df["macd_signal"]).diff()
    else:
        features["macd_slope"] = np.nan

    features["adx"] = df.get("adx", pd.Series(np.nan, index=df.index))

    if "atr" in df.columns:
        features["atr_pct"] = (df["atr"] / df["close"] * 100).replace([np.inf, -np.inf], np.nan)
    else:
        features["atr_pct"] = np.nan

    if "volume" in df.columns:
        vol_ma20 = df["volume"].rolling(20, min_periods=5).mean()
        features["volume_ratio"] = (df["volume"] / vol_ma20).replace([np.inf, -np.inf], np.nan)
        vol_ma5 = df["volume"].rolling(5, min_periods=2).mean()
        features["volume_trend"] = (vol_ma5 / vol_ma20).replace([np.inf, -np.inf], np.nan)
    else:
        features["volume_ratio"] = np.nan
        features["volume_trend"] = np.nan

    features["momentum_score"] = _compute_momentum_score(features)

    if "close" in df.columns:
        features["price_change_1d"] = df["close"].pct_change(1) * 100
        features["price_change_5d"] = df["close"].pct_change(5) * 100
        features["price_change_20d"] = df["close"].pct_change(20) * 100

        sma_20 = df["close"].rolling(20).mean()
        sma_std = df["close"].rolling(20).std()
        features["bollinger_width"] = ((2 * sma_std / sma_20) * 100).replace(
            [np.inf, -np.inf], np.nan
        )

    return features


def compute_fundamental_features(fundamentals: pd.DataFrame) -> dict[str, float | None]:
    """Extract fundamental features from a single-row fundamentals DataFrame.

    Args:
        fundamentals: Single-row DataFrame with flattened fundamental data.

    Returns:
        Dict of ~15 fundamental feature values (None where unavailable).
    """
    if fundamentals.empty:
        return _empty_fundamentals()

    row = fundamentals.iloc[0] if len(fundamentals) > 0 else {}

    def _get(key: str) -> float | None:
        val = (
            row.get(key)
            if isinstance(row, dict)
            else getattr(row, key, None)
            if hasattr(row, key)
            else None
        )
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return None
        try:
            return float(val)
        except TypeError, ValueError:
            return None

    return {
        "pe_ratio": _get("ratios_ttm_peRatioTTM"),
        "pb_ratio": _get("ratios_ttm_priceToBookRatioTTM"),
        "ev_ebitda": _get("ratios_ttm_enterpriseValueOverEBITDATTM"),
        "debt_equity": _get("ratios_ttm_debtEquityRatioTTM"),
        "roe": _get("ratios_ttm_returnOnEquityTTM"),
        "net_margin": _get("ratios_ttm_netProfitMarginTTM"),
        "revenue_growth": _get("key_metrics_ttm_revenuePerShareTTM"),
        "piotroski_score": _get("financial_scores_piotroskiScore"),
        "altman_z": _get("financial_scores_altmanZScore"),
        "analyst_target_upside": None,
        "insider_buy_ratio": _compute_insider_ratio(row),
        "current_ratio": _get("ratios_ttm_currentRatioTTM"),
        "dividend_yield": _get("ratios_ttm_dividendYieldTTM"),
        "roa": _get("ratios_ttm_returnOnAssetsTTM"),
        "composite_score": None,
    }


def compute_context_features(
    strategy_type: str,
    sector: str | None,
    date: pd.Timestamp,
    vix_level: float | None = None,
    market_breadth: float | None = None,
) -> dict[str, Any]:
    """Compute context features for a single data point.

    Args:
        strategy_type: Strategy template type (e.g. "swing", "momentum").
        sector: Stock sector (None for crypto).
        date: Snapshot date.
        vix_level: Current VIX value.
        market_breadth: % of universe above 200 EMA.

    Returns:
        Dict of ~8 context features.
    """
    market_regime = _classify_regime(vix_level)

    return {
        "strategy_type": strategy_type,
        "market_regime": market_regime,
        "sector": sector or "unknown",
        "day_of_week": date.dayofweek,
        "month": date.month,
        "vix_level": vix_level,
        "sector_relative_strength": None,
        "market_breadth_proxy": market_breadth,
    }


def compute_outcome_labels(
    prices: pd.DataFrame,
    idx: int,
    atr_pct: float | None = None,
) -> dict[str, Any]:
    """Compute forward-looking outcome labels for a given row index.

    Args:
        prices: OHLCV DataFrame sorted by date.
        idx: Row index to compute outcomes for.
        atr_pct: ATR as % of price (for stop-hit calculation).

    Returns:
        Dict with return_Xd, direction_Xd, MFE, MAE, stop_hit labels.
    """
    close = prices["close"].values
    high = prices["high"].values if "high" in prices.columns else close
    low = prices["low"].values if "low" in prices.columns else close
    n = len(close)

    labels: dict[str, Any] = {}

    for horizon in [5, 10, 20]:
        future_idx = idx + horizon
        if future_idx < n:
            ret = (close[future_idx] - close[idx]) / close[idx] * 100
            labels[f"return_{horizon}d"] = ret
            if ret > 2.0:
                labels[f"direction_{horizon}d"] = "UP"
            elif ret < -2.0:
                labels[f"direction_{horizon}d"] = "DOWN"
            else:
                labels[f"direction_{horizon}d"] = "FLAT"
        else:
            labels[f"return_{horizon}d"] = None
            labels[f"direction_{horizon}d"] = None

    max_horizon = min(idx + 20, n)
    if max_horizon > idx:
        future_highs = high[idx + 1 : max_horizon]
        future_lows = low[idx + 1 : max_horizon]
        if len(future_highs) > 0:
            labels["max_favorable_excursion"] = (
                (float(np.max(future_highs)) - close[idx]) / close[idx] * 100
            )
            labels["max_adverse_excursion"] = (
                (float(np.min(future_lows)) - close[idx]) / close[idx] * 100
            )

            if atr_pct is not None and atr_pct > 0:
                stop_level = close[idx] * (1 - 2 * atr_pct / 100)
                labels["stop_hit"] = bool(float(np.min(future_lows)) < stop_level)
            else:
                labels["stop_hit"] = None
        else:
            labels["max_favorable_excursion"] = None
            labels["max_adverse_excursion"] = None
            labels["stop_hit"] = None
    else:
        labels["max_favorable_excursion"] = None
        labels["max_adverse_excursion"] = None
        labels["stop_hit"] = None

    return labels


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _compute_ema_stack_score(df: pd.DataFrame) -> pd.Series:
    """Score from -1 (fully bearish) to +1 (fully bullish) based on EMA ordering."""
    score = pd.Series(0.0, index=df.index)
    ema_cols = [f"ema_{p}" for p in EMA_PERIODS if f"ema_{p}" in df.columns]
    if len(ema_cols) < 2:
        return score

    for i in range(len(ema_cols) - 1):
        fast = df[ema_cols[i]]
        slow = df[ema_cols[i + 1]]
        score += (fast > slow).astype(float) - (fast < slow).astype(float)

    max_pairs = len(ema_cols) - 1
    if max_pairs > 0:
        score = score / max_pairs
    return score


def _compute_ema_spread(df: pd.DataFrame) -> pd.Series:
    """% distance between fastest and slowest EMA."""
    ema_cols = [f"ema_{p}" for p in EMA_PERIODS if f"ema_{p}" in df.columns]
    if len(ema_cols) < 2:
        return pd.Series(np.nan, index=df.index)
    fast = df[ema_cols[0]]
    slow = df[ema_cols[-1]]
    return ((fast - slow) / slow * 100).replace([np.inf, -np.inf], np.nan)


def _rsi_zone_encode(rsi: float | None) -> float:
    """Encode RSI into zone: -1 (oversold), 0 (neutral), 1 (overbought)."""
    if rsi is None or np.isnan(rsi):
        return 0.0
    if rsi >= 70:
        return 1.0
    if rsi <= 30:
        return -1.0
    return 0.0


def _compute_momentum_score(features: pd.DataFrame) -> pd.Series:
    """Composite momentum score matching live pipeline's computation.

    Weighted: RSI(0.25) + MACD(0.25) + EMA_spread(0.30) + ADX(0.20)
    """
    score = pd.Series(0.0, index=features.index)
    count = pd.Series(0, index=features.index)

    if "rsi_14" in features.columns:
        rsi_norm = (features["rsi_14"] - 50) / 50
        valid = features["rsi_14"].notna()
        score = score + rsi_norm.fillna(0) * 0.25 * valid.astype(float)
        count = count + valid.astype(int)

    if "macd_histogram" in features.columns:
        macd_norm = features["macd_histogram"].clip(-5, 5) / 5
        valid = features["macd_histogram"].notna()
        score = score + macd_norm.fillna(0) * 0.25 * valid.astype(float)
        count = count + valid.astype(int)

    if "ema_spread_pct" in features.columns:
        spread_norm = features["ema_spread_pct"].clip(-20, 20) / 20
        valid = features["ema_spread_pct"].notna()
        score = score + spread_norm.fillna(0) * 0.30 * valid.astype(float)
        count = count + valid.astype(int)

    if "adx" in features.columns:
        adx_contrib = (features["adx"] - 25) / 75
        valid = features["adx"].notna()
        score = score + adx_contrib.fillna(0) * 0.20 * valid.astype(float)
        count = count + valid.astype(int)

    return score.clip(-1.0, 1.0)


def _compute_insider_ratio(row: Any) -> float | None:
    """Compute insider buy ratio from buy/sell counts."""
    buys = None
    sells = None

    if isinstance(row, dict):
        buys = row.get("insider_buy_count")
        sells = row.get("insider_sell_count")
    elif hasattr(row, "insider_buy_count"):
        buys = getattr(row, "insider_buy_count", None)
        sells = getattr(row, "insider_sell_count", None)

    if buys is None or sells is None:
        return None
    total = (buys or 0) + (sells or 0)
    if total == 0:
        return None
    return float(buys or 0) / total


def _classify_regime(vix_level: float | None) -> str:
    """Classify market regime from VIX level."""
    if vix_level is None:
        return "unknown"
    if vix_level < 15:
        return "low_volatility"
    if vix_level < 20:
        return "normal"
    if vix_level < 30:
        return "elevated"
    return "high_volatility"


def _empty_fundamentals() -> dict[str, float | None]:
    """Return an empty fundamentals feature dict with all keys set to None."""
    return {
        "pe_ratio": None,
        "pb_ratio": None,
        "ev_ebitda": None,
        "debt_equity": None,
        "roe": None,
        "net_margin": None,
        "revenue_growth": None,
        "piotroski_score": None,
        "altman_z": None,
        "analyst_target_upside": None,
        "insider_buy_ratio": None,
        "current_ratio": None,
        "dividend_yield": None,
        "roa": None,
        "composite_score": None,
    }
