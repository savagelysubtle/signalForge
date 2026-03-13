"""Prompt version hashing utilities."""

from __future__ import annotations

import hashlib


def prompt_hash(text: str) -> str:
    """Return an 8-character SHA-256 hex digest of the given prompt text.

    Args:
        text: The prompt string to hash.

    Returns:
        First 8 hex characters of the SHA-256 digest.
    """
    return hashlib.sha256(text.encode()).hexdigest()[:8]
