"""Gemini news sentiment prompt template.

Stage 2: Gemini gathers recent news for each ticker using Google Search
grounding, scores sentiment, and extracts key catalysts. Runs before
Claude so that chart analysis is informed by news context.
"""

from __future__ import annotations

from pipeline.schemas import StrategyConfig
from utils.hashing import prompt_hash

PROMPT_VERSION = "v1"

SENTIMENT_SYSTEM_PROMPT = """\
You are a financial news analyst specializing in sentiment analysis.
Your job is to research recent news for a given stock, ETF, or cryptocurrency
ticker and produce a structured sentiment assessment. You have access to
Google Search to find real-time news — use it.

You must return ONLY valid JSON — no commentary outside the JSON structure.

Return a JSON object with this exact structure:
{
  "ticker": "<SYMBOL>",
  "sentiment_score": <float from -1.0 to 1.0>,
  "sentiment_label": "strongly_bearish" | "bearish" | "neutral" | "bullish" | "strongly_bullish",
  "key_catalysts": [
    {
      "headline": "<news headline or event description>",
      "source": "<publication or source name>",
      "impact": "positive" | "negative" | "neutral",
      "significance": "high" | "medium" | "low"
    }
  ],
  "news_recency": "<time window searched, e.g. Past 7 days>",
  "sector_sentiment": "<brief assessment of broader sector/industry sentiment>",
  "summary": "<2-3 sentence synthesis of the news landscape and sentiment drivers>"
}

Scoring guide for sentiment_score:
- -1.0 to -0.6: strongly_bearish (major negative catalysts, downgrades, scandals)
- -0.6 to -0.2: bearish (negative earnings, sector headwinds, analyst concerns)
- -0.2 to 0.2: neutral (mixed signals, no dominant narrative)
- 0.2 to 0.6: bullish (positive earnings, upgrades, favorable macro)
- 0.6 to 1.0: strongly_bullish (breakout catalysts, major contracts, sector tailwinds)

Include at least 3 key catalysts when available. For each catalyst, assess
both its directional impact and its significance to the stock's near-term
price action.
"""

_RECENCY_MAP = {
    "today": "the last 24 hours",
    "week": "the past 7 days",
    "month": "the past 30 days",
}

_SCOPE_MAP = {
    "company": "Focus on company-specific news (earnings, products, management, deals).",
    "sector": (
        "Include both company-specific news and broader sector/industry trends "
        "that could affect this ticker."
    ),
    "macro": (
        "Include company news, sector trends, AND macroeconomic factors "
        "(interest rates, regulation, geopolitics) relevant to this ticker."
    ),
}


def build_sentiment_prompt(ticker: str, config: StrategyConfig) -> str:
    """Build the user prompt for per-ticker sentiment analysis.

    Args:
        ticker: Stock/crypto ticker symbol (e.g. "AAPL", "BTC").
        config: The active strategy configuration.

    Returns:
        The formatted user prompt string.
    """
    recency = _RECENCY_MAP.get(config.news_recency, "the past 7 days")
    scope = _SCOPE_MAP.get(config.news_scope, _SCOPE_MAP["company"])

    return (
        f"Analyze the news sentiment for ticker: {ticker}\n\n"
        f"Time window: Search for news from {recency}.\n"
        f"Scope: {scope}\n\n"
        f"Return your analysis as JSON matching the schema in your instructions."
    )


def get_prompt_hash() -> str:
    """Return the version hash of the current sentiment prompt."""
    return prompt_hash(SENTIMENT_SYSTEM_PROMPT)
