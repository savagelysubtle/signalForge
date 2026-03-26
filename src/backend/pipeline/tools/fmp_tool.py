"""FMP stock screener tool definition for Perplexity Agent API.

Defines the function-calling tool schema that Perplexity uses to
dynamically invoke the FMP screener, plus the execution handler
that runs the actual API call and formats the result.
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
        "Screen stocks using the Financial Modeling Prep (FMP) API. "
        "Returns a list of stocks matching the given financial criteria. "
        "Use this to find stocks by country, exchange, sector, market cap, "
        "volume, price range, and beta. "
        "Useful when the pre-screened candidates don't match the strategy "
        "requirements well, or when you want to explore a different universe "
        "of stocks. Each call counts against the FMP rate limit so use "
        "judiciously — prefer refining parameters over making many calls."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "country": {
                "type": "string",
                "description": "Country code (e.g. 'CA' for Canada, 'US' for USA)",
            },
            "exchange": {
                "type": "string",
                "description": "Exchange name (e.g. 'TSX', 'NASDAQ', 'NYSE')",
            },
            "sector": {
                "type": "string",
                "description": "Sector name (e.g. 'Technology', 'Energy', 'Healthcare')",
            },
            "industry": {
                "type": "string",
                "description": "Industry name (e.g. 'Consumer Electronics', 'Oil & Gas')",
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
                "description": "Minimum stock price in USD (e.g. 5.0 to filter penny stocks)",
            },
            "price_max": {
                "type": "number",
                "description": "Maximum stock price in USD",
            },
            "beta_min": {
                "type": "number",
                "description": "Minimum beta (volatility relative to market)",
            },
            "beta_max": {
                "type": "number",
                "description": "Maximum beta",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return (default 50)",
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
        results = await screen_stocks_from_params(
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
        )
        logger.info("FMP tool call returned %d stocks", len(results))
        return json.dumps(results[:30], default=str)
    except Exception as exc:
        logger.warning("FMP tool call failed: %s", exc)
        return json.dumps({"error": str(exc)})
