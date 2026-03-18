"""Chart-Img API client for TradingView chart screenshots.

Fetches chart images via the Chart-Img Advanced Chart API for Claude Vision
to analyze. In production, images are uploaded to Supabase Storage. In local
development (when SUPABASE_URL is empty), images fall back to local filesystem.

API Reference: https://doc.chart-img.com/
"""

from __future__ import annotations

import logging

import httpx
from supabase import Client, create_client

from config import paths, settings
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

_supabase_client: Client | None = None


def _get_supabase() -> Client:
    """Get or create a module-level Supabase client (lazy singleton).

    Returns:
        Initialized Supabase client using service role key.

    Raises:
        RuntimeError: If Supabase credentials are not configured.
    """
    global _supabase_client
    if _supabase_client is None:
        if not settings.supabase_url or not settings.supabase_service_key:
            raise RuntimeError(
                "Supabase credentials not configured. "
                "Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env (see .env.example)."
            )
        _supabase_client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _supabase_client


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
    user_id: str,
) -> tuple[bytes, str]:
    """Fetch a TradingView chart screenshot from Chart-Img API and store it.

    In production mode (SUPABASE_URL configured), uploads to Supabase Storage
    and returns a public URL. In local development mode, falls back to saving
    to local filesystem and returns the local path as a string.

    Args:
        ticker: Stock/crypto ticker symbol (e.g. "AAPL").
        timeframe: Strategy timeframe code (e.g. "D", "4H", "W").
        indicators: List of indicator names from strategy config.
        run_id: Pipeline run UUID for unique filenames.
        user_id: User UUID for storage path isolation.

    Returns:
        Tuple of (raw PNG bytes, public URL or local path string).

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

    # Production: Upload to Supabase Storage
    if settings.supabase_url:
        supabase = _get_supabase()
        upload_path = f"{user_id}/{run_id}/{ticker}_{timeframe}.png"

        supabase.storage.from_("charts").upload(
            path=upload_path,
            file=image_bytes,
            file_options={"content-type": "image/png"},
        )

        public_url = f"{settings.supabase_url}/storage/v1/object/public/charts/{upload_path}"
        logger.info("Chart image uploaded to Supabase: %s (%d bytes)", public_url, len(image_bytes))
        return image_bytes, public_url

    # Local development: Save to filesystem
    filename = f"{ticker}_{timeframe}_{run_id}.png"
    save_path = paths.charts_dir / filename
    save_path.write_bytes(image_bytes)
    logger.info("Chart image saved locally: %s (%d bytes)", save_path, len(image_bytes))
    return image_bytes, str(save_path)
