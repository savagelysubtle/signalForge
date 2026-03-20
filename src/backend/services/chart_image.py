"""Chart-Img v2 API client for TradingView chart screenshots.

Fetches chart images via the Chart-Img v2 Advanced Chart API (POST with
JSON body, real-time US data) for Claude Vision to analyze. Also generates
annotated charts with Horizontal Line drawings for key levels and trade
parameters. In production, images are uploaded to Supabase Storage. In
local development (when SUPABASE_URL is empty), images fall back to local
filesystem.

API Reference: https://doc.chart-img.com/
"""

from __future__ import annotations

import logging

import httpx
from supabase import Client, create_client

from config import paths, settings
from pipeline.schemas import TechnicalLevel
from services.keyring_service import get_api_key

logger = logging.getLogger(__name__)

CHART_IMG_V2_URL = "https://api.chart-img.com/v2/tradingview/advanced-chart"

INDICATOR_MAP: dict[str, str] = {
    "RSI": "Relative Strength Index",
    "MACD": "MACD",
    "Bollinger Bands": "Bollinger Bands",
    "Stochastic": "Stochastic",
    "ATR": "Average True Range",
    "EMA_20": "Exponential Moving Average",
    "EMA_50": "Exponential Moving Average",
    "SMA_50": "Moving Average",
    "SMA_200": "Moving Average",
    "VWAP": "VWAP",
    "Volume": "Volume",
    "OBV": "On Balance Volume",
    "CCI": "Commodity Channel Index",
    "Ichimoku": "Ichimoku Cloud",
    "DMI": "Directional Movement Index",
    "Parabolic SAR": "Parabolic SAR",
}

INDICATOR_INPUTS: dict[str, dict] = {
    "EMA_20": {"length": 20},
    "EMA_50": {"length": 50},
    "SMA_50": {"length": 50},
    "SMA_200": {"length": 200},
}

TIMEFRAME_MAP: dict[str, str] = {
    "1H": "1h",
    "2H": "2h",
    "4H": "4h",
    "D": "1D",
    "W": "1W",
    "M": "1M",
}

EXCHANGE_SUFFIX_MAP: dict[str, str] = {
    ".TO": "TSX",
    ".V": "TSXV",
    ".L": "LSE",
    ".AX": "ASX",
    ".HK": "HKEX",
    ".T": "TSE",
    ".DE": "XETR",
    ".PA": "EURONEXT",
    ".AS": "EURONEXT",
    ".MI": "MIL",
    ".SW": "SIX",
    ".SA": "BMFBOVESPA",
    ".NS": "NSE",
    ".BO": "BSE",
    ".SS": "SSE",
    ".SZ": "SZSE",
    ".KS": "KRX",
}


def _to_tradingview_symbol(ticker: str) -> str:
    """Convert Yahoo Finance ticker format to TradingView format.

    Examples:
        AC.TO  -> TSX:AC
        RY.TO  -> TSX:RY
        SHOP.V -> TSXV:SHOP
        AAPL   -> AAPL  (unchanged)
    """
    for suffix, exchange in EXCHANGE_SUFFIX_MAP.items():
        if ticker.endswith(suffix):
            base = ticker[: -len(suffix)]
            return f"{exchange}:{base}"
    return ticker


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


def _map_indicators(config_indicators: list[str]) -> list[dict]:
    """Map strategy indicator names to Chart-Img v2 study objects.

    Args:
        config_indicators: Indicator names from StrategyConfig.chart_indicators.

    Returns:
        List of Chart-Img v2 study objects (dicts with ``name`` and optional
        ``input``/``forceOverlay``). Unknown indicators are logged and skipped.
    """
    studies: list[dict] = []
    for ind in config_indicators:
        study_name = INDICATOR_MAP.get(ind)
        if not study_name:
            logger.warning("Unknown indicator '%s' — skipping in chart request", ind)
            continue

        study: dict = {"name": study_name}

        custom_inputs = INDICATOR_INPUTS.get(ind)
        if custom_inputs:
            study["input"] = custom_inputs

        if ind == "Volume":
            study["forceOverlay"] = True

        studies.append(study)
    return studies


