"""Strategy-aware historical simulation and dataset builder.

Replays each strategy's screening criteria against historical data,
computes feature snapshots, and labels with actual outcomes. Produces
the training dataset that feeds the LightGBM model.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from tqdm import tqdm

from ml_training.data.storage import ParquetStore
from ml_training.features.engineering import (
    compute_context_features,
    compute_fundamental_features,
    compute_llm_features,
    compute_multi_timeframe_features,
    compute_outcome_labels,
    compute_primary_signal,
    compute_technical_features,
    compute_triple_barrier_label,
    compute_tsfresh_features,
    get_barrier_config,
    get_ffd_d,
    neutralize_features,
)
from ml_training.threading import optimal_workers, parallel_map

logger = logging.getLogger(__name__)

STRATEGIES_PATH = Path(__file__).resolve().parents[4] / "templates" / "strategies.json"

MIN_PRICE_ROWS = 50
BASE_HORIZONS = [5, 10, 20]
LOOKBACK_BUFFER = 250

ATR_THRESHOLD_MULTIPLIER = 1.0

_HORIZON_MAP: dict[tuple[str, str], int] = {
    ("momentum_breakout", "D"): 5,
    ("golden_cross_swing", "D"): 10,
    ("bb_squeeze_breakout", "D"): 7,
    ("mean_reversion", "D"): 5,
    ("mean_reversion", "4H"): 10,
    ("value_accumulation", "D"): 10,
    ("value_accumulation", "4H"): 40,
    ("earnings_play", "D"): 10,
    ("earnings_play", "4H"): 10,
    ("intraday_scalp", "4H"): 8,
    ("intraday_scalp", "15m"): 10,
    ("intraday_scalp", "1H"): 4,
    ("crypto_swing", "D"): 5,
    ("crypto_swing", "4H"): 12,
    ("crypto_intraday_scalp", "4H"): 8,
    ("crypto_intraday_scalp", "1H"): 12,
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
        neutralize: bool = False,
    ) -> None:
        self._store = store
        self._strategies = strategies or load_strategies()
        self._vix_data = vix_data
        self._neutralize = neutralize
        self._breadth_cache: dict[str, float] = {}
        self._spy_returns: pd.DataFrame | None = None
        self._spy_prices: pd.DataFrame | None = None
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
        """Precompute daily market breadth: % of tickers above their 200-day EMA.

        Vectorised per-ticker (no iterrows) and parallelised across tickers
        via free-threading when the GIL is disabled.
        """

        def _breadth_for_ticker(symbol: str) -> pd.DataFrame | None:
            prices = self._store.load_prices(symbol, "D")
            if len(prices) < 200:
                return None
            prices = prices.copy()
            prices["date"] = pd.to_datetime(prices["date"])
            prices["ema_200"] = prices["close"].ewm(span=200, min_periods=100).mean()
            valid = prices.dropna(subset=["ema_200"])
            return pd.DataFrame(
                {
                    "date_str": valid["date"].dt.strftime("%Y-%m-%d").values,
                    "above": (valid["close"].values > valid["ema_200"].values).astype(int),
                }
            )

        chunks = parallel_map(_breadth_for_ticker, tickers, desc="market breadth")

        valid_chunks = [c for c in chunks if c is not None and not c.empty]
        if valid_chunks:
            combined = pd.concat(valid_chunks, ignore_index=True)
            grouped = combined.groupby("date_str")["above"].agg(["sum", "count"])
            self._breadth_cache = {
                str(d): row["sum"] / row["count"] for d, row in grouped.iterrows()
            }

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

    def _fit_regime_detector(
        self,
        spy_prices: pd.DataFrame,
    ) -> Any:
        """Fit an HMM regime detector on VIX/SPY/breadth data.

        Returns the fitted detector, or None if data is insufficient.
        """
        try:
            from ml_training.features.regime import RegimeDetector, compute_regime_features
        except ImportError:
            logger.warning("hmmlearn not available, skipping regime detection")
            return None

        if self._vix_data is None or self._vix_data.empty or spy_prices.empty:
            return None

        regime_df = compute_regime_features(
            self._vix_data,
            spy_prices,
            self._breadth_cache,
        )
        if len(regime_df) < 100:
            logger.warning("Insufficient data for regime detection (%d rows)", len(regime_df))
            return None

        detector = RegimeDetector(n_regimes=3)
        detector.fit(
            regime_df["vix_return"].values,
            regime_df["breadth"].values,
            regime_df["momentum"].values,
        )
        logger.info("HMM regime detector fitted on %d observations", len(regime_df))
        return detector

    def _add_regime_features(
        self,
        df: pd.DataFrame,
        detector: Any,
    ) -> pd.DataFrame:
        """Add HMM regime labels and probabilities to a dataset."""
        if detector is None:
            return df

        try:
            from ml_training.features.regime import compute_regime_features

            if self._vix_data is None or self._spy_prices is None:
                return df
            regime_df = compute_regime_features(
                self._vix_data,
                self._spy_prices,
                self._breadth_cache,
            )

            regime_df["date"] = pd.to_datetime(regime_df["date"])
            features_arr = regime_df[["vix_return", "breadth", "momentum"]].values

            regime_labels = detector.predict(features_arr)
            regime_probs = detector.predict_proba(features_arr)

            regime_lookup = pd.DataFrame(
                {
                    "date": regime_df["date"].dt.strftime("%Y-%m-%d"),
                    "hmm_regime": regime_labels,
                    "hmm_regime_prob_bear": regime_probs[:, 0],
                    "hmm_regime_prob_neutral": regime_probs[:, 1],
                    "hmm_regime_prob_bull": regime_probs[:, 2],
                }
            )

            df = df.copy()
            df["_date_str"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df.merge(
                regime_lookup,
                left_on="_date_str",
                right_on="date",
                how="left",
                suffixes=("", "_regime"),
            )
            df.drop(columns=["_date_str", "date_regime"], errors="ignore", inplace=True)

            for col in [
                "hmm_regime",
                "hmm_regime_prob_bear",
                "hmm_regime_prob_neutral",
                "hmm_regime_prob_bull",
            ]:
                if col in df.columns:
                    df[col] = df[col].fillna(1 if col == "hmm_regime" else 0.33)

        except Exception:
            logger.warning("Failed to add regime features", exc_info=True)

        return df

    def build_for_strategy(
        self,
        strategy: StrategyTemplate,
        tickers: list[str],
        timeframe: str | None = None,
    ) -> pd.DataFrame:
        """Build feature dataset for a single strategy.

        Ticker processing is parallelised via ``ThreadPoolExecutor``
        when free-threading is active (GIL disabled).  Each ticker's
        work is fully independent: load data → compute features →
        return rows.

        Args:
            strategy: Strategy template to simulate.
            tickers: List of ticker symbols to process.
            timeframe: Override timeframe (defaults to strategy's chart_timeframe).

        Returns:
            DataFrame with feature columns + outcome labels.
        """
        tf = timeframe or strategy.chart_timeframe

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

        horizons = sorted({*BASE_HORIZONS, strategy.target_horizon_bars})
        max_outcome_horizon = max(horizons)

        def _process_ticker(symbol: str) -> list[dict[str, Any]]:
            """Process one ticker — thread-safe, no shared mutable state."""
            prices = self._store.load_prices(symbol, tf)
            if len(prices) < MIN_PRICE_ROWS:
                return []

            indicators = self._store.load_indicators(symbol, tf)
            fundamentals_df = self._store.load_fundamentals(symbol)
            fund_features = compute_fundamental_features(fundamentals_df)

            ffd_d = get_ffd_d(strategy.strategy_type)
            tech_features = compute_technical_features(prices, indicators, ffd_d=ffd_d)
            if tech_features.empty:
                return []

            extra_tf_data: list[tuple[str, pd.DataFrame, pd.DataFrame]] = []
            for etf in extra_tfs:
                ep = self._store.load_prices(symbol, etf)
                ei = self._store.load_indicators(symbol, etf)
                if not ep.empty:
                    extra_tf_data.append((etf, ep, ei))

            rows: list[dict[str, Any]] = []
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

                effective_atr = float(atr_pct) if atr_pct is not None and atr_pct > 0 else 2.0
                barrier_cfg = get_barrier_config(strategy.strategy_type)
                tb_labels = compute_triple_barrier_label(
                    prices,
                    idx,
                    effective_atr,
                    profit_mult=barrier_cfg["profit_mult"],
                    stop_mult=barrier_cfg["stop_mult"],
                    max_horizon=strategy.target_horizon_bars,
                )

                signal_data = compute_primary_signal(
                    prices,
                    indicators,
                    strategy.strategy_type,
                    idx,
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
                for k, v in tb_labels.items():
                    row_dict[k] = v
                for k, v in signal_data.items():
                    row_dict[k] = v

                if strategy.strategy_type in ("intraday_scalp", "crypto_intraday_scalp"):
                    tsf = compute_tsfresh_features(prices, idx)
                    for k, v in tsf.items():
                        row_dict[k] = v

                for etf_label, etf_prices, etf_indicators in extra_tf_data:
                    mtf = compute_multi_timeframe_features(
                        etf_prices, etf_indicators, etf_label, date
                    )
                    row_dict.update(mtf)

                rows.append(row_dict)
            return rows

        workers = optimal_workers("cpu")
        all_rows: list[dict[str, Any]] = []

        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_process_ticker, sym): sym for sym in tickers}
                for future in tqdm(
                    as_completed(futures),
                    total=len(tickers),
                    desc=strategy.name,
                    unit="ticker",
                    leave=False,
                ):
                    all_rows.extend(future.result())
        else:
            for symbol in tqdm(tickers, desc=strategy.name, unit="ticker", leave=False):
                all_rows.extend(_process_ticker(symbol))

        if not all_rows:
            logger.warning("No samples generated for strategy %s", strategy.name)
            return pd.DataFrame()

        df = pd.DataFrame(all_rows)
        if self._neutralize:
            df = neutralize_features(df)
            logger.info(
                "Strategy %s: %d samples across %d tickers (features neutralized)",
                strategy.name,
                len(df),
                df["ticker"].nunique(),
            )
        else:
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
        augment: bool = False,
    ) -> pd.DataFrame:
        """Build feature datasets for all strategies and combine.

        Args:
            tickers: Override ticker list. If None, uses all available tickers.
            save: Whether to save the combined dataset to Parquet.
            augment: Whether to augment small strategy datasets with synthetic data.

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
            self._spy_prices = spy_prices[["date", "close"]].copy()
            self._spy_returns = spy_prices[["date", "ret_20d"]].dropna()
        else:
            self._spy_prices = None
            self._spy_returns = None

        self._precompute_market_breadth(tickers)

        regime_detector = self._fit_regime_detector(spy_prices)

        augmenter = None
        if augment:
            from ml_training.data.augmentation import TimeSeriesAugmenter

            augmenter = TimeSeriesAugmenter(target_size=25000)

        all_dfs: list[pd.DataFrame] = []
        type_dfs: dict[str, list[pd.DataFrame]] = {}

        for strategy in tqdm(self._strategies, desc="Strategies", unit="strategy"):
            df = self.build_for_strategy(strategy, tickers)
            if not df.empty:
                df = self._add_regime_features(df, regime_detector)
                if "triple_barrier_label" in df.columns:
                    dist = df["triple_barrier_label"].value_counts(normalize=True)
                    pos_pct = dist.get(1, 0) * 100
                    neg_pct = dist.get(0, 0) * 100
                    logger.info(
                        "[%s] Label distribution — positive: %.1f%%, negative: %.1f%% (%d samples)",
                        strategy.name,
                        pos_pct,
                        neg_pct,
                        len(df),
                    )
                    if pos_pct < 35 or pos_pct > 65:
                        logger.warning(
                            "[%s] Imbalanced labels (%.1f%% positive) — "
                            "model accuracy may be misleading",
                            strategy.name,
                            pos_pct,
                        )

                if augmenter is not None and len(df) < 15000:
                    original_size = len(df)
                    df = augmenter.augment(df, target_col="triple_barrier_label")
                    logger.info(
                        "Augmented %s: %d → %d samples",
                        strategy.name,
                        original_size,
                        len(df),
                    )
                all_dfs.append(df)
                type_dfs.setdefault(strategy.strategy_type, []).append(df)
                if save:
                    self._store.save_dataset(f"{strategy.id}_features", df)

        if not all_dfs:
            logger.error("No samples generated across any strategy")
            return pd.DataFrame()

        if save:
            for stype, dfs in type_dfs.items():
                if len(dfs) < 2:
                    logger.info(
                        "Strategy type '%s': only 1 sub-strategy, skipping type-level save "
                        "(identical to per-id dataset)",
                        stype,
                    )
                    continue
                clean_dfs = [d for d in dfs if not d.empty and not d.isna().all(axis=None)]
                merged = pd.concat(clean_dfs, ignore_index=True)
                self._store.save_dataset(f"{stype}_features", merged)
                logger.info(
                    "Strategy type '%s': %d samples from %d sub-strategies",
                    stype,
                    len(merged),
                    len(dfs),
                )

        clean_all = [d for d in all_dfs if not d.empty and not d.isna().all(axis=None)]
        combined = pd.concat(clean_all, ignore_index=True)
        logger.info(
            "Combined dataset: %d samples, %d features, %d strategies",
            len(combined),
            len(combined.columns),
            combined["strategy_type"].nunique(),
        )

        if save:
            self._store.save_dataset("all_features", combined)

        return combined

    def build_for_recommendations(
        self,
        recs_df: pd.DataFrame,
        save: bool = True,
        min_samples: int = 200,
    ) -> pd.DataFrame:
        """Build meta-label training features anchored at recommendation dates.

        For each graded recommendation, computes the same technical/context
        features as regular training PLUS LLM-derived features encoding
        the GPT pipeline's output. The result is a dataset where each row
        represents a GPT recommendation with both market features and
        GPT metadata, labeled with the graded outcome.

        Args:
            recs_df: Graded recommendations with columns from
                supabase_provider + outcome_grader (must have
                ``graded_profitable`` and ``graded_label``).
            save: Whether to save per-strategy datasets.
            min_samples: Minimum samples per strategy to save.

        Returns:
            Combined meta-label feature DataFrame.
        """
        required = {"ticker", "graded_profitable", "graded_label"}
        missing = required - set(recs_df.columns)
        if missing:
            logger.error("Missing required columns: %s. Run grade-recommendations first.", missing)
            return pd.DataFrame()

        active_recs = recs_df[
            recs_df["graded_label"].isin({"TP_HIT", "SL_HIT", "TIME_EXIT"})
        ].copy()
        if active_recs.empty:
            logger.warning("No active (BUY/SHORT) graded recommendations to build from")
            return pd.DataFrame()

        if self._vix_data is None:
            self._vix_data = self._store.load_prices("VIX", "D")

        spy_prices = self._store.load_prices("SPY", "D")
        if len(spy_prices) >= 20 and self._spy_returns is None:
            spy_prices = spy_prices.copy()
            spy_prices["date"] = pd.to_datetime(spy_prices["date"])
            spy_prices["ret_20d"] = spy_prices["close"].pct_change(20)
            self._spy_prices = spy_prices[["date", "close"]].copy()
            self._spy_returns = spy_prices[["date", "ret_20d"]].dropna()

        if not self._breadth_cache:
            daily_tickers = self._store.list_tickers("prices", "D")
            if daily_tickers:
                self._precompute_market_breadth(daily_tickers)

        all_rows: list[dict[str, Any]] = []

        for _, rec in active_recs.iterrows():
            ticker = rec["ticker"]
            signal_date = self._resolve_rec_date(rec)
            if signal_date is None:
                continue

            prices = self._store.load_prices(ticker, "D")
            if len(prices) < MIN_PRICE_ROWS:
                continue

            prices = prices.copy()
            prices["date"] = pd.to_datetime(prices["date"])

            entry_idx = self._find_date_index(prices, signal_date)
            if entry_idx is None or entry_idx < LOOKBACK_BUFFER:
                continue

            strategy_template = rec.get("strategy_template", "")
            strategy_type = self._infer_strategy_type(strategy_template)

            indicators = self._store.load_indicators(ticker, "D")
            fundamentals_df = self._store.load_fundamentals(ticker)
            fund_features = compute_fundamental_features(fundamentals_df)

            ffd_d_rec = get_ffd_d(strategy_type)
            tech_features = compute_technical_features(prices, indicators, ffd_d=ffd_d_rec)
            if tech_features.empty or entry_idx >= len(tech_features):
                continue

            tech_row = tech_features.iloc[entry_idx]

            date = pd.Timestamp(prices.iloc[entry_idx]["date"])
            vix = self._get_vix_at_date(date)

            context = compute_context_features(
                strategy_type=strategy_type,
                sector=None,
                date=date,
                vix_level=vix,
            )
            context["market_breadth_proxy"] = self._get_breadth_at_date(date)
            context["sector_relative_strength"] = self._get_spy_return_at_date(date)

            key_factors = rec.get("key_factors")
            if isinstance(key_factors, str):
                try:
                    import json

                    key_factors = json.loads(key_factors)
                except Exception:
                    key_factors = []

            warnings_list = rec.get("warnings")
            if isinstance(warnings_list, str):
                try:
                    import json

                    warnings_list = json.loads(warnings_list)
                except Exception:
                    warnings_list = []

            llm_feats = compute_llm_features(
                action=rec.get("action", ""),
                confidence=rec.get("confidence"),
                entry_price=rec.get("entry_price"),
                stop_loss=rec.get("stop_loss"),
                take_profit=rec.get("take_profit"),
                risk_reward_ratio=rec.get("risk_reward_ratio"),
                key_factors=key_factors if isinstance(key_factors, list) else None,
                warnings=warnings_list if isinstance(warnings_list, list) else None,
            )

            row_dict: dict[str, Any] = {
                "ticker": ticker,
                "date": date,
                "strategy_type": strategy_type,
                "close": float(prices.iloc[entry_idx]["close"]),
                "primary_signal": llm_feats["llm_action_encoded"],
                "signal_strength": llm_feats.get("llm_confidence", 0.5),
                "profitable": int(rec["graded_profitable"]),
                "graded_label": rec["graded_label"],
                "actual_return_pct": rec.get("actual_return_pct"),
            }

            if isinstance(tech_row, pd.Series):
                for col in tech_row.index:
                    if col != "date":
                        row_dict[col] = tech_row[col]

            for k, v in fund_features.items():
                row_dict[k] = v
            for k, v in context.items():
                row_dict[k] = v
            for k, v in llm_feats.items():
                row_dict[k] = v

            all_rows.append(row_dict)

        if not all_rows:
            logger.warning("No feature rows generated from recommendations")
            return pd.DataFrame()

        df = pd.DataFrame(all_rows)
        if self._neutralize:
            df = neutralize_features(df)

        logger.info(
            "Meta-label dataset: %d samples across %d tickers, %d features",
            len(df),
            df["ticker"].nunique(),
            len(df.columns),
        )

        if save:
            type_groups = df.groupby("strategy_type")
            for stype, group_df in type_groups:
                if len(group_df) >= min_samples:
                    self._store.save_dataset(f"meta_{stype}_features", group_df)
                    logger.info("Saved meta_%s_features: %d samples", stype, len(group_df))
                else:
                    logger.warning(
                        "Strategy '%s' has only %d samples (min=%d), skipping save",
                        stype,
                        len(group_df),
                        min_samples,
                    )
            self._store.save_dataset("meta_all_features", df)

        return df

    @staticmethod
    def _resolve_rec_date(rec: pd.Series) -> pd.Timestamp | None:
        """Extract signal date from a recommendation row."""
        for col in ("signal_generated_at", "created_at"):
            val = rec.get(col)
            if val is not None and pd.notna(val):
                try:
                    ts = pd.Timestamp(val)
                    if ts.tzinfo is not None:
                        ts = ts.tz_localize(None)
                    return ts
                except Exception:
                    continue
        return None

    @staticmethod
    def _find_date_index(prices: pd.DataFrame, target_date: pd.Timestamp) -> int | None:
        """Find index of the bar closest to target_date."""
        prices_dates = (
            prices["date"].dt.tz_localize(None)
            if prices["date"].dt.tz is not None
            else prices["date"]
        )
        target_norm = target_date.normalize()

        on_date = prices_dates == target_norm
        if on_date.any():
            return int(on_date.idxmax())

        before = prices_dates <= target_norm
        if before.any():
            return int(before[::-1].idxmax())

        return None

    @staticmethod
    def _infer_strategy_type(strategy_template: str) -> str:
        """Map a strategy template name to a granular strategy_type key."""
        if not strategy_template:
            return "momentum_breakout"
        tpl = strategy_template.lower()
        if "crypto" in tpl and ("intraday" in tpl or "scalp" in tpl):
            return "crypto_intraday_scalp"
        if "crypto" in tpl:
            return "crypto_swing"
        if "intraday" in tpl or "scalp" in tpl:
            return "intraday_scalp"
        if "mean_reversion" in tpl or "mean reversion" in tpl:
            return "mean_reversion"
        if "value" in tpl or "accumulation" in tpl:
            return "value_accumulation"
        if "event" in tpl or "earnings" in tpl:
            return "earnings_play"
        if "golden" in tpl or "50_200" in tpl or "50/200" in tpl:
            return "golden_cross_swing"
        if "bollinger" in tpl or "squeeze" in tpl or "bb_squeeze" in tpl:
            return "bb_squeeze_breakout"
        return "momentum_breakout"
