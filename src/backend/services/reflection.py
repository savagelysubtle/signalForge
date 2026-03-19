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
        client = await get_db()
        response = await (
            client.table("reflections")
            .select("injection_prompt")
            .order("generated_at", desc=True)
            .limit(1)
            .maybe_single()
            .execute()
        )
        if response.data and response.data.get("injection_prompt"):
            prompt = response.data["injection_prompt"]
            logger.info("Loaded reflection context (%d chars)", len(prompt))
            return prompt
    except Exception:
        logger.exception("Failed to load reflection context")

    return ""
