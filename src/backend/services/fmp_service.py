"""Financial Modeling Prep (FMP) screener service for stocks and crypto.

Thin async wrapper around the FMP ``/stable/`` API using ``httpx``.

**Stocks:** ``/stable/company-screener`` with optional ``ratios-ttm``
enrichment and client-side ratio post-filters.

**Crypto:** FMP has no crypto screener endpoint, so we combine
``/stable/cryptocurrency-list`` + ``/stable/batch-crypto-quotes``
and filter client-side by market cap, volume, and price.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from pipeline.schemas import FmpScreenerConfig
from services.keyring_service import get_api_key
from utils.ticker import to_fmp_symbol

logger = logging.getLogger(__name__)

FMP_BASE_URL = "https://financialmodelingprep.com/stable"
FMP_TIMEOUT = 30
_semaphore = asyncio.Semaphore(5)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class FmpScreenerResult(BaseModel):
    """Single result from the FMP company screener endpoint."""

    symbol: str
    companyName: str = ""
    marketCap: int | None = None
    price: float | None = None
    beta: float | None = None
    volume: int | None = None
    lastAnnualDividend: float | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    exchange: str | None = None
    exchangeShortName: str | None = None
    isEtf: bool = False
    isFund: bool = False
    isActivelyTrading: bool = True


class FmpRatiosTTM(BaseModel):
    """Trailing twelve-month financial ratios from FMP."""

    symbol: str = ""
    peRatioTTM: float | None = None
    pegRatioTTM: float | None = None
    priceToBookRatioTTM: float | None = None
    priceToSalesRatioTTM: float | None = None
    returnOnEquityTTM: float | None = None
    returnOnAssetsTTM: float | None = None
    debtEquityRatioTTM: float | None = None
    currentRatioTTM: float | None = None
    dividendYieldTTM: float | None = None
    freeCashFlowPerShareTTM: float | None = None
    netProfitMarginTTM: float | None = None


class FmpKeyMetrics(BaseModel):
    """Trailing twelve-month key metrics from FMP."""

    symbol: str = ""
    revenuePerShareTTM: float | None = None
    netIncomePerShareTTM: float | None = None
    freeCashFlowPerShareTTM: float | None = None
    bookValuePerShareTTM: float | None = None
    marketCapTTM: float | None = None
    peRatioTTM: float | None = None
    enterpriseValueOverEBITDATTM: float | None = None
    revenueGrowthTTM: float | None = None  # May not be in key-metrics-ttm


class FmpCryptoListItem(BaseModel):
    """Single item from the FMP cryptocurrency list endpoint."""

    symbol: str
    name: str = ""
    exchange: str = ""
    exchangeShortName: str = ""


class FmpCryptoQuote(BaseModel):
    """Quote data for a single cryptocurrency from FMP."""

    symbol: str
    name: str = ""
    price: float | None = None
    changesPercentage: float | None = None
    change: float | None = None
    dayLow: float | None = None
    dayHigh: float | None = None
    yearLow: float | None = None
    yearHigh: float | None = None
    marketCap: int | None = None
    volume: int | None = None
    avgVolume: int | None = None
    exchange: str = ""
    open: float | None = None
    previousClose: float | None = None


class FmpEarningsCalendarItem(BaseModel):
    """Single item from the FMP earnings calendar endpoint."""

    symbol: str
    date: str = ""
    eps: float | None = None
    epsEstimated: float | None = None
    revenue: float | None = None
    revenueEstimated: float | None = None
    fiscalDateEnding: str = ""


class FmpEarningsSurprise(BaseModel):
    """Earnings surprise data for a ticker from FMP."""

    symbol: str = ""
    date: str = ""
    actualEarningResult: float | None = None
    estimatedEarning: float | None = None


class FmpPriceChange(BaseModel):
    """Multi-period price change data from FMP.

    FMP returns percentage changes keyed as ``1D``, ``5D``, ``1M``, etc.
    Pydantic aliases map these to valid Python attribute names.
    """

    symbol: str = ""
    oneDay: float | None = Field(default=None, alias="1D")
    fiveDay: float | None = Field(default=None, alias="5D")
    oneMonth: float | None = Field(default=None, alias="1M")
    threeMonth: float | None = Field(default=None, alias="3M")
    sixMonth: float | None = Field(default=None, alias="6M")
    ytd: float | None = None
    oneYear: float | None = Field(default=None, alias="1Y")

    model_config = {"populate_by_name": True}


class FmpFinancialScores(BaseModel):
    """Piotroski and Altman Z-Score from FMP."""

    symbol: str = ""
    altmanZScore: float | None = None
    piotroskiScore: int | None = None


class FmpAnalystGrade(BaseModel):
    """Single analyst grade action from FMP."""

    symbol: str = ""
    date: str = ""
    gradingCompany: str = ""
    previousGrade: str = ""
    newGrade: str = ""
    action: str = ""


class FmpGradesConsensus(BaseModel):
    """Analyst grades consensus (buy/hold/sell counts)."""

    symbol: str = ""
    strongBuy: int = 0
    buy: int = 0
    hold: int = 0
    sell: int = 0
    strongSell: int = 0
    consensus: str = ""


class FmpPriceTargetConsensus(BaseModel):
    """Analyst price target consensus from FMP."""

    symbol: str = ""
    targetHigh: float | None = None
    targetLow: float | None = None
    targetConsensus: float | None = None
    targetMedian: float | None = None


class FmpInsiderStats(BaseModel):
    """Insider trading statistics for a symbol from FMP."""

    symbol: str = ""
    totalBought: int = 0
    totalSold: int = 0
    totalTransactions: int = 0


class FmpShareFloat(BaseModel):
    """Share float data from FMP."""

    symbol: str = ""
    freeFloat: float | None = None
    floatShares: float | None = None
    outstandingShares: float | None = None


class FmpMarketMover(BaseModel):
    """Market mover entry (gainers, losers, most active)."""

    symbol: str
    name: str = ""
    price: float | None = None
    change: float | None = None
    changesPercentage: float | None = None


class FmpSectorPerformance(BaseModel):
    """Sector performance snapshot from FMP."""

    sector: str = ""
    changesPercentage: float | None = None


class FmpEnrichedStock(BaseModel):
    """A screener result enriched with financial ratios, metrics, and signals.

    Combines data from company-screener, ratios-ttm, key-metrics-ttm,
    insider trading, price changes, financial scores, analyst consensus,
    and earnings data into a single scored model for downstream use.
    """

    symbol: str
    company_name: str = ""
    sector: str = ""
    industry: str = ""
    country: str = ""
    exchange: str = ""
    market_cap: int | None = None
    price: float | None = None
    volume: int | None = None
    beta: float | None = None
    is_actively_trading: bool = True

    # Valuation ratios
    pe_ratio: float | None = None
    peg_ratio: float | None = None
    pb_ratio: float | None = None
    ps_ratio: float | None = None
    ev_ebitda: float | None = None

    # Profitability & health
    roe: float | None = None
    roa: float | None = None
    debt_equity: float | None = None
    current_ratio: float | None = None
    dividend_yield: float | None = None
    fcf_per_share: float | None = None
    net_profit_margin: float | None = None

    # Price momentum (from /stable/stock-price-change)
    price_change_1d: float | None = None
    price_change_1m: float | None = None
    price_change_3m: float | None = None
    price_change_6m: float | None = None

    # Volume signals
    avg_volume: int | None = None
    relative_volume: float | None = None

    # Quality scores (from /stable/financial-scores)
    piotroski_score: int | None = None
    altman_z_score: float | None = None

    # Insider activity (from /stable/insider-trading/statistics)
    insider_net_buys: int | None = None
    insider_buy_ratio: float | None = None

    # Analyst consensus (from /stable/upgrades-downgrades-consensus-bulk)
    analyst_consensus: str | None = None
    analyst_buy_count: int | None = None
    analyst_target_upside: float | None = None

    # Earnings (from /stable/earnings-calendar + /stable/earnings)
    earnings_date: str | None = None
    earnings_beat_rate: float | None = None

    # Share float (from /stable/shares-float)
    free_float_pct: float | None = None
    float_shares: int | None = None

    # Multi-factor composite scores (0-100, computed by scoring engine)
    composite_score: float | None = None
    score_fundamental: float | None = None
    score_momentum: float | None = None
    score_sentiment: float | None = None
    score_quality: float | None = None


# ---------------------------------------------------------------------------
# Low-level API helpers
# ---------------------------------------------------------------------------


def _get_api_key() -> str:
    """Retrieve the FMP API key or raise."""
    key = get_api_key("fmp")
    if not key:
        raise RuntimeError(
            "FMP API key not configured. Set FMP_API_KEY in .env (see .env.example)."
        )
    return key


def equity_symbol_key(ticker: str) -> str:
    """Normalize to bare uppercase US symbol for sector map keys."""
    t = ticker.strip().upper()
    return t.split(":", 1)[-1] if ":" in t else t


async def fetch_stock_sectors(symbols: list[str]) -> dict[str, str]:
    """Fetch GICS sector labels for equity symbols via FMP ``profile``.

    Args:
        symbols: Ticker strings (``AAPL`` or ``NASDAQ:AAPL``).

    Returns:
        Map of bare uppercase symbol to sector name. Failed lookups are omitted.
        Returns an empty dict when the FMP API key is missing or all lookups fail.
    """
    try:
        _get_api_key()
    except RuntimeError:
        logger.info("FMP API key not configured; sector lookup skipped")
        return {}

    unique = list({equity_symbol_key(s) for s in symbols if s and s.strip()})
    if not unique:
        return {}

    async def one(sym: str) -> tuple[str, str] | None:
        try:
            fmp_sym = to_fmp_symbol(sym)
            data = await _fmp_get("profile", {"symbol": fmp_sym})
        except Exception as exc:
            logger.warning("FMP profile failed for %s: %s", sym, exc)
            return None
        if isinstance(data, list) and data:
            sector = (data[0].get("sector") or "").strip()
            if sector:
                return sym, sector
        return None

    results = await asyncio.gather(*[one(u) for u in unique])
    out: dict[str, str] = {}
    for r in results:
        if r:
            out[r[0]] = r[1]
    return out


async def _fmp_get(endpoint: str, params: dict[str, Any] | None = None) -> Any:
    """Make an authenticated GET request to the FMP stable API.

    Args:
        endpoint: Path segment after ``/stable/`` (e.g. ``"company-screener"``).
        params: Additional query parameters (apikey is added automatically).

    Returns:
        Parsed JSON response (list or dict).

    Raises:
        httpx.HTTPStatusError: On non-2xx responses.
        RuntimeError: If the API key is missing.
    """
    api_key = _get_api_key()
    query: dict[str, Any] = {"apikey": api_key}
    if params:
        query.update(params)

    async with _semaphore, httpx.AsyncClient(timeout=FMP_TIMEOUT) as client:
        url = f"{FMP_BASE_URL}/{endpoint}"
        response = await client.get(url, params=query)
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# Endpoint wrappers
# ---------------------------------------------------------------------------


async def screen_stocks(config: FmpScreenerConfig) -> list[FmpScreenerResult]:
    """Screen stocks using the FMP company screener endpoint.

    Args:
        config: Screener configuration with filter parameters.

    Returns:
        List of validated screener results.
    """
    params: dict[str, Any] = {
        "limit": config.limit,
        "isActivelyTrading": str(config.is_actively_trading).lower(),
        "isEtf": str(config.is_etf).lower(),
    }

    field_map: dict[str, str] = {
        "country": "country",
        "exchange": "exchange",
        "sector": "sector",
        "industry": "industry",
        "market_cap_min": "marketCapMoreThan",
        "market_cap_max": "marketCapLowerThan",
        "price_min": "priceMoreThan",
        "price_max": "priceLowerThan",
        "volume_min": "volumeMoreThan",
        "beta_min": "betaMoreThan",
        "beta_max": "betaLowerThan",
    }

    for attr, param_name in field_map.items():
        value = getattr(config, attr, None)
        if value is not None:
            params[param_name] = value

    data = await _fmp_get("company-screener", params)

    if not isinstance(data, list):
        logger.warning("FMP screener returned non-list response: %s", type(data))
        return []

    results = []
    for item in data:
        try:
            results.append(FmpScreenerResult.model_validate(item))
        except Exception:
            logger.debug("Skipping invalid FMP screener item: %s", item)
    return results


async def fetch_ratios_ttm(symbol: str) -> FmpRatiosTTM | None:
    """Fetch trailing twelve-month financial ratios for a symbol.

    Args:
        symbol: Stock ticker symbol (e.g. ``"AAPL"``).

    Returns:
        Validated ratios or ``None`` if unavailable.
    """
    try:
        data = await _fmp_get("ratios-ttm", {"symbol": symbol})
        if isinstance(data, list) and data:
            result = FmpRatiosTTM.model_validate(data[0])
            result.symbol = symbol
            return result
    except Exception as exc:
        logger.debug("Failed to fetch ratios-ttm for %s: %s", symbol, exc)
    return None


async def fetch_key_metrics_ttm(symbol: str) -> FmpKeyMetrics | None:
    """Fetch trailing twelve-month key metrics for a symbol.

    Args:
        symbol: Stock ticker symbol (e.g. ``"AAPL"``).

    Returns:
        Validated metrics or ``None`` if unavailable.
    """
    try:
        data = await _fmp_get("key-metrics-ttm", {"symbol": symbol})
        if isinstance(data, list) and data:
            result = FmpKeyMetrics.model_validate(data[0])
            result.symbol = symbol
            return result
    except Exception as exc:
        logger.debug("Failed to fetch key-metrics-ttm for %s: %s", symbol, exc)
    return None


# ---------------------------------------------------------------------------
# New endpoint wrappers (earnings, price change, scores, analyst, insider,
# share float, market context, bulk)
# ---------------------------------------------------------------------------


async def fetch_earnings_calendar(
    from_date: str,
    to_date: str,
) -> list[FmpEarningsCalendarItem]:
    """Fetch earnings calendar for a date range.

    Args:
        from_date: Start date (``YYYY-MM-DD``).
        to_date: End date (``YYYY-MM-DD``).

    Returns:
        List of earnings events within the range.
    """
    try:
        data = await _fmp_get("earnings-calendar", {"from": from_date, "to": to_date})
        if not isinstance(data, list):
            return []
        results: list[FmpEarningsCalendarItem] = []
        for item in data:
            with contextlib.suppress(Exception):
                results.append(FmpEarningsCalendarItem.model_validate(item))
        return results
    except Exception as exc:
        logger.warning("Failed to fetch earnings calendar: %s", exc)
        return []


async def fetch_earnings_surprises(symbol: str) -> list[FmpEarningsSurprise]:
    """Fetch historical earnings surprises for a symbol.

    Args:
        symbol: Stock ticker symbol.

    Returns:
        List of earnings surprise records (most recent first).
    """
    try:
        data = await _fmp_get("earnings", {"symbol": symbol})
        if not isinstance(data, list):
            return []
        results: list[FmpEarningsSurprise] = []
        for item in data:
            with contextlib.suppress(Exception):
                results.append(FmpEarningsSurprise.model_validate(item))
        return results
    except Exception as exc:
        logger.debug("Failed to fetch earnings surprises for %s: %s", symbol, exc)
        return []


def compute_beat_rate(surprises: list[FmpEarningsSurprise], lookback: int = 8) -> float | None:
    """Compute the percentage of quarters where actual > estimated.

    Args:
        surprises: Earnings surprise records (most recent first).
        lookback: Number of recent quarters to evaluate.

    Returns:
        Beat rate as 0-100 percentage, or ``None`` if insufficient data.
    """
    valid = [
        s
        for s in surprises[:lookback]
        if s.actualEarningResult is not None and s.estimatedEarning is not None
    ]
    if not valid:
        return None
    beats = sum(1 for s in valid if s.actualEarningResult > s.estimatedEarning)  # type: ignore[operator]
    return (beats / len(valid)) * 100


async def fetch_price_change(symbol: str) -> FmpPriceChange | None:
    """Fetch multi-period price change data for a symbol.

    Args:
        symbol: Stock ticker symbol.

    Returns:
        Price changes over 1D/5D/1M/3M/6M/YTD/1Y or ``None``.
    """
    try:
        data = await _fmp_get("stock-price-change", {"symbol": symbol})
        if isinstance(data, list) and data:
            result = FmpPriceChange.model_validate(data[0])
            result.symbol = symbol
            return result
    except Exception as exc:
        logger.debug("Failed to fetch price change for %s: %s", symbol, exc)
    return None


async def fetch_financial_scores(symbol: str) -> FmpFinancialScores | None:
    """Fetch Piotroski and Altman Z-Score for a symbol.

    Args:
        symbol: Stock ticker symbol.

    Returns:
        Financial scores or ``None`` if unavailable.
    """
    try:
        data = await _fmp_get("financial-scores", {"symbol": symbol})
        if isinstance(data, list) and data:
            result = FmpFinancialScores.model_validate(data[0])
            result.symbol = symbol
            return result
    except Exception as exc:
        logger.debug("Failed to fetch financial scores for %s: %s", symbol, exc)
    return None


async def fetch_analyst_grades(symbol: str, limit: int = 10) -> list[FmpAnalystGrade]:
    """Fetch recent analyst grade actions for a symbol.

    Args:
        symbol: Stock ticker symbol.
        limit: Maximum number of grade actions to return.

    Returns:
        List of analyst grade actions (most recent first).
    """
    try:
        data = await _fmp_get("grades", {"symbol": symbol, "limit": limit})
        if not isinstance(data, list):
            return []
        results: list[FmpAnalystGrade] = []
        for item in data:
            with contextlib.suppress(Exception):
                results.append(FmpAnalystGrade.model_validate(item))
        return results
    except Exception as exc:
        logger.debug("Failed to fetch analyst grades for %s: %s", symbol, exc)
        return []


async def fetch_price_target_consensus(symbol: str) -> FmpPriceTargetConsensus | None:
    """Fetch analyst price target consensus for a symbol.

    Args:
        symbol: Stock ticker symbol.

    Returns:
        Price target consensus or ``None`` if unavailable.
    """
    try:
        data = await _fmp_get("price-target-consensus", {"symbol": symbol})
        if isinstance(data, list) and data:
            result = FmpPriceTargetConsensus.model_validate(data[0])
            result.symbol = symbol
            return result
    except Exception as exc:
        logger.debug("Failed to fetch price target consensus for %s: %s", symbol, exc)
    return None


async def fetch_insider_stats(symbol: str) -> FmpInsiderStats | None:
    """Fetch insider trading statistics for a symbol.

    Args:
        symbol: Stock ticker symbol.

    Returns:
        Insider trading stats or ``None`` if unavailable.
    """
    try:
        data = await _fmp_get("insider-trading/statistics", {"symbol": symbol})
        if isinstance(data, list) and data:
            result = FmpInsiderStats.model_validate(data[0])
            result.symbol = symbol
            return result
        if isinstance(data, dict) and data:
            result = FmpInsiderStats.model_validate(data)
            result.symbol = symbol
            return result
    except Exception as exc:
        logger.debug("Failed to fetch insider stats for %s: %s", symbol, exc)
    return None


async def fetch_share_float(symbol: str) -> FmpShareFloat | None:
    """Fetch share float data for a symbol.

    Args:
        symbol: Stock ticker symbol.

    Returns:
        Share float data or ``None`` if unavailable.
    """
    try:
        data = await _fmp_get("shares-float", {"symbol": symbol})
        if isinstance(data, list) and data:
            result = FmpShareFloat.model_validate(data[0])
            result.symbol = symbol
            return result
    except Exception as exc:
        logger.debug("Failed to fetch share float for %s: %s", symbol, exc)
    return None


async def fetch_market_movers(
    kind: Literal["biggest-gainers", "biggest-losers", "most-actives"] = "biggest-gainers",
) -> list[FmpMarketMover]:
    """Fetch daily market movers (gainers, losers, or most active).

    Args:
        kind: Which movers list to fetch.

    Returns:
        List of market movers for the day.
    """
    try:
        data = await _fmp_get(kind)
        if not isinstance(data, list):
            return []
        results: list[FmpMarketMover] = []
        for item in data:
            with contextlib.suppress(Exception):
                results.append(FmpMarketMover.model_validate(item))
        return results
    except Exception as exc:
        logger.warning("Failed to fetch market movers (%s): %s", kind, exc)
        return []


class FmpQuote(BaseModel):
    """Real-time quote data from FMP ``/stable/quote`` endpoint.

    Used for VIX, individual stock quotes, and any symbol needing
    live intraday price data.
    """

    symbol: str = ""
    price: float | None = None
    changesPercentage: float | None = None
    change: float | None = None
    dayLow: float | None = None
    dayHigh: float | None = None
    previousClose: float | None = None
    volume: int | None = None
    avgVolume: int | None = None
    open: float | None = None


_VIX_LABELS: list[tuple[float, str]] = [
    (15.0, "calm"),
    (20.0, "normal"),
    (30.0, "elevated"),
]


async def fetch_vix_quote() -> tuple[float | None, str]:
    """Fetch the current VIX quote and map to a human-readable label.

    Returns:
        Tuple of (VIX value or None, label string).
        Label is one of ``"calm"``, ``"normal"``, ``"elevated"``, ``"fear"``.
    """
    try:
        data = await _fmp_get("quote", {"symbol": "^VIX"})
        if isinstance(data, list) and data:
            quote = FmpQuote.model_validate(data[0])
            vix = quote.price
            if vix is None:
                return None, "unknown"
            label = "fear"
            for threshold, lbl in _VIX_LABELS:
                if vix < threshold:
                    label = lbl
                    break
            return vix, label
        return None, "unknown"
    except Exception as exc:
        logger.warning("Failed to fetch VIX quote: %s", exc)
        return None, "unknown"


async def fetch_quotes(symbols: list[str]) -> dict[str, FmpQuote]:
    """Fetch real-time quotes for multiple symbols via FMP ``/stable/batch-quote``.

    Automatically converts TradingView-format tickers (``TSX:AGI``) to
    FMP-compatible format (``AGI.TO``) and maps response keys back so
    callers can look up results using the original TradingView keys.

    Args:
        symbols: List of ticker symbols in any format
            (TradingView ``"TSX:AGI"`` or bare ``"AAPL"``).

    Returns:
        Mapping of original symbol → FmpQuote. Missing symbols are omitted.
    """
    if not symbols:
        return {}
    try:
        fmp_to_original: dict[str, str] = {}
        fmp_symbols: list[str] = []
        for sym in symbols:
            fmp_sym = to_fmp_symbol(sym)
            fmp_symbols.append(fmp_sym)
            fmp_to_original[fmp_sym.upper()] = sym

        joined = ",".join(fmp_symbols)
        data = await _fmp_get("batch-quote", {"symbols": joined})
        if not isinstance(data, list):
            return {}
        result: dict[str, FmpQuote] = {}
        for item in data:
            try:
                quote = FmpQuote.model_validate(item)
                if quote.symbol:
                    original_key = fmp_to_original.get(quote.symbol.upper(), quote.symbol)
                    result[original_key] = quote
            except Exception:
                logger.debug("Skipping unparseable quote item: %s", item)
        logger.info("Fetched live quotes for %d/%d symbols", len(result), len(symbols))
        return result
    except Exception as exc:
        logger.warning("Failed to fetch live quotes: %s", exc)
        return {}


async def fetch_technical_indicator(
    symbol: str,
    timeframe: str = "daily",
    indicator_type: str = "rsi",
    period: int = 14,
) -> float | None:
    """Fetch a single technical indicator value for a symbol.

    Uses the FMP ``/api/v3/technical_indicator/{timeframe}/{symbol}`` endpoint.

    Args:
        symbol: Stock ticker symbol (e.g. ``"AAPL"``).
        timeframe: Chart timeframe (``"daily"``, ``"1hour"``, ``"4hour"``).
        indicator_type: Indicator type (``"rsi"``, ``"sma"``, ``"ema"``).
        period: Lookback period for the indicator.

    Returns:
        Most recent indicator value, or ``None`` if unavailable.
    """
    api_key = _get_api_key()
    fmp_sym = to_fmp_symbol(symbol)
    url = f"https://financialmodelingprep.com/api/v3/technical_indicator/{timeframe}/{fmp_sym}"
    params = {"type": indicator_type, "period": period, "apikey": api_key}
    try:
        async with _semaphore, httpx.AsyncClient(timeout=FMP_TIMEOUT) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        if isinstance(data, list) and data:
            return data[0].get(indicator_type)
    except Exception as exc:
        logger.debug("Failed to fetch %s for %s: %s", indicator_type, symbol, exc)
    return None


async def filter_by_rsi(
    stocks: list[FmpEnrichedStock],
    strategy_type: str,
    max_check: int = 20,
) -> list[FmpEnrichedStock]:
    """Filter stocks by RSI to reject technically invalid candidates.

    For momentum strategies: rejects overbought (RSI > 75).
    For mean-reversion strategies: rejects oversold (RSI < 30).

    Args:
        stocks: Pre-scored list of enriched stocks (top N).
        strategy_type: Strategy type string (e.g. ``"momentum"``, ``"mean_reversion"``).
        max_check: Maximum number of candidates to RSI-check.

    Returns:
        Filtered list with technically invalid candidates removed.
    """
    candidates = stocks[:max_check]
    if not candidates:
        return stocks

    rsi_tasks = [fetch_technical_indicator(s.symbol) for s in candidates]
    rsi_values = await asyncio.gather(*rsi_tasks)

    passed: list[FmpEnrichedStock] = []
    for stock, rsi in zip(candidates, rsi_values, strict=False):
        if rsi is None:
            passed.append(stock)
            continue
        if strategy_type == "momentum" and rsi > 75:
            logger.info(
                "RSI filter: rejecting %s (RSI=%.1f, overbought for momentum)", stock.symbol, rsi
            )
            continue
        if strategy_type == "mean_reversion" and rsi < 30:
            logger.info(
                "RSI filter: rejecting %s (RSI=%.1f, oversold for mean-reversion)",
                stock.symbol,
                rsi,
            )
            continue
        passed.append(stock)

    remaining = stocks[max_check:]
    logger.info("RSI pre-filter: %d → %d candidates", len(candidates), len(passed))
    return passed + remaining


async def fetch_sector_performance() -> list[FmpSectorPerformance]:
    """Fetch current sector performance snapshot.

    Returns:
        List of sector performance entries with change percentages.
    """
    from datetime import UTC, datetime

    try:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        data = await _fmp_get("sector-performance-snapshot", {"date": today})
        if not isinstance(data, list):
            return []
        results: list[FmpSectorPerformance] = []
        for item in data:
            with contextlib.suppress(Exception):
                results.append(FmpSectorPerformance.model_validate(item))
        return results
    except Exception as exc:
        logger.warning("Failed to fetch sector performance: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Economic calendar
# ---------------------------------------------------------------------------


async def fetch_economic_calendar(days_ahead: int = 7) -> list[dict]:
    """Fetch upcoming economic events from FMP.

    Args:
        days_ahead: Number of days to look ahead.

    Returns:
        List of event dicts with ``date``, ``event``, ``country``, ``impact``,
        sorted by date ascending. Empty list on failure.
    """
    from datetime import UTC, datetime, timedelta

    try:
        today = datetime.now(UTC).date()
        end = today + timedelta(days=days_ahead)
        data = await _fmp_get(
            "economic-calendar",
            {"from": today.isoformat(), "to": end.isoformat()},
        )
        if not isinstance(data, list):
            return []
        events: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            events.append(
                {
                    "date": item.get("date", ""),
                    "event": item.get("event", ""),
                    "country": item.get("country", ""),
                    "impact": item.get("impact", ""),
                    "estimate": item.get("estimate"),
                    "actual": item.get("actual"),
                    "previous": item.get("previous"),
                }
            )
        events.sort(key=lambda e: e.get("date", ""))
        return events
    except Exception as exc:
        logger.warning("Failed to fetch economic calendar: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Bulk endpoint wrappers (Premium tier — single call for all symbols)
# ---------------------------------------------------------------------------


async def fetch_bulk_ratios_ttm() -> dict[str, FmpRatiosTTM]:
    """Fetch TTM ratios for all companies in a single bulk call.

    Returns:
        Dict mapping symbol to ratios. Empty dict on failure.
    """
    try:
        data = await _fmp_get("ratios-ttm-bulk")
        if not isinstance(data, list):
            return {}
        result: dict[str, FmpRatiosTTM] = {}
        for item in data:
            with contextlib.suppress(Exception):
                sym = item.get("symbol", "")
                if sym:
                    r = FmpRatiosTTM.model_validate(item)
                    r.symbol = sym
                    result[sym] = r
        logger.info("Bulk ratios-ttm loaded %d symbols", len(result))
        return result
    except Exception as exc:
        logger.warning("Bulk ratios-ttm failed, will fall back to per-ticker: %s", exc)
        return {}


async def fetch_bulk_key_metrics_ttm() -> dict[str, FmpKeyMetrics]:
    """Fetch TTM key metrics for all companies in a single bulk call.

    Returns:
        Dict mapping symbol to key metrics. Empty dict on failure.
    """
    try:
        data = await _fmp_get("key-metrics-ttm-bulk")
        if not isinstance(data, list):
            return {}
        result: dict[str, FmpKeyMetrics] = {}
        for item in data:
            with contextlib.suppress(Exception):
                sym = item.get("symbol", "")
                if sym:
                    m = FmpKeyMetrics.model_validate(item)
                    m.symbol = sym
                    result[sym] = m
        logger.info("Bulk key-metrics-ttm loaded %d symbols", len(result))
        return result
    except Exception as exc:
        logger.warning("Bulk key-metrics-ttm failed, will fall back to per-ticker: %s", exc)
        return {}


async def fetch_bulk_scores() -> dict[str, FmpFinancialScores]:
    """Fetch Piotroski/Altman scores for all companies in a single bulk call.

    Returns:
        Dict mapping symbol to financial scores.
    """
    try:
        data = await _fmp_get("scores-bulk")
        if not isinstance(data, list):
            return {}
        result: dict[str, FmpFinancialScores] = {}
        for item in data:
            with contextlib.suppress(Exception):
                sym = item.get("symbol", "")
                if sym:
                    s = FmpFinancialScores.model_validate(item)
                    s.symbol = sym
                    result[sym] = s
        logger.info("Bulk scores loaded %d symbols", len(result))
        return result
    except Exception as exc:
        logger.warning("Bulk scores failed: %s", exc)
        return {}


async def fetch_bulk_grades_consensus() -> dict[str, FmpGradesConsensus]:
    """Fetch analyst grades consensus for all companies in a single bulk call.

    Returns:
        Dict mapping symbol to grades consensus.
    """
    try:
        data = await _fmp_get("upgrades-downgrades-consensus-bulk")
        if not isinstance(data, list):
            return {}
        result: dict[str, FmpGradesConsensus] = {}
        for item in data:
            with contextlib.suppress(Exception):
                sym = item.get("symbol", "")
                if sym:
                    g = FmpGradesConsensus.model_validate(item)
                    g.symbol = sym
                    result[sym] = g
        logger.info("Bulk grades consensus loaded %d symbols", len(result))
        return result
    except Exception as exc:
        logger.warning("Bulk grades consensus failed: %s", exc)
        return {}


async def fetch_bulk_price_targets() -> dict[str, FmpPriceTargetConsensus]:
    """Fetch price target consensus for all companies in a single bulk call.

    Returns:
        Dict mapping symbol to price target consensus.
    """
    try:
        data = await _fmp_get("price-target-summary-bulk")
        if not isinstance(data, list):
            return {}
        result: dict[str, FmpPriceTargetConsensus] = {}
        for item in data:
            with contextlib.suppress(Exception):
                sym = item.get("symbol", "")
                if sym:
                    pt = FmpPriceTargetConsensus.model_validate(item)
                    pt.symbol = sym
                    result[sym] = pt
        logger.info("Bulk price targets loaded %d symbols", len(result))
        return result
    except Exception as exc:
        logger.warning("Bulk price targets failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# High-level orchestration
# ---------------------------------------------------------------------------


def _apply_post_filters(
    stock: FmpEnrichedStock,
    config: FmpScreenerConfig,
) -> bool:
    """Check whether a stock passes all post-filters (ratios + signals).

    Applies all configured threshold checks. A filter is only enforced
    when both the config threshold and the stock's data are non-None,
    so missing data never causes a rejection.

    Args:
        stock: Enriched stock with ratio and signal data.
        config: Screener config containing filter thresholds.

    Returns:
        True if the stock passes all applicable filters.
    """
    checks: list[bool] = [
        not (
            config.pe_max is not None
            and stock.pe_ratio is not None
            and stock.pe_ratio > config.pe_max
        ),
        not (
            config.pe_min is not None
            and stock.pe_ratio is not None
            and stock.pe_ratio < config.pe_min
        ),
        not (config.roe_min is not None and stock.roe is not None and stock.roe < config.roe_min),
        not (
            config.debt_equity_max is not None
            and stock.debt_equity is not None
            and stock.debt_equity > config.debt_equity_max
        ),
        not (
            config.pb_max is not None
            and stock.pb_ratio is not None
            and stock.pb_ratio > config.pb_max
        ),
        not (
            config.pb_min is not None
            and stock.pb_ratio is not None
            and stock.pb_ratio < config.pb_min
        ),
        not (
            config.ps_max is not None
            and stock.ps_ratio is not None
            and stock.ps_ratio > config.ps_max
        ),
        not (
            config.ps_min is not None
            and stock.ps_ratio is not None
            and stock.ps_ratio < config.ps_min
        ),
        not (
            config.peg_max is not None
            and stock.peg_ratio is not None
            and stock.peg_ratio > config.peg_max
        ),
        not (
            config.net_profit_margin_min is not None
            and stock.net_profit_margin is not None
            and stock.net_profit_margin < config.net_profit_margin_min
        ),
        not (
            config.dividend_yield_min is not None
            and stock.dividend_yield is not None
            and stock.dividend_yield < config.dividend_yield_min
        ),
        not (
            config.piotroski_min is not None
            and stock.piotroski_score is not None
            and stock.piotroski_score < config.piotroski_min
        ),
        not (
            config.altman_z_min is not None
            and stock.altman_z_score is not None
            and stock.altman_z_score < config.altman_z_min
        ),
        not (
            config.price_change_1d_min is not None
            and stock.price_change_1d is not None
            and stock.price_change_1d < config.price_change_1d_min
        ),
        not (
            config.price_change_1m_min is not None
            and stock.price_change_1m is not None
            and stock.price_change_1m < config.price_change_1m_min
        ),
        not (
            config.price_change_1m_max is not None
            and stock.price_change_1m is not None
            and stock.price_change_1m > config.price_change_1m_max
        ),
        not (
            config.price_change_3m_min is not None
            and stock.price_change_3m is not None
            and stock.price_change_3m < config.price_change_3m_min
        ),
        not (
            config.rvol_min is not None
            and stock.relative_volume is not None
            and stock.relative_volume < config.rvol_min
        ),
        not (
            config.require_insider_buying
            and (stock.insider_net_buys is None or stock.insider_net_buys <= 0)
        ),
    ]
    return all(checks)


def _merge_enrichment(
    screener: FmpScreenerResult,
    ratios: FmpRatiosTTM | None,
    metrics: FmpKeyMetrics | None,
) -> FmpEnrichedStock:
    """Combine screener result with ratios and metrics into a single model.

    Args:
        screener: Base screener result.
        ratios: Optional TTM ratios.
        metrics: Optional TTM key metrics.

    Returns:
        Enriched stock combining all data sources.
    """
    stock = FmpEnrichedStock(
        symbol=screener.symbol,
        company_name=screener.companyName,
        sector=screener.sector or "",
        industry=screener.industry or "",
        country=screener.country or "",
        exchange=screener.exchangeShortName or screener.exchange or "",
        market_cap=screener.marketCap,
        price=screener.price,
        volume=screener.volume,
        beta=screener.beta,
        is_actively_trading=screener.isActivelyTrading,
    )

    if ratios:
        stock.pe_ratio = ratios.peRatioTTM
        stock.peg_ratio = ratios.pegRatioTTM
        stock.pb_ratio = ratios.priceToBookRatioTTM
        stock.ps_ratio = ratios.priceToSalesRatioTTM
        stock.roe = ratios.returnOnEquityTTM
        stock.roa = ratios.returnOnAssetsTTM
        stock.debt_equity = ratios.debtEquityRatioTTM
        stock.current_ratio = ratios.currentRatioTTM
        stock.dividend_yield = ratios.dividendYieldTTM
        stock.fcf_per_share = ratios.freeCashFlowPerShareTTM
        stock.net_profit_margin = ratios.netProfitMarginTTM

    if metrics:
        stock.ev_ebitda = metrics.enterpriseValueOverEBITDATTM
        if stock.pe_ratio is None:
            stock.pe_ratio = metrics.peRatioTTM
        if stock.fcf_per_share is None:
            stock.fcf_per_share = metrics.freeCashFlowPerShareTTM

    return stock


async def fetch_crypto_list() -> list[FmpCryptoListItem]:
    """Fetch the full cryptocurrency list from FMP.

    Returns:
        List of all tradable cryptos (~4,500+). No server-side filtering.
    """
    data = await _fmp_get("cryptocurrency-list")
    if not isinstance(data, list):
        logger.warning("FMP crypto list returned non-list response: %s", type(data))
        return []
    results = []
    for item in data:
        with contextlib.suppress(Exception):
            results.append(FmpCryptoListItem.model_validate(item))
    return results


async def fetch_batch_crypto_quotes() -> list[FmpCryptoQuote]:
    """Fetch real-time quotes for all cryptocurrencies in a single call.

    Returns:
        List of crypto quotes with price, volume, market cap.
    """
    data = await _fmp_get("batch-crypto-quotes")
    if not isinstance(data, list):
        logger.warning("FMP batch crypto quotes returned non-list: %s", type(data))
        return []
    results = []
    for item in data:
        with contextlib.suppress(Exception):
            results.append(FmpCryptoQuote.model_validate(item))
    return results


async def screen_crypto(config: FmpScreenerConfig) -> list[FmpEnrichedStock]:
    """Screen cryptocurrencies using batch quotes with client-side filtering.

    Fetches all crypto quotes and filters by market_cap, volume, price.
    Computes relative volume and attaches price change from quote data.

    Args:
        config: Screener configuration with filter thresholds.

    Returns:
        List of enriched stocks representing crypto assets, sorted by composite score.
    """
    quotes = await fetch_batch_crypto_quotes()
    logger.info("FMP batch crypto quotes returned %d results", len(quotes))

    if not quotes:
        return []

    enriched: list[FmpEnrichedStock] = []
    for q in quotes:
        if config.market_cap_min is not None and (
            q.marketCap is None or q.marketCap < config.market_cap_min
        ):
            continue
        if config.market_cap_max is not None and (
            q.marketCap is not None and q.marketCap > config.market_cap_max
        ):
            continue
        if config.volume_min is not None and (q.volume is None or q.volume < config.volume_min):
            continue
        if config.price_min is not None and (q.price is None or q.price < config.price_min):
            continue
        if config.price_max is not None and (q.price is not None and q.price > config.price_max):
            continue

        ticker = q.symbol.removesuffix("USD") if q.symbol.endswith("USD") else q.symbol

        rvol: float | None = None
        if q.volume and q.avgVolume and q.avgVolume > 0:
            rvol = q.volume / q.avgVolume

        enriched.append(
            FmpEnrichedStock(
                symbol=ticker,
                company_name=q.name,
                sector="Crypto",
                exchange="CRYPTO",
                market_cap=q.marketCap,
                price=q.price,
                volume=q.volume,
                avg_volume=q.avgVolume,
                relative_volume=rvol,
                price_change_1d=q.changesPercentage,
            )
        )

    enriched = compute_composite_scores(enriched, config)
    enriched.sort(key=lambda s: s.composite_score or 0, reverse=True)
    limited = enriched[: config.limit]
    logger.info(
        "FMP crypto screening: %d → %d after filters (limit %d)",
        len(quotes),
        len(limited),
        config.limit,
    )
    return limited


# ---------------------------------------------------------------------------
# Multi-factor composite scoring engine
# ---------------------------------------------------------------------------

_DEFAULT_WEIGHTS = {
    "fundamental": 25.0,
    "momentum": 25.0,
    "sentiment": 25.0,
    "quality": 25.0,
}


def _percentile_rank(
    values: list[float | None], value: float | None, invert: bool = False
) -> float:
    """Compute percentile rank (0-100) of *value* within *values*.

    Args:
        values: Population of comparable values (Nones ignored).
        value: The value to rank.
        invert: If ``True``, lower values rank higher (useful for P/E, debt).

    Returns:
        Percentile rank 0-100, or 50.0 if insufficient data.
    """
    if value is None:
        return 50.0
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return 50.0
    rank = sum(1 for v in clean if v <= value) / len(clean) * 100
    return (100 - rank) if invert else rank


def _score_fundamental(stock: FmpEnrichedStock, pool: list[FmpEnrichedStock]) -> float:
    """Score 0-100 on valuation and profitability metrics.

    Lower P/E, lower PEG, higher ROE, higher margins = better.
    """
    pe_vals = [s.pe_ratio for s in pool]
    roe_vals = [s.roe for s in pool]
    margin_vals = [s.net_profit_margin for s in pool]
    peg_vals = [s.peg_ratio for s in pool]
    ev_vals = [s.ev_ebitda for s in pool]

    scores = [
        _percentile_rank(pe_vals, stock.pe_ratio, invert=True),
        _percentile_rank(peg_vals, stock.peg_ratio, invert=True),
        _percentile_rank(roe_vals, stock.roe, invert=False),
        _percentile_rank(margin_vals, stock.net_profit_margin, invert=False),
        _percentile_rank(ev_vals, stock.ev_ebitda, invert=True),
    ]
    return sum(scores) / len(scores)


def _score_momentum(stock: FmpEnrichedStock, pool: list[FmpEnrichedStock]) -> float:
    """Score 0-100 on price momentum and volume signals.

    Higher price changes and relative volume = better (for momentum strategies).
    Mean reversion strategies invert this in the composite weights.
    """
    pc1d = [s.price_change_1d for s in pool]
    pc1m = [s.price_change_1m for s in pool]
    pc3m = [s.price_change_3m for s in pool]
    rvol = [s.relative_volume for s in pool]

    scores = [
        _percentile_rank(pc1d, stock.price_change_1d),
        _percentile_rank(pc1m, stock.price_change_1m),
        _percentile_rank(pc3m, stock.price_change_3m),
        _percentile_rank(rvol, stock.relative_volume),
    ]
    return sum(scores) / len(scores)


def _score_sentiment(stock: FmpEnrichedStock, pool: list[FmpEnrichedStock]) -> float:
    """Score 0-100 on insider activity and analyst consensus.

    More insider buying, more analyst buy ratings, higher target upside = better.
    """
    insider_vals = [s.insider_buy_ratio for s in pool]
    buy_count_vals = [float(s.analyst_buy_count) if s.analyst_buy_count else None for s in pool]
    upside_vals = [s.analyst_target_upside for s in pool]

    scores = [
        _percentile_rank(insider_vals, stock.insider_buy_ratio),
        _percentile_rank(
            buy_count_vals, float(stock.analyst_buy_count) if stock.analyst_buy_count else None
        ),
        _percentile_rank(upside_vals, stock.analyst_target_upside),
    ]
    return sum(scores) / len(scores)


def _score_quality(stock: FmpEnrichedStock, pool: list[FmpEnrichedStock]) -> float:
    """Score 0-100 on financial health and quality metrics.

    Higher Piotroski, higher Altman Z, lower debt, higher current ratio = better.
    """
    pio_vals = [float(s.piotroski_score) if s.piotroski_score is not None else None for s in pool]
    alt_vals = [s.altman_z_score for s in pool]
    de_vals = [s.debt_equity for s in pool]
    cr_vals = [s.current_ratio for s in pool]

    scores = [
        _percentile_rank(
            pio_vals, float(stock.piotroski_score) if stock.piotroski_score is not None else None
        ),
        _percentile_rank(alt_vals, stock.altman_z_score),
        _percentile_rank(de_vals, stock.debt_equity, invert=True),
        _percentile_rank(cr_vals, stock.current_ratio),
    ]
    return sum(scores) / len(scores)


def compute_composite_scores(
    stocks: list[FmpEnrichedStock],
    config: FmpScreenerConfig,
) -> list[FmpEnrichedStock]:
    """Compute multi-factor composite scores for a pool of stocks.

    Scores each stock 0-100 across four dimensions (fundamental,
    momentum, sentiment, quality) using percentile ranking within the
    pool. The composite is a weighted average using strategy-specific
    weights from the config, with missing dimensions redistributed.

    Args:
        stocks: Pool of enriched stocks to score.
        config: Screener config with optional weight overrides.

    Returns:
        Same list with ``composite_score`` and dimension scores populated.
    """
    if not stocks:
        return stocks

    weights = {
        "fundamental": config.weight_fundamental or _DEFAULT_WEIGHTS["fundamental"],
        "momentum": config.weight_momentum or _DEFAULT_WEIGHTS["momentum"],
        "sentiment": config.weight_sentiment or _DEFAULT_WEIGHTS["sentiment"],
        "quality": config.weight_quality or _DEFAULT_WEIGHTS["quality"],
    }
    total_weight = sum(weights.values())
    if total_weight == 0:
        total_weight = 100.0

    for stock in stocks:
        sf = _score_fundamental(stock, stocks)
        sm = _score_momentum(stock, stocks)
        ss = _score_sentiment(stock, stocks)
        sq = _score_quality(stock, stocks)

        stock.score_fundamental = round(sf, 1)
        stock.score_momentum = round(sm, 1)
        stock.score_sentiment = round(ss, 1)
        stock.score_quality = round(sq, 1)

        composite = (
            sf * weights["fundamental"]
            + sm * weights["momentum"]
            + ss * weights["sentiment"]
            + sq * weights["quality"]
        ) / total_weight
        stock.composite_score = round(composite, 1)

    return stocks


REGIME_WEIGHT_DELTAS: dict[str, dict[str, float]] = {
    "trending_bull": {"momentum": 15.0, "sentiment": 5.0, "fundamental": -10.0, "quality": -10.0},
    "trending_bear": {"quality": 15.0, "fundamental": 10.0, "momentum": -15.0, "sentiment": -10.0},
    "range_bound": {"fundamental": 10.0, "quality": 5.0, "momentum": -10.0, "sentiment": -5.0},
    "high_volatility": {"quality": 20.0, "fundamental": 5.0, "momentum": -15.0, "sentiment": -10.0},
    "risk_off": {"quality": 20.0, "fundamental": 10.0, "momentum": -20.0, "sentiment": -10.0},
    "sector_rotation": {
        "momentum": 10.0,
        "sentiment": 10.0,
        "fundamental": -10.0,
        "quality": -10.0,
    },
}


def apply_regime_weight_adjustments(
    config: FmpScreenerConfig,
    regime_type: str,
) -> FmpScreenerConfig:
    """Apply regime-based weight adjustments to an FMP screener config.

    Adjusts the strategy's scoring weights based on the current market regime.
    For example, in a ``risk_off`` regime, quality weight increases while
    momentum weight decreases.

    Args:
        config: Original FMP screener config (not mutated).
        regime_type: Regime classification string from the regime classifier.

    Returns:
        New FmpScreenerConfig with adjusted weights.
    """
    deltas = REGIME_WEIGHT_DELTAS.get(regime_type)
    if not deltas:
        return config

    data = config.model_dump()
    base_fundamental = data.get("weight_fundamental") or 25.0
    base_momentum = data.get("weight_momentum") or 25.0
    base_sentiment = data.get("weight_sentiment") or 25.0
    base_quality = data.get("weight_quality") or 25.0

    data["weight_fundamental"] = max(5.0, base_fundamental + deltas.get("fundamental", 0))
    data["weight_momentum"] = max(5.0, base_momentum + deltas.get("momentum", 0))
    data["weight_sentiment"] = max(5.0, base_sentiment + deltas.get("sentiment", 0))
    data["weight_quality"] = max(5.0, base_quality + deltas.get("quality", 0))

    return FmpScreenerConfig.model_validate(data)


def _apply_sector_cap(
    stocks: list[FmpEnrichedStock],
    max_per_sector: int,
) -> list[FmpEnrichedStock]:
    """Limit the number of stocks from any single sector.

    Assumes the input list is already sorted by composite score
    (descending). Preserves ranking order.

    Args:
        stocks: Score-sorted enriched stocks.
        max_per_sector: Maximum picks allowed per sector.

    Returns:
        Filtered list respecting sector concentration limits.
    """
    sector_counts: dict[str, int] = {}
    result: list[FmpEnrichedStock] = []
    for s in stocks:
        sector = s.sector or "Unknown"
        count = sector_counts.get(sector, 0)
        if count < max_per_sector:
            result.append(s)
            sector_counts[sector] = count + 1
    return result


# ---------------------------------------------------------------------------
# Extended enrichment helpers
# ---------------------------------------------------------------------------


async def _enrich_extended(
    stock: FmpEnrichedStock,
    config: FmpScreenerConfig,
    bulk_scores: dict[str, FmpFinancialScores] | None = None,
    bulk_grades: dict[str, FmpGradesConsensus] | None = None,
    bulk_targets: dict[str, FmpPriceTargetConsensus] | None = None,
) -> FmpEnrichedStock:
    """Attach insider stats, price changes, scores, analyst data, and float.

    Uses bulk data when available, falls back to per-ticker calls.

    Args:
        stock: Base enriched stock (already has ratios/metrics).
        config: Screener config (determines which enrichments to fetch).
        bulk_scores: Pre-fetched bulk financial scores (if available).
        bulk_grades: Pre-fetched bulk grades consensus (if available).
        bulk_targets: Pre-fetched bulk price targets (if available).

    Returns:
        The same stock object with additional fields populated.
    """
    sym = stock.symbol
    tasks: dict[str, Any] = {}

    tasks["insider"] = fetch_insider_stats(sym)
    tasks["price_change"] = fetch_price_change(sym)

    if bulk_scores and sym in bulk_scores:
        scores_data = bulk_scores[sym]
    else:
        tasks["scores"] = fetch_financial_scores(sym)
        scores_data = None

    if bulk_targets and sym in bulk_targets:
        target_data = bulk_targets[sym]
    else:
        tasks["targets"] = fetch_price_target_consensus(sym)
        target_data = None

    grades_data = bulk_grades[sym] if bulk_grades and sym in bulk_grades else None

    need_float = config.rvol_min is not None or config.weight_momentum is not None
    if need_float:
        tasks["share_float"] = fetch_share_float(sym)

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    result_map = dict(zip(tasks.keys(), results, strict=False))

    insider: FmpInsiderStats | None = result_map.get("insider")
    if isinstance(insider, FmpInsiderStats):
        stock.insider_net_buys = insider.totalBought - insider.totalSold
        if insider.totalTransactions > 0:
            stock.insider_buy_ratio = insider.totalBought / insider.totalTransactions

    price_chg: FmpPriceChange | None = result_map.get("price_change")
    if isinstance(price_chg, FmpPriceChange):
        stock.price_change_1d = price_chg.oneDay
        stock.price_change_1m = price_chg.oneMonth
        stock.price_change_3m = price_chg.threeMonth
        stock.price_change_6m = price_chg.sixMonth

    if scores_data is None:
        scores_data = result_map.get("scores")
    if isinstance(scores_data, FmpFinancialScores):
        stock.piotroski_score = scores_data.piotroskiScore
        stock.altman_z_score = scores_data.altmanZScore

    if target_data is None:
        target_data = result_map.get("targets")
    if (
        isinstance(target_data, FmpPriceTargetConsensus)
        and target_data.targetConsensus
        and stock.price
        and stock.price > 0
    ):
        stock.analyst_target_upside = (
            (target_data.targetConsensus - stock.price) / stock.price * 100
        )

    if isinstance(grades_data, FmpGradesConsensus):
        stock.analyst_consensus = grades_data.consensus
        stock.analyst_buy_count = grades_data.strongBuy + grades_data.buy

    sfloat: FmpShareFloat | None = result_map.get("share_float")
    if isinstance(sfloat, FmpShareFloat):
        stock.free_float_pct = sfloat.freeFloat
        stock.float_shares = int(sfloat.floatShares) if sfloat.floatShares else None

    return stock


async def _attach_earnings_data(
    stocks: list[FmpEnrichedStock],
    within_days: int,
    min_beat_pct: float | None,
) -> list[FmpEnrichedStock]:
    """Attach earnings dates and beat rates, filter by upcoming earnings.

    Args:
        stocks: Enriched stocks to augment.
        within_days: Only keep stocks reporting within this many days.
        min_beat_pct: Minimum historical beat rate (0-100) to keep.

    Returns:
        Filtered list of stocks with earnings data attached.
    """
    from datetime import date, timedelta

    today = date.today()
    from_date = today.isoformat()
    to_date = (today + timedelta(days=within_days)).isoformat()

    calendar = await fetch_earnings_calendar(from_date, to_date)
    calendar_map: dict[str, str] = {}
    for item in calendar:
        if item.symbol and item.date:
            calendar_map[item.symbol] = item.date

    if not calendar_map:
        logger.info("No earnings found in next %d days", within_days)
        return stocks

    reporting_symbols = set(calendar_map.keys())
    filtered: list[FmpEnrichedStock] = []
    for stock in stocks:
        if stock.symbol not in reporting_symbols:
            continue
        stock.earnings_date = calendar_map[stock.symbol]

        if min_beat_pct is not None:
            surprises = await fetch_earnings_surprises(stock.symbol)
            beat_rate = compute_beat_rate(surprises)
            stock.earnings_beat_rate = beat_rate
            if beat_rate is not None and beat_rate < min_beat_pct:
                continue

        filtered.append(stock)

    logger.info(
        "Earnings filter: %d → %d stocks (reporting in %d days)",
        len(stocks),
        len(filtered),
        within_days,
    )
    return filtered


async def screen_and_enrich(
    config: FmpScreenerConfig,
) -> list[FmpEnrichedStock]:
    """Screen stocks or crypto via FMP, enrich with multi-source data, and score.

    For stocks (``is_crypto=False``):
      1. Call ``/stable/company-screener`` with the config's filters.
      2. Bulk-fetch ratios, metrics, scores, grades, and price targets.
      3. Per-ticker: fetch insider stats, price changes, share float.
      4. Apply ratio and signal post-filters.
      5. Compute multi-factor composite scores.
      6. Sort by composite score descending.
      7. Apply sector concentration guard.
      8. If ``earnings_within_days`` is set, filter to upcoming earners.

    For crypto (``is_crypto=True``):
      Fetch all crypto quotes and filter client-side by market cap,
      volume, and price. Compute RVOL and composite scores.

    Args:
        config: FMP screener configuration from the strategy.

    Returns:
        List of enriched, scored stocks/crypto sorted by composite score.
    """
    if config.is_crypto:
        return await screen_crypto(config)

    screener_results = await screen_stocks(config)
    logger.info("FMP screener returned %d raw results", len(screener_results))

    if not screener_results:
        return []

    # Step 2: bulk fetch (3 calls instead of 6N)
    bulk_ratios: dict[str, FmpRatiosTTM] = {}
    bulk_metrics: dict[str, FmpKeyMetrics] = {}
    bulk_scores: dict[str, FmpFinancialScores] = {}
    bulk_grades: dict[str, FmpGradesConsensus] = {}
    bulk_targets: dict[str, FmpPriceTargetConsensus] = {}

    if config.enrich_with_ratios:
        (
            bulk_ratios,
            bulk_metrics,
            bulk_scores,
            bulk_grades,
            bulk_targets,
        ) = await asyncio.gather(
            fetch_bulk_ratios_ttm(),
            fetch_bulk_key_metrics_ttm(),
            fetch_bulk_scores(),
            fetch_bulk_grades_consensus(),
            fetch_bulk_price_targets(),
        )

    # Step 3: merge base enrichment using bulk data
    enriched: list[FmpEnrichedStock] = []
    for sr in screener_results:
        ratios = bulk_ratios.get(sr.symbol) if bulk_ratios else None
        metrics = bulk_metrics.get(sr.symbol) if bulk_metrics else None
        # Fall back to per-ticker if bulk missed this symbol
        if config.enrich_with_ratios and ratios is None:
            ratios = await fetch_ratios_ttm(sr.symbol)
        if config.enrich_with_ratios and metrics is None:
            metrics = await fetch_key_metrics_ttm(sr.symbol)
        enriched.append(_merge_enrichment(sr, ratios, metrics))

    # Step 4: extended enrichment (insider, price change, scores, analyst, float)
    if config.enrich_with_ratios:
        enriched = list(
            await asyncio.gather(
                *[
                    _enrich_extended(s, config, bulk_scores, bulk_grades, bulk_targets)
                    for s in enriched
                ]
            )
        )

    # Step 5: apply hard post-filters
    before_filter = len(enriched)
    enriched = [s for s in enriched if _apply_post_filters(s, config)]
    if len(enriched) < before_filter:
        logger.info(
            "Post-filters: %d → %d stocks after filtering",
            before_filter,
            len(enriched),
        )

    # Step 6: earnings calendar pre-fetch and filter
    if config.earnings_within_days is not None and enriched:
        enriched = await _attach_earnings_data(
            enriched, config.earnings_within_days, config.min_earnings_beat_pct
        )

    # Step 7: composite scoring
    enriched = compute_composite_scores(enriched, config)

    # Step 8: sort by composite score
    enriched.sort(key=lambda s: s.composite_score or 0, reverse=True)

    # Step 9: sector concentration guard
    if config.max_sector_concentration is not None:
        enriched = _apply_sector_cap(enriched, config.max_sector_concentration)

    final = enriched[: config.limit]
    logger.info(
        "FMP screen_and_enrich complete: %d final candidates (top score: %.1f)",
        len(final),
        final[0].composite_score if final and final[0].composite_score else 0,
    )
    return final


async def screen_stocks_from_params(
    *,
    is_crypto: bool = False,
    country: str | None = None,
    exchange: str | None = None,
    sector: str | None = None,
    industry: str | None = None,
    market_cap_min: int | None = None,
    market_cap_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    volume_min: int | None = None,
    beta_min: float | None = None,
    beta_max: float | None = None,
    limit: int = 50,
    pe_max: float | None = None,
    roe_min: float | None = None,
    debt_equity_max: float | None = None,
    piotroski_min: int | None = None,
    require_insider_buying: bool = False,
    rvol_min: float | None = None,
    earnings_within_days: int | None = None,
    altman_z_min: float | None = None,
    is_etf: bool | None = None,
    enrich_with_ratios: bool = False,
) -> list[dict[str, Any]]:
    """Screen stocks or crypto from raw parameters (used by Perplexity tool calls).

    This function accepts individual keyword arguments instead of a config
    object, making it suitable for dynamic tool-call execution where
    Perplexity constructs the parameters at runtime.

    Args:
        is_crypto: If ``True``, screen crypto via batch quotes instead
            of the stock-only company-screener endpoint.
        country: Country code filter (e.g. ``"CA"``, ``"US"``). Stocks only.
        exchange: Exchange filter (e.g. ``"TSX"``, ``"NASDAQ"``). Stocks only.
        sector: Sector filter (e.g. ``"Technology"``). Stocks only.
        industry: Industry filter. Stocks only.
        market_cap_min: Minimum market cap.
        market_cap_max: Maximum market cap.
        price_min: Minimum price.
        price_max: Maximum price.
        volume_min: Minimum daily volume.
        beta_min: Minimum beta. Stocks only.
        beta_max: Maximum beta. Stocks only.
        limit: Maximum results to return.
        pe_max: Maximum P/E ratio filter.
        roe_min: Minimum ROE filter.
        debt_equity_max: Maximum debt/equity ratio filter.
        piotroski_min: Minimum Piotroski F-Score filter.
        require_insider_buying: If ``True``, only stocks with net insider buys.
        rvol_min: Minimum relative volume filter.
        earnings_within_days: Only stocks with earnings within N days.
        enrich_with_ratios: If ``True``, run full signal enrichment pipeline.

    Returns:
        List of dicts with asset data (serialisable for tool-call output).
    """
    config = FmpScreenerConfig(
        enabled=True,
        is_crypto=is_crypto,
        is_etf=is_etf if is_etf is not None else False,
        country=country,
        exchange=exchange,
        sector=sector,
        industry=industry,
        market_cap_min=market_cap_min,
        market_cap_max=market_cap_max,
        price_min=price_min,
        price_max=price_max,
        volume_min=volume_min,
        beta_min=beta_min,
        beta_max=beta_max,
        limit=limit,
        pe_max=pe_max,
        roe_min=roe_min,
        debt_equity_max=debt_equity_max,
        piotroski_min=piotroski_min,
        altman_z_min=altman_z_min,
        require_insider_buying=require_insider_buying,
        rvol_min=rvol_min,
        earnings_within_days=earnings_within_days,
        enrich_with_ratios=enrich_with_ratios,
    )
    if is_crypto:
        results = await screen_crypto(config)
        return [r.model_dump() for r in results]
    if enrich_with_ratios:
        results = await screen_and_enrich(config)
        return [r.model_dump() for r in results]
    stock_results = await screen_stocks(config)
    return [r.model_dump() for r in stock_results]
