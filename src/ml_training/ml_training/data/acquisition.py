"""Multi-source data acquisition pipeline for ML training.

Orchestrates three data sources for maximum coverage at minimal cost:

* **yfinance** -- free daily OHLCV for US, TSX, and crypto
* **Binance data.binance.vision** -- free intraday + daily crypto OHLCV
* **FMP Stable API** -- intraday stock OHLCV + fundamentals (Premium)

Technical indicators (EMA, RSI, MACD, ADX, ATR) are computed locally
from the OHLCV data.
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
import numpy as np
import pandas as pd
from tqdm import tqdm

from ml_training.data.storage import ParquetStore

logger = logging.getLogger(__name__)

FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"
FMP_TIMEOUT = 30

EMA_PERIODS: list[int] = [9, 21, 50, 200]

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

MAX_CONCURRENT_REQUESTS = 3
RATE_LIMIT_RPM = 750
RATE_LIMIT_WINDOW = 60.0
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0


@dataclass
class AcquisitionConfig:
    """Configuration for a data acquisition run."""

    api_key: str
    data_dir: Path = Path("data/raw")
    timeframes: list[str] = field(default_factory=lambda: ["D", "4H", "1H"])
    daily_lookback_days: int = 5475
    intraday_lookback_days: int = 180
    checkpoint_file: str = "acquisition_checkpoint.json"
    max_concurrent: int = MAX_CONCURRENT_REQUESTS
    include_fundamentals: bool = True
    include_market_context: bool = True


# ---------------------------------------------------------------------------
# Rate limiter + Checkpoint (shared infra)
# ---------------------------------------------------------------------------


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
                sleep_time = self._timestamps[0] - cutoff + 0.5
                logger.info(
                    "Rate limit reached (%d/%d), pausing %.1fs",
                    len(self._timestamps),
                    self.max_rpm,
                    sleep_time,
                )
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

    @property
    def completed(self) -> set[str]:
        return self._completed


# ---------------------------------------------------------------------------
# Local technical indicator computation
# ---------------------------------------------------------------------------


def compute_indicators_from_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all technical indicators locally from OHLCV data.

    Args:
        df: DataFrame with columns: date, open, high, low, close, volume.

    Returns:
        DataFrame with date + all indicator columns.
    """
    if df.empty or "close" not in df.columns:
        return pd.DataFrame()

    result = pd.DataFrame({"date": df["date"]})
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    for period in EMA_PERIODS:
        result[f"ema_{period}"] = close.ewm(span=period, adjust=False).mean()

    result["rsi"] = _compute_rsi(close, 14)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    result["macd"] = ema12 - ema26
    result["macd_signal"] = result["macd"].ewm(span=9, adjust=False).mean()
    result["macd_histogram"] = result["macd"] - result["macd_signal"]

    result["adx"] = _compute_adx(high, low, close, 14)
    result["atr"] = _compute_atr(high, low, close, 14)

    return result


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Compute Relative Strength Index."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Compute Average True Range."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Compute Average Directional Index."""
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    plus_dm = (high - prev_high).clip(lower=0)
    minus_dm = (prev_low - low).clip(lower=0)
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0

    atr = _compute_atr(high, low, close, period)
    atr_safe = atr.replace(0, np.nan)

    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_safe
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_safe

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(span=period, adjust=False).mean()


# ---------------------------------------------------------------------------
# FMP Stable API client (for intraday stocks + fundamentals)
# ---------------------------------------------------------------------------


class FMPHistoricalClient:
    """Async FMP client using the Stable API with connection pooling."""

    def __init__(self, config: AcquisitionConfig) -> None:
        self._config = config
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._rate_limiter = RateLimiter()
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=FMP_TIMEOUT,
                limits=httpx.Limits(
                    max_connections=MAX_CONCURRENT_REQUESTS + 2,
                    max_keepalive_connections=MAX_CONCURRENT_REQUESTS,
                ),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a rate-limited GET request with retry on 403/429."""
        query: dict[str, Any] = {"apikey": self._config.api_key}
        if params:
            query.update(params)

        client = await self._ensure_client()

        for attempt in range(MAX_RETRIES):
            await self._rate_limiter.acquire()
            async with self._semaphore:
                try:
                    resp = await client.get(url, params=query)
                except httpx.ConnectError, httpx.ReadTimeout:
                    if attempt < MAX_RETRIES - 1:
                        wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                        logger.warning("Connection error, retrying in %.0fs...", wait)
                        await asyncio.sleep(wait)
                        continue
                    raise

                if resp.status_code == 402:
                    short_url = url.replace(FMP_STABLE_BASE, "")
                    logger.warning("402 Payment Required: %s not available on your plan", short_url)
                    return None

                if resp.status_code in (429, 403):
                    if attempt < MAX_RETRIES - 1:
                        wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                        logger.warning(
                            "%d from FMP, backing off %.0fs (attempt %d/%d)",
                            resp.status_code,
                            wait,
                            attempt + 1,
                            MAX_RETRIES,
                        )
                        await asyncio.sleep(wait)
                        continue
                    short_url = url.replace(FMP_STABLE_BASE, "")
                    logger.warning(
                        "Giving up after %d retries: %d %s",
                        MAX_RETRIES,
                        resp.status_code,
                        short_url,
                    )
                    return None

                resp.raise_for_status()
                return resp.json()

        return None

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "D",
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV candle history from the Stable API."""
        fmp_tf = TIMEFRAME_MAP.get(timeframe, timeframe)
        params: dict[str, Any] = {"symbol": symbol}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        if fmp_tf == "daily":
            url = f"{FMP_STABLE_BASE}/historical-price-eod/full"
        else:
            url = f"{FMP_STABLE_BASE}/historical-chart/{fmp_tf}"

        try:
            data = await self._get(url, params)
            if data is None:
                return []
            if isinstance(data, dict) and "historical" in data:
                rows = data["historical"]
            elif isinstance(data, list):
                rows = data
            else:
                return []
            rows.sort(key=lambda r: r.get("date", ""))
            return rows
        except Exception:
            logger.warning("Failed to fetch OHLCV for %s/%s", symbol, timeframe)
            return []

    async def fetch_ratios_ttm(self, symbol: str) -> dict[str, Any] | None:
        url = f"{FMP_STABLE_BASE}/ratios-ttm"
        try:
            data = await self._get(url, {"symbol": symbol})
            if isinstance(data, list) and data:
                return data[0]
        except Exception:
            logger.debug("Failed to fetch ratios TTM for %s", symbol)
        return None

    async def fetch_key_metrics_ttm(self, symbol: str) -> dict[str, Any] | None:
        url = f"{FMP_STABLE_BASE}/key-metrics-ttm"
        try:
            data = await self._get(url, {"symbol": symbol})
            if isinstance(data, list) and data:
                return data[0]
        except Exception:
            logger.debug("Failed to fetch key metrics TTM for %s", symbol)
        return None

    async def fetch_financial_scores(self, symbol: str) -> dict[str, Any] | None:
        url = f"{FMP_STABLE_BASE}/financial-scores"
        try:
            data = await self._get(url, {"symbol": symbol})
            if isinstance(data, list) and data:
                return data[0]
        except Exception:
            logger.debug("Failed to fetch financial scores for %s", symbol)
        return None

    async def fetch_insider_trades(self, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
        url = f"{FMP_STABLE_BASE}/insider-trading"
        try:
            data = await self._get(url, {"symbol": symbol, "limit": limit})
            return data if isinstance(data, list) else []
        except Exception:
            logger.debug("Failed to fetch insider trades for %s", symbol)
            return []


# ---------------------------------------------------------------------------
# Universe helpers
# ---------------------------------------------------------------------------


def _default_universe() -> dict[str, list[str]]:
    return {"tsx": [], "us": [], "crypto": []}


# ---------------------------------------------------------------------------
# Multi-source acquisition pipeline
# ---------------------------------------------------------------------------


class DataAcquisitionPipeline:
    """Orchestrates multi-source data acquisition.

    Source routing:

    * **Daily OHLCV** (all assets) → yfinance (free)
    * **Intraday OHLCV** (stocks) → FMP Stable API (Premium)
    * **All crypto OHLCV** (D/4H/1H) → Binance data.binance.vision (free)
    * **Fundamentals** (stocks) → FMP Stable API (Premium)
    * **Market context** (VIX/SPY) → yfinance (free)
    * **Technical indicators** → computed locally from OHLCV data
    """

    def __init__(self, config: AcquisitionConfig) -> None:
        self._config = config
        self._client = FMPHistoricalClient(config)
        self._store = ParquetStore(config.data_dir)
        self._checkpoint = Checkpoint(config.data_dir / config.checkpoint_file)

    async def fetch_universe(self) -> dict[str, list[str]]:
        """Fetch the ticker universe from FMP screener endpoints."""
        universe = _default_universe()

        logger.info("Fetching TSX universe...")
        tsx_url = f"{FMP_STABLE_BASE}/company-screener"
        tsx_tickers: list[str] = []
        page_limit = 1000
        for offset in range(0, 5000, page_limit):
            tsx_params: dict[str, Any] = {
                "exchange": "TSX",
                "isActivelyTrading": "true",
                "volumeMoreThan": "100000",
                "limit": page_limit,
                "offset": offset,
            }
            try:
                data = await self._client._get(tsx_url, tsx_params)
                if not isinstance(data, list) or len(data) == 0:
                    break
                tsx_tickers.extend(r["symbol"] for r in data if "symbol" in r)
                if len(data) < page_limit:
                    break
            except Exception:
                logger.exception("Failed to fetch TSX universe (offset=%d)", offset)
                break
        universe["tsx"] = tsx_tickers
        logger.info("TSX: %d tickers", len(universe["tsx"]))

        logger.info("Fetching US universe (S&P 500)...")
        sp500_url = f"{FMP_STABLE_BASE}/sp500-constituent"
        try:
            data = await self._client._get(sp500_url)
            if isinstance(data, list):
                universe["us"] = [r["symbol"] for r in data if "symbol" in r]
                logger.info("US: %d tickers", len(universe["us"]))
        except Exception:
            logger.exception("Failed to fetch S&P 500 constituents")

        if not universe["us"]:
            logger.info("S&P 500 endpoint failed, falling back to US screener...")
            us_url = f"{FMP_STABLE_BASE}/company-screener"
            us_tickers: list[str] = []
            for offset in range(0, 5000, page_limit):
                us_params: dict[str, Any] = {
                    "exchange": "NASDAQ,NYSE",
                    "isActivelyTrading": "true",
                    "marketCapMoreThan": "10000000000",
                    "volumeMoreThan": "500000",
                    "limit": page_limit,
                    "offset": offset,
                }
                try:
                    data = await self._client._get(us_url, us_params)
                    if not isinstance(data, list) or len(data) == 0:
                        break
                    us_tickers.extend(r["symbol"] for r in data if "symbol" in r)
                    if len(data) < page_limit:
                        break
                except Exception:
                    logger.exception("Failed to fetch US universe (offset=%d)", offset)
                    break
            universe["us"] = us_tickers
            logger.info("US (screener fallback): %d tickers", len(universe["us"]))

        from ml_training.data.binance_provider import TOP_CRYPTO_PAIRS

        universe["crypto"] = [p.replace("USDT", "USD") for p in TOP_CRYPTO_PAIRS]
        logger.info("Crypto: %d pairs (Binance top coins)", len(universe["crypto"]))

        return universe

    # -- Phase 1: Daily OHLCV via yfinance (free) ----------------------------

    def _pull_yfinance_ohlcv(
        self,
        tickers: list[str],
        category: str,
        timeframe: str = "D",
    ) -> None:
        """Download OHLCV for a category via yfinance (daily, weekly, or monthly)."""
        from ml_training.data.yfinance_provider import download_daily_ohlcv

        download_daily_ohlcv(
            tickers=tickers,
            category=category,
            store=self._store,
            completed=self._checkpoint.completed,
            lookback_years=self._config.daily_lookback_days // 365 or 2,
            timeframe=timeframe,
        )
        self._checkpoint.save()

    # -- Phase 2: Intraday OHLCV via FMP (stocks only) ----------------------

    async def _pull_intraday_fmp(
        self,
        tickers: list[str],
        timeframes: list[str],
    ) -> None:
        """Download intraday OHLCV for stocks via FMP Premium."""
        yf_handled = {"D", "W", "M"}
        intraday_tfs = [tf for tf in timeframes if tf not in yf_handled]
        if not intraday_tfs:
            return

        logger.info(
            "Fetching intraday OHLCV via FMP: %d tickers x %s",
            len(tickers),
            intraday_tfs,
        )
        pbar = tqdm(total=len(tickers), desc="fmp intraday", unit="ticker")

        for symbol in tickers:
            for tf in intraday_tfs:
                key = f"prices:{symbol}:{tf}"
                if self._checkpoint.is_done(key):
                    continue

                from_date = (
                    datetime.now(tz=UTC) - timedelta(days=self._config.intraday_lookback_days)
                ).strftime("%Y-%m-%d")
                to_date = datetime.now(tz=UTC).strftime("%Y-%m-%d")

                data = await self._client.fetch_ohlcv(symbol, tf, from_date, to_date)
                if data:
                    self._store.save_prices(symbol, tf, data)
                    self._checkpoint.mark_done(key)
                    logger.debug("Stored %d candles for %s/%s (FMP)", len(data), symbol, tf)

            pbar.update(1)
            self._checkpoint.save()

        pbar.close()

    # -- Phase 3: Crypto OHLCV via Binance (free) ---------------------------

    def _pull_crypto_binance(self, timeframes: list[str]) -> None:
        """Download crypto OHLCV from Binance public data."""
        from ml_training.data.binance_provider import download_crypto_ohlcv

        months = self._config.daily_lookback_days // 30
        download_crypto_ohlcv(
            timeframes=timeframes,
            store=self._store,
            completed=self._checkpoint.completed,
            months_back=months,
        )
        self._checkpoint.save()

    # -- Phase 4: Compute indicators locally ---------------------------------

    def _compute_all_indicators(
        self,
        tickers: list[str],
        timeframes: list[str],
    ) -> None:
        """Compute technical indicators for all downloaded OHLCV data.

        Parallelised across ticker x timeframe pairs when free-threading
        is active.  Each pair is independent: load OHLCV → compute
        indicators → save Parquet.
        """
        from ml_training.threading import parallel_map

        tasks: list[tuple[str, str]] = [
            (symbol, tf)
            for symbol in tickers
            for tf in timeframes
            if not self._checkpoint.is_done(f"indicators:{symbol}:{tf}")
        ]

        if not tasks:
            logger.info("All indicators already computed, skipping")
            return

        logger.info("Computing technical indicators for %d ticker-timeframe pairs...", len(tasks))

        def _compute_one(pair: tuple[str, str]) -> bool:
            symbol, tf = pair
            prices_df = self._store.load_prices(symbol, tf)
            if prices_df.empty:
                return False

            required = {"open", "high", "low", "close", "volume"}
            if not required.issubset(prices_df.columns):
                return False

            indicators_df = compute_indicators_from_ohlcv(prices_df)
            if not indicators_df.empty:
                self._store.save_indicators_df(symbol, tf, indicators_df)
                return True
            return False

        results = parallel_map(_compute_one, tasks, desc="indicators")

        computed = 0
        for task, success in zip(tasks, results):
            if success:
                symbol, tf = task
                self._checkpoint.mark_done(f"indicators:{symbol}:{tf}")
                computed += 1

        self._checkpoint.save()
        logger.info("Computed indicators for %d ticker-timeframe combinations", computed)

    # -- Phase 5: Fundamentals via FMP ---------------------------------------

    async def _pull_fundamentals_fmp(self, tickers: list[str]) -> None:
        """Download fundamental data for stocks via FMP."""
        to_fetch = [s for s in tickers if not self._checkpoint.is_done(f"fundamentals:{s}")]
        if not to_fetch:
            logger.info("All fundamentals already downloaded, skipping")
            return

        logger.info("Fetching fundamentals via FMP: %d tickers", len(to_fetch))
        pbar = tqdm(total=len(to_fetch), desc="fmp fundamentals", unit="ticker")

        for symbol in to_fetch:
            try:
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
                self._checkpoint.mark_done(f"fundamentals:{symbol}")
            except Exception:
                logger.warning("Failed fundamentals for %s", symbol)

            pbar.update(1)
            self._checkpoint.save()

        pbar.close()

    # -- Phase 6: Market context via yfinance --------------------------------

    def _pull_market_context(self) -> None:
        """Download VIX + SPY daily data via yfinance (free)."""
        if self._checkpoint.is_done("market_context"):
            return

        from ml_training.data.yfinance_provider import download_market_context

        download_market_context(self._store, self._checkpoint.completed)
        self._checkpoint.mark_done("market_context")
        self._checkpoint.save()

    # -- Main orchestrator ---------------------------------------------------

    async def run(
        self,
        universe: dict[str, list[str]] | None = None,
        category: Literal["all", "tsx", "us", "crypto"] | None = None,
    ) -> dict[str, int]:
        """Execute the full multi-source data acquisition pipeline.

        Pipeline phases:
            1. Market context (VIX/SPY) → yfinance
            2. Daily OHLCV (all assets) → yfinance
            3. Crypto OHLCV (D/4H/1H) → Binance
            4. Intraday stock OHLCV (4H/1H) → FMP
            5. Technical indicators → local computation
            6. Fundamentals (stocks only) → FMP
        """
        try:
            if universe is None:
                universe = await self.fetch_universe()

            categories = [category] if category and category != "all" else ["tsx", "us", "crypto"]
            results: dict[str, int] = {}
            timeframes = self._config.timeframes

            # Phase 1: Market context
            logger.info("=" * 60)
            logger.info("Phase 1: Market context (yfinance)")
            logger.info("=" * 60)
            if self._config.include_market_context:
                self._pull_market_context()

            all_stock_tickers: list[str] = []
            all_tickers: list[str] = []

            for cat in categories:
                tickers = universe.get(cat, [])
                if not tickers:
                    logger.warning("No tickers for %s, skipping", cat)
                    continue
                results[cat] = len(tickers)
                all_tickers.extend(tickers)
                if cat != "crypto":
                    all_stock_tickers.extend(tickers)

            # Phase 2: Daily/Weekly/Monthly OHLCV via yfinance (free)
            yf_timeframes = [tf for tf in timeframes if tf in ("D", "W", "M")]
            if yf_timeframes:
                logger.info("=" * 60)
                logger.info("Phase 2: OHLCV via yfinance -- free (%s)", ", ".join(yf_timeframes))
                logger.info("=" * 60)
                for cat in categories:
                    tickers = universe.get(cat, [])
                    if tickers:
                        for tf in yf_timeframes:
                            self._pull_yfinance_ohlcv(tickers, cat, timeframe=tf)

            # Phase 3: Crypto OHLCV via Binance (free -- all timeframes)
            if "crypto" in categories:
                logger.info("=" * 60)
                logger.info("Phase 3: Crypto OHLCV (Binance -- free)")
                logger.info("=" * 60)
                self._pull_crypto_binance(timeframes)

            # Phase 4: Intraday stock OHLCV via FMP (paid)
            yf_handled = {"D", "W", "M"}
            intraday_tfs = [tf for tf in timeframes if tf not in yf_handled]
            if all_stock_tickers and intraday_tfs:
                logger.info("=" * 60)
                logger.info("Phase 4: Intraday stock OHLCV (FMP Premium)")
                logger.info("=" * 60)
                await self._pull_intraday_fmp(all_stock_tickers, timeframes)

            # Phase 5: Compute indicators locally
            logger.info("=" * 60)
            logger.info("Phase 5: Technical indicators (local computation)")
            logger.info("=" * 60)
            self._compute_all_indicators(all_tickers, timeframes)

            # Phase 6: Fundamentals via FMP
            if all_stock_tickers and self._config.include_fundamentals:
                logger.info("=" * 60)
                logger.info("Phase 6: Fundamentals (FMP Premium)")
                logger.info("=" * 60)
                await self._pull_fundamentals_fmp(all_stock_tickers)

            total = sum(results.values())
            logger.info("=" * 60)
            logger.info(
                "Acquisition complete: %d tickers across %s",
                total,
                ", ".join(results.keys()),
            )
            logger.info("=" * 60)
            return results
        finally:
            await self._client.close()

    def verify(self) -> dict[str, Any]:
        """Run verification checks on acquired data."""
        return self._store.verify_data()
