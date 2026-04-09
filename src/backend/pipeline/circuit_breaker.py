"""Simple circuit breaker for LLM provider calls.

Tracks consecutive failures per provider and fast-fails when a provider
is "open" (too many recent failures). Resets automatically after a
cooldown period.

States:
- CLOSED: normal operation, calls go through
- OPEN: provider is failing, calls are rejected immediately
- HALF_OPEN: cooldown expired, one call is allowed to test recovery
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Defaults
_FAILURE_THRESHOLD = 3  # consecutive failures before opening
_COOLDOWN_SECONDS = 120  # seconds before allowing a retry


@dataclass
class _BreakerState:
    """Internal state for a single provider's circuit breaker."""

    consecutive_failures: int = 0
    last_failure_time: float = 0.0
    is_open: bool = False


_breakers: dict[str, _BreakerState] = {}


def _get_state(provider: str) -> _BreakerState:
    if provider not in _breakers:
        _breakers[provider] = _BreakerState()
    return _breakers[provider]


def check_provider(provider: str) -> None:
    """Check if a provider is available. Raises if circuit is open.

    Args:
        provider: Provider name (e.g. "openai", "anthropic", "google", "perplexity").

    Raises:
        CircuitOpenError: If the provider has too many consecutive failures.
    """
    state = _get_state(provider)
    if not state.is_open:
        return

    elapsed = time.monotonic() - state.last_failure_time
    if elapsed >= _COOLDOWN_SECONDS:
        # Half-open: allow one attempt
        logger.info(
            "Circuit breaker half-open for %s (cooldown %ds elapsed), allowing retry",
            provider,
            int(elapsed),
        )
        return

    raise CircuitOpenError(
        f"Circuit breaker OPEN for {provider}: {state.consecutive_failures} "
        f"consecutive failures. Retry in {int(_COOLDOWN_SECONDS - elapsed)}s."
    )


def record_success(provider: str) -> None:
    """Record a successful call — resets the breaker to closed.

    Args:
        provider: Provider name.
    """
    state = _get_state(provider)
    if state.consecutive_failures > 0 or state.is_open:
        logger.info("Circuit breaker closed for %s (recovered)", provider)
    state.consecutive_failures = 0
    state.is_open = False
    state.last_failure_time = 0.0


def record_failure(provider: str) -> None:
    """Record a failed call — may trip the breaker to open.

    Args:
        provider: Provider name.
    """
    state = _get_state(provider)
    state.consecutive_failures += 1
    state.last_failure_time = time.monotonic()

    if state.consecutive_failures >= _FAILURE_THRESHOLD and not state.is_open:
        state.is_open = True
        logger.warning(
            "Circuit breaker OPEN for %s after %d consecutive failures (cooldown %ds)",
            provider,
            state.consecutive_failures,
            _COOLDOWN_SECONDS,
        )


def get_status() -> dict[str, dict[str, object]]:
    """Return current circuit breaker status for all tracked providers.

    Returns:
        Dict mapping provider name to state info.
    """
    return {
        provider: {
            "is_open": state.is_open,
            "consecutive_failures": state.consecutive_failures,
            "seconds_since_last_failure": (
                round(time.monotonic() - state.last_failure_time, 1)
                if state.last_failure_time > 0
                else None
            ),
        }
        for provider, state in _breakers.items()
    }


def reset(provider: str | None = None) -> None:
    """Reset circuit breaker state. Mainly for testing.

    Args:
        provider: Specific provider to reset, or None to reset all.
    """
    if provider:
        _breakers.pop(provider, None)
    else:
        _breakers.clear()


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit breaker is open."""
