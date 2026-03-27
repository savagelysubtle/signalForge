"""FMP screener tool definition for Perplexity Agent API.

Defines the function-calling tool schema that Perplexity uses to
dynamically invoke the FMP screener (stocks or crypto), plus the
execution handler that runs the actual API call and formats the result.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from services.fmp_service import screen_stocks_from_params

logger = logging.getLogger(__name__)

FMP_TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "name": "screen_stocks",
    "description": (
        "Screen stocks or cryptocurrencies using the Financial Modeling Prep "
        "(FMP) API. Returns a list of assets matching the given criteria. "
        "For stocks: filter by country, exchange, sector, market cap, volume, "
        "price range, and beta. For crypto: set is_crypto=true and filter by "
        "market cap, volume, and price range. "
        "Useful when the pre-screened candidates don't match the strategy "
        "requirements well, or when you want to explore a different universe. "
        "Each call counts against the FMP rate limit so use judiciously — "
        "prefer refining parameters over making many calls."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "is_crypto": {
                "type": "boolean",
                "description": (
                    "Set to true to screen cryptocurrencies instead of stocks. "
                    "When true, only market_cap_min/max, volume_min, price_min/max, "
                    "and limit are used — stock-specific filters are ignored."
                ),
            },
            "country": {
                "type": "string",
                "description": "Country code (e.g. 'CA' for Canada, 'US' for USA). Stocks only.",
            },
            "exchange": {
                "type": "string",
                "description": "Exchange name (e.g. 'TSX', 'NASDAQ', 'NYSE'). Stocks only.",
            },
            "sector": {
                "type": "string",
                "description": "Sector name (e.g. 'Technology', 'Energy'). Stocks only.",
            },
            "industry": {
                "type": "string",
                "description": "Industry name (e.g. 'Consumer Electronics'). Stocks only.",
            },
            "market_cap_min": {
                "type": "integer",
                "description": "Minimum market capitalisation in USD (e.g. 500000000 for $500M)",
            },
            "market_cap_max": {
                "type": "integer",
                "description": "Maximum market capitalisation in USD",
            },
            "volume_min": {
                "type": "integer",
                "description": "Minimum average daily trading volume (e.g. 200000)",
            },
            "price_min": {
                "type": "number",
                "description": "Minimum price in USD (e.g. 5.0 to filter penny stocks)",
            },
            "price_max": {
                "type": "number",
                "description": "Maximum price in USD",
            },
            "beta_min": {
                "type": "number",
                "description": "Minimum beta (volatility relative to market). Stocks only.",
            },
            "beta_max": {
                "type": "number",
                "description": "Maximum beta. Stocks only.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return (default 50)",
            },
            "pe_max": {
                "type": "number",
                "description": "Maximum P/E ratio filter. Stocks only.",
            },
            "roe_min": {
                "type": "number",
                "description": "Minimum return on equity (%). Stocks only.",
            },
            "debt_equity_max": {
                "type": "number",
                "description": "Maximum debt-to-equity ratio. Stocks only.",
            },
            "piotroski_min": {
                "type": "integer",
                "description": "Minimum Piotroski financial quality score (0-9). Stocks only.",
            },
            "require_insider_buying": {
                "type": "boolean",
                "description": "Only include stocks with net insider buying activity. Stocks only.",
            },
            "rvol_min": {
                "type": "number",
                "description": "Minimum relative volume (current volume / average volume). Stocks only.",
            },
            "earnings_within_days": {
                "type": "integer",
                "description": "Only include stocks with earnings within this many days. Stocks only.",
            },
        },
    },
}


async def execute_fmp_tool(arguments: dict[str, Any]) -> str:
    """Execute the FMP screen_stocks function call.

    Called when Perplexity's Agent API returns a ``function_call``
    output item for the ``screen_stocks`` tool. Runs the FMP screener
    with the provided parameters and returns JSON-serialised results.

    Args:
        arguments: Parsed arguments from the function call
            (keys match FMP_TOOL_DEFINITION parameters).

    Returns:
        JSON string of screener results for inclusion in the
        ``function_call_output`` sent back to Perplexity.
    """
    try:
        is_crypto = arguments.get("is_crypto", False)
        needs_enrichment = any(
            arguments.get(k) is not None
            for k in (
                "pe_max",
                "roe_min",
                "debt_equity_max",
                "piotroski_min",
                "require_insider_buying",
                "rvol_min",
                "earnings_within_days",
            )
        )
        results = await screen_stocks_from_params(
            is_crypto=is_crypto,
            country=arguments.get("country"),
            exchange=arguments.get("exchange"),
            sector=arguments.get("sector"),
            industry=arguments.get("industry"),
            market_cap_min=arguments.get("market_cap_min"),
            market_cap_max=arguments.get("market_cap_max"),
            price_min=arguments.get("price_min"),
            price_max=arguments.get("price_max"),
            volume_min=arguments.get("volume_min"),
            beta_min=arguments.get("beta_min"),
            beta_max=arguments.get("beta_max"),
            limit=arguments.get("limit", 50),
            pe_max=arguments.get("pe_max"),
            roe_min=arguments.get("roe_min"),
            debt_equity_max=arguments.get("debt_equity_max"),
            piotroski_min=arguments.get("piotroski_min"),
            require_insider_buying=arguments.get("require_insider_buying", False),
            rvol_min=arguments.get("rvol_min"),
            earnings_within_days=arguments.get("earnings_within_days"),
            enrich_with_ratios=needs_enrichment,
        )
        asset_type = "crypto" if is_crypto else "stocks"
        logger.info("FMP tool call returned %d %s", len(results), asset_type)
        return json.dumps(results[:30], default=str)
    except Exception as exc:
        logger.warning("FMP tool call failed: %s", exc)
        return json.dumps({"error": str(exc)})
