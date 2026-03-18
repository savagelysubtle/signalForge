"""Reflection context loader for the self-learning loop.

Loads the latest injection prompt from the reflections table to provide
historical performance context to the GPT judge. The full reflection
*generation* engine is a future feature — this module only reads
previously generated reflections.
"""

from __future__ import annotations

import logging

from database.connection import get_db

logger = logging.getLogger(__name__)


async def load_reflection_context() -> str:
    """Load the most recent reflection injection prompt from the database.

    Queries the ``reflections`` table for the latest ``injection_prompt``,
    which contains concrete performance stats (win rates, confidence
    calibration, sector performance) that GPT uses to self-correct.

    Returns:
        The injection prompt text, or empty string if no reflections exist.
    """
    try:
        pool = await get_db()
        row = await pool.fetchrow(
            "SELECT injection_prompt FROM reflections ORDER BY generated_at DESC LIMIT 1"
        )
        if row and row["injection_prompt"]:
            logger.info("Loaded reflection context (%d chars)", len(row["injection_prompt"]))
            return row["injection_prompt"]
    except Exception:
        logger.exception("Failed to load reflection context")

    return ""
