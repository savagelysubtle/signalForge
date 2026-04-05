"""Bulk daily OHLCV downloads via yfinance (free, no API key).

yfinance wraps Yahoo Finance data and supports US, TSX (.TO), and
crypto (-USD) tickers. Daily data goes back decades. Intraday is
limited to 60 days so we only use this for daily candles.
"""

from __future__ import annotations

import logging
import time

import pandas as pd
from tqdm import tqdm

from ml_training.data.storage import ParquetStore

logger = logging.getLogger(__name__)

YF_BATCH_SIZE = 50
YF_DELAY_BETWEEN_BATCHES = 2.0


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns that yfinance sometimes returns."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    return df


def _to_yf_symbol(symbol: str, category: str) -> str:
    """Convert internal symbol to yfinance format.

    FMP crypto symbols like ``BTCUSD`` become ``BTC-USD`` for Yahoo.
    TSX and US symbols pass through unchanged.
    """
    if category == "crypto":
        clean = symbol.replace("USD", "").replace("USDT", "")
        return f"{clean}-USD"
    return symbol


def _from_yf_symbol(yf_symbol: str) -> str:
    """Convert yfinance symbol back to internal format."""
    if yf_symbol.endswith("-USD"):
        base = yf_symbol.replace("-USD", "")
        return f"{base}USD"
    return yf_symbol


YF_INTERVAL_MAP: dict[str, str] = {
    "D": "1d",
    "W": "1wk",
    "M": "1mo",
}


def download_daily_ohlcv(
    tickers: list[str],
    category: str,
    store: ParquetStore,
    completed: set[str],
    lookback_years: int = 2,
    timeframe: str = "D",
) -> dict[str, int]:
    """Batch-download OHLCV for all tickers via yfinance.

    Supports daily (D), weekly (W), and monthly (M) intervals.

    Args:
        tickers: List of ticker symbols in internal format.
        category: 'tsx', 'us', or 'crypto'.
        store: ParquetStore to save data into.
        completed: Set of checkpoint keys already done.
        lookback_years: How many years of history to fetch.
        timeframe: Internal timeframe code ('D', 'W', or 'M').

    Returns:
        Dict mapping symbol → number of candles stored.
    """
    import yfinance as yf

    yf_interval = YF_INTERVAL_MAP.get(timeframe, "1d")
    tf_label = {"D": "daily", "W": "weekly", "M": "monthly"}.get(timeframe, timeframe)

    to_fetch: list[str] = []
    yf_to_internal: dict[str, str] = {}

    for sym in tickers:
        key = f"prices:{sym}:{timeframe}"
        if key in completed:
            continue
        yf_sym = _to_yf_symbol(sym, category)
        to_fetch.append(yf_sym)
        yf_to_internal[yf_sym] = sym

    if not to_fetch:
        logger.info("All %s %s prices already downloaded, skipping", category, tf_label)
        return {}

    logger.info(
        "Downloading %s OHLCV via yfinance: %d %s tickers (%d yr history)",
        tf_label,
        len(to_fetch),
        category,
        lookback_years,
    )

    results: dict[str, int] = {}
    pbar = tqdm(total=len(to_fetch), desc=f"yf {category} {tf_label}", unit="ticker")

    for batch_start in range(0, len(to_fetch), YF_BATCH_SIZE):
        batch = to_fetch[batch_start : batch_start + YF_BATCH_SIZE]

        try:
            data = yf.download(
                tickers=batch,
                period=f"{lookback_years}y",
                interval=yf_interval,
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False,
            )
        except Exception:
            logger.warning("yfinance batch download failed for batch starting at %d", batch_start)
            pbar.update(len(batch))
            continue

        if data.empty:
            pbar.update(len(batch))
            continue

        is_single = len(batch) == 1
        is_multi_index = isinstance(data.columns, pd.MultiIndex)

        for yf_sym in batch:
            internal_sym = yf_to_internal[yf_sym]
            try:
                if is_single or not is_multi_index:
                    ticker_df = _flatten_columns(data.copy())
                else:
                    if yf_sym not in data.columns.get_level_values(0):
                        pbar.update(1)
                        continue
                    ticker_df = data[yf_sym].copy()

                close_col = "Close" if "Close" in ticker_df.columns else "close"
                ticker_df = ticker_df.dropna(subset=[close_col])
                if ticker_df.empty:
                    pbar.update(1)
                    continue

                ticker_df = ticker_df.reset_index()
                col_map = {
                    "Date": "date",
                    "Datetime": "date",
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
                ticker_df = ticker_df.rename(columns=col_map)

                keep = [
                    c
                    for c in ["date", "open", "high", "low", "close", "volume"]
                    if c in ticker_df.columns
                ]
                ticker_df = ticker_df[keep]

                candle_list = ticker_df.to_dict("records")
                for row in candle_list:
                    if hasattr(row.get("date"), "isoformat"):
                        row["date"] = row["date"].isoformat()[:10]

                store.save_prices(internal_sym, timeframe, candle_list)
                results[internal_sym] = len(candle_list)
                completed.add(f"prices:{internal_sym}:{timeframe}")
            except Exception:
                logger.warning("Failed to process yfinance data for %s", yf_sym)

            pbar.update(1)

        if batch_start + YF_BATCH_SIZE < len(to_fetch):
            time.sleep(YF_DELAY_BETWEEN_BATCHES)

    pbar.close()
    stored = sum(results.values())
    logger.info(
        "yfinance: stored %s OHLCV for %d/%d %s tickers (%d total candles)",
        tf_label,
        len(results),
        len(to_fetch),
        category,
        stored,
    )
    return results


def download_market_context(store: ParquetStore, completed: set[str]) -> None:
    """Download VIX and SPY daily data via yfinance (free)."""
    import yfinance as yf

    if "market_context" in completed:
        return

    for symbol, internal in [("^VIX", "VIX"), ("SPY", "SPY")]:
        try:
            data = yf.download(
                tickers=symbol,
                period="2y",
                interval="1d",
                auto_adjust=True,
                progress=False,
            )
            if data.empty:
                logger.warning("yfinance returned no data for %s", symbol)
                continue

            data = _flatten_columns(data)
            data = data.reset_index()
            col_map = {
                "Date": "date",
                "Datetime": "date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
            data = data.rename(columns=col_map)
            keep = [
                c for c in ["date", "open", "high", "low", "close", "volume"] if c in data.columns
            ]
            data = data[keep]

            candle_list = data.to_dict("records")
            for row in candle_list:
                if hasattr(row.get("date"), "isoformat"):
                    row["date"] = row["date"].isoformat()[:10]

            store.save_prices(internal, "D", candle_list)
            logger.info(
                "Stored %s daily data via yfinance (%d candles)", internal, len(candle_list)
            )
        except Exception:
            logger.warning("Failed to download %s via yfinance", symbol)

    completed.add("market_context")
