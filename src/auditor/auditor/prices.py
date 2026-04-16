"""Price data fetcher for auditing — yfinance primary, with ParquetStore fallback."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class PriceFetcher:
    """Fetches daily OHLCV data for audit grading.

    Uses yfinance as the primary source (free, no API key). Falls back to
    ParquetStore from the ml_training data directory if available.

    Args:
        parquet_data_dir: Optional path to ml_training's data/raw directory
            for ParquetStore fallback.
        cache: If True, cache downloaded data in memory for the session.
    """

    def __init__(
        self,
        parquet_data_dir: Path | None = None,
        cache: bool = True,
    ) -> None:
        self._parquet_store: Any = None
        if parquet_data_dir and parquet_data_dir.exists():
            try:
                from ml_training.data.storage import (
                    ParquetStore,  # type: ignore[unresolved-import] — optional fallback
                )

                self._parquet_store = ParquetStore(parquet_data_dir)
                logger.info("ParquetStore fallback available at %s", parquet_data_dir)
            except ImportError:
                logger.debug("ml_training not importable; ParquetStore fallback unavailable")

        self._cache_enabled = cache
        self._cache: dict[str, pd.DataFrame] = {}

    def get_prices(
        self,
        ticker: str,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
    ) -> pd.DataFrame:
        """Fetch daily OHLCV for a ticker.

        Args:
            ticker: yfinance-compatible ticker symbol.
            start: Start date (defaults to 2 years ago).
            end: End date (defaults to today).

        Returns:
            DataFrame with columns: date, open, high, low, close, volume.
            Empty DataFrame if data unavailable.
        """
        cache_key = f"{ticker}|{start}|{end}"
        if self._cache_enabled and cache_key in self._cache:
            return self._cache[cache_key]

        df = self._fetch_yfinance(ticker, start, end)

        if df.empty and self._parquet_store is not None:
            df = self._fetch_parquet(ticker)

        if self._cache_enabled and not df.empty:
            self._cache[cache_key] = df

        return df

    def _fetch_yfinance(
        self,
        ticker: str,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
    ) -> pd.DataFrame:
        """Download daily OHLCV from yfinance."""
        if start is None:
            start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        if end is None:
            end = datetime.now().strftime("%Y-%m-%d")

        try:
            data = yf.download(
                ticker,
                start=str(start),
                end=str(end),
                interval="1d",
                progress=False,
                auto_adjust=True,
            )
        except Exception:
            logger.warning("yfinance download failed for %s", ticker, exc_info=True)
            return pd.DataFrame()

        if data is None or data.empty:
            logger.debug("No yfinance data for %s (%s to %s)", ticker, start, end)
            return pd.DataFrame()

        df = data.reset_index()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [str(level0).lower() for level0, *_ in df.columns]
        else:
            df.columns = [str(c).lower() for c in df.columns]

        needed = {"date", "open", "high", "low", "close", "volume"}
        if not needed.issubset(set(df.columns)):
            logger.warning("yfinance columns mismatch for %s: %s", ticker, list(df.columns))
            return pd.DataFrame()

        df = df[list(needed)].copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df

    def _fetch_parquet(self, ticker: str) -> pd.DataFrame:
        """Load prices from the ml_training ParquetStore."""
        try:
            df = self._parquet_store.load_prices(ticker, "D")
            if df.empty:
                return df
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)
        except Exception:
            logger.debug("ParquetStore load failed for %s", ticker, exc_info=True)
            return pd.DataFrame()

    def prefetch(self, tickers: list[str], start: str, end: str) -> dict[str, int]:
        """Batch-prefetch prices for multiple tickers.

        Args:
            tickers: List of yfinance-compatible ticker symbols.
            start: Start date string.
            end: End date string.

        Returns:
            Dict mapping ticker to row count fetched (0 if failed).
        """
        results: dict[str, int] = {}
        for ticker in tickers:
            df = self.get_prices(ticker, start=start, end=end)
            results[ticker] = len(df)
            if df.empty:
                logger.warning("No price data for %s", ticker)
        logger.info(
            "Prefetched %d/%d tickers with data",
            sum(1 for v in results.values() if v > 0),
            len(tickers),
        )
        return results
