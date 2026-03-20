"""Perplexity discovery mode prompt template.

Discovery mode: Perplexity screens the market for tickers matching
the strategy's screening criteria. Returns structured JSON with
fundamental data for each discovered ticker.
"""

from __future__ import annotations

from pipeline.schemas import StrategyConfig
from utils.hashing import prompt_hash

PROMPT_VERSION = "v3"

DISCOVERY_SYSTEM_PROMPT = """\
You are a financial research analyst specializing in market screening.
Your job is to find stocks, ETFs, or cryptocurrencies that match specific
screening criteria. You must return ONLY valid JSON — no commentary outside
the JSON structure.

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
    """Build the user prompt for discovery mode screening.

    Args:
        config: The active strategy configuration.

    Returns:
        The formatted user prompt string.
    """
    constraint_instruction = (
        "Apply strict filtering — only return tickers that strongly match ALL criteria."
        if config.constraint_style == "tight"
        else "Apply loose filtering — return tickers that match most criteria, even partially."
    )

    return (
        f"Strategy: {config.name}\n\n"
        f"Screening criteria:\n{config.screening_prompt}\n\n"
        f"{constraint_instruction}\n\n"
        f"Return up to {config.max_tickers} tickers as JSON. "
        f"Include both traditional securities and crypto if the criteria apply."
    )


def build_prompted_discovery_prompt(
    user_prompt: str,
    config: StrategyConfig | None = None,
) -> str:
    """Build the user prompt for prompt-driven discovery mode.

    The user's free-form prompt is the primary screening instruction.
    If a strategy is selected, its constraints and limits are layered on.

    Args:
        user_prompt: The user's free-form screening request.
        config: Optional strategy configuration for additional context.

    Returns:
        The formatted user prompt string.
    """
    parts: list[str] = [f"User request:\n{user_prompt}"]

    if config:
        parts.append(f"\nStrategy context: {config.name}")
        if config.screening_prompt:
            parts.append(f"Additional screening criteria:\n{config.screening_prompt}")
        constraint_instruction = (
            "Apply strict filtering — only return tickers that strongly match ALL criteria."
            if config.constraint_style == "tight"
            else "Apply loose filtering — return tickers that match most criteria, even partially."
        )
        parts.append(constraint_instruction)
        parts.append(
            f"\nReturn up to {config.max_tickers} tickers as JSON. "
            f"Include both traditional securities and crypto if the criteria apply."
        )
    else:
        parts.append(
            "\nReturn up to 10 tickers as JSON. "
            "Include both traditional securities and crypto if the criteria apply."
        )

    return "\n".join(parts)


def get_prompt_hash() -> str:
    """Return the version hash of the current discovery prompt."""
    return prompt_hash(DISCOVERY_SYSTEM_PROMPT)
