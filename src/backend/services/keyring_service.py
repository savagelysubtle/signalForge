"""API key management via .env file.

Keys are loaded from a ``.env`` file in the project root using
``python-dotenv``. Users copy ``.env.example`` to ``.env`` and fill
in their keys. The ``.env`` file is gitignored.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

PROVIDERS: dict[str, str] = {
    "perplexity": "PERPLEXITY_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "chartimg": "CHARTIMG_API_KEY",
}


def load_env() -> None:
    """Load or reload the .env file into the process environment.

    Called once at startup. Safe to call again to pick up changes.
    """
    if _ENV_FILE.exists():
        load_dotenv(_ENV_FILE, override=True)
        logger.info("Loaded .env from %s", _ENV_FILE)
    else:
        logger.warning("No .env file found at %s", _ENV_FILE)


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
