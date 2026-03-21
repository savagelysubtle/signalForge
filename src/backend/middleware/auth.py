"""JWT authentication middleware for FastAPI using Supabase tokens.

Provides a dependency function that extracts and validates JWT tokens from
the Authorization header, returning the authenticated user ID.

Supabase uses ES256 (ECDSA) JWTs. Verification keys are fetched from the
project's JWKS endpoint and cached automatically by PyJWKClient.
"""

from __future__ import annotations

import logging
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException
from jwt import PyJWKClient

from config import settings

logger = logging.getLogger(__name__)

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    """Return a cached PyJWKClient for the Supabase JWKS endpoint."""
    global _jwks_client
    if _jwks_client is None:
        jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)
        logger.info("JWKS client initialized for %s", jwks_url)
    return _jwks_client


async def get_current_user(authorization: Annotated[str | None, Header()] = None) -> str:
    """Extract and validate JWT token from Authorization header.

    Decodes the Bearer token using Supabase's JWKS endpoint (ES256).
    Falls back to a dev user ID when SUPABASE_URL is not configured.

    Args:
        authorization: Authorization header value (injected by FastAPI).

    Returns:
        User ID string extracted from the JWT "sub" claim.

    Raises:
        HTTPException: 401 if token is missing, invalid, or expired.
    """
    if not settings.supabase_url:
        if settings.environment == "production":
            raise RuntimeError(
                "SUPABASE_URL is required in production. Set the SUPABASE_URL environment variable."
            )
        logger.warning(
            "SUPABASE_URL not configured — using dev user ID. "
            "This is only allowed in development mode."
        )
        return "dev-user-local"

    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = parts[1]

    try:
        jwks_client = _get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token: missing sub claim")
        return str(user_id)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None
    except jwt.InvalidTokenError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None
    except Exception:
        logger.exception("Unexpected error during JWT validation")
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


CurrentUser = Annotated[str, Depends(get_current_user)]
