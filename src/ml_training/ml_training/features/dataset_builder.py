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
    compute_multi_timeframe_features,
    compute_outcome_labels,
    compute_technical_features,
)

logger = logging.getLogger(__name__)

STRATEGIES_PATH = Path(__file__).resolve().parents[4] / "templates" / "strategies.json"

MIN_PRICE_ROWS = 50
BASE_HORIZONS = [5, 10, 20]
LOOKBACK_BUFFER = 250

ATR_THRESHOLD_MULTIPLIER = 1.0

_HORIZON_MAP: dict[tuple[str, str], int] = {
    ("intraday", "15m"): 10,
    ("intraday", "30m"): 8,
    ("intraday", "1H"): 4,
    ("intraday", "4H"): 3,
    ("swing", "D"): 5,
    ("swing", "4H"): 10,
    ("mean_reversion", "D"): 5,
    ("mean_reversion", "4H"): 10,
    ("value", "D"): 10,
    ("value", "4H"): 20,
    ("event", "D"): 10,
    ("event", "4H"): 10,
    ("crypto_intraday", "4H"): 6,
    ("crypto_intraday", "1H"): 12,
    ("crypto_swing", "D"): 5,
    ("crypto_swing", "4H"): 12,
}


def _default_horizon_bars(strategy_type: str, chart_timeframe: str) -> int:
    """Compute strategy-appropriate target horizon in bars.

    Maps (strategy_type, chart_timeframe) to a bar count that represents
    a meaningful prediction horizon for each trading style.
    """
    return _HORIZON_MAP.get((strategy_type, chart_timeframe), 10)


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
    target_horizon_bars: int

    @property
    def target_col(self) -> str:
        return f"direction_{self.target_horizon_bars}d"

    @property
    def return_col(self) -> str:
        return f"return_{self.target_horizon_bars}d"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StrategyTemplate:
        strategy_type = d.get("strategy_type", "swing")
        chart_timeframe = d.get("chart_timeframe", "D")
        raw_id = d.get("id") or d["name"].lower().replace(" ", "_").replace("-", "_").replace(
            "/", "_"
        )
        return cls(
            id=raw_id,
            name=d["name"],
            strategy_type=strategy_type,
            chart_timeframe=chart_timeframe,
            additional_timeframes=d.get("additional_timeframes", []),
            fmp_screener=d.get("fmp_screener"),
            risk_params=d.get("risk_params", {}),
            enable_debate=d.get("enable_debate", True),
            target_horizon_bars=d.get("target_horizon_bars")
            or _default_horizon_bars(strategy_type, chart_timeframe),
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

    Maps strategies.json screener keys to checks against price row and
    fundamental features. Returns True if all applicable filters pass.
    """
    if screener_config is None or not screener_config.get("enabled", True):
        return True

    price = row.get("close", 0)
    if not price:
        return False

    volume = row.get("volume", 0)

    checks: list[tuple[str, str, Any]] = [
        ("volume_min", "gte", volume),
        ("price_min", "gte", price),
        ("price_max", "lte", price),
    ]
    for key, op, val in checks:
        threshold = screener_config.get(key)
        if threshold is None:
            continue
        if op == "gte" and val and val < threshold:
            return False
        if op == "lte" and val and val > threshold:
            return False

    fund_checks: list[tuple[str, str, str]] = [
        ("pe_min", "gte", "pe_ratio"),
        ("pe_max", "lte", "pe_ratio"),
        ("roe_min", "gte", "roe"),
        ("piotroski_min", "gte", "piotroski_score"),
        ("altman_z_min", "gte", "altman_z"),
        ("debt_equity_max", "lte", "debt_equity"),
    ]
    for key, op, feat_name in fund_checks:
        threshold = screener_config.get(key)
        if threshold is None:
            continue
        feat_val = fundamentals.get(feat_name)
        if feat_val is None:
            continue
        if op == "gte" and feat_val < threshold:
            return False
        if op == "lte" and feat_val > threshold:
            return False

    return True


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
        self._breadth_cache: dict[str, float] = {}
        self._spy_returns: pd.DataFrame | None = None
        self._tf_available: dict[str, bool] = {}

    def _get_vix_at_date(self, date: pd.Timestamp) -> float | None:
        """Look up VIX value at a given date."""
        if self._vix_data is None or self._vix_data.empty:
            return None
        mask = self._vix_data["date"] <= date
        if mask.any():
            return float(self._vix_data.loc[mask, "close"].iloc[-1])
        return None

    def _precompute_market_breadth(self, tickers: list[str]) -> None:
        """Precompute daily market breadth: % of tickers above their 200-day EMA."""
        date_above: dict[str, int] = {}
        date_total: dict[str, int] = {}

        for symbol in tickers:
            prices = self._store.load_prices(symbol, "D")
            if len(prices) < 200:
                continue
            prices["date"] = pd.to_datetime(prices["date"])
            prices["ema_200"] = prices["close"].ewm(span=200, min_periods=100).mean()

            for _, row in prices.dropna(subset=["ema_200"]).iterrows():
                d = str(row["date"])[:10]
                date_total[d] = date_total.get(d, 0) + 1
                if row["close"] > row["ema_200"]:
                    date_above[d] = date_above.get(d, 0) + 1

        for d in date_total:
            self._breadth_cache[d] = date_above.get(d, 0) / date_total[d]

        logger.info("Precomputed market breadth for %d trading days", len(self._breadth_cache))

    def _get_breadth_at_date(self, date: pd.Timestamp) -> float | None:
        """Look up market breadth at a given date."""
        key = str(date)[:10]
        return self._breadth_cache.get(key)

    def _get_spy_return_at_date(self, date: pd.Timestamp) -> float | None:
        """Look up SPY 20-day return as a sector-relative-strength proxy."""
        if self._spy_returns is None or self._spy_returns.empty:
            return None
        mask = self._spy_returns["date"] <= date
        if mask.any():
            return float(self._spy_returns.loc[mask, "ret_20d"].iloc[-1])
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

        extra_tfs = [t for t in strategy.additional_timeframes if t != tf]
        for etf_check in extra_tfs:
            if etf_check not in self._tf_available:
                self._tf_available[etf_check] = bool(self._store.list_tickers("prices", etf_check))
            if not self._tf_available[etf_check]:
                logger.warning(
                    "Strategy '%s' requests timeframe '%s' but 0 data files exist",
                    strategy.name,
                    etf_check,
                )
        extra_tfs = [t for t in extra_tfs if self._tf_available.get(t, False)]

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

            extra_tf_data: list[tuple[str, pd.DataFrame, pd.DataFrame]] = []
            for etf in extra_tfs:
                ep = self._store.load_prices(symbol, etf)
                ei = self._store.load_indicators(symbol, etf)
                if not ep.empty:
                    extra_tf_data.append((etf, ep, ei))

            horizons = sorted({*BASE_HORIZONS, strategy.target_horizon_bars})
            max_outcome_horizon = max(horizons)

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
                context["market_breadth_proxy"] = self._get_breadth_at_date(date)
                context["sector_relative_strength"] = self._get_spy_return_at_date(date)
                outcomes = compute_outcome_labels(
                    prices,
                    idx,
                    atr_pct,
                    horizons=horizons,
                    atr_threshold_multiplier=ATR_THRESHOLD_MULTIPLIER,
                )

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

                for etf_label, etf_prices, etf_indicators in extra_tf_data:
                    mtf = compute_multi_timeframe_features(
                        etf_prices, etf_indicators, etf_label, date
                    )
                    row_dict.update(mtf)

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

        spy_prices = self._store.load_prices("SPY", "D")
        if len(spy_prices) >= 20:
            spy_prices = spy_prices.copy()
            spy_prices["date"] = pd.to_datetime(spy_prices["date"])
            spy_prices["ret_20d"] = spy_prices["close"].pct_change(20)
            self._spy_returns = spy_prices[["date", "ret_20d"]].dropna()
        else:
            self._spy_returns = None

        self._precompute_market_breadth(tickers)

        all_dfs: list[pd.DataFrame] = []
        type_dfs: dict[str, list[pd.DataFrame]] = {}

        for strategy in tqdm(self._strategies, desc="Strategies", unit="strategy"):
            df = self.build_for_strategy(strategy, tickers)
            if not df.empty:
                all_dfs.append(df)
                type_dfs.setdefault(strategy.strategy_type, []).append(df)
                if save:
                    self._store.save_dataset(f"{strategy.id}_features", df)

        if not all_dfs:
            logger.error("No samples generated across any strategy")
            return pd.DataFrame()

        if save:
            for stype, dfs in type_dfs.items():
                merged = pd.concat(dfs, ignore_index=True)
                self._store.save_dataset(f"{stype}_features", merged)
                logger.info(
                    "Strategy type '%s': %d samples from %d sub-strategies",
                    stype,
                    len(merged),
                    len(dfs),
                )

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
