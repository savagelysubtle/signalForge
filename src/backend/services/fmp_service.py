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
from typing import Any

import httpx
from pydantic import BaseModel, Field

from pipeline.schemas import FmpScreenerConfig, ScoringWeights
from services.keyring_service import get_api_key

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


class FmpPriceChange(BaseModel):
    """Multi-period price change data from /stable/stock-price-change."""

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
    """Piotroski and Altman Z from /stable/financial-scores."""

    symbol: str = ""
    altmanZScore: float | None = None
    piotroskiScore: int | None = None


class FmpInsiderStats(BaseModel):
    """Insider trading statistics from /stable/insider-trading-statistics."""

    symbol: str = ""
    totalBought: int = 0
    totalSold: int = 0
    totalTransactions: int = 0


class FmpEarningsCalendarItem(BaseModel):
    """Single earnings calendar entry from /stable/earning-calendar."""

    symbol: str
    date: str = ""
    eps: float | None = None
    epsEstimated: float | None = None
    revenue: float | None = None
    revenueEstimated: float | None = None


class FmpEarningsSurprise(BaseModel):
    """Earnings surprise data from /stable/earnings-surprises."""

    symbol: str = ""
    date: str = ""
    actualEarningResult: float | None = None
    estimatedEarning: float | None = None


class FmpAnalystRecommendation(BaseModel):
    """Analyst recommendations from /stable/analyst-stock-recommendations."""

    symbol: str = ""
    analystRatingsBuy: int = 0
    analystRatingsHold: int = 0
    analystRatingsSell: int = 0
    analystRatingsStrongBuy: int = 0
    analystRatingsStrongSell: int = 0


class FmpPriceTargetConsensus(BaseModel):
    """Price target consensus from /stable/price-target-consensus."""

    symbol: str = ""
    targetHigh: float | None = None
    targetLow: float | None = None
    targetConsensus: float | None = None
    targetMedian: float | None = None


