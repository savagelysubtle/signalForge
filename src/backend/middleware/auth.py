"""JWT authentication middleware for FastAPI using Supabase tokens.

Provides a dependency function that extracts and validates JWT tokens from
the Authorization header, returning the authenticated user ID.
"""

from __future__ import annotations

import logging
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException

from config import settings

logger = logging.getLogger(__name__)


async def get_current_user(authorization: Annotated[str | None, Header()] = None) -> str:
    """Extract and validate JWT token from Authorization header.

    This dependency function reads the Bearer token from the Authorization header,
    decodes it using the Supabase JWT secret, and returns the user ID (sub claim).

    In development mode (when SUPABASE_JWT_SECRET is empty), returns a hardcoded
    dev user ID and logs a warning.

    Args:
        authorization: Authorization header value (injected by FastAPI).

    Returns:
        User ID string extracted from the JWT "sub" claim.

    Raises:
        HTTPException: 401 if token is missing, invalid, or expired.

    Example:
        ```python
        @app.get("/protected")
        async def protected_route(user_id: CurrentUser):
            return {"user_id": user_id}
        ```
    """
    # Development mode fallback
    if not settings.supabase_jwt_secret:
        logger.warning(
            "SUPABASE_JWT_SECRET not configured — using dev user ID. "
            "This should NEVER happen in production!"
        )
        return "dev-user-local"

    # Check for Authorization header
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Extract Bearer token
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = parts[1]

    # Decode and validate JWT
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token: missing sub claim")
        return str(user_id)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None
    except Exception:
        logger.exception("Unexpected error during JWT validation")
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


# Type alias for easy use in route handlers
CurrentUser = Annotated[str, Depends(get_current_user)]
