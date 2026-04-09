"""Numerical technical analysis service using the FMP Technical Indicators API.

Fetches pre-computed indicators (EMA, RSI, MACD, ADX, ATR) from FMP's v3
technical-indicator endpoint and structures them into rich
``TechnicalSnapshot`` objects with derived signals (EMA crosses, trend
alignment, momentum score).

Phase 1 of the pipeline overhaul: provides the numerical foundation that
replaces Claude's pixel-based chart guessing.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
import numpy as np

from pipeline.schemas import (
    EMACross,
    EMASnapshot,
    MACDSnapshot,
    MultiTimeframeTechnical,
    RSISnapshot,
    TechnicalSnapshot,
    VolumeSnapshot,
)
from services.http_clients import get_http_client
from services.keyring_service import get_api_key
from utils.ticker import to_fmp_symbol

logger = logging.getLogger(__name__)

FMP_V3_BASE = "https://financialmodelingprep.com/api/v3"
FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"
FMP_TIMEOUT = 30
_semaphore = asyncio.Semaphore(5)

EMA_PERIODS: list[int] = [9, 21, 50, 200]
CROSS_LOOKBACK = 10

# FMP timeframe strings accepted by the v3 technical-indicator endpoint
TIMEFRAME_MAP: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1H": "1hour",
    "4H": "4hour",
    "D": "daily",
    "W": "weekly",
    "M": "monthly",
}

_INTRADAY_FMP_TIMEFRAMES = frozenset({"1min", "5min", "15min", "30min", "1hour", "4hour"})


def _get_api_key() -> str:
    """Retrieve the FMP API key or raise."""
    key = get_api_key("fmp")
    if not key:
        raise RuntimeError(
            "FMP API key not configured. Set FMP_API_KEY in .env (see .env.example)."
        )
    return key


def _map_timeframe(tf: str) -> str:
    """Map strategy timeframe notation to FMP API timeframe string."""
    return TIMEFRAME_MAP.get(tf, tf)


# ---------------------------------------------------------------------------
# Low-level FMP fetchers
# ---------------------------------------------------------------------------


async def _fetch_indicator_series(
    symbol: str,
    timeframe: str,
    indicator_type: str,
    period: int = 14,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Fetch a series of indicator values from FMP v3.

    Args:
        symbol: Ticker symbol.
        timeframe: FMP timeframe string (e.g. ``"daily"``, ``"4hour"``).
        indicator_type: Indicator name (``"ema"``, ``"rsi"``, ``"macd"``, etc.).
        period: Lookback period for the indicator.
        limit: Number of data points to return.

    Returns:
        List of dicts sorted most-recent-first, or empty list on failure.
    """
    api_key = _get_api_key()
    fmp_sym = to_fmp_symbol(symbol)
    url = f"{FMP_V3_BASE}/technical_indicator/{timeframe}/{fmp_sym}"
    params: dict[str, Any] = {
        "type": indicator_type,
        "period": period,
        "apikey": api_key,
    }
    try:
        client = await get_http_client()
        async with _semaphore:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        if isinstance(data, list):
            return data[:limit]
    except Exception as exc:
        logger.debug(
            "Failed to fetch %s(%d) for %s/%s: %s", indicator_type, period, symbol, timeframe, exc
        )
    return []