class FmpEnrichedStock(BaseModel):
    """A screener result enriched with financial ratios, metrics, and signals.

    Combines data from the company-screener, ratios-ttm, key-metrics-ttm,
    and signal endpoints (price changes, financial scores, insider stats,
    analyst recommendations, earnings) into a single model for downstream use.
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
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    ps_ratio: float | None = None
    roe: float | None = None
    roa: float | None = None
    debt_equity: float | None = None
    current_ratio: float | None = None
    dividend_yield: float | None = None
    fcf_per_share: float | None = None
    net_profit_margin: float | None = None
    ev_ebitda: float | None = None
    is_actively_trading: bool = True

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

    # Insider activity (from /stable/insider-trading-statistics)
    insider_net_buys: int | None = None
    insider_buy_ratio: float | None = None

    # Analyst consensus
    analyst_consensus: str | None = None
    analyst_buy_count: int | None = None
    analyst_target_upside: float | None = None

    # Earnings
    earnings_date: str | None = None
    earnings_beat_rate: float | None = None

    # Composite scores (computed by scoring engine)
    score_fundamental: float | None = None
    score_momentum: float | None = None
    score_sentiment: float | None = None
    score_quality: float | None = None
    composite_score: float | None = None


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


async def fetch_price_changes(symbol: str) -> FmpPriceChange | None:
    """Fetch multi-period price changes for a symbol."""
    try:
        data = await _fmp_get("stock-price-change", {"symbol": symbol})
        if isinstance(data, list) and data:
            return FmpPriceChange.model_validate(data[0])
    except Exception as exc:
        logger.debug("Failed to fetch price-change for %s: %s", symbol, exc)
    return None


async def fetch_financial_scores(symbol: str) -> FmpFinancialScores | None:
    """Fetch Piotroski and Altman Z-Score for a symbol."""
    try:
        data = await _fmp_get("financial-scores", {"symbol": symbol})
        if isinstance(data, list) and data:
            return FmpFinancialScores.model_validate(data[0])
    except Exception as exc:
        logger.debug("Failed to fetch financial-scores for %s: %s", symbol, exc)
    return None


async def fetch_insider_stats(symbol: str) -> FmpInsiderStats | None:
    """Fetch insider trading statistics for a symbol."""
    try:
        data = await _fmp_get("insider-trading-statistics", {"symbol": symbol})
        if isinstance(data, list) and data:
            return FmpInsiderStats.model_validate(data[0])
    except Exception as exc:
        logger.debug("Failed to fetch insider stats for %s: %s", symbol, exc)
    return None


async def fetch_earnings_calendar(from_date: str, to_date: str) -> list[FmpEarningsCalendarItem]:
    """Fetch earnings calendar for a date range (bulk, not per-symbol)."""
    try:
        data = await _fmp_get("earning-calendar", {"from": from_date, "to": to_date})
        if isinstance(data, list):
            results: list[FmpEarningsCalendarItem] = []
            for item in data:
                with contextlib.suppress(Exception):
                    results.append(FmpEarningsCalendarItem.model_validate(item))
            return results
    except Exception as exc:
        logger.debug("Failed to fetch earnings calendar: %s", exc)
    return []


async def fetch_earnings_surprises(symbol: str) -> list[FmpEarningsSurprise]:
    """Fetch historical earnings surprises for a symbol."""
    try:
        data = await _fmp_get("earnings-surprises", {"symbol": symbol})
        if isinstance(data, list):
            results: list[FmpEarningsSurprise] = []
            for item in data:
                with contextlib.suppress(Exception):
                    results.append(FmpEarningsSurprise.model_validate(item))
            return results
    except Exception as exc:
        logger.debug("Failed to fetch earnings surprises for %s: %s", symbol, exc)
    return []


async def fetch_analyst_recommendations(symbol: str) -> FmpAnalystRecommendation | None:
    """Fetch analyst buy/hold/sell recommendations for a symbol."""
    try:
        data = await _fmp_get("analyst-stock-recommendations", {"symbol": symbol})
        if isinstance(data, list) and data:
            return FmpAnalystRecommendation.model_validate(data[0])
    except Exception as exc:
        logger.debug("Failed to fetch analyst recommendations for %s: %s", symbol, exc)
    return None


async def fetch_price_target_consensus(symbol: str) -> FmpPriceTargetConsensus | None:
    """Fetch analyst price target consensus for a symbol."""
    try:
        data = await _fmp_get("price-target-consensus", {"symbol": symbol})
        if isinstance(data, list) and data:
            return FmpPriceTargetConsensus.model_validate(data[0])
    except Exception as exc:
        logger.debug("Failed to fetch price target consensus for %s: %s", symbol, exc)
    return None


# ---------------------------------------------------------------------------
# High-level orchestration
# ---------------------------------------------------------------------------


def _apply_post_filters(
    stock: FmpEnrichedStock,
    config: FmpScreenerConfig,
) -> bool:
    """Check whether a stock passes all post-filters (ratios + signals).

    Args:
        stock: Enriched stock with ratio and signal data.
        config: Screener config containing filter thresholds.

    Returns:
        True if the stock passes all applicable filters.
    """
    if config.pe_max is not None and stock.pe_ratio is not None and stock.pe_ratio > config.pe_max:
        return False
    if config.pe_min is not None and stock.pe_ratio is not None and stock.pe_ratio < config.pe_min:
        return False
    if config.roe_min is not None and stock.roe is not None and stock.roe < config.roe_min:
        return False
    if (
        config.debt_equity_max is not None
        and stock.debt_equity is not None
        and stock.debt_equity > config.debt_equity_max
    ):
        return False

    if (
        config.piotroski_min is not None
        and stock.piotroski_score is not None
        and stock.piotroski_score < config.piotroski_min
    ):
        return False
    if config.require_insider_buying and (
        stock.insider_net_buys is None or stock.insider_net_buys <= 0
    ):
        return False
    if (
        config.rvol_min is not None
        and stock.relative_volume is not None
        and stock.relative_volume < config.rvol_min
    ):
        return False
    if config.earnings_within_days is not None:
        if not stock.earnings_date:
            return False
        from datetime import UTC, datetime

        try:
            earn_dt = datetime.strptime(stock.earnings_date, "%Y-%m-%d").replace(tzinfo=UTC)
            now = datetime.now(tz=UTC)
            days_until = (earn_dt - now).days
            if days_until < 0 or days_until > config.earnings_within_days:
                return False
        except ValueError:
            return False

    return True


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
    """Screen cryptocurrencies using FMP list + batch quotes with client-side filtering.

    FMP has no crypto screener endpoint, so this fetches all crypto
    quotes and filters by market_cap_min, volume_min, price_min, etc.

    Args:
        config: Screener configuration with filter thresholds.

    Returns:
        List of enriched stocks representing crypto assets.
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

        # Strip "USD" suffix to get the trading symbol (BTCUSD → BTC)
        ticker = q.symbol.removesuffix("USD") if q.symbol.endswith("USD") else q.symbol

        enriched.append(
            FmpEnrichedStock(
                symbol=ticker,
                company_name=q.name,
                sector="Crypto",
                exchange="CRYPTO",
                market_cap=q.marketCap,
                price=q.price,
                volume=q.volume,
            )
        )

    # Sort by market cap descending, take top N
    enriched.sort(key=lambda s: s.market_cap or 0, reverse=True)
    limited = enriched[: config.limit]
    logger.info(
        "FMP crypto screening: %d → %d after filters (limit %d)",
        len(quotes),
        len(limited),
        config.limit,
    )
    return limited


