"""Tests for pipeline/http_retry.py — transient HTTP error retry logic."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pipeline.http_retry import _extract_status_code, with_transient_retry


class _FakeExcWithCode(Exception):
    def __init__(self, code: int):
        super().__init__(f"Error {code}")
        self.code = code


class _FakeExcWithStatusCode(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"Error {status_code}")
        self.status_code = status_code


# ---------------------------------------------------------------------------
# _extract_status_code
# ---------------------------------------------------------------------------


class TestExtractStatusCode:
    def test_from_code_attr(self):
        exc = _FakeExcWithCode(429)
        assert _extract_status_code(exc) == 429

    def test_from_status_code_attr(self):
        exc = _FakeExcWithStatusCode(503)
        assert _extract_status_code(exc) == 503

    def test_from_string_fallback(self):
        exc = Exception("Rate limit hit, HTTP 429 returned")
        assert _extract_status_code(exc) == 429

    def test_returns_none_when_no_code(self):
        exc = Exception("Something went wrong")
        assert _extract_status_code(exc) is None


# ---------------------------------------------------------------------------
# with_transient_retry
# ---------------------------------------------------------------------------


class TestWithTransientRetry:
    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        @with_transient_retry(max_retries=3, base_delay=0)
        async def good_call() -> str:
            return "ok"

        result = await good_call()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_retries_on_429_then_succeeds(self):
        call_count = 0

        @with_transient_retry(max_retries=3, base_delay=0)
        async def flaky_call() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise _FakeExcWithCode(429)
            return "recovered"

        with patch("pipeline.http_retry.asyncio.sleep", return_value=None):
            result = await flaky_call()
        assert result == "recovered"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_non_transient_error_raises_immediately(self):
        @with_transient_retry(max_retries=3, base_delay=0)
        async def bad_call() -> str:
            raise _FakeExcWithCode(401)

        with pytest.raises(_FakeExcWithCode):
            await bad_call()

    @pytest.mark.asyncio
    async def test_raises_last_exception_after_all_retries(self):
        @with_transient_retry(max_retries=2, base_delay=0)
        async def always_fails() -> str:
            raise _FakeExcWithCode(500)

        with (
            patch("pipeline.http_retry.asyncio.sleep", return_value=None),
            pytest.raises(_FakeExcWithCode),
        ):
            await always_fails()

    @pytest.mark.asyncio
    async def test_retries_on_503(self):
        call_count = 0

        @with_transient_retry(max_retries=3, base_delay=0)
        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise _FakeExcWithStatusCode(503)
            return "done"

        with patch("pipeline.http_retry.asyncio.sleep", return_value=None):
            result = await flaky()
        assert result == "done"
        assert call_count == 3