async def _fetch_historical_prices(
    symbol: str,
    timeframe: str = "daily",
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Fetch historical OHLCV candles from FMP ``/stable/`` endpoints.

    For daily data uses ``/stable/historical-price-eod/full``.
    For intraday uses ``/stable/historical-chart/{timeframe}``.

    Both legacy v3 equivalents were deprecated Aug 2025 (403).

    Args:
        symbol: Ticker symbol.
        timeframe: FMP timeframe string (``"daily"``, ``"4hour"``, etc.).
        limit: Number of candles.

    Returns:
        List of candle dicts sorted most-recent-first.
    """
    api_key = _get_api_key()
    fmp_sym = to_fmp_symbol(symbol)
    if timeframe == "daily":
        url = f"{FMP_STABLE_BASE}/historical-price-eod/full"
    else:
        url = f"{FMP_STABLE_BASE}/historical-chart/{timeframe}"
    params: dict[str, Any] = {"symbol": fmp_sym, "apikey": api_key}

    try:
        client = await get_http_client()
        async with _semaphore:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if isinstance(data, dict) and "historical" in data:
            return data["historical"][:limit]
        if isinstance(data, list):
            return data[:limit]
    except Exception as exc:
        logger.debug("Failed to fetch historical prices for %s/%s: %s", symbol, timeframe, exc)
    return []


async def fetch_ohlcv_stable(
    symbol: str,
    limit: int = 300,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Fetch OHLCV candles from the FMP ``/stable/`` endpoint.

    Uses the new stable historical-price-eod endpoint which replaces
    the deprecated v3 ``historical-price-full`` endpoint (403 since Aug 2025).

    Args:
        symbol: Ticker symbol.
        limit: Maximum number of candles to return.
        client: Optional shared ``httpx.AsyncClient`` for batched calls.

    Returns:
        List of candle dicts sorted most-recent-first, or empty on failure.
    """
    api_key = _get_api_key()
    fmp_sym = to_fmp_symbol(symbol)
    url = f"{FMP_STABLE_BASE}/historical-price-eod/full"
    params: dict[str, Any] = {"symbol": fmp_sym, "apikey": api_key}

    try:
        hc = client or await get_http_client()
        async with _semaphore:
            resp = await hc.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data[:limit]
        if isinstance(data, dict) and "historical" in data:
            return data["historical"][:limit]
    except httpx.HTTPStatusError as exc:
        logger.warning("OHLCV stable HTTP %d for %s: %s", exc.response.status_code, symbol, exc)
    except Exception as exc:
        logger.debug("Failed to fetch OHLCV (stable) for %s: %s", symbol, exc)
    return []


# ---------------------------------------------------------------------------
# Derived signal computation
# ---------------------------------------------------------------------------


def _build_ema_snapshots(ema_series_by_period: dict[int, list[dict]]) -> list[EMASnapshot]:
    """Build EMASnapshot list from raw FMP EMA series.

    Args:
        ema_series_by_period: Mapping of EMA period → list of candle dicts
            (each with an ``ema`` key), sorted most-recent-first.

    Returns:
        List of EMASnapshot for each period with sufficient data.
    """
    snapshots: list[EMASnapshot] = []
    for period in EMA_PERIODS:
        series = ema_series_by_period.get(period, [])
        if len(series) < 2:
            continue
        current = series[0].get("ema")
        previous = series[1].get("ema")
        if current is None or previous is None:
            continue
        snapshots.append(EMASnapshot(period=period, current_value=current, previous_value=previous))
    return snapshots


def _detect_ema_crosses(
    ema_series_by_period: dict[int, list[dict]],
    lookback: int = CROSS_LOOKBACK,
) -> list[EMACross]:
    """Detect EMA crossover events within the lookback window.

    Compares every (fast, slow) pair in ``EMA_PERIODS`` across the last
    *lookback* candles. A cross is detected when fast EMA switches from
    below to above (bullish) or above to below (bearish) the slow EMA.

    Args:
        ema_series_by_period: Mapping of period → FMP EMA series.
        lookback: Number of candles to scan for crosses.

    Returns:
        List of detected EMACross events.
    """
    crosses: list[EMACross] = []
    for i, fast_period in enumerate(EMA_PERIODS[:-1]):
        for slow_period in EMA_PERIODS[i + 1 :]:
            fast_series = ema_series_by_period.get(fast_period, [])
            slow_series = ema_series_by_period.get(slow_period, [])
            scan_len = min(len(fast_series), len(slow_series), lookback)
            if scan_len < 2:
                continue

            for j in range(1, scan_len):
                fn = fast_series[j - 1].get("ema")
                fp = fast_series[j].get("ema")
                sn = slow_series[j - 1].get("ema")
                sp = slow_series[j].get("ema")
                if fn is None or fp is None or sn is None or sp is None:
                    continue
                fast_now: float = float(fn)
                fast_prev: float = float(fp)
                slow_now: float = float(sn)
                slow_prev: float = float(sp)

                was_below = fast_prev < slow_prev
                is_above = fast_now > slow_now

                if was_below and is_above:
                    cross_type = "bullish"
                elif not was_below and not is_above:
                    cross_type = "bearish"
                else:
                    continue

                current_fast = fast_series[0].get("ema", fast_now)
                current_slow = slow_series[0].get("ema", slow_now)
                spread_pct = (
                    abs(current_fast - current_slow) / current_slow * 100 if current_slow else 0.0
                )

                prev_spread = abs(fast_now - slow_now) / slow_now * 100 if slow_now else 0.0
                spread_direction = "widening" if spread_pct > prev_spread else "narrowing"

                crosses.append(
                    EMACross(
                        fast_period=fast_period,
                        slow_period=slow_period,
                        cross_type=cross_type,
                        candles_ago=j,
                        spread_pct=round(spread_pct, 4),
                        spread_direction=spread_direction,
                    )
                )
                break  # only report the most recent cross per pair
    return crosses


def _build_macd_snapshot(macd_series: list[dict]) -> MACDSnapshot | None:
    """Build MACDSnapshot from FMP MACD series.

    FMP returns MACD data with keys ``macd``, ``signal``, and ``histogram``
    (actual key names may vary — we check common variants).

    Args:
        macd_series: FMP MACD series sorted most-recent-first.

    Returns:
        MACDSnapshot or None if data is insufficient.
    """
    if len(macd_series) < 2:
        return None

    curr = macd_series[0]
    prev = macd_series[1]

    macd_raw = curr.get("macd")
    signal_raw = curr.get("signal")
    hist_raw = curr.get("histogram")
    prev_hist_raw = prev.get("histogram")

    if macd_raw is None or signal_raw is None or hist_raw is None:
        return None

    macd_val: float = float(macd_raw)
    signal_val: float = float(signal_raw)
    hist_val: float = float(hist_raw)
    prev_hist: float = float(prev_hist_raw) if prev_hist_raw is not None else 0.0

    hist_slope: Literal["expanding", "contracting"] = (
        "expanding" if abs(hist_val) > abs(prev_hist) else "contracting"
    )
    sig_cross: Literal["above", "below"] = "above" if macd_val > signal_val else "below"

    return MACDSnapshot(
        macd_line=round(macd_val, 4),
        signal_line=round(signal_val, 4),
        histogram=round(hist_val, 4),
        histogram_slope=hist_slope,
        signal_cross=sig_cross,
    )


def _build_rsi_snapshot(rsi_series: list[dict]) -> RSISnapshot | None:
    """Build RSISnapshot from FMP RSI series.

    Args:
        rsi_series: FMP RSI series sorted most-recent-first.

    Returns:
        RSISnapshot or None if data is insufficient.
    """
    if len(rsi_series) < 2:
        return None

    current = rsi_series[0].get("rsi")
    previous = rsi_series[1].get("rsi")
    if current is None or previous is None:
        return None

    return RSISnapshot(
        current=round(current, 2),
        previous=round(previous, 2),
        trend="flat",
        zone="neutral",
        divergence="none",
    )


def _build_volume_snapshot(candles: list[dict]) -> VolumeSnapshot | None:
    """Build VolumeSnapshot from historical price candles.

    Args:
        candles: OHLCV candles sorted most-recent-first (need >= 21).

    Returns:
        VolumeSnapshot or None if data is insufficient.
    """
    if not candles:
        return None

    current_vol = candles[0].get("volume")
    if current_vol is None:
        return None

    volumes = [c.get("volume", 0) for c in candles[:21] if c.get("volume") is not None]
    if len(volumes) < 2:
        return VolumeSnapshot(current=int(current_vol), avg_20=float(current_vol), ratio=1.0)

    avg_20 = sum(volumes[1:21]) / len(volumes[1:21])

    recent_3 = volumes[:3]
    older_3 = volumes[3:6] if len(volumes) >= 6 else volumes[1:4]
    if recent_3 and older_3:
        recent_avg = sum(recent_3) / len(recent_3)
        older_avg = sum(older_3) / len(older_3)
        if recent_avg > older_avg * 1.1:
            vol_trend = "increasing"
        elif recent_avg < older_avg * 0.9:
            vol_trend = "decreasing"
        else:
            vol_trend = "stable"
    else:
        vol_trend = "stable"

    return VolumeSnapshot(
        current=int(current_vol),
        avg_20=round(avg_20, 2),
        trend=vol_trend,
    )


def _compute_trend_alignment(
    emas: list[EMASnapshot],
) -> Literal["all_bullish", "all_bearish", "mixed"]:
    """Check whether EMAs are stacked in bullish or bearish order.

    Bullish: 9 > 21 > 50 > 200. Bearish: reverse. Anything else is mixed.

    Args:
        emas: List of EMASnapshot sorted by period ascending.

    Returns:
        ``"all_bullish"``, ``"all_bearish"``, or ``"mixed"``.
    """
    if len(emas) < 2:
        return "mixed"

    sorted_emas = sorted(emas, key=lambda e: e.period)
    is_bullish = all(
        sorted_emas[i].current_value > sorted_emas[i + 1].current_value
        for i in range(len(sorted_emas) - 1)
    )
    is_bearish = all(
        sorted_emas[i].current_value < sorted_emas[i + 1].current_value
        for i in range(len(sorted_emas) - 1)
    )

    if is_bullish:
        return "all_bullish"
    if is_bearish:
        return "all_bearish"
    return "mixed"


def compute_momentum_score(
    rsi: RSISnapshot | None,
    macd: MACDSnapshot | None,
    emas: list[EMASnapshot],
    adx: float,
) -> float:
    """Weighted composite momentum score, range -1.0 to +1.0.

    Starting weights (Phase 6 feedback loop tunes over time):
    RSI 0.25, MACD 0.25, EMA spread 0.30, ADX 0.20.

    Args:
        rsi: Current RSI snapshot (None treated as neutral).
        macd: Current MACD snapshot (None treated as neutral).
        emas: EMA snapshots sorted by period ascending.
        adx: Current ADX value.

    Returns:
        Momentum score clamped to [-1.0, +1.0].
    """
    rsi_component = 0.0
    if rsi:
        rsi_component = (rsi.current - 50) / 50

    macd_component = 0.0
    if macd:
        macd_component = 1.0 if macd.histogram > 0 else -1.0
        if macd.histogram_slope == "contracting":
            macd_component *= 0.5

    ema_spread_component = 0.0
    if len(emas) >= 2:
        sorted_emas = sorted(emas, key=lambda e: e.period)
        bullish_pairs = sum(
            1
            for i in range(len(sorted_emas) - 1)
            if sorted_emas[i].current_value > sorted_emas[i + 1].current_value
        )
        ema_spread_component = (bullish_pairs / max(len(sorted_emas) - 1, 1)) * 2 - 1

    adx_component = min(adx / 50, 1.0)

    score = (
        rsi_component * 0.25
        + macd_component * 0.25
        + ema_spread_component * 0.30
        + adx_component * 0.20
    )
    return max(-1.0, min(1.0, round(score, 4)))


def _compute_atr(candles: list[dict], period: int = 14) -> float:
    """Compute Average True Range from OHLCV candles.

    Args:
        candles: OHLCV candles sorted most-recent-first.
        period: ATR period (default 14).

    Returns:
        ATR value, or 0.0 if insufficient data.
    """
    if len(candles) < period + 1:
        return 0.0

    true_ranges: list[float] = []
    for i in range(period):
        c = candles[i]
        prev_c = candles[i + 1]
        high = c.get("high", 0)
        low = c.get("low", 0)
        prev_close = prev_c.get("close", 0)
        if high and low and prev_close:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)

    return round(sum(true_ranges) / len(true_ranges), 4) if true_ranges else 0.0


