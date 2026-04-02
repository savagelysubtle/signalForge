"""Strategy-aware historical simulation and dataset builder.

Replays each strategy's screening criteria against historical data,
computes feature snapshots, and labels with actual outcomes. Produces
the training dataset that feeds the LightGBM model.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from tqdm import tqdm

from ml_training.data.storage import ParquetStore
from ml_training.features.engineering import (
    compute_context_features,
    compute_fundamental_features,
    compute_outcome_labels,
    compute_technical_features,
)

logger = logging.getLogger(__name__)

STRATEGIES_PATH = Path("templates/strategies.json")

MIN_PRICE_ROWS = 50
OUTCOME_HORIZONS = [5, 10, 20]
LOOKBACK_BUFFER = 250


@dataclass
class StrategyTemplate:
    """Parsed strategy template from strategies.json."""

    id: str
    name: str
    strategy_type: str
    chart_timeframe: str
    additional_timeframes: list[str]
    fmp_screener: dict[str, Any] | None
    risk_params: dict[str, Any]
    enable_debate: bool

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StrategyTemplate:
        return cls(
            id=d["id"],
            name=d["name"],
            strategy_type=d.get("strategy_type", "swing"),
            chart_timeframe=d.get("chart_timeframe", "D"),
            additional_timeframes=d.get("additional_timeframes", []),
            fmp_screener=d.get("fmp_screener"),
            risk_params=d.get("risk_params", {}),
            enable_debate=d.get("enable_debate", True),
        )


def load_strategies(path: Path | None = None) -> list[StrategyTemplate]:
    """Load strategy templates from JSON.

    Args:
        path: Path to strategies.json. Defaults to templates/strategies.json.

    Returns:
        List of parsed StrategyTemplate objects.
    """
    p = path or STRATEGIES_PATH
    data = json.loads(p.read_text())
    strategies = data if isinstance(data, list) else data.get("strategies", [])
    return [StrategyTemplate.from_dict(s) for s in strategies]


def _passes_screener_filters(
    row: pd.Series,
    fundamentals: dict[str, float | None],
    screener_config: dict[str, Any] | None,
) -> bool:
    """Check if a ticker/date combination passes the strategy's FMP screener filters.

    This replays the FMP screener historically by applying filter criteria
    against stored data.

    Args:
        row: Price row with OHLCV data.
        fundamentals: Fundamental feature dict.
        screener_config: Strategy's fmp_screener config dict.

    Returns:
        True if the ticker passes all applicable filters.
    """
    if screener_config is None:
        return True

    volume = row.get("volume", 0)
    min_vol = screener_config.get("volumeMoreThan", 0)
    if volume and min_vol and volume < min_vol:
        return False

    price = row.get("close", 0)
    min_price = screener_config.get("priceMoreThan", 0)
    max_price = screener_config.get("priceLowerThan", float("inf"))
    return not (price and (price < min_price or price > max_price))


class DatasetBuilder:
    """Builds ML-ready datasets from historical data using strategy templates.

    For each strategy, replays screening at each historical date,
    computes features, and labels with forward-looking outcomes.
    """

    def __init__(
        self,
        store: ParquetStore,
        strategies: list[StrategyTemplate] | None = None,
        vix_data: pd.DataFrame | None = None,
    ) -> None:
        self._store = store
        self._strategies = strategies or load_strategies()
        self._vix_data = vix_data

    def _get_vix_at_date(self, date: pd.Timestamp) -> float | None:
        """Look up VIX value at a given date."""
        if self._vix_data is None or self._vix_data.empty:
            return None
        mask = self._vix_data["date"] <= date
        if mask.any():
            return float(self._vix_data.loc[mask, "close"].iloc[-1])
        return None

    def build_for_strategy(
        self,
        strategy: StrategyTemplate,
        tickers: list[str],
        timeframe: str | None = None,
    ) -> pd.DataFrame:
        """Build feature dataset for a single strategy.

        Args:
            strategy: Strategy template to simulate.
            tickers: List of ticker symbols to process.
            timeframe: Override timeframe (defaults to strategy's chart_timeframe).

        Returns:
            DataFrame with feature columns + outcome labels.
        """
        tf = timeframe or strategy.chart_timeframe
        all_rows: list[dict[str, Any]] = []

        for symbol in tqdm(tickers, desc=f"{strategy.name}", unit="ticker", leave=False):
            prices = self._store.load_prices(symbol, tf)
            if len(prices) < MIN_PRICE_ROWS:
                continue

            indicators = self._store.load_indicators(symbol, tf)
            fundamentals_df = self._store.load_fundamentals(symbol)
            fund_features = compute_fundamental_features(fundamentals_df)

            tech_features = compute_technical_features(prices, indicators)
            if tech_features.empty:
                continue

            max_outcome_horizon = max(OUTCOME_HORIZONS)

            for idx in range(LOOKBACK_BUFFER, len(prices) - max_outcome_horizon):
                price_row = prices.iloc[idx]

                if not _passes_screener_filters(price_row, fund_features, strategy.fmp_screener):
                    continue

                date = pd.Timestamp(price_row["date"])
                vix = self._get_vix_at_date(date)

                tech_row = tech_features.iloc[idx] if idx < len(tech_features) else {}
                atr_pct = tech_row.get("atr_pct") if isinstance(tech_row, pd.Series) else None

                context = compute_context_features(
                    strategy_type=strategy.strategy_type,
                    sector=None,
                    date=date,
                    vix_level=vix,
                )
                outcomes = compute_outcome_labels(prices, idx, atr_pct)

                row_dict: dict[str, Any] = {
                    "ticker": symbol,
                    "date": date,
                    "strategy_id": strategy.id,
                    "strategy_type": strategy.strategy_type,
                    "timeframe": tf,
                    "close": float(price_row["close"]),
                }

                if isinstance(tech_row, pd.Series):
                    for col in tech_row.index:
                        if col != "date":
                            row_dict[col] = tech_row[col]

                for k, v in fund_features.items():
                    row_dict[k] = v
                for k, v in context.items():
                    row_dict[k] = v
                for k, v in outcomes.items():
                    row_dict[k] = v

                all_rows.append(row_dict)

        if not all_rows:
            logger.warning("No samples generated for strategy %s", strategy.name)
            return pd.DataFrame()

        df = pd.DataFrame(all_rows)
        logger.info(
            "Strategy %s: %d samples across %d tickers",
            strategy.name,
            len(df),
            df["ticker"].nunique(),
        )
        return df

    def build_all(
        self,
        tickers: list[str] | None = None,
        save: bool = True,
    ) -> pd.DataFrame:
        """Build feature datasets for all strategies and combine.

        Args:
            tickers: Override ticker list. If None, uses all available tickers.
            save: Whether to save the combined dataset to Parquet.

        Returns:
            Combined DataFrame with all strategy samples.
        """
        if tickers is None:
            tickers = self._store.list_tickers("prices", "D")

        if not tickers:
            logger.error("No tickers available for dataset building")
            return pd.DataFrame()

        self._vix_data = self._store.load_prices("VIX", "D")

        all_dfs: list[pd.DataFrame] = []

        for strategy in tqdm(self._strategies, desc="Strategies", unit="strategy"):
            df = self.build_for_strategy(strategy, tickers)
            if not df.empty:
                all_dfs.append(df)
                if save:
                    name = f"{strategy.strategy_type}_features"
                    self._store.save_dataset(name, df)

        if not all_dfs:
            logger.error("No samples generated across any strategy")
            return pd.DataFrame()

        combined = pd.concat(all_dfs, ignore_index=True)
        logger.info(
            "Combined dataset: %d samples, %d features, %d strategies",
            len(combined),
            len(combined.columns),
            combined["strategy_type"].nunique(),
        )

        if save:
            self._store.save_dataset("all_features", combined)

        return combined
