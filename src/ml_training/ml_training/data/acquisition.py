"""FMP historical data puller with rate limiting, checkpointing, and progress logging.

Pulls OHLCV price history, technical indicators, and fundamental data
for a configurable universe of tickers. Stores results as Parquet files
via the storage module.

FMP Fundamental tier limits: 750 requests/minute, 50 GB/month.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
from tqdm import tqdm

from ml_training.data.storage import ParquetStore

logger = logging.getLogger(__name__)

FMP_V3_BASE = "https://financialmodelingprep.com/api/v3"
FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"
FMP_TIMEOUT = 30

EMA_PERIODS: list[int] = [9, 21, 50, 200]
INDICATOR_TYPES: list[str] = ["rsi", "macd", "adx", "atr"]

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

MAX_CONCURRENT_REQUESTS = 5
RATE_LIMIT_RPM = 750
RATE_LIMIT_WINDOW = 60.0


@dataclass
class AcquisitionConfig:
    """Configuration for a data acquisition run."""

    api_key: str
    data_dir: Path = Path("src/ml_training/data/raw")
    timeframes: list[str] = field(default_factory=lambda: ["D", "4H", "1H"])
    daily_lookback_days: int = 730  # ~2 years
    intraday_lookback_days: int = 180  # ~6 months
    checkpoint_file: str = "acquisition_checkpoint.json"
    max_concurrent: int = MAX_CONCURRENT_REQUESTS
    include_fundamentals: bool = True
    include_market_context: bool = True


@dataclass
class RateLimiter:
    """Token-bucket rate limiter for FMP API calls."""

    max_rpm: int = RATE_LIMIT_RPM
    _timestamps: list[float] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def acquire(self) -> None:
        """Wait until a request slot is available within the rate limit window."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            cutoff = now - RATE_LIMIT_WINDOW
            self._timestamps = [t for t in self._timestamps if t > cutoff]

            if len(self._timestamps) >= self.max_rpm:
                sleep_time = self._timestamps[0] - cutoff + 0.1
                logger.debug("Rate limit reached, sleeping %.1fs", sleep_time)
                await asyncio.sleep(sleep_time)

            self._timestamps.append(asyncio.get_event_loop().time())


