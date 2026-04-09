"""Binance public API wrapper for crypto universe discovery and OHLCV data.

Replaces the FMP crypto endpoints (paywalled at 402/404) with Binance's
free, unauthenticated REST API.  Provides two entry points:

- ``fetch_crypto_universe_binance`` — single ``ticker/24hr`` call for top
  crypto tickers ranked by 24h USDT quote volume.
- ``fetch_crypto_ohlcv_binance`` — per-symbol ``klines`` call returning
  candle dicts in the same shape that ``build_snapshot_from_ohlcv`` expects.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BINANCE_BASE_URL = "https://api.binance.com/api/v3"
BINANCE_TIMEOUT = 20

_EXCLUDED_BASES: frozenset[str] = frozenset(
    {
        "USDC",
        "USDT",
        "DAI",
        "BUSD",
        "TUSD",
        "FDUSD",
        "USD1",
        "USDP",
        "PYUSD",
        "GUSD",
        "FRAX",
        "LUSD",
        "SUSD",
        "CUSD",
        "EUSD",
        "USDD",
        "CEUR",
        "EUR",
        "GBP",
        "AUD",
        "JPY",
        "TRY",
        "BRL",
        "ARS",
        "PLN",
        "RON",
        "UAH",
        "BFUSD",
        "WBTC",
        "RLUSD",
        "XAUT",
        "PAXG",
        "AEUR",
    }
)

_LEVERAGED_TOKENS: frozenset[str] = frozenset(
    {
        "UP",
        "DOWN",
        "BULL",
        "BEAR",
    }
)

_semaphore = asyncio.Semaphore(10)


def _is_noise_symbol(symbol: str) -> bool:
    """Return True for stablecoins, leveraged tokens, forex, and other noise pairs."""
    base = symbol.removesuffix("USDT")
    if not base:
        return True
    if base in _EXCLUDED_BASES:
        return True
    if any(tok in base for tok in _LEVERAGED_TOKENS):
        return True
    return not base.isascii()


async def fetch_crypto_universe_binance(
    *,
    min_quote_volume: float = 1_000_000,
    limit: int = 50,
) -> tuple[list[str], dict[str, str]]:
    """Fetch top crypto tickers from Binance ranked by 24h USDT volume.

    Args:
        min_quote_volume: Minimum 24h USDT quote volume to include.
        limit: Maximum number of tickers to return.

    Returns:
        Tuple of (display_tickers, binance_map) where display_tickers is a
        list like ``["BTC", "ETH", ...]`` and binance_map maps display
        ticker -> Binance symbol (``{"BTC": "BTCUSDT", ...}``).
    """
    try:
        from services.http_clients import get_http_client

        client = await get_http_client()
        resp = await client.get(f"{BINANCE_BASE_URL}/ticker/24hr")
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Binance ticker/24hr fetch failed: %s", exc)
        return [], {}

    if not isinstance(data, list):
        logger.warning("Binance ticker/24hr returned non-list: %s", type(data))
        return [], {}

    candidates: list[tuple[str, str, float]] = []
    for item in data:
        symbol: str = item.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue
        if _is_noise_symbol(symbol):
            continue

        quote_vol = float(item.get("quoteVolume", 0))
        if quote_vol < min_quote_volume:
            continue

        display = symbol.removesuffix("USDT")
        candidates.append((display, symbol, quote_vol))

    candidates.sort(key=lambda t: t[2], reverse=True)
    top = candidates[:limit]

    display_tickers = [t[0] for t in top]
    binance_map = {t[0]: t[1] for t in top}

    logger.info(
        "Binance crypto universe: %d tickers (from %d USDT pairs, %d total)",
        len(display_tickers),
        len(candidates),
        len(data),
    )
    return display_tickers, binance_map


async def fetch_crypto_ohlcv_binance(
    symbol: str,
    *,
    interval: str = "1d",
    limit: int = 300,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Fetch OHLCV candles from Binance klines endpoint.

    Returns data in the same dict shape as FMP's OHLCV so that
    ``build_snapshot_from_ohlcv`` works unchanged:

    .. code-block:: python

        {"date": "2026-04-08", "open": 71000.0, "high": 72000.0,
         "low": 70500.0, "close": 71500.0, "volume": 18975.3}

    Candles are sorted **most-recent-first** (same as FMP convention).

    Args:
        symbol: Binance symbol (e.g. ``"BTCUSDT"``).
        interval: Kline interval (``"1d"``, ``"4h"``, ``"1h"``).
        limit: Maximum candles to return.
        client: Optional shared ``httpx.AsyncClient`` for batched calls.

    Returns:
        List of candle dicts sorted most-recent-first, or empty on failure.
    """
    params: dict[str, Any] = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    try:
        from services.http_clients import get_http_client

        hc = client or await get_http_client()
        async with _semaphore:
            resp = await hc.get(f"{BINANCE_BASE_URL}/klines", params=params)
        resp.raise_for_status()
        raw = resp.json()
    except Exception as exc:
        logger.debug("Binance klines failed for %s/%s: %s", symbol, interval, exc)
        return []

    if not isinstance(raw, list):
        return []

    candles: list[dict[str, Any]] = []
    for k in raw:
        # Binance kline: [open_time, open, high, low, close, volume, close_time, ...]
        open_time_ms = k[0]
        dt = datetime.fromtimestamp(open_time_ms / 1000, tz=UTC)
        candles.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "adjClose": float(k[4]),
                "volume": float(k[5]),
            }
        )

    candles.reverse()
    return candles
