"""Shared transient HTTP error retry decorator for LLM API calls.

Extracted from Gemini's retry pattern. Wraps async functions to retry
on transient HTTP errors (429 rate limit, 5xx server errors) with
exponential backoff. Works alongside ``with_validation_retry`` which
handles JSON/schema validation retries at a higher level.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

TRANSIENT_CODES: frozenset[int] = frozenset({429, 500, 502, 503})


def _extract_status_code(exc: Exception) -> int | None:
    """Extract HTTP status code from an exception.

    Checks structured attributes first (``code``, ``status_code``,
    ``status``), then falls back to substring matching in the
    exception message.
    """
    for attr in ("code", "status_code", "status"):
        code = getattr(exc, attr, None)
        if isinstance(code, int):
            return code

    err_str = str(exc)
    for c in TRANSIENT_CODES:
        if str(c) in err_str:
            return c
    return None


def with_transient_retry(
    max_retries: int = 3,
    base_delay: float = 2.0,
    transient_codes: frozenset[int] = TRANSIENT_CODES,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator that retries async functions on transient HTTP errors.

    On non-transient errors, the exception is raised immediately.
    On transient errors, retries with exponential backoff. After all
    retries are exhausted, the last exception is re-raised.

    Args:
        max_retries: Maximum number of retry attempts.
        base_delay: Base delay in seconds (doubles each retry).
        transient_codes: HTTP status codes considered transient.

    Returns:
        Decorator that adds transient retry logic.
    """

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(fn)
        async def wrapper(*args: object, **kwargs: object) -> T:
            last_exc: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    code = _extract_status_code(exc)
                    if code not in transient_codes:
                        raise
                    wait = base_delay * (2**attempt)
                    fn_label = getattr(fn, "__name__", None)
                    if not isinstance(fn_label, str):
                        fn_label = repr(fn)
                    logger.warning(
                        "Transient error in %s (attempt %d/%d, code=%s), retrying in %.0fs: %s",
                        fn_label,
                        attempt + 1,
                        max_retries,
                        code,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)

            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
