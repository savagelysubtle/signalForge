"""Chart image serving endpoint.

Serves chart screenshots saved in AppData/charts/ to the frontend.
Images are stored outside the web root, so this endpoint provides
access to them via HTTP.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from config import paths

router = APIRouter(tags=["charts"])


@router.get("/charts/{filename}")
async def get_chart_image(filename: str) -> FileResponse:
    """Serve a chart image PNG from the AppData charts directory.

    Args:
        filename: The chart image filename (e.g. "AAPL_D_abc123.png").

    Returns:
        The PNG image as a file response.

    Raises:
        HTTPException: 404 if the file does not exist.
    """
    file_path = paths.charts_dir / filename

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Chart image not found")

    return FileResponse(file_path, media_type="image/png")
