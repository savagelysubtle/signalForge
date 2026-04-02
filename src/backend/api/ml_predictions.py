"""API endpoints for ML model management and shadow prediction dashboard.

Provides endpoints for checking model status, viewing shadow comparison
stats, and triggering model operations.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from middleware.auth import get_current_user
from ml.inference import get_model_info, ml_model_available, reload_model
from ml.schemas import MLModelInfo, ShadowStats
from ml.shadow_runner import get_shadow_stats

router = APIRouter(prefix="/ml", tags=["ml"])


@router.get("/status")
async def ml_status(user: dict = Depends(get_current_user)) -> MLModelInfo:
    """Get the current ML model status and metadata."""
    info = get_model_info()
    return MLModelInfo(**info)


@router.get("/shadow/stats")
async def shadow_stats(user: dict = Depends(get_current_user)) -> ShadowStats:
    """Get aggregated shadow mode comparison statistics."""
    user_id = user.get("sub", "")
    return await get_shadow_stats(user_id)


@router.post("/reload")
async def reload_ml_model(user: dict = Depends(get_current_user)) -> dict[str, str]:
    """Hot-reload the ML model artifact.

    Use after promoting a new model version to shadow mode.
    """
    success = reload_model()
    if success:
        info = get_model_info()
        return {"status": "reloaded", "model_version": info.get("model_version", "unknown")}
    return {"status": "failed", "model_version": "none"}


@router.get("/available")
async def ml_available(user: dict = Depends(get_current_user)) -> dict[str, bool]:
    """Check if ML model is available for predictions."""
    return {"available": ml_model_available()}