async def _enrich_batch(
    stocks: list[FmpEnrichedStock],
) -> list[FmpEnrichedStock]:
    """Enrich a batch of stocks with signal data from multiple FMP endpoints.

    Fetches price changes, financial scores, insider stats, analyst
    recommendations, price targets, and earnings surprises for all
    symbols in parallel.

    Args:
        stocks: Stocks already enriched with ratios/metrics.

    Returns:
        Same stocks with signal fields populated.
    """
    if not stocks:
        return stocks

    from datetime import UTC, datetime, timedelta

    today = datetime.now(tz=UTC).date()
    cal_from = today.isoformat()
    cal_to = (today + timedelta(days=30)).isoformat()
    earnings_cal = await fetch_earnings_calendar(cal_from, cal_to)
    earnings_map: dict[str, str] = {}
    for item in earnings_cal:
        if item.symbol not in earnings_map:
            earnings_map[item.symbol] = item.date

    async def _fetch_signals(stock: FmpEnrichedStock) -> None:
        sym = stock.symbol

        price_chg, fin_scores, insider, analyst_rec, price_tgt, surprises = await asyncio.gather(
            fetch_price_changes(sym),
            fetch_financial_scores(sym),
            fetch_insider_stats(sym),
            fetch_analyst_recommendations(sym),
            fetch_price_target_consensus(sym),
            fetch_earnings_surprises(sym),
            return_exceptions=True,
        )

        if isinstance(price_chg, FmpPriceChange):
            stock.price_change_1d = price_chg.oneDay
            stock.price_change_1m = price_chg.oneMonth
            stock.price_change_3m = price_chg.threeMonth
            stock.price_change_6m = price_chg.sixMonth

        if isinstance(fin_scores, FmpFinancialScores):
            stock.piotroski_score = fin_scores.piotroskiScore
            stock.altman_z_score = fin_scores.altmanZScore

        if isinstance(insider, FmpInsiderStats):
            stock.insider_net_buys = insider.totalBought - insider.totalSold
            total = insider.totalTransactions
            stock.insider_buy_ratio = insider.totalBought / total if total > 0 else None

        if isinstance(analyst_rec, FmpAnalystRecommendation):
            buy_total = analyst_rec.analystRatingsBuy + analyst_rec.analystRatingsStrongBuy
            sell_total = analyst_rec.analystRatingsSell + analyst_rec.analystRatingsStrongSell
            hold = analyst_rec.analystRatingsHold
            stock.analyst_buy_count = buy_total
            if buy_total > sell_total:
                stock.analyst_consensus = "Buy"
            elif sell_total > buy_total:
                stock.analyst_consensus = "Sell"
            elif hold >= buy_total:
                stock.analyst_consensus = "Hold"
            else:
                stock.analyst_consensus = "Hold"

        if (
            isinstance(price_tgt, FmpPriceTargetConsensus)
            and price_tgt.targetConsensus is not None
            and stock.price is not None
            and stock.price > 0
        ):
            stock.analyst_target_upside = (
                (price_tgt.targetConsensus - stock.price) / stock.price * 100
            )

        if sym in earnings_map:
            stock.earnings_date = earnings_map[sym]

        if isinstance(surprises, list) and surprises:
            beats = sum(
                1
                for s in surprises
                if s.actualEarningResult is not None
                and s.estimatedEarning is not None
                and s.actualEarningResult > s.estimatedEarning
            )
            stock.earnings_beat_rate = (beats / len(surprises)) * 100 if surprises else None

    await asyncio.gather(*[_fetch_signals(s) for s in stocks], return_exceptions=True)
    return stocks


