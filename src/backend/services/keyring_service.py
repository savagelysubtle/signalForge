"""API key management via environment variables.

In production (Railway), API keys are set as environment variables directly.
In development, keys are loaded from a ``.env`` file using ``python-dotenv``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PROVIDERS: dict[str, str] = {
    "perplexity": "PERPLEXITY_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "chartimg": "CHARTIMG_API_KEY",
}


def load_env() -> None:
    """Load the .env file into the process environment if it exists.

    In production, environment variables are pre-set by the hosting platform
    (Railway) and this function is effectively a no-op. In development, it
    loads from the .env file at the project root.

    Called once at startup.
    """
    env_candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[3] / ".env",
    ]
    for env_file in env_candidates:
        if env_file.exists():
            load_dotenv(env_file, override=True)
            logger.info("Loaded .env from %s", env_file)
            return

    logger.info("No .env file found — using existing environment variables")


def get_api_key(provider: str) -> str | None:
    """Retrieve an API key from the environment.

    Args:
        provider: Short provider name (e.g. "perplexity").

    Returns:
        The API key string, or ``None`` if not set.
    """
    env_var = PROVIDERS.get(provider)
    if not env_var:
        return None
    return os.environ.get(env_var) or None


def get_key_status() -> dict[str, bool]:
    """Check which API keys are configured (values are never returned).

    Returns:
        Dict mapping provider name to ``True`` if the key is set.
    """
    return {provider: get_api_key(provider) is not None for provider in PROVIDERS}