class Checkpoint:
    """Tracks completed ticker/timeframe combinations for resumable acquisition."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._completed: set[str] = set()
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            data = json.loads(self._path.read_text())
            self._completed = set(data.get("completed", []))
            logger.info("Loaded checkpoint with %d completed items", len(self._completed))

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"completed": sorted(self._completed)}))

    def is_done(self, key: str) -> bool:
        return key in self._completed

    def mark_done(self, key: str) -> None:
        self._completed.add(key)

    @property
    def completed_count(self) -> int:
        return len(self._completed)


class FMPHistoricalClient:
    """Async FMP client for bulk historical data retrieval."""

    def __init__(self, config: AcquisitionConfig) -> None:
        self._config = config
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._rate_limiter = RateLimiter()

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a rate-limited GET request against FMP."""
        await self._rate_limiter.acquire()
        query: dict[str, Any] = {"apikey": self._config.api_key}
        if params:
            query.update(params)

        async with self._semaphore, httpx.AsyncClient(timeout=FMP_TIMEOUT) as client:
            resp = await client.get(url, params=query)
            resp.raise_for_status()
            return resp.json()

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "D",
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV candle history for a symbol.

        Args:
            symbol: Ticker symbol (e.g. "AAPL", "BTCUSD").
            timeframe: One of the keys in TIMEFRAME_MAP.
            from_date: Start date "YYYY-MM-DD".
            to_date: End date "YYYY-MM-DD".

        Returns:
            List of candle dicts sorted chronologically (oldest first).
        """
        fmp_tf = TIMEFRAME_MAP.get(timeframe, timeframe)

        if fmp_tf == "daily":
            url = f"{FMP_V3_BASE}/historical-price-full/{symbol}"
            params: dict[str, Any] = {"serietype": "line"}
            if from_date:
                params["from"] = from_date
            if to_date:
                params["to"] = to_date
        else:
            url = f"{FMP_V3_BASE}/historical-chart/{fmp_tf}/{symbol}"
            params = {}
            if from_date:
                params["from"] = from_date
            if to_date:
                params["to"] = to_date

        try:
            data = await self._get(url, params)
            if isinstance(data, dict) and "historical" in data:
                rows = data["historical"]
            elif isinstance(data, list):
                rows = data
            else:
                return []
            rows.sort(key=lambda r: r.get("date", ""))
            return rows
        except Exception:
            logger.exception("Failed to fetch OHLCV for %s/%s", symbol, timeframe)
            return []

    async def fetch_indicator(
        self,
        symbol: str,
        timeframe: str,
        indicator_type: str,
        period: int = 14,
    ) -> list[dict[str, Any]]:
        """Fetch a technical indicator series from FMP v3.

        Args:
            symbol: Ticker symbol.
            timeframe: Strategy timeframe (mapped internally).
            indicator_type: "ema", "rsi", "macd", "adx", "atr".
            period: Lookback period.

        Returns:
            List of indicator dicts sorted chronologically (oldest first).
        """
        fmp_tf = TIMEFRAME_MAP.get(timeframe, timeframe)
        url = f"{FMP_V3_BASE}/technical_indicator/{fmp_tf}/{symbol}"
        params: dict[str, Any] = {"type": indicator_type, "period": period}

        try:
            data = await self._get(url, params)
            if isinstance(data, list):
                data.sort(key=lambda r: r.get("date", ""))
                return data
            return []
        except Exception:
            logger.exception(
                "Failed to fetch %s(%d) for %s/%s", indicator_type, period, symbol, timeframe
            )
            return []

    async def fetch_ratios_ttm(self, symbol: str) -> dict[str, Any] | None:
        """Fetch trailing twelve-month financial ratios."""
        url = f"{FMP_STABLE_BASE}/ratios-ttm"
        try:
            data = await self._get(url, {"symbol": symbol})
            if isinstance(data, list) and data:
                return data[0]
        except Exception:
            logger.debug("Failed to fetch ratios TTM for %s", symbol)
        return None

    async def fetch_key_metrics_ttm(self, symbol: str) -> dict[str, Any] | None:
        """Fetch trailing twelve-month key metrics."""
        url = f"{FMP_STABLE_BASE}/key-metrics-ttm"
        try:
            data = await self._get(url, {"symbol": symbol})
            if isinstance(data, list) and data:
                return data[0]
        except Exception:
            logger.debug("Failed to fetch key metrics TTM for %s", symbol)
        return None

    async def fetch_financial_scores(self, symbol: str) -> dict[str, Any] | None:
        """Fetch Piotroski and Altman Z scores."""
        url = f"{FMP_STABLE_BASE}/financial-scores"
        try:
            data = await self._get(url, {"symbol": symbol})
            if isinstance(data, list) and data:
                return data[0]
        except Exception:
            logger.debug("Failed to fetch financial scores for %s", symbol)
        return None

    async def fetch_insider_trades(self, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch recent insider trading activity."""
        url = f"{FMP_STABLE_BASE}/insider-trading"
        try:
            data = await self._get(url, {"symbol": symbol, "limit": limit})
            return data if isinstance(data, list) else []
        except Exception:
            logger.debug("Failed to fetch insider trades for %s", symbol)
            return []

    async def fetch_analyst_estimates(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch analyst consensus estimates."""
        url = f"{FMP_STABLE_BASE}/analyst-estimates"
        try:
            data = await self._get(url, {"symbol": symbol, "limit": 4})
            return data if isinstance(data, list) else []
        except Exception:
            logger.debug("Failed to fetch analyst estimates for %s", symbol)
            return []

    async def fetch_market_index(
        self,
        symbol: str = "SPY",
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch daily OHLCV for a market index (SPY, ^VIX, etc.)."""
        return await self.fetch_ohlcv(symbol, "D", from_date, to_date)


def _default_universe() -> dict[str, list[str]]:
    """Return the default ticker universe grouped by exchange type.

    Returns a skeleton -- the actual lists are populated by fetch_universe().
    """
    return {"tsx": [], "us": [], "crypto": []}


class DataAcquisitionPipeline:
    """Orchestrates the full data acquisition process with checkpointing.

    Usage::

        config = AcquisitionConfig(api_key="YOUR_KEY")
        pipeline = DataAcquisitionPipeline(config)
        await pipeline.run()
    """

    def __init__(self, config: AcquisitionConfig) -> None:
        self._config = config
        self._client = FMPHistoricalClient(config)
        self._store = ParquetStore(config.data_dir)
        self._checkpoint = Checkpoint(config.data_dir / config.checkpoint_file)

    async def fetch_universe(self) -> dict[str, list[str]]:
        """Fetch the ticker universe from FMP screener endpoints.

        Returns:
            Dict with keys 'tsx', 'us', 'crypto' mapping to ticker lists.
        """
        universe = _default_universe()

        logger.info("Fetching TSX universe...")
        tsx_url = f"{FMP_STABLE_BASE}/company-screener"
        tsx_params = {
            "exchange": "TSX",
            "isActivelyTrading": "true",
            "volumeMoreThan": "100000",
            "limit": 200,
        }
        try:
            data = await self._client._get(tsx_url, tsx_params)
            if isinstance(data, list):
                universe["tsx"] = [r["symbol"] for r in data if "symbol" in r]
                logger.info("TSX: %d tickers", len(universe["tsx"]))
        except Exception:
            logger.exception("Failed to fetch TSX universe")

        logger.info("Fetching US universe (S&P 500)...")
        sp500_url = f"{FMP_V3_BASE}/sp500_constituent"
        try:
            data = await self._client._get(sp500_url)
            if isinstance(data, list):
                universe["us"] = [r["symbol"] for r in data if "symbol" in r]
                logger.info("US: %d tickers", len(universe["us"]))
        except Exception:
            logger.exception("Failed to fetch S&P 500 constituents")

        logger.info("Fetching crypto universe...")
        crypto_url = f"{FMP_STABLE_BASE}/cryptocurrency-list"
        try:
            data = await self._client._get(crypto_url)
            if isinstance(data, list):
                sorted_by_cap = sorted(
                    [c for c in data if c.get("marketCap")],
                    key=lambda c: c.get("marketCap", 0),
                    reverse=True,
                )
                universe["crypto"] = [c["symbol"] for c in sorted_by_cap[:50]]
                logger.info("Crypto: %d tickers", len(universe["crypto"]))
        except Exception:
            logger.exception("Failed to fetch crypto universe")

        return universe

    async def _pull_ticker_prices(self, symbol: str, timeframe: str) -> None:
        """Pull and store OHLCV data for one ticker/timeframe."""
        key = f"prices:{symbol}:{timeframe}"
        if self._checkpoint.is_done(key):
            return

        is_daily = timeframe == "D"
        lookback = (
            self._config.daily_lookback_days if is_daily else self._config.intraday_lookback_days
        )
        from_date = (datetime.now(tz=UTC) - timedelta(days=lookback)).strftime("%Y-%m-%d")
        to_date = datetime.now(tz=UTC).strftime("%Y-%m-%d")

        data = await self._client.fetch_ohlcv(symbol, timeframe, from_date, to_date)
        if data:
            self._store.save_prices(symbol, timeframe, data)
            self._checkpoint.mark_done(key)
            logger.debug("Stored %d candles for %s/%s", len(data), symbol, timeframe)

    async def _pull_ticker_indicators(self, symbol: str, timeframe: str) -> None:
        """Pull and store all technical indicators for one ticker/timeframe."""
        key = f"indicators:{symbol}:{timeframe}"
        if self._checkpoint.is_done(key):
            return

        all_indicators: dict[str, list[dict[str, Any]]] = {}

        for period in EMA_PERIODS:
            ema_data = await self._client.fetch_indicator(symbol, timeframe, "ema", period)
            if ema_data:
                all_indicators[f"ema_{period}"] = ema_data

        for ind_type in INDICATOR_TYPES:
            ind_data = await self._client.fetch_indicator(symbol, timeframe, ind_type)
            if ind_data:
                all_indicators[ind_type] = ind_data

        if all_indicators:
            self._store.save_indicators(symbol, timeframe, all_indicators)
            self._checkpoint.mark_done(key)
            logger.debug(
                "Stored %d indicator series for %s/%s",
                len(all_indicators),
                symbol,
                timeframe,
            )

    async def _pull_ticker_fundamentals(self, symbol: str) -> None:
        """Pull and store fundamental data for one ticker."""
        key = f"fundamentals:{symbol}"
        if self._checkpoint.is_done(key):
            return

        ratios, metrics, scores, insiders = await asyncio.gather(
            self._client.fetch_ratios_ttm(symbol),
            self._client.fetch_key_metrics_ttm(symbol),
            self._client.fetch_financial_scores(symbol),
            self._client.fetch_insider_trades(symbol),
            return_exceptions=True,
        )

        fundamentals: dict[str, Any] = {"symbol": symbol}

        if isinstance(ratios, dict):
            fundamentals["ratios_ttm"] = ratios
        if isinstance(metrics, dict):
            fundamentals["key_metrics_ttm"] = metrics
        if isinstance(scores, dict):
            fundamentals["financial_scores"] = scores
        if isinstance(insiders, list):
            buy_count = sum(1 for t in insiders if t.get("transactionType") == "P-Purchase")
            sell_count = sum(1 for t in insiders if t.get("transactionType") == "S-Sale")
            fundamentals["insider_buy_count"] = buy_count
            fundamentals["insider_sell_count"] = sell_count

        self._store.save_fundamentals(symbol, fundamentals)
        self._checkpoint.mark_done(key)
        logger.debug("Stored fundamentals for %s", symbol)

    async def _pull_market_context(self) -> None:
        """Pull VIX history and market indices."""
        key = "market_context"
        if self._checkpoint.is_done(key):
            return

        from_date = (
            datetime.now(tz=UTC) - timedelta(days=self._config.daily_lookback_days)
        ).strftime("%Y-%m-%d")
        to_date = datetime.now(tz=UTC).strftime("%Y-%m-%d")

        vix_data = await self._client.fetch_market_index("^VIX", from_date, to_date)
        if vix_data:
            self._store.save_prices("VIX", "D", vix_data)

        spy_data = await self._client.fetch_market_index("SPY", from_date, to_date)
        if spy_data:
            self._store.save_prices("SPY", "D", spy_data)

        self._checkpoint.mark_done(key)
        logger.info("Stored market context (VIX + SPY)")

    async def _pull_single_ticker(
        self,
        symbol: str,
        timeframes: list[str],
        is_crypto: bool = False,
        pbar: tqdm[Any] | None = None,
    ) -> None:
        """Pull all data for a single ticker."""
        for tf in timeframes:
            await self._pull_ticker_prices(symbol, tf)
            await self._pull_ticker_indicators(symbol, tf)

        if not is_crypto and self._config.include_fundamentals:
            await self._pull_ticker_fundamentals(symbol)

        if pbar is not None:
            pbar.update(1)

    async def run(
        self,
        universe: dict[str, list[str]] | None = None,
        category: Literal["all", "tsx", "us", "crypto"] | None = None,
    ) -> dict[str, int]:
        """Execute the full data acquisition pipeline.

        Args:
            universe: Pre-built ticker universe. If None, fetches from FMP.
            category: Limit to a specific category. Defaults to all.

        Returns:
            Dict with counts of tickers processed per category.
        """
        if universe is None:
            universe = await self.fetch_universe()

        categories = [category] if category and category != "all" else ["tsx", "us", "crypto"]
        results: dict[str, int] = {}

        if self._config.include_market_context:
            await self._pull_market_context()

        for cat in categories:
            tickers = universe.get(cat, [])
            if not tickers:
                logger.warning("No tickers for category %s", cat)
                continue

            timeframes = self._config.timeframes
            is_crypto = cat == "crypto"

            logger.info(
                "Starting %s acquisition: %d tickers x %d timeframes",
                cat,
                len(tickers),
                len(timeframes),
            )

            pbar = tqdm(total=len(tickers), desc=f"{cat} tickers", unit="ticker")

            batch_size = self._config.max_concurrent
            for i in range(0, len(tickers), batch_size):
                batch = tickers[i : i + batch_size]
                tasks = [
                    self._pull_single_ticker(sym, timeframes, is_crypto, pbar) for sym in batch
                ]
                await asyncio.gather(*tasks, return_exceptions=True)
                self._checkpoint.save()

            pbar.close()
            results[cat] = len(tickers)

        total = sum(results.values())
        logger.info("Acquisition complete: %d tickers across %s", total, ", ".join(results.keys()))
        return results

    def verify(self) -> dict[str, Any]:
        """Run verification checks on acquired data.

        Returns:
            Dict with verification results: counts, gaps, sanity checks.
        """
        return self._store.verify_data()
