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

from pipeline.schemas import (
    EMACross,
    EMASnapshot,
    MACDSnapshot,
    MultiTimeframeTechnical,
    RSISnapshot,
    TechnicalSnapshot,
    VolumeSnapshot,
)
from services.keyring_service import get_api_key

logger = logging.getLogger(__name__)

FMP_V3_BASE = "https://financialmodelingprep.com/api/v3"
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
    url = f"{FMP_V3_BASE}/technical_indicator/{timeframe}/{symbol}"
    params: dict[str, Any] = {
        "type": indicator_type,
        "period": period,
        "apikey": api_key,
    }
    try:
        async with _semaphore, httpx.AsyncClient(timeout=FMP_TIMEOUT) as client:
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
    """Fetch historical OHLCV candles from FMP.

    For daily data uses ``/api/v3/historical-price-full/{symbol}``.
    For intraday uses ``/api/v3/historical-chart/{timeframe}/{symbol}``.

    Args:
        symbol: Ticker symbol.
        timeframe: FMP timeframe string.
        limit: Number of candles.

    Returns:
        List of candle dicts sorted most-recent-first.
    """
    api_key = _get_api_key()
    if timeframe == "daily":
        url = f"{FMP_V3_BASE}/historical-price-full/{symbol}"
        params: dict[str, Any] = {"apikey": api_key, "serietype": "line"}
    else:
        url = f"{FMP_V3_BASE}/historical-chart/{timeframe}/{symbol}"
        params = {"apikey": api_key}

    try:
        async with _semaphore, httpx.AsyncClient(timeout=FMP_TIMEOUT) as client:
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
# Main orchestration — build a TechnicalSnapshot for one ticker+timeframe
# ---------------------------------------------------------------------------


async def build_technical_snapshot(
    symbol: str,
    timeframe: str,
) -> TechnicalSnapshot | None:
    """Fetch all indicators and build a TechnicalSnapshot for one ticker+timeframe.

    Fetches EMA (4 periods), RSI, MACD, ADX, and historical prices concurrently.
    Then computes derived signals: EMA crosses, trend alignment, momentum score,
    ATR, and volume analysis.

    Args:
        symbol: Ticker symbol (e.g. ``"AAPL"``).
        timeframe: Strategy-notation timeframe (e.g. ``"D"``, ``"4H"``, ``"1H"``).

    Returns:
        Validated TechnicalSnapshot, or None if critical data is missing.
    """
    fmp_tf = _map_timeframe(timeframe)

    ema_tasks = {
        period: _fetch_indicator_series(
            symbol, fmp_tf, "ema", period=period, limit=CROSS_LOOKBACK + 2
        )
        for period in EMA_PERIODS
    }
    tasks: dict[str, Any] = {
        "rsi": _fetch_indicator_series(symbol, fmp_tf, "rsi", period=14, limit=5),
        "macd": _fetch_indicator_series(symbol, fmp_tf, "macd", limit=5),
        "adx": _fetch_indicator_series(symbol, fmp_tf, "adx", period=14, limit=3),
        "candles": _fetch_historical_prices(symbol, fmp_tf, limit=25),
    }
    for period, coro in ema_tasks.items():
        tasks[f"ema_{period}"] = coro

    keys = list(tasks.keys())
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    fetched: dict[str, list[dict]] = {}
    for key, result in zip(keys, results, strict=False):
        if isinstance(result, Exception):
            logger.warning("Indicator fetch failed for %s/%s/%s: %s", symbol, fmp_tf, key, result)
            fetched[key] = []
        else:
            fetched[key] = result

    candles = fetched.get("candles", [])
    if not candles:
        logger.warning("No price data for %s/%s — cannot build snapshot", symbol, timeframe)
        return None

    # For intraday timeframes, candles[0] is the currently forming (incomplete)
    # bar whose partial close/high/low would contaminate indicators. Use the
    # most recently *completed* bar instead.
    latest = candles[1] if fmp_tf in _INTRADAY_FMP_TIMEFRAMES and len(candles) > 1 else candles[0]
    # Prefer split/dividend-adjusted close for equities (daily FMP endpoint
    # returns adjClose). This keeps inference aligned with training data which
    # uses yfinance auto_adjust=True.  For intraday or when adjClose is absent
    # (crypto), fall back to raw close.
    price_current = latest.get("adjClose") or latest.get("close") or latest.get("price", 0)
    if not price_current:
        return None

    ema_series_by_period: dict[int, list[dict]] = {
        period: fetched.get(f"ema_{period}", []) for period in EMA_PERIODS
    }
    emas = _build_ema_snapshots(ema_series_by_period)
    ema_crosses = _detect_ema_crosses(ema_series_by_period)
    macd = _build_macd_snapshot(fetched.get("macd", []))
    rsi = _build_rsi_snapshot(fetched.get("rsi", []))

    adx_series = fetched.get("adx", [])
    adx_val = 0.0
    if adx_series:
        adx_val = adx_series[0].get("adx", 0.0) or 0.0

    volume = _build_volume_snapshot(candles)
    atr = _compute_atr(candles)
    atr_pct = round(atr / price_current * 100, 4) if price_current else 0.0

    trend_alignment = _compute_trend_alignment(emas)
    momentum = compute_momentum_score(rsi, macd, emas, adx_val)

    return TechnicalSnapshot(
        ticker=symbol,
        timeframe=timeframe,
        timestamp=datetime.now(tz=UTC),
        price_current=round(price_current, 4),
        price_open=round(latest.get("open", price_current), 4),
        price_high=round(latest.get("high", price_current), 4),
        price_low=round(latest.get("low", price_current), 4),
        emas=emas,
        ema_crosses=ema_crosses,
        macd=macd,
        rsi=rsi,
        adx=round(adx_val, 2),
        atr=atr,
        atr_pct=atr_pct,
        volume=volume,
        trend_alignment=trend_alignment,
        momentum_score=momentum,
    )


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
