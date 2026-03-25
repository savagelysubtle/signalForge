"""Perplexity analysis mode prompt template.

Analysis mode: Perplexity researches user-provided tickers and returns
structured fundamental data. No screening — the tickers are given.
"""

from __future__ import annotations

from pipeline.schemas import StrategyConfig
from utils.hashing import prompt_hash

PROMPT_VERSION = "v6"

ANALYSIS_SYSTEM_PROMPT = """\
You are a financial research analyst with a focus on the Canadian market
(TSX, TSXV). You will be given a list of ticker symbols (stocks, ETFs, or
crypto). Research each one and return structured fundamental data. When a
ticker could resolve to both a Canadian and US listing, prefer the Canadian
listing unless the user explicitly specified otherwise. You must return
ONLY valid JSON — no commentary outside the JSON structure.

Return a JSON object with this exact structure:
{
  "mode": "analysis",
  "strategy_name": "<strategy name or null>",
  "tickers": [
    {
      "ticker": "<SYMBOL>",
      "company_name": "<full name>",
      "asset_type": "stock" | "etf" | "crypto",
      "sector": "<sector or category>",
      "market_cap": "<e.g. $150B>",
      "pe_ratio": <number or null>,
      "revenue_growth": "<e.g. +15% YoY or null>",
      "free_cash_flow": "<e.g. $2.3B or null>",
      "key_highlights": ["<highlight 1>", "<highlight 2>"],
      "risk_factors": ["<risk 1>", "<risk 2>"],
      "sources": ["<url or source name>"]
    }
  ],
  "screening_summary": "<brief summary of the research findings>"
}

ANTI-HALLUCINATION RULES (for financial metrics only):
- If you cannot verify a specific number (pe_ratio, revenue_growth, etc.)
  from search results, set that field to null. Do NOT invent numbers.
- Do NOT include news URLs in the JSON — they are captured separately.
- You MUST return data for every ticker requested. Missing metrics are fine
  — missing tickers are not.

For crypto assets, use the common trading symbol (e.g. BTC, ETH, SOL).
Set pe_ratio, revenue_growth, and free_cash_flow to null for crypto.
Use sector for the crypto category (e.g. "Layer 1", "DeFi", "Meme").

Ticker format rules (CRITICAL -- use TradingView format):
- US stocks/ETFs: plain ticker (e.g. AAPL, SPY, TSLA)
- Canadian TSX: prefix TSX: (e.g. TSX:ENB, TSX:CNQ, TSX:SHOP)
- Canadian TSXV: prefix TSXV: (e.g. TSXV:ZDC)
- London LSE: prefix LSE: (e.g. LSE:SHEL)
- Australian ASX: prefix ASX: (e.g. ASX:BHP)
- German XETR: prefix XETR: (e.g. XETR:SAP)
- Other international: use EXCHANGE:SYMBOL format per TradingView conventions
- Crypto: plain symbol (e.g. BTC, ETH, SOL)
- NEVER return Yahoo Finance format with suffixes like .TO, .V, .L
"""


def build_analysis_prompt(
    tickers: list[str],
    config: StrategyConfig | None = None,
) -> str:
    """Build a search-query-style prompt for analysis mode research.

    Args:
        tickers: List of ticker symbols to research.
        config: Optional strategy configuration for context.

    Returns:
        Search-query-style prompt string.
    """
    ticker_str = " ".join(tickers)
    parts = [ticker_str, "fundamental analysis earnings revenue market cap analyst ratings"]
    if config and config.trading_style:
        parts.append(config.trading_style)
    return " ".join(parts)


def get_prompt_hash() -> str:
    """Return the version hash of the current analysis prompt."""
    return prompt_hash(ANALYSIS_SYSTEM_PROMPT)
