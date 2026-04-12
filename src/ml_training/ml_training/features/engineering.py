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

# Per-strategy triple-barrier TP/SL multipliers.  The TP/SL ratio must match
# each strategy's natural edge: mean-reversion needs tight TP with wider SL,
# momentum should let winners run, scalps need symmetric tight barriers, etc.
STRATEGY_BARRIER_CONFIG: dict[str, dict[str, float]] = {
    "mean_reversion": {"profit_mult": 1.0, "stop_mult": 1.5},
    "momentum_breakout": {"profit_mult": 3.0, "stop_mult": 1.0},
    "swing": {"profit_mult": 2.0, "stop_mult": 1.0},
    "earnings_play": {"profit_mult": 2.5, "stop_mult": 1.0},
    "value_accumulation": {"profit_mult": 2.0, "stop_mult": 1.5},
    "bollinger_band_squeeze_breakout": {"profit_mult": 1.5, "stop_mult": 1.0},
    "intraday_scalp": {"profit_mult": 1.2, "stop_mult": 1.0},
    "vwap_reversal_scalp": {"profit_mult": 1.0, "stop_mult": 1.0},
    "ema_21_pullback": {"profit_mult": 2.0, "stop_mult": 1.0},
    "ema_50_200_golden_cross": {"profit_mult": 2.5, "stop_mult": 1.0},
    "ema_stack_momentum": {"profit_mult": 2.0, "stop_mult": 1.0},
    "crypto_swing": {"profit_mult": 2.0, "stop_mult": 1.0},
    "crypto_intraday": {"profit_mult": 1.5, "stop_mult": 1.0},
    "crypto_intraday_scalp": {"profit_mult": 1.2, "stop_mult": 1.0},
    "intraday": {"profit_mult": 1.5, "stop_mult": 1.0},
}
_DEFAULT_BARRIER = {"profit_mult": 2.0, "stop_mult": 1.0}


def get_barrier_config(strategy_type: str) -> dict[str, float]:
    """Return triple-barrier TP/SL config for a strategy type.

    Falls back to the default 2:1 ratio for unknown strategies.
    """
    return STRATEGY_BARRIER_CONFIG.get(strategy_type, _DEFAULT_BARRIER)


# Per-asset-class FFD differencing order.  Crypto is more mean-reverting and
# needs less differencing; high-frequency intraday has more noise to remove.
FFD_D_BY_STRATEGY: dict[str, float] = {
    "crypto_swing": 0.3,
    "crypto_intraday": 0.3,
    "crypto_intraday_scalp": 0.3,
    "intraday_scalp": 0.5,
    "vwap_reversal_scalp": 0.5,
    "ema_stack_momentum": 0.5,
    "intraday": 0.45,
}
_DEFAULT_FFD_D = 0.4


def get_ffd_d(strategy_type: str) -> float:
    """Return the FFD differencing order for a strategy type."""
    return FFD_D_BY_STRATEGY.get(strategy_type, _DEFAULT_FFD_D)