def _compute_composite_scores(
    stocks: list[FmpEnrichedStock],
    weights: ScoringWeights | None = None,
) -> list[FmpEnrichedStock]:
    """Compute composite scores using percentile ranking across the pool.

    Each of 4 dimensions is scored 0-100 by ranking the stock's raw
    value against all candidates. The composite is a weighted average.

    Args:
        stocks: Enriched stocks with signal data populated.
        weights: Per-strategy scoring weights. Uses equal weights if None.

    Returns:
        Same stocks with score_* and composite_score fields populated.
    """
    if not stocks:
        return stocks

    w = weights or ScoringWeights()
    total_w = w.fundamental + w.momentum + w.sentiment + w.quality
    if total_w == 0:
        total_w = 1.0

    def _percentile_rank(
        values: list[float | None], *, higher_is_better: bool = True
    ) -> list[float]:
        """Rank values as 0-100 percentiles. None values get 50 (neutral)."""
        valid = [(i, v) for i, v in enumerate(values) if v is not None]
        result = [50.0] * len(values)
        if not valid:
            return result
        sorted_vals = sorted(valid, key=lambda x: x[1], reverse=not higher_is_better)
        for rank, (idx, _) in enumerate(sorted_vals):
            if higher_is_better:
                result[idx] = ((len(valid) - 1 - rank) / max(len(valid) - 1, 1)) * 100
            else:
                result[idx] = (rank / max(len(valid) - 1, 1)) * 100
        return result

    # Fundamental: ROE, net_profit_margin, Piotroski
    roe_ranks = _percentile_rank([s.roe for s in stocks])
    margin_ranks = _percentile_rank([s.net_profit_margin for s in stocks])
    piotroski_ranks = _percentile_rank(
        [float(s.piotroski_score) if s.piotroski_score is not None else None for s in stocks]
    )

    # Momentum: price_change_1m, price_change_3m, relative_volume
    mom_1m_ranks = _percentile_rank([s.price_change_1m for s in stocks])
    mom_3m_ranks = _percentile_rank([s.price_change_3m for s in stocks])
    rvol_ranks = _percentile_rank([s.relative_volume for s in stocks])

    # Sentiment: insider_net_buys, analyst_buy_count, analyst_target_upside
    insider_ranks = _percentile_rank(
        [float(s.insider_net_buys) if s.insider_net_buys is not None else None for s in stocks]
    )
    analyst_ranks = _percentile_rank(
        [float(s.analyst_buy_count) if s.analyst_buy_count is not None else None for s in stocks]
    )
    upside_ranks = _percentile_rank([s.analyst_target_upside for s in stocks])

    # Quality: altman_z_score, current_ratio, debt_equity (lower is better)
    altman_ranks = _percentile_rank([s.altman_z_score for s in stocks])
    current_ranks = _percentile_rank([s.current_ratio for s in stocks])
    debt_ranks = _percentile_rank([s.debt_equity for s in stocks], higher_is_better=False)

    for i, stock in enumerate(stocks):
        stock.score_fundamental = (roe_ranks[i] + margin_ranks[i] + piotroski_ranks[i]) / 3
        stock.score_momentum = (mom_1m_ranks[i] + mom_3m_ranks[i] + rvol_ranks[i]) / 3
        stock.score_sentiment = (insider_ranks[i] + analyst_ranks[i] + upside_ranks[i]) / 3
        stock.score_quality = (altman_ranks[i] + current_ranks[i] + debt_ranks[i]) / 3

        stock.composite_score = (
            w.fundamental * stock.score_fundamental
            + w.momentum * stock.score_momentum
            + w.sentiment * stock.score_sentiment
            + w.quality * stock.score_quality
        ) / total_w

    return stocks


