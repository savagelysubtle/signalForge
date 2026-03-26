"""Financial Modeling Prep (FMP) stock screener service.

Thin async wrapper around the FMP ``/stable/`` API using ``httpx``.
Provides structured screening, ratio enrichment, and profile lookup
so the pipeline can pre-filter stocks before Perplexity analysis.

The screener itself only supports basic filters (market cap, volume,
sector, country, exchange). Financial-ratio filters (P/E, ROE, etc.)
require a two-step workflow: screen first, then fetch ``ratios-ttm``
per ticker and filter client-side.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from pydantic import BaseModel

from pipeline.schemas import FmpScreenerConfig
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


class FmpEnrichedStock(BaseModel):
    """A screener result enriched with financial ratios and metrics.

    Combines data from the company-screener, ratios-ttm, and
    key-metrics-ttm endpoints into a single model for downstream use.
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


# ---------------------------------------------------------------------------
# High-level orchestration
# ---------------------------------------------------------------------------


def _apply_ratio_filters(
    stock: FmpEnrichedStock,
    config: FmpScreenerConfig,
) -> bool:
    """Check whether a stock passes the ratio-based post-filters.

    Args:
        stock: Enriched stock with ratio data.
        config: Screener config containing ratio filter thresholds.

    Returns:
        ``True`` if the stock passes all applicable filters.
    """
    if config.pe_max is not None and stock.pe_ratio is not None and stock.pe_ratio > config.pe_max:
        return False
    if config.pe_min is not None and stock.pe_ratio is not None and stock.pe_ratio < config.pe_min:
        return False
    if config.roe_min is not None and stock.roe is not None and stock.roe < config.roe_min:
        return False
    return not (
        config.debt_equity_max is not None
        and stock.debt_equity is not None
        and stock.debt_equity > config.debt_equity_max
    )


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


async def screen_and_enrich(
    config: FmpScreenerConfig,
) -> list[FmpEnrichedStock]:
    """Screen stocks via FMP and optionally enrich with financial ratios.

    Two-step workflow:
    1. Call ``/stable/company-screener`` with the config's filters.
    2. For each result, concurrently fetch ``ratios-ttm`` and
       ``key-metrics-ttm`` for enrichment (if ``enrich_with_ratios``).
    3. Apply ratio-based post-filters (P/E range, min ROE, etc.).

    Args:
        config: FMP screener configuration from the strategy.

    Returns:
        List of enriched stocks that pass all filters.
    """
    screener_results = await screen_stocks(config)
    logger.info("FMP screener returned %d raw results", len(screener_results))

    if not screener_results:
        return []

    if not config.enrich_with_ratios:
        return [_merge_enrichment(s, None, None) for s in screener_results]

    async def _enrich_one(
        sr: FmpScreenerResult,
    ) -> FmpEnrichedStock:
        ratios, metrics = await asyncio.gather(
            fetch_ratios_ttm(sr.symbol),
            fetch_key_metrics_ttm(sr.symbol),
        )
        return _merge_enrichment(sr, ratios, metrics)

    enriched = await asyncio.gather(*[_enrich_one(sr) for sr in screener_results])

    has_ratio_filters = any(
        getattr(config, f) is not None for f in ("pe_max", "pe_min", "roe_min", "debt_equity_max")
    )
    if has_ratio_filters:
        filtered = [s for s in enriched if _apply_ratio_filters(s, config)]
        logger.info(
            "FMP ratio filters: %d → %d stocks after filtering",
            len(enriched),
            len(filtered),
        )
        return filtered

    return list(enriched)


async def screen_stocks_from_params(
    *,
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
) -> list[dict[str, Any]]:
    """Screen stocks from raw parameters (used by Perplexity tool calls).

    This function accepts individual keyword arguments instead of a config
    object, making it suitable for dynamic tool-call execution where
    Perplexity constructs the parameters at runtime.

    Args:
        country: Country code filter (e.g. ``"CA"``, ``"US"``).
        exchange: Exchange filter (e.g. ``"TSX"``, ``"NASDAQ"``).
        sector: Sector filter (e.g. ``"Technology"``).
        industry: Industry filter.
        market_cap_min: Minimum market cap.
        market_cap_max: Maximum market cap.
        price_min: Minimum stock price.
        price_max: Maximum stock price.
        volume_min: Minimum daily volume.
        beta_min: Minimum beta.
        beta_max: Maximum beta.
        limit: Maximum results to return.

    Returns:
        List of dicts with stock data (serialisable for tool-call output).
    """
    config = FmpScreenerConfig(
        enabled=True,
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
        enrich_with_ratios=False,
    )
    results = await screen_stocks(config)
    return [r.model_dump() for r in results]
