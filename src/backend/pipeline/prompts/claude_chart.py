"""Claude Vision chart analysis prompt template.

Stage 3: Claude analyzes a TradingView chart screenshot, incorporating
news context from the Gemini sentiment stage (Stage 2) when available.
This is the key integration point — Claude sees both the chart AND recent
news so it can interpret price action in context of known catalysts.
"""

from __future__ import annotations

from pipeline.schemas import SentimentAnalysis, StrategyConfig
from utils.hashing import prompt_hash

PROMPT_VERSION = "v3"

CHART_SYSTEM_PROMPT = """\
You are an expert technical analyst reviewing a TradingView chart screenshot.
Your job is to perform a thorough technical analysis and return a structured
assessment as JSON. Consider the visible price action, indicators, patterns,
volume, and key support/resistance levels.

CRITICAL: Read the current/last traded price from the chart. This is the most
recent price shown — typically the rightmost point of the price line or the
value displayed on the price axis. This price is essential for downstream
entry/exit calculations.

You must return ONLY valid JSON — no commentary outside the JSON structure.

Return a JSON object with this exact structure:
{
  "ticker": "<SYMBOL>",
  "timeframe": "<timeframe of the chart, e.g. D, 4H, W>",
  "current_price": <float — the last/current price visible on the chart>,
  "trend_direction": "bullish" | "bearish" | "neutral" | "transitioning",
  "trend_strength": "strong" | "moderate" | "weak",
  "key_levels": [
    {
      "price": <float>,
      "level_type": "support" | "resistance",
      "strength": "strong" | "moderate" | "weak"
    }
  ],
  "patterns_detected": ["<pattern name>"],
  "indicator_readings": [
    {
      "indicator": "<name>",
      "value": "<current reading>",
      "signal": "bullish" | "bearish" | "neutral",
      "notes": "<brief explanation>"
    }
  ],
  "volume_analysis": "<brief volume assessment>",
  "overall_bias": "strongly_bullish" | "bullish" | "neutral" | "bearish" | "strongly_bearish",
  "confidence": "high" | "medium" | "low",
  "summary": "<2-3 sentence synthesis of the technical picture>"
}

Scoring guides:

trend_direction:
- bullish: Clear uptrend with higher highs and higher lows
- bearish: Clear downtrend with lower highs and lower lows
- neutral: Range-bound or consolidating
- transitioning: Showing signs of trend reversal

trend_strength:
- strong: Clear trend with conviction, supported by volume and indicators
- moderate: Trend present but with some mixed signals
- weak: Barely discernible trend, likely to reverse

overall_bias (combining all factors):
- strongly_bullish: Multiple confirming bullish signals across price, indicators, and volume
- bullish: Predominant bullish signals with minor caveats
- neutral: Mixed or inconclusive signals
- bearish: Predominant bearish signals with minor caveats
- strongly_bearish: Multiple confirming bearish signals

confidence:
- high: Clear, unambiguous signals with strong conviction
- medium: Reasonable signals but some ambiguity
- low: Conflicting signals or unclear chart

Identify at least 2 key support/resistance levels when visible. Note all
visible indicator readings. If chart patterns (head & shoulders, double top/bottom,
flags, wedges, triangles, etc.) are present, name them.
"""


def build_chart_prompt(
    ticker: str,
    config: StrategyConfig,
    sentiment: SentimentAnalysis | None = None,
    timeframe_override: str | None = None,
) -> str:
    """Build the user prompt for per-ticker chart analysis.

    Includes chart configuration from the strategy and, when available,
    recent news context from Gemini's sentiment analysis.

    Args:
        ticker: Stock/crypto ticker symbol.
        config: The active strategy configuration.
        sentiment: Gemini's sentiment result for this ticker, or None.
        timeframe_override: If set, use this timeframe instead of the
            strategy's ``chart_timeframe``.

    Returns:
        The formatted user prompt string.
    """
    effective_timeframe = timeframe_override or config.chart_timeframe
    parts: list[str] = [
        f"Analyze the attached TradingView chart for: {ticker}",
        f"\nTimeframe: {effective_timeframe}",
        f"Indicators on chart: {', '.join(config.chart_indicators)}",
    ]

    if config.ta_focus:
        parts.append(f"\nAnalysis focus: {config.ta_focus}")

    if sentiment is not None:
        catalysts_text = ""
        if sentiment.key_catalysts:
            catalyst_lines = [
                f"  - [{c.impact.upper()}] {c.headline} ({c.significance} significance)"
                for c in sentiment.key_catalysts[:5]
            ]
            catalysts_text = "\n".join(catalyst_lines)

        parts.append(
            f"\n--- RECENT NEWS CONTEXT ---"
            f"\nSentiment score: {sentiment.sentiment_score:+.2f} ({sentiment.sentiment_label})"
            f"\nSummary: {sentiment.summary}"
        )
        if catalysts_text:
            parts.append(f"Key catalysts:\n{catalysts_text}")
        parts.append(
            "Consider how this news context aligns with or contradicts "
            "the technical signals you observe on the chart."
            "\n--- END NEWS CONTEXT ---"
        )

    parts.append("\nReturn your analysis as JSON matching the schema in your instructions.")

    return "\n".join(parts)


def get_prompt_hash() -> str:
    """Return the version hash of the current chart analysis prompt."""
    return prompt_hash(CHART_SYSTEM_PROMPT)
