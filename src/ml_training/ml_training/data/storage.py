"""Local Parquet storage for ML training data.

Provides a file-based storage layer that reads/writes Parquet files
organized by ticker, timeframe, and data type. Designed for fast bulk
reads during feature engineering.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class ParquetStore:
    """File-based storage for historical market data using Parquet format.

    Directory structure::

        {data_dir}/
          prices/{SYMBOL}_{TIMEFRAME}.parquet
          indicators/{SYMBOL}_{TIMEFRAME}.parquet
          fundamentals/{SYMBOL}.parquet
          datasets/{name}.parquet
    """

    def __init__(self, data_dir: Path | str) -> None:
        self._data_dir = Path(data_dir)
        self._prices_dir = self._data_dir / "prices"
        self._indicators_dir = self._data_dir / "indicators"
        self._fundamentals_dir = self._data_dir / "fundamentals"
        self._datasets_dir = self._data_dir.parent / "datasets"

        for d in (
            self._prices_dir,
            self._indicators_dir,
            self._fundamentals_dir,
            self._datasets_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def save_prices(self, symbol: str, timeframe: str, data: list[dict[str, Any]]) -> Path:
        """Save OHLCV candle data to Parquet.

        Args:
            symbol: Ticker symbol.
            timeframe: Timeframe key (e.g. "D", "4H").
            data: List of candle dicts with date, open, high, low, close, volume.

        Returns:
            Path to the written Parquet file.
        """
        path = self._prices_dir / f"{symbol}_{timeframe}.parquet"
        df = pd.DataFrame(data)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
        df.to_parquet(path, engine="pyarrow", index=False)
        return path

    def load_prices(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """Load OHLCV data from Parquet.

        Returns:
            DataFrame with OHLCV columns, or empty DataFrame if not found.
        """
        path = self._prices_dir / f"{symbol}_{timeframe}.parquet"
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_parquet(path, engine="pyarrow")
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df

    def save_indicators(
        self,
        symbol: str,
        timeframe: str,
        indicators: dict[str, list[dict[str, Any]]],
    ) -> Path:
        """Save technical indicator series to Parquet.

        Each indicator type's series is merged on the date column into
        a single DataFrame.

        Args:
            symbol: Ticker symbol.
            timeframe: Timeframe key.
            indicators: Mapping of indicator name → list of data dicts.

        Returns:
            Path to the written Parquet file.
        """
        path = self._indicators_dir / f"{symbol}_{timeframe}.parquet"

        merged: pd.DataFrame | None = None
        for ind_name, series in indicators.items():
            if not series:
                continue
            df = pd.DataFrame(series)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])

            value_cols = [
                c for c in df.columns if c not in ("date", "open", "high", "low", "close", "volume")
            ]
            rename_map = {c: f"{ind_name}_{c}" if c != ind_name else ind_name for c in value_cols}
            df = df.rename(columns=rename_map)

            keep_cols = ["date"] + [rename_map.get(c, c) for c in value_cols]
            df = df[[c for c in keep_cols if c in df.columns]]

            merged = df if merged is None else pd.merge(merged, df, on="date", how="outer")

        if merged is not None:
            merged = merged.sort_values("date").reset_index(drop=True)
            merged.to_parquet(path, engine="pyarrow", index=False)
        return path

    def save_indicators_df(self, symbol: str, timeframe: str, df: pd.DataFrame) -> Path:
        """Save a pre-computed indicator DataFrame to Parquet.

        Args:
            symbol: Ticker symbol.
            timeframe: Timeframe key.
            df: DataFrame with a 'date' column and indicator columns.

        Returns:
            Path to the written Parquet file.
        """
        path = self._indicators_dir / f"{symbol}_{timeframe}.parquet"
        if "date" in df.columns:
            df = df.sort_values("date").reset_index(drop=True)
        df.to_parquet(path, engine="pyarrow", index=False)
        return path

    def load_indicators(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """Load merged indicator data from Parquet."""
        path = self._indicators_dir / f"{symbol}_{timeframe}.parquet"
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_parquet(path, engine="pyarrow")
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df

    def save_fundamentals(self, symbol: str, data: dict[str, Any]) -> Path:
        """Save fundamental data snapshot to Parquet.

        Nested dicts (ratios_ttm, key_metrics_ttm, etc.) are flattened
        into a single row.

        Args:
            symbol: Ticker symbol.
            data: Fundamental data dict.

        Returns:
            Path to the written Parquet file.
        """
        path = self._fundamentals_dir / f"{symbol}.parquet"

        flat: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, dict):
                for k, v in value.items():
                    flat[f"{key}_{k}"] = v
            else:
                flat[key] = value

        df = pd.DataFrame([flat])
        df.to_parquet(path, engine="pyarrow", index=False)
        return path

    def load_fundamentals(self, symbol: str) -> pd.DataFrame:
        """Load fundamental data from Parquet."""
        path = self._fundamentals_dir / f"{symbol}.parquet"
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path, engine="pyarrow")

    def save_dataset(self, name: str, df: pd.DataFrame) -> Path:
        """Save a processed feature dataset.

        Args:
            name: Dataset name (e.g. "swing_features", "all_features").
            df: Feature DataFrame to persist.

        Returns:
            Path to the written Parquet file.
        """
        path = self._datasets_dir / f"{name}.parquet"
        df.to_parquet(path, engine="pyarrow", index=False)
        logger.info("Saved dataset '%s': %d rows x %d cols", name, len(df), len(df.columns))
        return path

    def load_dataset(self, name: str) -> pd.DataFrame:
        """Load a processed feature dataset."""
        path = self._datasets_dir / f"{name}.parquet"
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path, engine="pyarrow")

    def list_tickers(self, data_type: str = "prices", timeframe: str = "D") -> list[str]:
        """List all tickers that have data for a given type and timeframe.

        Args:
            data_type: "prices", "indicators", or "fundamentals".
            timeframe: Timeframe key (ignored for fundamentals).

        Returns:
            Sorted list of ticker symbols.
        """
        if data_type == "fundamentals":
            dir_path = self._fundamentals_dir
            return sorted(p.stem for p in dir_path.glob("*.parquet"))

        dir_path = self._prices_dir if data_type == "prices" else self._indicators_dir
        suffix = f"_{timeframe}.parquet"
        return sorted(
            p.stem.replace(suffix.replace(".parquet", ""), "") for p in dir_path.glob(f"*{suffix}")
        )

    def list_strategy_datasets(self, per_id_only: bool = False) -> list[str]:
        """Discover available per-strategy feature datasets.

        Args:
            per_id_only: When True, filter out type-level aggregate datasets
                that duplicate a single per-id dataset.  This prevents
                training identical models under different names.

        Returns:
            Sorted list of strategy names that have saved datasets.
        """
        suffix = "_features.parquet"
        all_names = sorted(
            p.stem.replace("_features", "")
            for p in self._datasets_dir.glob(f"*{suffix}")
            if p.stem != "all_features"
        )

        if not per_id_only:
            return all_names

        from ml_training.features.dataset_builder import load_strategies

        strategies = load_strategies()
        id_set = {s.id for s in strategies}
        type_counts: dict[str, int] = {}
        for s in strategies:
            type_counts[s.strategy_type] = type_counts.get(s.strategy_type, 0) + 1

        return [name for name in all_names if name in id_set or type_counts.get(name, 0) >= 2]

    def verify_data(self) -> dict[str, Any]:
        """Run verification checks on stored data.

        Returns:
            Dict with verification results including counts, gaps, and sanity checks.
        """
        results: dict[str, Any] = {
            "price_files": 0,
            "indicator_files": 0,
            "fundamental_files": 0,
            "tickers_with_gaps": [],
            "tickers_with_issues": [],
            "summary": {},
        }

        price_files = list(self._prices_dir.glob("*.parquet"))
        results["price_files"] = len(price_files)
        results["indicator_files"] = len(list(self._indicators_dir.glob("*.parquet")))
        results["fundamental_files"] = len(list(self._fundamentals_dir.glob("*.parquet")))

        gap_tickers: list[str] = []
        issue_tickers: list[str] = []

        for pf in price_files:
            stem = pf.stem
            try:
                df = pd.read_parquet(pf, engine="pyarrow")
            except Exception:
                issue_tickers.append(f"{stem}: unreadable parquet")
                continue

            if len(df) < 100:
                gap_tickers.append(f"{stem}: only {len(df)} rows")

            if "close" in df.columns:
                if (df["close"] <= 0).any():
                    issue_tickers.append(f"{stem}: has zero/negative close prices")
                if df["close"].isna().sum() > len(df) * 0.05:
                    issue_tickers.append(f"{stem}: >5% null close values")

            if "volume" in df.columns and (df["volume"] == 0).sum() > len(df) * 0.1:
                issue_tickers.append(f"{stem}: >10% zero volume days")

        results["tickers_with_gaps"] = gap_tickers
        results["tickers_with_issues"] = issue_tickers
        results["summary"] = {
            "total_price_files": results["price_files"],
            "total_indicator_files": results["indicator_files"],
            "total_fundamental_files": results["fundamental_files"],
            "files_with_gaps": len(gap_tickers),
            "files_with_issues": len(issue_tickers),
        }

        return results