async def fetch_chart_image(
    ticker: str,
    timeframe: str,
    indicators: list[str],
    run_id: str,
    user_id: str,
) -> tuple[bytes, str]:
    """Fetch a TradingView chart screenshot from Chart-Img v2 API and store it.

    Uses the v2 POST API with JSON body for real-time data and full
    customization. PRO plan supports up to 5 studies at 1920x1080.

    In production mode (SUPABASE_URL configured), uploads to Supabase Storage
    and returns a public URL. In local development mode, falls back to saving
    to local filesystem and returns the local path as a string.

    Args:
        ticker: Stock/crypto ticker symbol (e.g. "AAPL", "TSX:ENB").
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
            "Chart-Img API key not configured. Set CHARTIMG_API_KEY in .env (see .env.example)."
        )

    interval = TIMEFRAME_MAP.get(timeframe, "1D")
    studies = _map_indicators(indicators)
    tv_symbol = _to_tradingview_symbol(ticker)

    body: dict = {
        "symbol": tv_symbol,
        "interval": interval,
        "theme": "dark",
        "width": 1920,
        "height": 1080,
    }
    if studies:
        body["studies"] = studies

    headers = {
        "x-api-key": api_key,
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(CHART_IMG_V2_URL, json=body, headers=headers)
        response.raise_for_status()

    image_bytes = response.content

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

    filename = f"{ticker}_{timeframe}_{run_id}.png"
    save_path = paths.charts_dir / filename
    save_path.write_bytes(image_bytes)
    logger.info("Chart image saved locally: %s (%d bytes)", save_path, len(image_bytes))
    return image_bytes, str(save_path)


STRENGTH_RANK = {"strong": 0, "moderate": 1, "weak": 2}

MAX_DRAWINGS = 5


def _build_drawings(
    key_levels: list[TechnicalLevel],
    entry_price: float | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
) -> list[dict]:
    """Build a prioritised list of Horizontal Line drawing objects.

    Trade parameters (entry, stop, target) take priority, then key levels
    ranked by strength. Total capped at ``MAX_DRAWINGS`` (PRO plan limit).
    """
    drawings: list[dict] = []

    if entry_price is not None:
        drawings.append(
            {
                "name": "Horizontal Line",
                "input": {"price": entry_price},
                "override": {"lineWidth": 2, "lineColor": "rgb(59,130,246)"},
            }
        )

    if stop_loss is not None:
        drawings.append(
            {
                "name": "Horizontal Line",
                "input": {"price": stop_loss},
                "override": {"lineWidth": 2, "lineColor": "rgb(239,68,68)"},
            }
        )

    if take_profit is not None:
        drawings.append(
            {
                "name": "Horizontal Line",
                "input": {"price": take_profit},
                "override": {"lineWidth": 2, "lineColor": "rgb(34,197,94)"},
            }
        )

    remaining = MAX_DRAWINGS - len(drawings)
    if remaining > 0:
        ranked = sorted(key_levels, key=lambda lv: STRENGTH_RANK.get(lv.strength, 9))
        for lv in ranked[:remaining]:
            color = "rgb(34,197,94)" if lv.level_type == "support" else "rgb(239,68,68)"
            drawings.append(
                {
                    "name": "Horizontal Line",
                    "input": {"price": lv.price},
                    "override": {"lineWidth": 1, "lineColor": color},
                }
            )

    return drawings


async def fetch_annotated_chart(
    ticker: str,
    timeframe: str,
    key_levels: list[TechnicalLevel],
    run_id: str,
    user_id: str,
    entry_price: float | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
) -> str:
    """Generate a chart image with key-level and trade-parameter overlays.

    Calls Chart-Img v2 POST with only ``drawings[]`` (no studies) to render
    Horizontal Lines for support/resistance levels and trade parameters
    directly on the TradingView chart. PRO plan allows up to 5 combined
    studies + drawings; we use 0 studies and up to 5 drawings.

    Args:
        ticker: Stock ticker symbol (e.g. "TSX:WCP", "AAPL").
        timeframe: Strategy timeframe code (e.g. "D", "4H").
        key_levels: Support/resistance levels from Claude's analysis.
        run_id: Pipeline run UUID for unique storage path.
        user_id: User UUID for storage path isolation.
        entry_price: GPT-recommended entry price (optional).
        stop_loss: GPT-recommended stop loss (optional).
        take_profit: GPT-recommended take profit (optional).

    Returns:
        Public URL (Supabase) or local file path of the annotated chart PNG.

    Raises:
        RuntimeError: If CHARTIMG_API_KEY is not configured.
        httpx.HTTPStatusError: If the API returns a non-2xx response.
    """
    api_key = get_api_key("chartimg")
    if not api_key:
        raise RuntimeError("Chart-Img API key not configured. Set CHARTIMG_API_KEY in .env.")

    drawings = _build_drawings(key_levels, entry_price, stop_loss, take_profit)
    if not drawings:
        logger.info(
            "No drawings to overlay for %s %s — skipping annotated chart", ticker, timeframe
        )
        return ""

    interval = TIMEFRAME_MAP.get(timeframe, "1D")
    tv_symbol = _to_tradingview_symbol(ticker)

    body: dict = {
        "symbol": tv_symbol,
        "interval": interval,
        "theme": "dark",
        "width": 1920,
        "height": 1080,
        "drawings": drawings,
    }

    headers = {
        "x-api-key": api_key,
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(CHART_IMG_V2_URL, json=body, headers=headers)
        response.raise_for_status()

    image_bytes = response.content

    if settings.supabase_url:
        supabase = _get_supabase()
        upload_path = f"{user_id}/{run_id}/annotated/{ticker}_{timeframe}.png"

        supabase.storage.from_("charts").upload(
            path=upload_path,
            file=image_bytes,
            file_options={"content-type": "image/png"},
        )

        public_url = f"{settings.supabase_url}/storage/v1/object/public/charts/{upload_path}"
        logger.info("Annotated chart uploaded: %s (%d bytes)", public_url, len(image_bytes))
        return public_url

    filename = f"annotated_{ticker}_{timeframe}_{run_id}.png"
    save_path = paths.charts_dir / filename
    save_path.write_bytes(image_bytes)
    logger.info("Annotated chart saved locally: %s (%d bytes)", save_path, len(image_bytes))
    return str(save_path)
