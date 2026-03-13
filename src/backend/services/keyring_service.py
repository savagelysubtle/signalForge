"""API key management via the OS keyring (Windows Credential Manager).

Keys are never stored in SQLite, config files, or logs.
"""

from __future__ import annotations

import logging

import keyring

logger = logging.getLogger(__name__)

SERVICE_NAME = "signalforge"

PROVIDERS = ("perplexity", "anthropic", "google", "openai", "chartimg")


def store_api_key(provider: str, key: str) -> None:
    """Store an API key in the OS credential manager.

    Args:
        provider: One of the recognized provider names (e.g. "perplexity").
        key: The API key value.

    Raises:
        ValueError: If the provider name is not recognized.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider '{provider}'. Must be one of {PROVIDERS}")
    keyring.set_password(SERVICE_NAME, provider, key)
    logger.info("Stored API key for provider '%s'", provider)


def get_api_key(provider: str) -> str | None:
    """Retrieve an API key from the OS credential manager.

    Args:
        provider: The provider name.

    Returns:
        The API key string, or ``None`` if not configured.
    """
    return keyring.get_password(SERVICE_NAME, provider)


def delete_api_key(provider: str) -> None:
    """Remove an API key from the OS credential manager.

    Args:
        provider: The provider name.
    """
    try:
        keyring.delete_password(SERVICE_NAME, provider)
        logger.info("Deleted API key for provider '%s'", provider)
    except keyring.errors.PasswordDeleteError:
        logger.warning("No API key found for provider '%s' to delete", provider)


def get_key_status() -> dict[str, bool]:
    """Check which API keys are configured (no values returned).

    Returns:
        Dict mapping provider name to ``True`` if a key exists.
    """
    return {provider: get_api_key(provider) is not None for provider in PROVIDERS}
