"""Tests for canonical ticker matching (US prefix vs bare symbol)."""

from __future__ import annotations

import pytest

from utils.ticker import (
    canonical_ticker_match_key,
    dedupe_ticker_symbols_preserve_order,
    normalize_ticker,
)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("AAPL", "NASDAQ:AAPL"),
        ("NYSE:MSFT", "MSFT"),
        ("AMEX:SPY", "SPY"),
        ("aapl", "NASDAQ:AAPL"),
    ],
)
def test_us_listing_aliases_match(a: str, b: str) -> None:
    assert canonical_ticker_match_key(a) == canonical_ticker_match_key(b)


def test_international_not_collapsed() -> None:
    assert canonical_ticker_match_key("TSX:ENB") == "TSX:ENB"
    assert canonical_ticker_match_key("ENB.TO") == canonical_ticker_match_key("TSX:ENB")


def test_dedupe_preserves_first_spelling() -> None:
    out = dedupe_ticker_symbols_preserve_order(["NASDAQ:AAPL", "AAPL", "MSFT"])
    assert out == ["NASDAQ:AAPL", "MSFT"]


def test_dedupe_after_normalize() -> None:
    raw = ["  AAPL  ", "NASDAQ:AAPL"]
    out = dedupe_ticker_symbols_preserve_order(raw)
    assert len(out) == 1
    assert canonical_ticker_match_key(out[0]) == "AAPL"
    assert out[0] == normalize_ticker(raw[0])
