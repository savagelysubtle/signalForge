"""Supabase async client management for database operations.

Replaces the previous asyncpg connection pool with the Supabase Python
client, which connects via PostgREST (HTTPS) instead of the PostgreSQL
wire protocol. This eliminates all IPv6/pooler/DNS connectivity issues
when deploying to Railway.
"""

from __future__ import annotations

import logging

from supabase import AsyncClient, create_async_client

from config import settings

logger = logging.getLogger(__name__)

_client: AsyncClient | None = None


async def get_db() -> AsyncClient:
    """Get the Supabase async client singleton.

    Returns:
        The initialized Supabase AsyncClient.

    Raises:
        RuntimeError: If database not initialized.
    """
    if _client is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _client


async def init_db() -> None:
    """Initialize the Supabase async client.

    Uses SUPABASE_URL and SUPABASE_SERVICE_KEY from settings. The service
    key bypasses Row Level Security, which is appropriate for the backend.
    """
    global _client
    logger.info("Initializing Supabase client for %s", settings.supabase_url)
    _client = await create_async_client(
        settings.supabase_url,
        settings.supabase_service_key,
    )
    logger.info("Supabase client initialized successfully.")


async def close_db() -> None:
    """Release the Supabase client reference."""
    global _client
    if _client is not None:
        _client = None
        logger.info("Supabase client released.")
