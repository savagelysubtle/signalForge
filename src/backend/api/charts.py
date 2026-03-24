"""Chart image API endpoints.

Provides on-demand chart image fetching for the frontend, allowing users
to view charts at any supported timeframe without re-running the pipeline.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from middleware.auth import CurrentUser
from services.chart_image import TIMEFRAME_MAP, fetch_chart_image

router = APIRouter(prefix="/charts", tags=["charts"])


class ChartRequest(BaseModel):
    """Request body for on-demand chart fetch."""

    ticker: str
    timeframe: str
    indicators: list[str] = []


class ChartResponse(BaseModel):
    """Response with the chart image URL."""

    ticker: str
    timeframe: str
    image_url: str


@router.post("/fetch", response_model=ChartResponse)
async def fetch_chart(body: ChartRequest, user_id: CurrentUser) -> ChartResponse:
    """Fetch a chart image for a given ticker and timeframe.

    Args:
        body: Chart request with ticker, timeframe, and optional indicators.
        user_id: Authenticated user ID from JWT.

    Returns:
        ChartResponse with the public image URL.
    """
    if body.timeframe not in TIMEFRAME_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported timeframe '{body.timeframe}'. "
            f"Supported: {', '.join(sorted(TIMEFRAME_MAP.keys()))}",
        )

    run_id = f"adhoc-{uuid.uuid4().hex[:12]}"

    try:
        _image_bytes, image_url = await fetch_chart_image(
            ticker=body.ticker,
            timeframe=body.timeframe,
            indicators=body.indicators,
            run_id=run_id,
            user_id=user_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Chart-Img API error: {exc}") from exc

    return ChartResponse(
        ticker=body.ticker,
        timeframe=body.timeframe,
        image_url=image_url,
    )
