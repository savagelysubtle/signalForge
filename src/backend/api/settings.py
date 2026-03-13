"""Settings API endpoints for API key management and app configuration."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.keyring_service import (
    PROVIDERS,
    delete_api_key,
    get_key_status,
    store_api_key,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class ApiKeyRequest(BaseModel):
    """Request body for storing an API key."""

    provider: str
    key: str


class ApiKeyStatusResponse(BaseModel):
    """Response showing which API keys are configured."""

    keys: dict[str, bool]


@router.post("/api-keys")
async def set_api_key(request: ApiKeyRequest) -> dict[str, str]:
    """Store an API key in the OS credential manager.

    The key value is never logged or stored in SQLite.
    """
    try:
        store_api_key(request.provider, request.key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "provider": request.provider}


@router.delete("/api-keys/{provider}")
async def remove_api_key(provider: str) -> dict[str, str]:
    """Remove an API key from the OS credential manager."""
    if provider not in PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{provider}'. Must be one of {PROVIDERS}",
        )
    delete_api_key(provider)
    return {"status": "ok", "provider": provider}


@router.get("/api-keys/status", response_model=ApiKeyStatusResponse)
async def check_api_key_status() -> ApiKeyStatusResponse:
    """Check which API keys are configured (values are never returned)."""
    return ApiKeyStatusResponse(keys=get_key_status())
