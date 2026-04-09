"""LLM response validation and retry logic.

Every LLM call is wrapped so that:
1. The raw response is parsed as JSON.
2. The JSON is validated against a Pydantic schema.
3. On validation failure, the call is retried with error context
   appended to the prompt (max 2 retries) and exponential backoff.
4. On final failure, ``None`` is returned and the error is logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from pipeline.circuit_breaker import (
    CircuitOpenError,
    check_provider,
    record_failure,
    record_success,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _strip_control_chars(text: str) -> str:
    """Remove ASCII control characters that LLMs sometimes embed in JSON strings.

    Preserves tab (0x09), newline (0x0a), and carriage return (0x0d) which are
    valid JSON whitespace.
    """
    return _CONTROL_CHAR_RE.sub("", text)


def extract_json(text: str) -> str:
    """Extract a JSON object or array from LLM text.

    Handles markdown fences (````json ...` ```) and ``<think>`` reasoning
    tokens emitted by models like ``sonar-reasoning-pro``.

    Args:
        text: Raw LLM response text.

    Returns:
        The extracted JSON string.

    Raises:
        ValueError: If no JSON object/array can be located in the text.
    """
    stripped = _THINK_RE.sub("", text).strip()
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
    json_str = _strip_control_chars(json_str)
    data = json.loads(json_str)
    return schema.model_validate(data)


def with_validation_retry(  # noqa: UP047
    schema: type[T],
    max_retries: int = 2,
    provider: str = "",
    base_delay: float = 1.0,
) -> Callable[
    [Callable[..., Awaitable[str]]],
    Callable[..., Awaitable[T | None]],
]:
    """Decorator that adds JSON parsing, Pydantic validation, and retry logic.

    The decorated function must be an ``async`` function that returns the raw
    LLM response string. On validation failure, the function is called again
    with an ``error_context`` keyword argument containing the validation error
    details so the LLM can self-correct.

    Retries use exponential backoff: ``base_delay * 2^attempt`` seconds.

    Args:
        schema: Pydantic model class to validate against.
        max_retries: Maximum number of retries on validation failure.
        provider: LLM provider name for circuit breaker tracking
            (e.g. "openai", "anthropic", "google", "perplexity").
        base_delay: Base delay in seconds for exponential backoff between
            retries. First retry waits ``base_delay``, second waits
            ``base_delay * 2``, etc. Set to 0 to disable backoff.

    Returns:
        Decorator that wraps an async LLM call with validation + retry.
    """

    def decorator(
        fn: Callable[..., Awaitable[str]],
    ) -> Callable[..., Awaitable[T | None]]:
        @wraps(fn)
        async def wrapper(*args: object, **kwargs: object) -> T | None:
            breaker_provider = provider or fn.__module__.split(".")[-1]
            try:
                check_provider(breaker_provider)
            except CircuitOpenError as exc:
                logger.warning("Skipping %s: %s", fn.__name__, exc)
                return None

            last_error: str = ""

            for attempt in range(1 + max_retries):
                if attempt > 0:
                    delay = base_delay * (2 ** (attempt - 1))
                    if delay > 0:
                        logger.info(
                            "Backing off %.1fs before retry %d/%d for %s",
                            delay,
                            attempt,
                            max_retries,
                            fn.__name__,
                        )
                        await asyncio.sleep(delay)

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
                    validated = validate_llm_json(raw_text, schema)
                    validated.__dict__["_retry_count"] = attempt
                    record_success(breaker_provider)
                    return validated
                except (ValueError, json.JSONDecodeError) as exc:
                    last_error = f"JSON parse error: {exc}"
                except ValidationError as exc:
                    last_error = f"Schema validation error: {exc}"
                except Exception as exc:
                    last_error = f"Provider error: {exc}"
                    record_failure(breaker_provider)

            logger.error(
                "All %d attempts failed for %s. Last error: %s",
                1 + max_retries,
                fn.__name__,
                last_error,
            )
            record_failure(breaker_provider)
            return None

        return wrapper

    return decorator
