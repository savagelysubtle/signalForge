"""LLM response validation and retry logic.

Every LLM call is wrapped so that:
1. The raw response is parsed as JSON.
2. The JSON is validated against a Pydantic schema.
3. On validation failure, the call is retried with error context
   appended to the prompt (max 2 retries).
4. On final failure, ``None`` is returned and the error is logged.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def extract_json(text: str) -> str:
    """Extract a JSON object or array from LLM text that may include markdown fences.

    Args:
        text: Raw LLM response text, possibly wrapped in ```json ... ```.

    Returns:
        The extracted JSON string.

    Raises:
        ValueError: If no JSON object/array can be located in the text.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n", 1)
        body = lines[1] if len(lines) > 1 else ""
        if body.endswith("```"):
            body = body[: -len("```")]
        return body.strip()

    for start_char, end_char in (("{", "}"), ("[", "]")):
        start = stripped.find(start_char)
        end = stripped.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            return stripped[start : end + 1]

    raise ValueError("No JSON object or array found in LLM response")


def validate_llm_json(raw_text: str, schema: type[T]) -> T:  # noqa: UP047
    """Parse raw LLM text as JSON and validate against a Pydantic model.

    Args:
        raw_text: The raw string response from the LLM.
        schema: The Pydantic model class to validate against.

    Returns:
        A validated instance of the schema.

    Raises:
        ValueError: If JSON extraction fails.
        json.JSONDecodeError: If the extracted text is not valid JSON.
        ValidationError: If the JSON does not match the schema.
    """
    json_str = extract_json(raw_text)
    data = json.loads(json_str)
    return schema.model_validate(data)


def with_validation_retry(  # noqa: UP047
    schema: type[T],
    max_retries: int = 2,
) -> Callable[
    [Callable[..., Awaitable[str]]],
    Callable[..., Awaitable[T | None]],
]:
    """Decorator that adds JSON parsing, Pydantic validation, and retry logic.

    The decorated function must be an ``async`` function that returns the raw
    LLM response string. On validation failure, the function is called again
    with an ``error_context`` keyword argument containing the validation error
    details so the LLM can self-correct.

    Args:
        schema: Pydantic model class to validate against.
        max_retries: Maximum number of retries on validation failure.

    Returns:
        Decorator that wraps an async LLM call with validation + retry.
    """

    def decorator(
        fn: Callable[..., Awaitable[str]],
    ) -> Callable[..., Awaitable[T | None]]:
        @wraps(fn)
        async def wrapper(*args: object, **kwargs: object) -> T | None:
            last_error: str = ""

            for attempt in range(1 + max_retries):
                if attempt > 0:
                    kwargs["error_context"] = (
                        f"Your previous response failed validation: {last_error}. "
                        f"Please respond with valid JSON matching this schema: "
                        f"{schema.model_json_schema()}"
                    )
                    logger.warning(
                        "Retry %d/%d for %s: %s",
                        attempt,
                        max_retries,
                        fn.__name__,
                        last_error,
                    )

                try:
                    raw_text = await fn(*args, **kwargs)
                    return validate_llm_json(raw_text, schema)
                except (ValueError, json.JSONDecodeError) as exc:
                    last_error = f"JSON parse error: {exc}"
                except ValidationError as exc:
                    last_error = f"Schema validation error: {exc}"

            logger.error(
                "All %d attempts failed for %s. Last error: %s",
                1 + max_retries,
                fn.__name__,
                last_error,
            )
            return None

        return wrapper

    return decorator
