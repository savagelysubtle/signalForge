"""Perplexity discovery mode prompt template.

Discovery mode: Perplexity screens the market for tickers matching
the strategy's screening criteria. Returns structured JSON with
fundamental data for each discovered ticker.
"""

from __future__ import annotations

from pipeline.schemas import StrategyConfig
from utils.hashing import prompt_hash

PROMPT_VERSION = "v6"

DISCOVERY_SYSTEM_PROMPT = """\
You are a financial research analyst specializing in market screening.
Your job is to find stocks, ETFs, or cryptocurrencies that match specific
screening criteria. You must return ONLY valid JSON — no commentary outside
the JSON structure.

IMPORTANT: Always return tickers. If you cannot find stocks matching every
criterion perfectly, return the best available matches. An empty tickers
array should only be returned if the search yields absolutely nothing
relevant. Partial matches are valuable — note any caveats in key_highlights.

Return a JSON object with this exact structure:
{
  "mode": "discovery",
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
  "screening_summary": "<brief summary of screening rationale and methodology>"
}

ANTI-HALLUCINATION RULES (for financial metrics only):
- If you cannot verify a specific number (pe_ratio, revenue_growth, etc.)
  from search results, set that field to null. Do NOT invent numbers.
- Do NOT include news URLs in the JSON — they are captured separately.
- You CAN and SHOULD still return the ticker with whatever data you have.
  Missing metrics are fine — missing tickers are not.

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


def build_discovery_prompt(config: StrategyConfig) -> str:
    """Build a search-query-style user prompt for discovery screening.

    Sonar Pro's search component triggers on the user prompt text, so this
    should read like a web search query rather than an instruction set.
    Constraint style is NOT included — it pollutes the search query.

    Args:
        config: The active strategy configuration.

    Returns:
        Search-query-style prompt string.
    """
    parts = [config.screening_prompt]
    parts.append(f"top {config.max_tickers} picks")
    return " ".join(parts)


def build_prompted_discovery_prompt(
    user_prompt: str,
    config: StrategyConfig | None = None,
) -> str:
    """Build a search-query-style prompt from user free-form text.

    The user's text is used directly as the search query, with optional
    strategy context appended as additional search terms.

    Args:
        user_prompt: The user's free-form screening request.
        config: Optional strategy configuration for additional context.

    Returns:
        Search-query-style prompt string.
    """
    parts = [user_prompt]
    if config and config.screening_prompt:
        parts.append(config.screening_prompt)
    if config:
        parts.append(f"top {config.max_tickers} picks")
    else:
        parts.append("top 10 picks")
    return " ".join(parts)


def get_prompt_hash() -> str:
    """Return the version hash of the current discovery prompt."""
    return prompt_hash(DISCOVERY_SYSTEM_PROMPT)
