"""Authentication middleware package.

Exports:
    CurrentUser: Type alias for authenticated user ID dependency.
    get_current_user: FastAPI dependency function for JWT validation.
"""

from __future__ import annotations

from middleware.auth import CurrentUser, get_current_user

__all__ = ["CurrentUser", "get_current_user"]