def compute_technical_features(
    prices: pd.DataFrame,
    indicators: pd.DataFrame,
    ffd_d: float = _DEFAULT_FFD_D,
) -> pd.DataFrame:
    """Compute technical features for each row in the price DataFrame.

    Merges indicator data with price data on the date column and computes
    derived features matching the live TechnicalSnapshot.

    Args:
        prices: OHLCV DataFrame with columns: date, open, high, low, close, volume.
        indicators: Merged indicator DataFrame with date + indicator columns.
        ffd_d: Fractional differencing order for FFD features.

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

        daily_ret = df["close"].pct_change(1)
        features["volatility_20d"] = daily_ret.rolling(20, min_periods=10).std() * 100

        features["high_low_range"] = ((df["high"] - df["low"]) / df["close"] * 100).replace(
            [np.inf, -np.inf], np.nan
        )

        features["gap_pct"] = (
            (df["open"] - df["close"].shift(1)) / df["close"].shift(1) * 100
        ).replace([np.inf, -np.inf], np.nan)

        rolling_high_20 = df["close"].rolling(20, min_periods=10).max()
        features["distance_from_20d_high"] = (
            (df["close"] - rolling_high_20) / rolling_high_20 * 100
        ).replace([np.inf, -np.inf], np.nan)

        rolling_low_20 = df["close"].rolling(20, min_periods=10).min()
        features["distance_from_20d_low"] = (
            (df["close"] - rolling_low_20) / rolling_low_20 * 100
        ).replace([np.inf, -np.inf], np.nan)

    ffd = compute_ffd_features(df, d=ffd_d)
    features["ffd_close"] = ffd["ffd_close"]
    features["ffd_return_1d"] = ffd["ffd_return_1d"]

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

    pe = _get("ratios_ttm_priceToEarningsRatioTTM")
    roe_val = _get("key_metrics_ttm_returnOnEquityTTM")
    roa_val = _get("key_metrics_ttm_returnOnAssetsTTM")
    piotroski = _get("financial_scores_piotroskiScore")
    altman = _get("financial_scores_altmanZScore")

    composite = _compute_composite_score(pe, roe_val, piotroski, altman)

    return {
        "pe_ratio": pe,
        "pb_ratio": _get("ratios_ttm_priceToBookRatioTTM"),
        "ev_ebitda": _get("ratios_ttm_enterpriseValueMultipleTTM"),
        "debt_equity": _get("ratios_ttm_debtToEquityRatioTTM"),
        "roe": roe_val,
        "net_margin": _get("ratios_ttm_netProfitMarginTTM"),
        "revenue_growth": _get("ratios_ttm_revenuePerShareTTM"),
        "piotroski_score": piotroski,
        "altman_z": altman,
        "analyst_target_upside": _get("key_metrics_ttm_priceToFairValueTTM"),
        "insider_buy_ratio": _compute_insider_ratio(row),
        "current_ratio": _get("ratios_ttm_currentRatioTTM"),
        "dividend_yield": _get("ratios_ttm_dividendYieldTTM"),
        "roa": roa_val,
        "composite_score": composite,
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


def compute_ffd_features(
    prices: pd.DataFrame,
    d: float = 0.4,
    threshold: float = 1e-5,
) -> pd.DataFrame:
    """Compute fractionally differenced price features (FFD).

    Implements Fixed-Width Window Fractional Differencing from Lopez de Prado
    Ch. 5. Produces a stationary series that preserves long-term memory,
    unlike standard differencing which destroys it.

    Args:
        prices: DataFrame with a ``close`` column.
        d: Fractional differencing order. 0.4 is typically the minimum
            for stationarity while preserving memory.
        threshold: Minimum weight magnitude for truncation.

    Returns:
        DataFrame with ``ffd_close`` and ``ffd_return_1d`` columns.
    """
    close = prices["close"].values.astype(float)
    n = len(close)

    weights = [1.0]
    k = 1
    while True:
        w = -weights[-1] * (d - k + 1) / k
        if abs(w) < threshold:
            break
        weights.append(w)
        k += 1
    weights = np.array(weights)
    width = len(weights)

    ffd = np.full(n, np.nan)
    for i in range(width - 1, n):
        ffd[i] = np.dot(weights, close[i - width + 1 : i + 1])

    ffd_series = pd.Series(ffd, index=prices.index)
    ffd_return = ffd_series.pct_change(fill_method=None) * 100

    return pd.DataFrame(
        {"ffd_close": ffd_series, "ffd_return_1d": ffd_return},
        index=prices.index,
    )


def compute_triple_barrier_label(
    prices: pd.DataFrame,
    idx: int,
    atr_pct: float,
    profit_mult: float = 2.0,
    stop_mult: float = 1.0,
    max_horizon: int = 20,
) -> dict[str, Any]:
    """Compute triple-barrier label for path-dependent outcomes.

    Walks forward bar-by-bar from ``idx`` checking whether price hits
    the profit barrier (upper), stop-loss barrier (lower), or the
    vertical (time) barrier first.

    Args:
        prices: OHLCV DataFrame sorted by date.
        idx: Row index to label.
        atr_pct: ATR as percentage of price.
        profit_mult: Multiplier for upper barrier (profit target).
        stop_mult: Multiplier for lower barrier (stop-loss).
        max_horizon: Maximum bars to look forward (vertical barrier).

    Returns:
        Dict with ``triple_barrier_label``, ``barrier_type``,
        ``bars_to_barrier``, and ``risk_reward_ratio``.
    """
    close = prices["close"].values
    high = prices["high"].values if "high" in prices.columns else close
    low = prices["low"].values if "low" in prices.columns else close
    n = len(close)

    entry_price = close[idx]
    if atr_pct is None or atr_pct <= 0:
        atr_pct = 2.0

    upper = entry_price * (1 + profit_mult * atr_pct / 100)
    lower = entry_price * (1 - stop_mult * atr_pct / 100)

    for bar in range(1, min(max_horizon + 1, n - idx)):
        future_idx = idx + bar
        if high[future_idx] >= upper:
            return {
                "triple_barrier_label": 1,
                "barrier_type": "profit",
                "bars_to_barrier": bar,
                "risk_reward_ratio": profit_mult / stop_mult,
            }
        if low[future_idx] <= lower:
            return {
                "triple_barrier_label": 0,
                "barrier_type": "stop",
                "bars_to_barrier": bar,
                "risk_reward_ratio": profit_mult / stop_mult,
            }

    final_return = (close[min(idx + max_horizon, n - 1)] - entry_price) / entry_price
    return {
        "triple_barrier_label": 1 if final_return > 0 else 0,
        "barrier_type": "timeout",
        "bars_to_barrier": max_horizon,
        "risk_reward_ratio": profit_mult / stop_mult,
    }


def compute_tsfresh_features(
    prices: pd.DataFrame,
    idx: int,
    window: int = 20,
) -> dict[str, float]:
    """Extract automated statistical features via TSFresh.

    Uses the ``MinimalFCParameters`` subset (~30 features) on close
    and volume series from a rolling window ending at ``idx``.

    Args:
        prices: OHLCV DataFrame sorted by date.
        idx: Row index (end of window).
        window: Lookback window size.

    Returns:
        Dict of prefixed features (e.g. ``tsf_close_mean``).
    """
    try:
        from tsfresh import extract_features
        from tsfresh.feature_extraction import MinimalFCParameters
    except ImportError:
        return {}

    start = max(0, idx - window + 1)
    if idx - start < 5:
        return {}

    window_df = prices.iloc[start : idx + 1].copy()

    ts_input = pd.DataFrame(
        {
            "id": 0,
            "time": range(len(window_df)),
            "close": window_df["close"].values,
            "volume": window_df["volume"].values if "volume" in window_df.columns else 0.0,
        }
    )

    try:
        extracted = extract_features(
            ts_input,
            column_id="id",
            column_sort="time",
            default_fc_parameters=MinimalFCParameters(),
            disable_progressbar=True,
            n_jobs=0,
        )
        result: dict[str, float] = {}
        for col in extracted.columns:
            clean_name = col.replace("__", "_").replace('"', "")
            result[f"tsf_{clean_name}"] = float(extracted[col].iloc[0])
        return result
    except Exception:
        logger.debug("TSFresh extraction failed at idx=%d", idx, exc_info=True)
        return {}


def compute_primary_signal(
    prices: pd.DataFrame,
    indicators: pd.DataFrame,
    strategy_type: str,
    idx: int,
) -> dict[str, Any]:
    """Generate a rule-based primary trade signal for meta-labeling.

    Produces a directional signal (+1 long, -1 short, 0 neutral)
    based on classic strategy rules. The meta-labeler then decides
    whether to take each signal.

    Args:
        prices: OHLCV DataFrame.
        indicators: Indicator DataFrame with EMAs, RSI, etc.
        strategy_type: Strategy type string.
        idx: Row index to evaluate.

    Returns:
        Dict with ``primary_signal`` and ``signal_strength``.
    """
    close = prices["close"].values
    if idx < 21:
        return {"primary_signal": 0, "signal_strength": 0.0}

    signal = 0
    strength = 0.0

    if strategy_type in ("swing", "crypto_swing"):
        ema_9 = _safe_ema_at(indicators, "ema_9", idx)
        ema_21 = _safe_ema_at(indicators, "ema_21", idx)
        if ema_9 is not None and ema_21 is not None:
            if ema_9 > ema_21:
                signal = 1
                strength = min(1.0, (ema_9 - ema_21) / ema_21 * 100)
            elif ema_9 < ema_21:
                signal = -1
                strength = min(1.0, (ema_21 - ema_9) / ema_21 * 100)

    elif strategy_type == "mean_reversion":
        rsi = _safe_indicator_at(indicators, "rsi", idx)
        if rsi is not None:
            if rsi < 30:
                signal = 1
                strength = (30 - rsi) / 30
            elif rsi > 70:
                signal = -1
                strength = (rsi - 70) / 30

    elif strategy_type in ("value", "value_accumulation"):
        if idx > 0:
            ret_20 = (close[idx] - close[max(0, idx - 20)]) / close[max(0, idx - 20)]
            if ret_20 < -0.05:
                signal = 1
                strength = min(1.0, abs(ret_20) / 0.10)

    elif strategy_type in ("event", "earnings_play"):
        signal = 1
        strength = 0.5

    elif strategy_type in ("intraday", "crypto_intraday"):
        if idx >= 5:
            high_5 = float(np.max(prices["high"].values[idx - 5 : idx]))
            if close[idx] > high_5:
                signal = 1
                strength = min(1.0, (close[idx] - high_5) / high_5 * 100)

    return {"primary_signal": signal, "signal_strength": strength}


def _safe_ema_at(indicators: pd.DataFrame, col: str, idx: int) -> float | None:
    """Safely retrieve an EMA value at a given index."""
    if col not in indicators.columns or idx >= len(indicators):
        return None
    val = indicators[col].iloc[idx]
    return float(val) if pd.notna(val) else None


def _safe_indicator_at(indicators: pd.DataFrame, col: str, idx: int) -> float | None:
    """Safely retrieve an indicator value at a given index."""
    if col not in indicators.columns or idx >= len(indicators):
        return None
    val = indicators[col].iloc[idx]
    return float(val) if pd.notna(val) else None


def compute_outcome_labels(
    prices: pd.DataFrame,
    idx: int,
    atr_pct: float | None = None,
    horizons: list[int] | None = None,
    atr_threshold_multiplier: float | None = None,
) -> dict[str, Any]:
    """Compute forward-looking outcome labels for a given row index.

    Args:
        prices: OHLCV DataFrame sorted by date.
        idx: Row index to compute outcomes for.
        atr_pct: ATR as % of price (for stop-hit and threshold calculation).
        horizons: Bar horizons for return/direction labels. Defaults to ``[5, 10, 20]``.
        atr_threshold_multiplier: When set, the UP/DOWN threshold becomes
            ``atr_pct * multiplier`` instead of a fixed 2 %. Adapts labels
            to each asset's recent volatility.

    Returns:
        Dict with return_Xd, direction_Xd, MFE, MAE, stop_hit, profitable labels.
    """
    close = prices["close"].values
    high = prices["high"].values if "high" in prices.columns else close
    low = prices["low"].values if "low" in prices.columns else close
    n = len(close)

    effective_horizons = horizons or [5, 10, 20]

    threshold = 2.0
    if atr_pct is not None and atr_pct > 0 and atr_threshold_multiplier is not None:
        threshold = max(0.5, atr_pct * atr_threshold_multiplier)

    labels: dict[str, Any] = {}

    for horizon in effective_horizons:
        future_idx = idx + horizon
        if future_idx < n:
            ret = (close[future_idx] - close[idx]) / close[idx] * 100
            labels[f"return_{horizon}d"] = ret
            if ret > threshold:
                labels[f"direction_{horizon}d"] = "UP"
            elif ret < -threshold:
                labels[f"direction_{horizon}d"] = "DOWN"
            else:
                labels[f"direction_{horizon}d"] = "FLAT"
        else:
            labels[f"return_{horizon}d"] = None
            labels[f"direction_{horizon}d"] = None

    max_h = max(effective_horizons)
    max_horizon_idx = min(idx + max_h, n)
    if max_horizon_idx > idx:
        future_highs = high[idx + 1 : max_horizon_idx]
        future_lows = low[idx + 1 : max_horizon_idx]
        if len(future_highs) > 0:
            mfe = (float(np.max(future_highs)) - close[idx]) / close[idx] * 100
            mae = (float(np.min(future_lows)) - close[idx]) / close[idx] * 100
            labels["max_favorable_excursion"] = mfe
            labels["max_adverse_excursion"] = mae
            labels["profitable"] = 1 if mfe > abs(mae) else 0

            if atr_pct is not None and atr_pct > 0:
                stop_level = close[idx] * (1 - 2 * atr_pct / 100)
                labels["stop_hit"] = bool(float(np.min(future_lows)) < stop_level)
            else:
                labels["stop_hit"] = None
        else:
            labels["max_favorable_excursion"] = None
            labels["max_adverse_excursion"] = None
            labels["stop_hit"] = None
            labels["profitable"] = None
    else:
        labels["max_favorable_excursion"] = None
        labels["max_adverse_excursion"] = None
        labels["stop_hit"] = None
        labels["profitable"] = None

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


def _compute_composite_score(
    pe: float | None,
    roe: float | None,
    piotroski: float | None,
    altman_z: float | None,
) -> float | None:
    """Weighted quality composite from fundamental ratios.

    Components (each normalized to 0-1 range):
      - PE attractiveness (lower is better, capped 5-40): weight 0.25
      - ROE quality (higher is better, capped 0-0.40): weight 0.25
      - Piotroski score (0-9 scale): weight 0.30
      - Altman Z-score safety (>3 safe, <1.8 danger): weight 0.20
    """
    scores: list[float] = []
    weights: list[float] = []

    if pe is not None and pe > 0:
        pe_norm = max(0.0, min(1.0, (40 - pe) / 35))
        scores.append(pe_norm)
        weights.append(0.25)

    if roe is not None:
        roe_norm = max(0.0, min(1.0, roe / 0.40))
        scores.append(roe_norm)
        weights.append(0.25)

    if piotroski is not None:
        scores.append(piotroski / 9.0)
        weights.append(0.30)

    if altman_z is not None:
        z_norm = max(0.0, min(1.0, (altman_z - 1.0) / 4.0))
        scores.append(z_norm)
        weights.append(0.20)

    if not scores:
        return None

    total_w = sum(weights)
    return sum(s * w for s, w in zip(scores, weights)) / total_w


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


def compute_multi_timeframe_features(
    prices: pd.DataFrame,
    indicators: pd.DataFrame,
    timeframe_label: str,
    anchor_date: pd.Timestamp,
) -> dict[str, float | None]:
    """Compute summary features from an additional timeframe's data.

    For a given ticker and date, looks up the most recent data in the
    secondary timeframe and computes RSI, EMA position, EMA stack score,
    and momentum features.

    Args:
        prices: Price DataFrame for the secondary timeframe.
        indicators: Indicator DataFrame for the secondary timeframe.
        timeframe_label: Label for column prefixing (e.g. "4H", "W").
        anchor_date: Date to look up the most recent row for.

    Returns:
        Dict of prefixed features (e.g. ``tf_4H_rsi_14``).
    """
    prefix = f"tf_{timeframe_label}"
    result: dict[str, float | None] = {
        f"{prefix}_rsi_14": None,
        f"{prefix}_price_vs_ema_200": None,
        f"{prefix}_ema_stack_score": None,
        f"{prefix}_momentum_score": None,
    }

    if prices.empty:
        return result

    prices_dt = prices.copy()
    prices_dt["date"] = pd.to_datetime(prices_dt["date"])
    mask = prices_dt["date"] <= anchor_date
    if not mask.any():
        return result

    recent = prices_dt.loc[mask].iloc[-1]
    close = float(recent["close"])

    if not indicators.empty:
        ind_dt = indicators.copy()
        if "date" in ind_dt.columns:
            ind_dt["date"] = pd.to_datetime(ind_dt["date"])
            ind_mask = ind_dt["date"] <= anchor_date
            if ind_mask.any():
                ind_row = ind_dt.loc[ind_mask].iloc[-1]
                rsi = ind_row.get("rsi_14") or ind_row.get("rsi")
                if rsi is not None:
                    result[f"{prefix}_rsi_14"] = float(rsi)

    ema_200_col = None
    for col in ["ema_200", "EMA_200"]:
        if col in prices_dt.columns:
            ema_200_col = col
            break

    if ema_200_col is None and len(prices_dt) >= 200:
        prices_dt["_ema200"] = prices_dt["close"].ewm(span=200, min_periods=100).mean()
        ema_200_col = "_ema200"

    if ema_200_col is not None:
        ema_val = prices_dt.loc[mask, ema_200_col].iloc[-1]
        if pd.notna(ema_val) and ema_val > 0:
            result[f"{prefix}_price_vs_ema_200"] = (close - float(ema_val)) / float(ema_val)

    ema_vals = []
    for period in [9, 21, 50, 200]:
        col = f"ema_{period}"
        if col in prices_dt.columns:
            v = prices_dt.loc[mask, col].iloc[-1]
            if pd.notna(v):
                ema_vals.append(float(v))

    if len(ema_vals) >= 2:
        aligned = sum(1 for i in range(len(ema_vals) - 1) if ema_vals[i] > ema_vals[i + 1])
        result[f"{prefix}_ema_stack_score"] = aligned / (len(ema_vals) - 1)

    tail_20 = prices_dt.loc[mask].tail(20)
    if len(tail_20) >= 2:
        ret = (tail_20["close"].iloc[-1] - tail_20["close"].iloc[0]) / tail_20["close"].iloc[0]
        result[f"{prefix}_momentum_score"] = float(ret)

    return result


_ACTION_ENCODE = {
    "BUY": 1,
    "SHORT": -1,
    "HOLD": 0,
    "NO_TRADE": 0,
    "WATCH": 0,
}


def compute_llm_features(
    action: str,
    confidence: float | None,
    entry_price: float | None,
    stop_loss: float | None,
    take_profit: float | None,
    risk_reward_ratio: float | None = None,
    key_factors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, float | None]:
    """Encode GPT recommendation metadata as numeric ML features.

    These features capture the LLM pipeline's "opinion" so the meta-labeler
    can learn which GPT signals are worth following.

    Args:
        action: Recommendation action (BUY, SHORT, HOLD, NO_TRADE, WATCH).
        confidence: GPT confidence score (0-1).
        entry_price: Recommended entry price.
        stop_loss: Recommended stop-loss level.
        take_profit: Recommended take-profit level.
        risk_reward_ratio: Explicit R/R ratio from GPT.
        key_factors: List of key factors cited.
        warnings: List of warnings.

    Returns:
        Dict of LLM-derived numeric features.
    """
    action_encoded = _ACTION_ENCODE.get(action.upper() if action else "", 0)

    sl_dist = None
    tp_dist = None
    if entry_price and entry_price > 0:
        if stop_loss and stop_loss > 0:
            sl_dist = abs(entry_price - stop_loss) / entry_price * 100
        if take_profit and take_profit > 0:
            tp_dist = abs(take_profit - entry_price) / entry_price * 100

    computed_rr = None
    if sl_dist and tp_dist and sl_dist > 0:
        computed_rr = tp_dist / sl_dist

    return {
        "llm_action_encoded": float(action_encoded),
        "llm_confidence": float(confidence) if confidence is not None else None,
        "llm_rr_ratio": float(risk_reward_ratio) if risk_reward_ratio is not None else computed_rr,
        "llm_sl_distance_pct": sl_dist,
        "llm_tp_distance_pct": tp_dist,
        "llm_key_factor_count": float(len(key_factors)) if key_factors else 0.0,
        "llm_warning_count": float(len(warnings)) if warnings else 0.0,
    }


from ml_training.features.feature_spec import (  # noqa: E402
    CATEGORICAL_FEATURE_NAMES,
    TRAINING_ONLY_NAMES,
    is_training_only,
)

CATEGORICAL_FEATURES = CATEGORICAL_FEATURE_NAMES
TRAINING_ONLY_FEATURES = TRAINING_ONLY_NAMES
is_training_only_feature = is_training_only

# Re-export for backward compatibility
LLM_FEATURES: frozenset[str] = frozenset(
    {
        "llm_action_encoded",
        "llm_confidence",
        "llm_rr_ratio",
        "llm_sl_distance_pct",
        "llm_tp_distance_pct",
        "llm_key_factor_count",
        "llm_warning_count",
    }
)


def load_dead_features() -> frozenset[str]:
    """Load the auto-generated dead features list from disk.

    Returns an empty frozenset if the file doesn't exist yet.
    """
    from pathlib import Path

    dead_path = Path(__file__).resolve().parents[2] / "data" / "raw" / "dead_features.json"
    if not dead_path.exists():
        return frozenset()
    import json

    try:
        data = json.loads(dead_path.read_text())
        return frozenset(data.get("dead_features", []))
    except json.JSONDecodeError, KeyError:
        return frozenset()


_NEUTRALIZE_EXCLUDE = {
    "ticker",
    "date",
    "strategy_id",
    "strategy_type",
    "timeframe",
    "close",
    "market_regime",
    "sector",
    "day_of_week",
    "month",
    "profitable",
    "stop_hit",
    "max_favorable_excursion",
    "max_adverse_excursion",
    "triple_barrier_label",
    "barrier_type",
    "bars_to_barrier",
    "risk_reward_ratio",
    "primary_signal",
    "signal_strength",
    "hmm_regime",
}


def neutralize_features(df: pd.DataFrame) -> pd.DataFrame:
    """Z-score normalize numeric features within each date across tickers.

    This removes ticker-level identity from features.  After neutralization
    a feature value represents "how extreme is this reading relative to the
    cross-section today?" rather than an absolute level that the model can
    use to fingerprint individual tickers.

    Categorical and metadata columns are left untouched.  Dates with only
    a single ticker are set to 0 (no cross-section to compare against).
    """
    numeric_cols = [
        c
        for c in df.select_dtypes(include=[np.number]).columns
        if c not in _NEUTRALIZE_EXCLUDE
        and not c.startswith("return_")
        and not c.startswith("direction_")
    ]
    if not numeric_cols or "date" not in df.columns:
        return df

    df = df.copy()
    for col in numeric_cols:
        df[col] = df.groupby("date")[col].transform(
            lambda x: (x - x.mean()) / (x.std() + 1e-8) if len(x) > 1 else 0.0
        )
    return df


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
