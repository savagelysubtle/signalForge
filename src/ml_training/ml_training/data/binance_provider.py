"""Free crypto OHLCV downloads from Binance public data.

Downloads historical kline (candle) data from data.binance.vision
which is a free, unlimited, no-auth-required static file server
hosting all Binance spot market data in CSV format.
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime, timedelta

import httpx
import pandas as pd
from tqdm import tqdm

from ml_training.data.storage import ParquetStore

logger = logging.getLogger(__name__)

BINANCE_DATA_BASE = "https://data.binance.vision/data/spot"

BINANCE_INTERVAL_MAP: dict[str, str] = {
    "15m": "15m",
    "30m": "30m",
    "1H": "1h",
    "4H": "4h",
    "D": "1d",
    "W": "1w",
}

TOP_CRYPTO_PAIRS: list[str] = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "DOTUSDT",
    "LINKUSDT",
    "MATICUSDT",
    "SHIBUSDT",
    "TRXUSDT",
    "UNIUSDT",
    "LTCUSDT",
    "ATOMUSDT",
    "XLMUSDT",
    "NEARUSDT",
    "BCHUSDT",
    "APTUSDT",
    "FILUSDT",
    "ALGOUSDT",
    "VETUSDT",
    "ICPUSDT",
    "HBARUSDT",
    "AAVEUSDT",
    "ARBUSDT",
    "OPUSDT",
    "MKRUSDT",
    "GRTUSDT",
    "INJUSDT",
    "FTMUSDT",
    "SANDUSDT",
    "MANAUSDT",
    "AXSUSDT",
    "RUNEUSDT",
    "SNXUSDT",
    "CRVUSDT",
    "LDOUSDT",
    "RENDERUSDT",
    "SUIUSDT",
    "SEIUSDT",
    "TIAUSDT",
    "JUPUSDT",
    "WLDUSDT",
    "STXUSDT",
    "PEPEUSDT",
    "ORDIUSDT",
    "WIFUSDT",
    "BONKUSDT",
]

KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]


def _to_internal_symbol(binance_pair: str) -> str:
    """Convert BTCUSDT → BTCUSD for internal consistency."""
    return binance_pair.replace("USDT", "USD")


def _generate_monthly_urls(
    pair: str,
    interval: str,
    months_back: int = 24,
) -> list[tuple[str, str]]:
    """Generate monthly archive URLs for a pair/interval.

    Returns:
        List of (url, label) tuples for each month.
    """
    bn_interval = BINANCE_INTERVAL_MAP.get(interval, interval)
    urls: list[tuple[str, str]] = []
    now = datetime.now()

    for m in range(months_back):
        dt = now - timedelta(days=30 * m)
        year = dt.year
        month = dt.month
        label = f"{year}-{month:02d}"
        filename = f"{pair}-{bn_interval}-{label}.zip"
        url = f"{BINANCE_DATA_BASE}/monthly/klines/{pair}/{bn_interval}/{filename}"
        urls.append((url, label))

    return urls


def _parse_kline_csv(csv_bytes: bytes) -> pd.DataFrame:
    """Parse Binance kline CSV into a clean OHLCV DataFrame."""
    df = pd.read_csv(
        io.BytesIO(csv_bytes),
        header=None,
        names=KLINE_COLUMNS,
    )
    df["date"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df[["date", "open", "high", "low", "close", "volume"]].copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def download_crypto_ohlcv(
    timeframes: list[str],
    store: ParquetStore,
    completed: set[str],
    pairs: list[str] | None = None,
    months_back: int = 24,
) -> dict[str, int]:
    """Download crypto OHLCV from Binance public data (free, no auth).

    Args:
        timeframes: List of timeframe keys (e.g. ['D', '4H', '1H']).
        store: ParquetStore to save data into.
        completed: Set of checkpoint keys already done.
        pairs: Binance pair symbols. Defaults to TOP_CRYPTO_PAIRS.
        months_back: How many months of history to download.

    Returns:
        Dict mapping internal_symbol → total candles stored.
    """
    if pairs is None:
        pairs = TOP_CRYPTO_PAIRS

    valid_tfs = [tf for tf in timeframes if tf in BINANCE_INTERVAL_MAP]
    if not valid_tfs:
        logger.warning("No valid Binance timeframes in %s", timeframes)
        return {}

    results: dict[str, int] = {}
    total_tasks = len(pairs) * len(valid_tfs)
    pbar = tqdm(total=total_tasks, desc="binance crypto", unit="pair-tf")

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for pair in pairs:
            internal = _to_internal_symbol(pair)

            for tf in valid_tfs:
                key = f"prices:{internal}:{tf}"
                if key in completed:
                    pbar.update(1)
                    continue

                monthly_urls = _generate_monthly_urls(pair, tf, months_back)
                all_candles: list[pd.DataFrame] = []

                for url, label in monthly_urls:
                    try:
                        resp = client.get(url)
                        if resp.status_code == 404:
                            continue
                        if resp.status_code != 200:
                            continue

                        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                            csv_name = zf.namelist()[0]
                            csv_bytes = zf.read(csv_name)

                        chunk = _parse_kline_csv(csv_bytes)
                        if not chunk.empty:
                            all_candles.append(chunk)
                    except Exception:
                        logger.debug("Failed to download %s %s %s", pair, tf, label)

                if all_candles:
                    combined = pd.concat(all_candles, ignore_index=True)
                    combined = combined.sort_values("date").drop_duplicates(subset=["date"])
                    combined = combined.reset_index(drop=True)

                    candle_list = combined.to_dict("records")
                    for row in candle_list:
                        if hasattr(row.get("date"), "isoformat"):
                            row["date"] = row["date"].isoformat()

                    store.save_prices(internal, tf, candle_list)
                    completed.add(key)
                    results[f"{internal}:{tf}"] = len(candle_list)
                    logger.debug(
                        "Stored %d candles for %s/%s (Binance)", len(candle_list), internal, tf
                    )

                pbar.update(1)

    pbar.close()
    total_candles = sum(results.values())
    unique_pairs = len({k.split(":")[0] for k in results})
    logger.info(
        "Binance: stored %d candles across %d crypto pairs x %d timeframes",
        total_candles,
        unique_pairs,
        len(valid_tfs),
    )
    return results
