"""Ticker symbol normalization utilities.

Provides a single canonical function to clean ticker strings flowing through
the pipeline. Handles whitespace, Yahoo Finance suffixes (.TO, .V), LLM
formatting artifacts ($, quotes, trailing punctuation), verbose exchange
names, and ensures consistent TradingView ``EXCHANGE:SYMBOL`` format.
"""

from __future__ import annotations

import re

YAHOO_TO_TV: dict[str, str] = {
    ".TO": "TSX",
    ".V": "TSXV",
    ".L": "LSE",
    ".AX": "ASX",
    ".HK": "HKEX",
    ".T": "TSE",
    ".DE": "XETR",
    ".PA": "EURONEXT",
    ".AS": "EURONEXT",
    ".MI": "MIL",
    ".SW": "SIX",
    ".SA": "BMFBOVESPA",
    ".NS": "NSE",
    ".BO": "BSE",
    ".SS": "SSE",
    ".SZ": "SZSE",
    ".KS": "KRX",
}

EXCHANGE_ALIASES: dict[str, str] = {
    "TORONTO": "TSX",
    "VENTURE": "TSXV",
    "TSXVENTURE": "TSXV",
    "TSX-V": "TSXV",
    "LONDON": "LSE",
    "NYSEARCA": "AMEX",
    "NYSEMKT": "AMEX",
    "CBOE_BZX": "AMEX",
}

# TradingView exchange codes for US listings where FMP uses a bare symbol (no suffix).
# Used only for cross-format matching (``AAPL`` vs ``NASDAQ:AAPL``), not for intl. tickers.
_US_STOCK_TV_EXCHANGES: frozenset[str] = frozenset(
    {
        "AMEX",
        "BATS",
        "GREY",
        "NASDAQ",
        "NASDAQCM",
        "NASDAQGM",
        "NASDAQGS",
        "NYSE",
        "NYSEAMERICAN",
        "OTC",
        "OTCMKTS",
        "PINK",
        "US",
    }
)

_WHITESPACE_RE = re.compile(r"\s+")
_WRAP_CHARS_RE = re.compile(r'^[\s"\'$`*()[\]{}]+|[\s"\'`*.,;!?()[\]{}]+$')


def _strip_wrapping(text: str) -> str:
    """Strip dollar signs, quotes, brackets, and trailing punctuation."""
    return _WRAP_CHARS_RE.sub("", text)


def _strip_yahoo_suffix(symbol: str) -> str:
    """Remove Yahoo Finance suffix from a symbol (e.g. ``SHOP.TO`` → ``SHOP``)."""
    for suffix in YAHOO_TO_TV:
        if symbol.endswith(suffix):
            return symbol[: -len(suffix)]
    return symbol


def normalize_ticker(ticker: str) -> str:
    """Normalize a ticker symbol to clean TradingView format.

    Handles all common malformations from LLM output and external APIs:
    - Strips leading/trailing whitespace
    - Removes wrapping characters: ``$``, quotes, brackets, asterisks
    - Strips trailing punctuation: ``.``, ``,``, ``;``, ``!``, ``?``
    - Collapses internal whitespace (``TSX: CVE`` → ``TSX:CVE``)
    - Converts Yahoo Finance suffixes to TradingView prefixes
      (``ENB.TO`` → ``TSX:ENB``, ``NVX.V`` → ``TSXV:NVX``)
    - Strips redundant Yahoo suffixes from already-prefixed tickers
      (``TSX:SHOP.TO`` → ``TSX:SHOP``)
    - Normalizes verbose exchange names
      (``TORONTO:SHOP`` → ``TSX:SHOP``, ``NYSEARCA:SPY`` → ``AMEX:SPY``)
    - Uppercases everything

    Args:
        ticker: Raw ticker string from any source.

    Returns:
        Cleaned ticker in TradingView format.

    Examples:
        >>> normalize_ticker("TSX: CVE")
        'TSX:CVE'
        >>> normalize_ticker("  aapl  ")
        'AAPL'
        >>> normalize_ticker("ENB.TO")
        'TSX:ENB'
        >>> normalize_ticker("NVX.V")
        'TSXV:NVX'
        >>> normalize_ticker("TSX :  ENB")
        'TSX:ENB'
        >>> normalize_ticker("TSX:SHOP.TO")
        'TSX:SHOP'
        >>> normalize_ticker("$AAPL")
        'AAPL'
        >>> normalize_ticker('"TSX:ENB"')
        'TSX:ENB'
        >>> normalize_ticker("AAPL.")
        'AAPL'
        >>> normalize_ticker("TORONTO:SHOP")
        'TSX:SHOP'
        >>> normalize_ticker("NYSEARCA:SPY")
        'AMEX:SPY'
    """
    cleaned = _strip_wrapping(ticker)
    cleaned = _WHITESPACE_RE.sub("", cleaned)

    if not cleaned:
        return ticker.strip()

    if ":" in cleaned:
        exchange, symbol = cleaned.split(":", 1)
        exchange = exchange.upper()
        symbol = _strip_yahoo_suffix(symbol.upper())
        exchange = EXCHANGE_ALIASES.get(exchange, exchange)
        return f"{exchange}:{symbol}"

    upper = cleaned.upper()
    for suffix, exchange in YAHOO_TO_TV.items():
        if upper.endswith(suffix):
            base = upper[: -len(suffix)]
            return f"{exchange}:{base}"

    return upper


