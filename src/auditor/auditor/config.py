"""Configuration from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ENV_LOADED = False


def _ensure_env() -> None:
    """Load .env from the repo root once."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    repo_root = Path(__file__).resolve().parents[2]
    for candidate in [repo_root / ".env", repo_root.parent / ".env"]:
        if candidate.exists():
            load_dotenv(candidate)
            break
    _ENV_LOADED = True


def supabase_url() -> str:
    """Return SUPABASE_URL from environment."""
    _ensure_env()
    val = os.environ.get("SUPABASE_URL", "")
    if not val:
        raise SystemExit("SUPABASE_URL must be set in .env or environment")
    return val


def supabase_key() -> str:
    """Return SUPABASE_SERVICE_KEY (or SUPABASE_KEY) from environment."""
    _ensure_env()
    val = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY", "")
    if not val:
        raise SystemExit(
            "SUPABASE_SERVICE_KEY (or SUPABASE_KEY) must be set in .env or environment"
        )
    return val


def default_output_dir() -> Path:
    """Default directory for audit output artifacts."""
    return Path(__file__).resolve().parents[1] / "audit_results"
