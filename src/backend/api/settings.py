"""Settings API endpoints for API key status and app configuration."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from services.keyring_service import get_key_status, load_env

router = APIRouter(prefix="/settings", tags=["settings"])


class ApiKeyStatusResponse(BaseModel):
    """Response showing which API keys are configured."""

    keys: dict[str, bool]


@router.get("/api-keys/status", response_model=ApiKeyStatusResponse)
async def check_api_key_status() -> ApiKeyStatusResponse:
    """Check which API keys are configured (values are never returned).

    Keys are read from the ``.env`` file in the project root.
    """
    return ApiKeyStatusResponse(keys=get_key_status())


@router.post("/api-keys/reload")
async def reload_api_keys() -> dict[str, str]:
    """Reload API keys from the .env file.

    Call this after editing .env without restarting the server.
    """
    load_env()
    return {"status": "ok"}