async def screen_and_enrich(
    config: FmpScreenerConfig,
) -> list[FmpEnrichedStock]:
    """Screen stocks or crypto via FMP and enrich with full signal data.

    For stocks (is_crypto=False):
      1. Call /stable/company-screener with API-level filters.
      2. Fetch ratios-ttm and key-metrics-ttm per symbol.
      3. If enrich_with_ratios: fetch signal data (price changes, insider,
         Piotroski, analyst, earnings) via _enrich_batch().
      4. Compute composite scores with strategy-specific weights.
      5. Apply all post-filters (ratio + signal).
      6. Sort by composite score descending.
      7. Apply sector concentration guard if configured.

    For crypto (is_crypto=True):
      Fetch crypto quotes and filter client-side. No signal enrichment.

    Args:
        config: FMP screener configuration from the strategy.

    Returns:
        List of enriched stocks that pass all filters, scored and sorted.
    """
    if config.is_crypto:
        return await screen_crypto(config)

    screener_results = await screen_stocks(config)
    logger.info("FMP screener returned %d raw results", len(screener_results))

    if not screener_results:
        return []

    if not config.enrich_with_ratios:
        return [_merge_enrichment(s, None, None) for s in screener_results]

    async def _enrich_one(sr: FmpScreenerResult) -> FmpEnrichedStock:
        ratios, metrics = await asyncio.gather(
            fetch_ratios_ttm(sr.symbol),
            fetch_key_metrics_ttm(sr.symbol),
        )
        return _merge_enrichment(sr, ratios, metrics)

    enriched = list(await asyncio.gather(*[_enrich_one(sr) for sr in screener_results]))

    enriched = await _enrich_batch(enriched)
    logger.info("FMP signal enrichment complete for %d stocks", len(enriched))

    enriched = _compute_composite_scores(enriched, config.scoring_weights)

    has_filters = (
        any(
            getattr(config, f) is not None
            for f in (
                "pe_max",
                "pe_min",
                "roe_min",
                "debt_equity_max",
                "piotroski_min",
                "rvol_min",
                "earnings_within_days",
            )
        )
        or config.require_insider_buying
    )
    if has_filters:
        filtered = [s for s in enriched if _apply_post_filters(s, config)]
        logger.info(
            "FMP post-filters: %d → %d stocks",
            len(enriched),
            len(filtered),
        )
        enriched = filtered

    enriched.sort(key=lambda s: s.composite_score or 0, reverse=True)

    if config.max_per_sector is not None:
        sector_counts: dict[str, int] = {}
        capped: list[FmpEnrichedStock] = []
        for s in enriched:
            sector = s.sector or "Unknown"
            count = sector_counts.get(sector, 0)
            if count < config.max_per_sector:
                capped.append(s)
                sector_counts[sector] = count + 1
        if len(capped) < len(enriched):
            logger.info(
                "Sector cap (%d/sector): %d → %d stocks",
                config.max_per_sector,
                len(enriched),
                len(capped),
            )
            enriched = capped

    return enriched[: config.limit]


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