# ---------------------------------------------------------------------------
# Local indicator computation (numpy — replaces deprecated FMP v3 endpoints)
# ---------------------------------------------------------------------------


def _np_ema(data: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average over chronologically-ordered data.

    Args:
        data: 1-D array of prices in chronological order (oldest first).
        period: EMA period.

    Returns:
        Array of same length with EMA values.
    """
    k = 2.0 / (period + 1)
    ema = np.empty(len(data), dtype=np.float64)
    ema[0] = float(data[0])
    for i in range(1, len(data)):
        ema[i] = float(data[i]) * k + ema[i - 1] * (1.0 - k)
    return ema


def _np_rsi(closes: np.ndarray, period: int = 14) -> tuple[float, float]:
    """Wilder-smoothed RSI from chronologically-ordered closes.

    Args:
        closes: Close prices, oldest first.
        period: RSI lookback (default 14).

    Returns:
        ``(current_rsi, previous_rsi)`` tuple.
    """
    if len(closes) < period + 2:
        return 50.0, 50.0

    deltas = np.diff(closes)
    gains = np.maximum(deltas, 0.0)
    losses = np.maximum(-deltas, 0.0)

    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    prev_rsi = 50.0
    current_rsi = 50.0

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + float(gains[i])) / period
        avg_loss = (avg_loss * (period - 1) + float(losses[i])) / period

        rsi_val = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

        if i == len(gains) - 2:
            prev_rsi = rsi_val
        if i == len(gains) - 1:
            current_rsi = rsi_val

    return current_rsi, prev_rsi


def _np_macd(
    closes: np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[float, float, float, float]:
    """MACD from chronologically-ordered closes.

    Args:
        closes: Close prices, oldest first.
        fast: Fast EMA period.
        slow: Slow EMA period.
        signal_period: Signal line EMA period.

    Returns:
        ``(macd_line, signal_line, histogram, prev_histogram)`` tuple.
    """
    if len(closes) < slow + signal_period:
        return 0.0, 0.0, 0.0, 0.0

    ema_fast = _np_ema(closes, fast)
    ema_slow = _np_ema(closes, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _np_ema(macd_line, signal_period)
    histogram = macd_line - signal_line

    return (
        float(macd_line[-1]),
        float(signal_line[-1]),
        float(histogram[-1]),
        float(histogram[-2]) if len(histogram) > 1 else 0.0,
    )


def _np_adx(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> float:
    """Average Directional Index via Wilder smoothing.

    Args:
        highs: High prices, oldest first.
        lows: Low prices, oldest first.
        closes: Close prices, oldest first.
        period: ADX period (default 14).

    Returns:
        Latest ADX value, or 0.0 if insufficient data.
    """
    n = len(closes)
    if n < period + 2:
        return 0.0

    tr = np.empty(n - 1)
    plus_dm = np.empty(n - 1)
    minus_dm = np.empty(n - 1)

    for i in range(1, n):
        j = i - 1
        hl = float(highs[i] - lows[i])
        hpc = abs(float(highs[i] - closes[i - 1]))
        lpc = abs(float(lows[i] - closes[i - 1]))
        tr[j] = max(hl, hpc, lpc)

        up = float(highs[i] - highs[i - 1])
        down = float(lows[i - 1] - lows[i])
        plus_dm[j] = up if up > down and up > 0 else 0.0
        minus_dm[j] = down if down > up and down > 0 else 0.0

    atr_s = float(np.mean(tr[:period]))
    pdm_s = float(np.mean(plus_dm[:period]))
    mdm_s = float(np.mean(minus_dm[:period]))

    dx_values: list[float] = []
    for i in range(period, len(tr)):
        atr_s = (atr_s * (period - 1) + float(tr[i])) / period
        pdm_s = (pdm_s * (period - 1) + float(plus_dm[i])) / period
        mdm_s = (mdm_s * (period - 1) + float(minus_dm[i])) / period

        if atr_s == 0:
            continue
        pdi = 100.0 * pdm_s / atr_s
        mdi = 100.0 * mdm_s / atr_s
        di_sum = pdi + mdi
        dx = 100.0 * abs(pdi - mdi) / di_sum if di_sum > 0 else 0.0
        dx_values.append(dx)

    if not dx_values:
        return 0.0

    adx = (
        float(np.mean(dx_values[:period]))
        if len(dx_values) >= period
        else float(np.mean(dx_values))
    )
    for i in range(period, len(dx_values)):
        adx = (adx * (period - 1) + dx_values[i]) / period

    return adx


def build_snapshot_from_ohlcv(
    symbol: str,
    timeframe: str,
    candles: list[dict[str, Any]],
    *,
    skip_first_bar: bool = False,
) -> TechnicalSnapshot | None:
    """Build a ``TechnicalSnapshot`` from raw OHLCV candles using local numpy computation.

    Replaces the deprecated FMP v3 indicator API calls with local EMA, RSI,
    MACD, and ADX calculation.  ATR and volume analysis reuse the existing
    candle-based helpers.

    Args:
        symbol: Ticker symbol.
        timeframe: Strategy-notation timeframe (e.g. ``"D"``).
        candles: OHLCV candle dicts sorted **most-recent-first** (FMP order).
        skip_first_bar: If ``True``, skip the first (currently forming)
            intraday bar.

    Returns:
        Validated ``TechnicalSnapshot``, or ``None`` if data is insufficient.
    """
    if skip_first_bar and len(candles) > 1:
        candles = candles[1:]

    if len(candles) < 30:
        logger.warning("Insufficient OHLCV data for %s (%d bars)", symbol, len(candles))
        return None

    chrono = list(reversed(candles))
    closes = np.array(
        [float(c.get("adjClose") or c.get("close") or 0) for c in chrono],
        dtype=np.float64,
    )
    highs = np.array([float(c.get("high") or 0) for c in chrono], dtype=np.float64)
    lows = np.array([float(c.get("low") or 0) for c in chrono], dtype=np.float64)

    if closes[-1] == 0:
        return None

    latest = candles[0]
    price_current = float(latest.get("adjClose") or latest.get("close") or 0)
    if not price_current:
        return None

    # -- EMA --
    ema_snapshots: list[EMASnapshot] = []
    ema_series_by_period: dict[int, list[dict]] = {}
    for period in EMA_PERIODS:
        if len(closes) < period:
            continue
        ema_vals = _np_ema(closes, period)
        ema_snapshots.append(
            EMASnapshot(
                period=period,
                current_value=round(float(ema_vals[-1]), 4),
                previous_value=round(float(ema_vals[-2]), 4),
            )
        )
        n_cross = min(CROSS_LOOKBACK + 2, len(ema_vals))
        ema_series_by_period[period] = [{"ema": float(ema_vals[-(i + 1)])} for i in range(n_cross)]

    ema_crosses = _detect_ema_crosses(ema_series_by_period)

    # -- RSI --
    rsi_current, rsi_previous = _np_rsi(closes)
    rsi_snap = RSISnapshot(
        current=round(rsi_current, 2),
        previous=round(rsi_previous, 2),
        trend="flat",
        zone="neutral",
        divergence="none",
    )

    # -- MACD --
    macd_line, signal_val, hist, prev_hist = _np_macd(closes)
    hist_slope: Literal["expanding", "contracting"] = (
        "expanding" if abs(hist) > abs(prev_hist) else "contracting"
    )
    sig_cross: Literal["above", "below"] = "above" if macd_line > signal_val else "below"
    macd_snap = MACDSnapshot(
        macd_line=round(macd_line, 4),
        signal_line=round(signal_val, 4),
        histogram=round(hist, 4),
        histogram_slope=hist_slope,
        signal_cross=sig_cross,
    )

    # -- ADX --
    adx_val = _np_adx(highs, lows, closes)

    # -- Volume & ATR (existing helpers, most-recent-first candles) --
    volume = _build_volume_snapshot(candles)
    atr = _compute_atr(candles)
    atr_pct = round(atr / price_current * 100, 4) if price_current else 0.0

    # -- Derived signals --
    trend_alignment = _compute_trend_alignment(ema_snapshots)
    momentum = compute_momentum_score(rsi_snap, macd_snap, ema_snapshots, adx_val)

    return TechnicalSnapshot(
        ticker=symbol,
        timeframe=timeframe,
        timestamp=datetime.now(tz=UTC),
        price_current=round(price_current, 4),
        price_open=round(float(latest.get("open") or price_current), 4),
        price_high=round(float(latest.get("high") or price_current), 4),
        price_low=round(float(latest.get("low") or price_current), 4),
        emas=ema_snapshots,
        ema_crosses=ema_crosses,
        macd=macd_snap,
        rsi=rsi_snap,
        adx=round(adx_val, 2),
        atr=atr,
        atr_pct=atr_pct,
        volume=volume,
        trend_alignment=trend_alignment,
        momentum_score=momentum,
    )


# ---------------------------------------------------------------------------
# Main orchestration — build a TechnicalSnapshot for one ticker+timeframe
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Multi-timeframe helpers for the scanner (weekly from daily, intraday fetch)
# ---------------------------------------------------------------------------


def aggregate_daily_to_weekly(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate daily candle dicts into weekly bars (ISO week grouping).

    Args:
        candles: Daily OHLCV dicts sorted most-recent-first.

    Returns:
        Weekly OHLCV dicts sorted most-recent-first.
    """

    weekly: dict[tuple[int, int], dict[str, Any]] = {}
    order: list[tuple[int, int]] = []

    for c in reversed(candles):
        date_str = c.get("date", "")
        if not date_str:
            continue
        try:
            dt = datetime.fromisoformat(str(date_str)[:10])
        except ValueError, TypeError:
            continue

        key = dt.isocalendar()[:2]
        close = float(c.get("adjClose") or c.get("close") or 0)
        high = float(c.get("high") or 0)
        low = float(c.get("low") or 0)
        opn = float(c.get("open") or 0)
        vol = int(c.get("volume") or 0)

        if key not in weekly:
            weekly[key] = {
                "date": date_str,
                "open": opn,
                "high": high,
                "low": low,
                "close": close,
                "adjClose": close,
                "volume": vol,
            }
            order.append(key)
        else:
            bar = weekly[key]
            bar["high"] = max(bar["high"], high)
            bar["low"] = min(bar["low"], low)
            bar["close"] = close
            bar["adjClose"] = close
            bar["volume"] += vol
            bar["date"] = date_str

    return [weekly[k] for k in reversed(order)]


def compute_tf_features(candles: list[dict[str, Any]], label: str) -> dict[str, float | None]:
    """Compute the 4 timeframe-prefixed features from OHLCV candles.

    Produces ``tf_{label}_rsi_14``, ``tf_{label}_price_vs_ema_200``,
    ``tf_{label}_ema_stack_score``, and ``tf_{label}_momentum_score``.

    Args:
        candles: OHLCV dicts sorted most-recent-first (at least 30 bars).
        label: Timeframe label (``"W"`` or ``"4H"``).

    Returns:
        Dict of 4 features keyed with ``tf_{label}_`` prefix.
        Missing features are ``None``.
    """
    prefix = f"tf_{label}_"
    result: dict[str, float | None] = {
        f"{prefix}rsi_14": None,
        f"{prefix}price_vs_ema_200": None,
        f"{prefix}ema_stack_score": None,
        f"{prefix}momentum_score": None,
    }

    if not candles or len(candles) < 20:
        return result

    chrono = list(reversed(candles))
    closes = np.array(
        [float(c.get("adjClose") or c.get("close") or 0) for c in chrono],
        dtype=np.float64,
    )

    if closes[-1] == 0:
        return result

    rsi_cur, _ = _np_rsi(closes)
    result[f"{prefix}rsi_14"] = round(rsi_cur, 2)

    if len(closes) >= 200:
        ema200 = _np_ema(closes, 200)
        ema200_val = float(ema200[-1])
        if ema200_val > 0:
            result[f"{prefix}price_vs_ema_200"] = round(
                (float(closes[-1]) - ema200_val) / ema200_val * 100, 4
            )

    ema_vals: dict[int, float] = {}
    for period in EMA_PERIODS:
        if len(closes) >= period:
            ema_arr = _np_ema(closes, period)
            ema_vals[period] = float(ema_arr[-1])

    if len(ema_vals) >= 2:
        sorted_periods = sorted(ema_vals.keys())
        bullish_pairs = sum(
            1
            for i in range(len(sorted_periods) - 1)
            if ema_vals[sorted_periods[i]] > ema_vals[sorted_periods[i + 1]]
        )
        total_pairs = max(len(sorted_periods) - 1, 1)
        result[f"{prefix}ema_stack_score"] = round(bullish_pairs / total_pairs * 4.0, 2)

    if len(closes) >= 20:
        momentum = (float(closes[-1]) - float(closes[-20])) / float(closes[-20]) * 100
        result[f"{prefix}momentum_score"] = round(momentum, 4)

    return result


def compute_extra_daily_features(candles: list[dict[str, Any]]) -> dict[str, float | None]:
    """Compute daily features that the ML models expect but the scanner didn't previously supply.

    Covers ``price_change_1d``, ``price_change_5d``, ``price_change_20d``,
    ``bollinger_width``, ``volatility_20d``, ``high_low_range``, and ``gap_pct``.

    Args:
        candles: Daily OHLCV dicts sorted most-recent-first.

    Returns:
        Dict of extra feature values. Missing features are ``None``.
    """
    result: dict[str, float | None] = {
        "price_change_1d": None,
        "price_change_5d": None,
        "price_change_20d": None,
        "bollinger_width": None,
        "volatility_20d": None,
        "high_low_range": None,
        "gap_pct": None,
    }

    if not candles or len(candles) < 2:
        return result

    latest = candles[0]
    close = float(latest.get("adjClose") or latest.get("close") or 0)
    high = float(latest.get("high") or 0)
    low = float(latest.get("low") or 0)
    opn = float(latest.get("open") or 0)

    if close == 0:
        return result

    prev_close = float(candles[1].get("adjClose") or candles[1].get("close") or 0)
    if prev_close > 0:
        result["price_change_1d"] = round((close - prev_close) / prev_close * 100, 4)
        result["gap_pct"] = round((opn - prev_close) / prev_close * 100, 4)

    if high > 0 and low > 0:
        result["high_low_range"] = round((high - low) / close * 100, 4)

    if len(candles) >= 6:
        close_5d = float(candles[5].get("adjClose") or candles[5].get("close") or 0)
        if close_5d > 0:
            result["price_change_5d"] = round((close - close_5d) / close_5d * 100, 4)

    if len(candles) >= 21:
        close_20d = float(candles[20].get("adjClose") or candles[20].get("close") or 0)
        if close_20d > 0:
            result["price_change_20d"] = round((close - close_20d) / close_20d * 100, 4)

        chrono = list(reversed(candles[:21]))
        closes_arr = np.array(
            [float(c.get("adjClose") or c.get("close") or 0) for c in chrono],
            dtype=np.float64,
        )
        sma20 = float(np.mean(closes_arr[-20:]))
        std20 = float(np.std(closes_arr[-20:]))
        if sma20 > 0:
            result["bollinger_width"] = round((2 * std20 / sma20) * 100, 4)

        daily_returns = np.diff(closes_arr) / closes_arr[:-1]
        result["volatility_20d"] = round(float(np.std(daily_returns[-20:])) * 100, 4)

    return result


async def fetch_intraday_ohlcv(
    symbol: str,
    timeframe: str = "4hour",
    limit: int = 200,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Fetch intraday OHLCV candles from the FMP ``/stable/`` endpoint.

    Uses ``/stable/historical-chart/{timeframe}`` with ``symbol`` as a query
    parameter.  The legacy v3 path-based endpoint was deprecated Aug 2025.

    Args:
        symbol: Ticker symbol.
        timeframe: FMP timeframe (``"4hour"``, ``"1hour"``, etc.).
        limit: Maximum candles to return.
        client: Optional shared ``httpx.AsyncClient``.

    Returns:
        List of candle dicts sorted most-recent-first, or empty on failure.
    """
    api_key = _get_api_key()
    fmp_sym = to_fmp_symbol(symbol)
    url = f"{FMP_STABLE_BASE}/historical-chart/{timeframe}"
    params: dict[str, Any] = {"symbol": fmp_sym, "apikey": api_key}

    try:
        hc = client or await get_http_client()
        async with _semaphore:
            resp = await hc.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data[:limit]
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Intraday OHLCV HTTP %d for %s/%s: %s",
            exc.response.status_code,
            symbol,
            timeframe,
            exc,
        )
    except Exception as exc:
        logger.debug("Failed to fetch intraday OHLCV for %s/%s: %s", symbol, timeframe, exc)
    return []


async def build_technical_snapshot(
    symbol: str,
    timeframe: str,
) -> TechnicalSnapshot | None:
    """Fetch OHLCV and build a TechnicalSnapshot using local numpy computation.

    Fetches historical candles (1 API call) from the FMP ``/stable/`` endpoint
    for both daily and intraday data, then computes all indicators locally
    (EMA, RSI, MACD, ADX, ATR, volume).

    Args:
        symbol: Ticker symbol (e.g. ``"AAPL"``).
        timeframe: Strategy-notation timeframe (e.g. ``"D"``, ``"4H"``, ``"1H"``).

    Returns:
        Validated TechnicalSnapshot, or None if critical data is missing.
    """
    fmp_tf = _map_timeframe(timeframe)
    is_intraday = fmp_tf in _INTRADAY_FMP_TIMEFRAMES

    if is_intraday:
        candles = await _fetch_historical_prices(symbol, fmp_tf, limit=300)
    else:
        candles = await fetch_ohlcv_stable(symbol, limit=300)

    if not candles:
        logger.warning("No OHLCV data for %s/%s — cannot build snapshot", symbol, timeframe)
        return None

    return build_snapshot_from_ohlcv(symbol, timeframe, candles, skip_first_bar=is_intraday)


# ---------------------------------------------------------------------------
# Multi-timeframe aggregation
# ---------------------------------------------------------------------------


def _compute_timeframe_alignment(
    primary: TechnicalSnapshot,
    others: list[TechnicalSnapshot],
) -> Literal["aligned_bullish", "aligned_bearish", "divergent"]:
    """Determine whether timeframes agree on direction.

    Args:
        primary: The primary timeframe snapshot.
        others: Additional/short timeframe snapshots.

    Returns:
        ``"aligned_bullish"``, ``"aligned_bearish"``, or ``"divergent"``.
    """
    all_snapshots = [primary, *others]
    scores = [s.momentum_score for s in all_snapshots]

    if all(s > 0.1 for s in scores):
        return "aligned_bullish"
    if all(s < -0.1 for s in scores):
        return "aligned_bearish"
    return "divergent"


async def build_multi_timeframe(
    symbol: str,
    primary_tf: str,
    additional_tfs: list[str],
    short_tfs: list[str] | None = None,
) -> MultiTimeframeTechnical | None:
    """Build a MultiTimeframeTechnical for one ticker across all timeframes.

    Fetches all timeframes concurrently, then computes cross-timeframe alignment.

    Args:
        symbol: Ticker symbol.
        primary_tf: Primary strategy timeframe (e.g. ``"4H"``).
        additional_tfs: Additional timeframes (e.g. ``["D", "W"]``).
        short_tfs: Short timeframes (e.g. ``["15m", "1H"]``).

    Returns:
        MultiTimeframeTechnical, or None if the primary timeframe fails.
    """
    all_tfs = [primary_tf] + [tf for tf in additional_tfs if tf != primary_tf]
    if short_tfs:
        all_tfs += [tf for tf in short_tfs if tf not in all_tfs]

    tasks = [build_technical_snapshot(symbol, tf) for tf in all_tfs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    snapshots: dict[str, TechnicalSnapshot] = {}
    for tf, result in zip(all_tfs, results, strict=False):
        if isinstance(result, Exception):
            logger.warning("TA snapshot failed for %s/%s: %s", symbol, tf, result)
        elif result is not None:
            snapshots[tf] = result

    primary = snapshots.get(primary_tf)
    if not primary:
        logger.warning("Primary timeframe %s failed for %s — skipping ticker", primary_tf, symbol)
        return None

    additional = [snapshots[tf] for tf in additional_tfs if tf in snapshots and tf != primary_tf]
    short = [snapshots[tf] for tf in (short_tfs or []) if tf in snapshots]

    alignment = _compute_timeframe_alignment(primary, additional + short)

    return MultiTimeframeTechnical(
        ticker=symbol,
        primary=primary,
        additional=additional,
        short=short,
        timeframe_alignment=alignment,
    )