def canonical_ticker_match_key(ticker: str) -> str:
    """Stable key for comparing tickers that may differ only by US exchange prefix.

    US-listed symbols in ``EXCHANGE:SYMBOL`` form (e.g. ``NASDAQ:AAPL``) map to the
    same key as a bare ``AAPL``. International listings keep ``EXCHANGE:SYMBOL`` so
    ``TSX:SHOP`` never collides with a different ``SHOP`` on another venue.

    Always applies :func:`normalize_ticker` first.

    Args:
        ticker: Raw or normalized ticker string.

    Returns:
        Uppercase match key suitable for set/dict lookups and deduplication.

    Examples:
        >>> canonical_ticker_match_key("NASDAQ:AAPL")
        'AAPL'
        >>> canonical_ticker_match_key("AAPL")
        'AAPL'
        >>> canonical_ticker_match_key("TSX:ENB")
        'TSX:ENB'
    """
    norm = normalize_ticker(ticker)
    if ":" not in norm:
        return norm
    exchange, symbol = norm.split(":", 1)
    if exchange in _US_STOCK_TV_EXCHANGES:
        return symbol
    return norm


def dedupe_ticker_symbols_preserve_order(symbols: list[str]) -> list[str]:
    """Drop duplicate tickers that share the same :func:`canonical_ticker_match_key`.

    Preserves the first occurrence's normalized spelling; later duplicates are removed.

    Args:
        symbols: Pipeline ticker list (any mix of formats).

    Returns:
        Deduplicated normalized tickers in original order.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in symbols:
        norm = normalize_ticker(raw)
        key = canonical_ticker_match_key(norm)
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    return out


TV_TO_FMP_SUFFIX: dict[str, str] = {
    "TSX": ".TO",
    "TSXV": ".V",
    "LSE": ".L",
    "ASX": ".AX",
    "HKEX": ".HK",
    "TSE": ".T",
    "XETR": ".DE",
    "EURONEXT": ".PA",
    "MIL": ".MI",
    "SIX": ".SW",
    "BMFBOVESPA": ".SA",
    "NSE": ".NS",
    "BSE": ".BO",
    "SSE": ".SS",
    "SZSE": ".SZ",
    "KRX": ".KS",
}


def to_fmp_symbol(ticker: str) -> str:
    """Convert a TradingView ``EXCHANGE:SYMBOL`` ticker to FMP format.

    International exchanges get a Yahoo-style suffix (e.g. ``TSX:AGI`` → ``AGI.TO``).
    US exchanges (NASDAQ, NYSE, AMEX, etc.) and bare symbols pass through as-is.

    Args:
        ticker: Ticker string, optionally prefixed with exchange.

    Returns:
        FMP-compatible symbol string.

    Examples:
        >>> to_fmp_symbol("TSX:AGI")
        'AGI.TO'
        >>> to_fmp_symbol("TSXV:NVX")
        'NVX.V'
        >>> to_fmp_symbol("LSE:BP")
        'BP.L'
        >>> to_fmp_symbol("NASDAQ:AAPL")
        'AAPL'
        >>> to_fmp_symbol("AAPL")
        'AAPL'
        >>> to_fmp_symbol("BTCUSD")
        'BTCUSD'
    """
    cleaned = _strip_wrapping(ticker)
    cleaned = _WHITESPACE_RE.sub("", cleaned)
    if not cleaned:
        return ticker.strip()

    if ":" not in cleaned:
        return cleaned.upper()

    exchange, symbol = cleaned.split(":", 1)
    exchange = exchange.upper()
    symbol = symbol.upper()
    exchange = EXCHANGE_ALIASES.get(exchange, exchange)

    suffix = TV_TO_FMP_SUFFIX.get(exchange)
    if suffix:
        return f"{symbol}{suffix}"
    return symbol


def normalize_tickers(tickers: list[str]) -> list[str]:
    """Normalize a list of ticker symbols, preserving order and removing duplicates.

    Args:
        tickers: Raw ticker strings.

    Returns:
        Deduplicated list of normalized tickers in original order.
    """
    return list(dict.fromkeys(normalize_ticker(t) for t in tickers))
