"""Perplexity discovery mode prompt template.

Discovery mode: Perplexity screens the market for tickers matching
the strategy's screening criteria. Returns structured JSON with
fundamental data for each discovered ticker.
"""

from __future__ import annotations

from pipeline.schemas import StrategyConfig
from utils.hashing import prompt_hash

PROMPT_VERSION = "v1"

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


def get_prompt_hash() -> str:
    """Return the version hash of the current discovery prompt."""
    return prompt_hash(DISCOVERY_SYSTEM_PROMPT)
