"""Process-wide shared ``httpx.AsyncClient`` for outbound HTTP.

Avoids per-request TCP/TLS handshakes to FMP, Chart-Img, and similar APIs.
Initialized from app lifespan; lazily created if used outside FastAPI.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_lock = asyncio.Lock()

DEFAULT_TIMEOUT_S = 30.0
DEFAULT_LIMITS = httpx.Limits(max_connections=32, max_keepalive_connections=16)


async def init_http_clients() -> None:
    """Create the shared client (FastAPI lifespan startup)."""
    global _client
    async with _lock:
        if _client is not None and not _client.is_closed:
            return
        if _client is not None:
            await _client.aclose()
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(DEFAULT_TIMEOUT_S),
            limits=DEFAULT_LIMITS,
        )
        logger.info("Shared httpx AsyncClient initialized")


async def close_http_clients() -> None:
    """Close the shared client (FastAPI lifespan shutdown)."""
    global _client
    async with _lock:
        if _client is not None:
            await _client.aclose()
            _client = None
        logger.info("Shared httpx AsyncClient closed")


async def get_http_client() -> httpx.AsyncClient:
    """Return the shared client, creating it lazily if needed."""
    global _client
    async with _lock:
        if _client is None or _client.is_closed:
            _client = httpx.AsyncClient(
                timeout=httpx.Timeout(DEFAULT_TIMEOUT_S),
                limits=DEFAULT_LIMITS,
            )
            logger.debug("Lazy-initialized shared httpx AsyncClient")
        return _client
