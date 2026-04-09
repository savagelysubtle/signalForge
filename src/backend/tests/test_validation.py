"""Tests for pipeline/validation.py — JSON extraction, schema validation, and retry logic."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from pydantic import BaseModel, ValidationError

from pipeline.validation import (
    _strip_control_chars,
    extract_json,
    validate_llm_json,
    with_validation_retry,
)


class _TestModel(BaseModel):
    ticker: str
    score: int


# ---------------------------------------------------------------------------
# extract_json
# ---------------------------------------------------------------------------


class TestExtractJson:
    def test_plain_json_object(self):
        raw = '{"ticker": "AAPL", "score": 85}'
        assert json.loads(extract_json(raw)) == {"ticker": "AAPL", "score": 85}

    def test_json_in_markdown_fence(self):
        raw = '```json\n{"ticker": "MSFT", "score": 90}\n```'
        result = json.loads(extract_json(raw))
        assert result == {"ticker": "MSFT", "score": 90}

    def test_strips_think_tokens(self):
        raw = '<think>I need to analyze AAPL...</think>{"ticker": "AAPL", "score": 77}'
        result = json.loads(extract_json(raw))
        assert result["ticker"] == "AAPL"

    def test_json_buried_in_prose(self):
        raw = 'Here is my analysis:\n\n{"ticker": "GOOG", "score": 60}\n\nHope that helps!'
        result = json.loads(extract_json(raw))
        assert result == {"ticker": "GOOG", "score": 60}

    def test_json_array(self):
        raw = "Results: [1, 2, 3]"
        result = json.loads(extract_json(raw))
        assert isinstance(result, list)
        assert result == [1, 2, 3]

    def test_raises_on_no_json(self):
        with pytest.raises(ValueError, match="No JSON"):
            extract_json("no json here at all")

    def test_handles_control_characters(self):
        text = "hello\x00world\x07test"
        cleaned = _strip_control_chars(text)
        assert "\x00" not in cleaned
        assert "\x07" not in cleaned
        assert "helloworld" in cleaned

    def test_preserves_valid_whitespace(self):
        text = "line1\nline2\ttab\rcarriage"
        cleaned = _strip_control_chars(text)
        assert "\n" in cleaned
        assert "\t" in cleaned
        assert "\r" in cleaned


# ---------------------------------------------------------------------------
# validate_llm_json
# ---------------------------------------------------------------------------


class TestValidateLlmJson:
    def test_valid_json_passes(self):
        raw = '{"ticker": "TSLA", "score": 92}'
        result = validate_llm_json(raw, _TestModel)
        assert result.ticker == "TSLA"
        assert result.score == 92

    def test_non_json_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_llm_json("not json at all", _TestModel)

    def test_wrong_schema_raises_validation_error(self):
        raw = '{"wrong_field": "value"}'
        with pytest.raises(ValidationError):
            validate_llm_json(raw, _TestModel)

    def test_extra_fields_are_ignored(self):
        raw = '{"ticker": "NVDA", "score": 80, "extra": true}'
        result = validate_llm_json(raw, _TestModel)
        assert result.ticker == "NVDA"


# ---------------------------------------------------------------------------
# with_validation_retry
# ---------------------------------------------------------------------------


class TestWithValidationRetry:
    @pytest.mark.asyncio
    async def test_succeeds_on_first_try(self):
        @with_validation_retry(schema=_TestModel, provider="test_provider")
        async def llm_call(**kwargs: object) -> str:
            return '{"ticker": "AMD", "score": 70}'

        with (
            patch("pipeline.validation.check_provider"),
            patch("pipeline.validation.record_success"),
        ):
            result = await llm_call()
        assert result is not None
        assert result.ticker == "AMD"
        assert result.__dict__["_retry_count"] == 0

    @pytest.mark.asyncio
    async def test_retries_on_failure_then_succeeds(self):
        call_count = 0

        @with_validation_retry(
            schema=_TestModel, max_retries=2, provider="test_provider", base_delay=0
        )
        async def llm_call(**kwargs: object) -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return "not valid json"
            return '{"ticker": "INTC", "score": 55}'

        with (
            patch("pipeline.validation.check_provider"),
            patch("pipeline.validation.record_success"),
        ):
            result = await llm_call()
        assert result is not None
        assert result.ticker == "INTC"
        assert result.__dict__["_retry_count"] == 1

    @pytest.mark.asyncio
    async def test_returns_none_after_retries_exhausted(self):
        @with_validation_retry(
            schema=_TestModel, max_retries=1, provider="test_provider", base_delay=0
        )
        async def llm_call(**kwargs: object) -> str:
            return "always bad"

        with (
            patch("pipeline.validation.check_provider"),
            patch("pipeline.validation.record_failure"),
        ):
            result = await llm_call()
        assert result is None

    @pytest.mark.asyncio
    async def test_retry_count_attached(self):
        call_count = 0

        @with_validation_retry(
            schema=_TestModel, max_retries=2, provider="test_provider", base_delay=0
        )
        async def llm_call(**kwargs: object) -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return "bad"
            return '{"ticker": "X", "score": 1}'

        with (
            patch("pipeline.validation.check_provider"),
            patch("pipeline.validation.record_success"),
        ):
            result = await llm_call()
        assert result is not None
        assert result.__dict__["_retry_count"] == 2

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        call_count = 0

        @with_validation_retry(
            schema=_TestModel, max_retries=2, provider="test_provider", base_delay=1.0
        )
        async def llm_call(**kwargs: object) -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return "bad"
            return '{"ticker": "Y", "score": 2}'

        sleep_calls: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        with (
            patch("pipeline.validation.check_provider"),
            patch("pipeline.validation.record_success"),
            patch("pipeline.validation.asyncio.sleep", side_effect=fake_sleep),
        ):
            await llm_call()

        assert sleep_calls == [1.0, 2.0]

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_returns_none(self):
        from pipeline.circuit_breaker import CircuitOpenError

        @with_validation_retry(schema=_TestModel, provider="dead_provider")
        async def llm_call(**kwargs: object) -> str:
            return '{"ticker": "Z", "score": 99}'

        with patch(
            "pipeline.validation.check_provider",
            side_effect=CircuitOpenError("circuit open"),
        ):
            result = await llm_call()
        assert result is None
