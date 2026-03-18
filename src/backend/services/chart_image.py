"""Chart-Img API client for TradingView chart screenshots.

Fetches chart images via the Chart-Img Advanced Chart API for Claude
Vision to analyze. Images are saved to the OS AppData charts directory.

API Reference: https://doc.chart-img.com/
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from config import paths
from services.keyring_service import get_api_key

logger = logging.getLogger(__name__)

CHART_IMG_BASE = "https://api.chart-img.com/v1/tradingview/advanced-chart"

INDICATOR_MAP: dict[str, str] = {
    "RSI": "RSI",
    "MACD": "MACD",
    "Bollinger Bands": "BB",
    "Stochastic": "Stoch",
    "ATR": "ATR",
    "EMA_20": "EMA:20",
    "EMA_50": "EMA:50",
    "SMA_50": "SMA:50",
    "SMA_200": "SMA:200",
    "VWAP": "VWAP",
}

TIMEFRAME_MAP: dict[str, str] = {
    "1H": "1h",
    "4H": "4h",
    "D": "1D",
    "W": "1W",
    "M": "1M",
}


def _map_indicators(config_indicators: list[str]) -> list[str]:
    """Map strategy indicator names to Chart-Img study parameter values.

    Args:
        config_indicators: Indicator names from StrategyConfig.chart_indicators.

    Returns:
        List of Chart-Img compatible study strings. Unknown indicators and
        "Volume" (built-in) are silently skipped.
    """
    studies: list[str] = []
    for ind in config_indicators:
        mapped = INDICATOR_MAP.get(ind)
        if mapped:
            studies.append(mapped)
        elif ind.lower() != "volume":
            logger.warning("Unknown indicator '%s' — skipping in chart request", ind)
    return studies


async def fetch_chart_image(
    ticker: str,
    timeframe: str,
    indicators: list[str],
    run_id: str,
) -> tuple[bytes, Path]:
    """Fetch a TradingView chart screenshot from Chart-Img API.

    Args:
        ticker: Stock/crypto ticker symbol (e.g. "AAPL").
        timeframe: Strategy timeframe code (e.g. "D", "4H", "W").
        indicators: List of indicator names from strategy config.
        run_id: Pipeline run UUID for unique filenames.

    Returns:
        Tuple of (raw PNG bytes, saved file path).

    Raises:
        RuntimeError: If CHARTIMG_API_KEY is not configured.
        httpx.HTTPStatusError: If the API returns a non-2xx response.
    """
    api_key = get_api_key("chartimg")
    if not api_key:
        raise RuntimeError(
            "Chart-Img API key not configured. "
            "Set CHARTIMG_API_KEY in .env (see .env.example)."
        )

    interval = TIMEFRAME_MAP.get(timeframe, "1D")
    studies = _map_indicators(indicators)

    params: dict[str, str | int] = {
        "symbol": ticker,
        "interval": interval,
        "theme": "dark",
        "width": 800,
        "height": 600,
    }
    if studies:
        params["studies"] = ",".join(studies)

    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(CHART_IMG_BASE, params=params, headers=headers)
        response.raise_for_status()

    image_bytes = response.content
    filename = f"{ticker}_{timeframe}_{run_id}.png"
    save_path = paths.charts_dir / filename
    save_path.write_bytes(image_bytes)

    logger.info("Chart image saved: %s (%d bytes)", save_path, len(image_bytes))
    return image_bytes, save_path
