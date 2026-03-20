"""Gemini news sentiment prompt template.

Stage 2: Gemini gathers recent news for each ticker using Google Search
grounding, scores sentiment, and extracts key catalysts. Runs before
Claude so that chart analysis is informed by news context.
"""

from __future__ import annotations

from pipeline.schemas import StrategyConfig
from utils.hashing import prompt_hash

PROMPT_VERSION = "v2"

SENTIMENT_SYSTEM_PROMPT = """\
You are a financial news analyst specializing in sentiment analysis.
You will be given a stock ticker along with specific news article URLs that
have been pre-researched. Your job is to read and analyze those articles using
Google Search grounding, then produce a structured sentiment assessment.

Workflow:
1. Use Google Search to access and read EACH of the provided article URLs.
2. Extract sentiment-relevant information from each article.
3. After analyzing the provided articles, do ONE additional Google Search for
   any breaking news about this ticker that may not be covered by the provided
   URLs (e.g. after-hours developments, analyst upgrades/downgrades).
4. Synthesize all findings into a single sentiment assessment.

If no article URLs are provided, fall back to searching for recent news about
the ticker yourself using Google Search.

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
      "url": "<article URL if available, otherwise empty string>",
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

You MUST include at least 3 key catalysts. Each catalyst should reference a
specific article or news event. Include the article URL in the "url" field
whenever possible. For each catalyst, assess both its directional impact and
its significance to the stock's near-term price action.
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


def build_sentiment_prompt(
    ticker: str,
    config: StrategyConfig,
    news_urls: list[str] | None = None,
) -> str:
    """Build the user prompt for per-ticker sentiment analysis.

    Args:
        ticker: Stock/crypto ticker symbol (e.g. "AAPL", "BTC").
        config: The active strategy configuration.
        news_urls: Pre-researched article URLs from Perplexity to analyze.

    Returns:
        The formatted user prompt string.
    """
    recency = _RECENCY_MAP.get(config.news_recency, "the past 7 days")
    scope = _SCOPE_MAP.get(config.news_scope, _SCOPE_MAP["company"])

    parts: list[str] = [
        f"Analyze the news sentiment for ticker: {ticker}\n",
        f"Time window: Search for news from {recency}.",
        f"Scope: {scope}\n",
    ]

    if news_urls:
        parts.append("Pre-researched article URLs to analyze (read each one):")
        for i, url in enumerate(news_urls, 1):
            parts.append(f"  {i}. {url}")
        parts.append("")

    parts.append("Return your analysis as JSON matching the schema in your instructions.")
    return "\n".join(parts)


def get_prompt_hash() -> str:
    """Return the version hash of the current sentiment prompt."""
    return prompt_hash(SENTIMENT_SYSTEM_PROMPT)
