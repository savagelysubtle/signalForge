"""Tests for pipeline/token_budget.py — token counting and budget enforcement."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pipeline.token_budget import (
    _TRUNCATION_ORDER,
    count_tokens,
    enforce_token_budget,
)


def _build_prompt(*sections: str) -> str:
    """Build a fake user prompt with the given section headers and filler text."""
    parts = []
    for header in sections:
        parts.append(header)
        parts.append("Lorem ipsum dolor sit amet. " * 50)
        parts.append("")
    return "\n".join(parts)


class TestCountTokens:
    def test_nonempty_text_positive(self):
        assert count_tokens("Hello, world!") > 0

    def test_empty_text_zero(self):
        assert count_tokens("") == 0


class TestEnforceTokenBudget:
    def test_under_budget_returns_unchanged(self):
        system = "You are an analyst."
        user = "Analyze AAPL"
        result = enforce_token_budget(system, user, model="gpt-4o")
        assert result == user

    def test_truncates_historical_performance_first(self):
        system = "System"
        user = _build_prompt(
            "## HISTORICAL PERFORMANCE CONTEXT",
            "## SECTOR SENTIMENT CONSENSUS",
            "## BULL CASE ARGUMENTS",
        )

        with patch("pipeline.token_budget.count_tokens", side_effect=_over_then_under):
            result = enforce_token_budget(system, user, model="gpt-4o")

        assert "[TRUNCATED" in result
        assert "HISTORICAL PERFORMANCE" in result
        assert "SECTOR SENTIMENT CONSENSUS" in result

    def test_truncates_multiple_sections(self):
        system = "System"
        user = _build_prompt(
            "## HISTORICAL PERFORMANCE CONTEXT",
            "## SECTOR SENTIMENT CONSENSUS",
            "## BULL CASE ARGUMENTS",
        )

        call_count = 0

        def always_over(text: str) -> int:
            nonlocal call_count
            call_count += 1
            return 999_999

        with patch("pipeline.token_budget.count_tokens", side_effect=always_over):
            result = enforce_token_budget(system, user, model="gpt-4o")

        truncated_count = result.count("[TRUNCATED")
        assert truncated_count >= 2

    def test_truncation_marker_present(self):
        system = "System"
        user = _build_prompt("## HISTORICAL PERFORMANCE CONTEXT")

        with patch("pipeline.token_budget.count_tokens", side_effect=_over_then_under):
            result = enforce_token_budget(system, user, model="gpt-4o")

        assert "tokens removed to fit budget]" in result

    def test_truncation_order_matches_expected(self):
        assert _TRUNCATION_ORDER[0] == "## HISTORICAL PERFORMANCE CONTEXT"
        assert len(_TRUNCATION_ORDER) >= 4


def _over_then_under(text: str) -> int:
    """First two calls (system+user check) return over-budget, subsequent calls return under."""
    if not hasattr(_over_then_under, "_calls"):
        _over_then_under._calls = 0  # type: ignore[attr-defined]
    _over_then_under._calls += 1  # type: ignore[attr-defined]
    if _over_then_under._calls <= 2:  # type: ignore[attr-defined]
        return 999_999
    _over_then_under._calls = 0  # type: ignore[attr-defined]
    return 1


# Reset the counter between tests
@pytest.fixture(autouse=True)
def _reset_over_then_under():
    if hasattr(_over_then_under, "_calls"):
        _over_then_under._calls = 0  # type: ignore[attr-defined]
    yield
    if hasattr(_over_then_under, "_calls"):
        _over_then_under._calls = 0  # type: ignore[attr-defined]
