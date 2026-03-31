"""Claude Vision chart analysis prompt template.

Stage 3: Claude analyzes a TradingView chart screenshot, incorporating
news context from the Gemini sentiment stage (Stage 2) when available.
This is the key integration point — Claude sees both the chart AND recent
news so it can interpret price action in context of known catalysts.
"""

from __future__ import annotations

from pipeline.schemas import SentimentAnalysis, StrategyConfig
from utils.hashing import prompt_hash

PROMPT_VERSION = "v7"

CHART_SYSTEM_PROMPT = """\
You are an expert technical analyst reviewing a TradingView chart screenshot.
Your job is to perform a thorough technical analysis and return a structured
assessment as JSON. Consider the visible price action, indicators, patterns,
volume, and key support/resistance levels.

CRITICAL — MANDATORY FIELDS:
1. current_price: You MUST read and return the current/last traded price from
   the chart. This is the most recent price shown — typically the rightmost
   point of the price line or the value displayed on the price axis. This
   field must NEVER be null. It is essential for downstream entry/exit
   calculations.
2. key_levels: You MUST identify and return at least 2 support/resistance
   levels in key_levels. If exact levels are not immediately obvious, estimate
   them from the nearest visible support/resistance zones, round numbers, or
   recent swing highs/lows. NEVER return an empty key_levels array.

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

You MUST identify at least 2 key support/resistance levels — this is not
optional. Use recent swing lows for support and swing highs for resistance.
If the chart is unclear, use round-number levels or indicator-derived levels
(e.g. VWAP, moving average crossover prices). Note all visible indicator
readings. If chart patterns (head & shoulders, double top/bottom, flags,
wedges, triangles, etc.) are present, name them.

ATR (Average True Range) — IMPORTANT for downstream stop-loss:
- Read the current ATR value from the indicator pane. It is a single numeric
  value (e.g. 1.23, 0.45, 15.80). Report the EXACT numeric value as a string
  in the indicator_readings value field (e.g. "value": "1.23").
- GPT uses this value downstream for ATR-based stop-loss placement, so
  accuracy matters. Do NOT round aggressively or omit decimal places.
- Signal guidance: "neutral" is typical. Use "bearish" if ATR is spiking
  (elevated volatility = higher risk). Use "bullish" if ATR is contracting
  from elevated levels (volatility compression often precedes breakouts).
- In notes, state whether ATR is expanding, contracting, or stable compared
  to its recent history on the visible chart.
"""


def build_chart_prompt(
    ticker: str,
    config: StrategyConfig,
    sentiment: SentimentAnalysis | None = None,
    timeframe_override: str | None = None,
    indicators_override: list[str] | None = None,
    fmp_context: str | None = None,
    regime_context: str = "",
) -> str:
    """Build the user prompt for per-ticker chart analysis.

    Includes chart configuration from the strategy and, when available,
    recent news context from Gemini's sentiment analysis and fundamental
    context from FMP pre-screening.

    Args:
        ticker: Stock/crypto ticker symbol.
        config: The active strategy configuration.
        sentiment: Gemini's sentiment result for this ticker, or None.
        timeframe_override: If set, use this timeframe instead of the
            strategy's ``chart_timeframe``.
        indicators_override: If set, use these indicators instead of the
            strategy's ``chart_indicators`` (for short-TF analysis).
        fmp_context: Pre-formatted FMP fundamental context string, or None.
        regime_context: Pre-formatted market regime header block, or empty.

    Returns:
        The formatted user prompt string.
    """
    effective_timeframe = timeframe_override or config.chart_timeframe
    effective_indicators = indicators_override or config.chart_indicators
    parts: list[str] = []

    if regime_context:
        parts.append(f"{regime_context}\n")

    parts.extend(
        [
            f"Analyze the attached TradingView chart for: {ticker}",
            f"\nTimeframe: {effective_timeframe}",
            f"Indicators on chart: {', '.join(effective_indicators)}",
        ]
    )

    if config.ta_focus:
        parts.append(f"\nAnalysis focus: {config.ta_focus}")

    if sentiment is not None:
        catalysts_text = ""
        if sentiment.key_catalysts:
            catalyst_lines = []
            for c in sentiment.key_catalysts[:5]:
                recency = f", {c.hours_ago}h ago" if c.hours_ago is not None else ""
                catalyst_lines.append(
                    f"  - [{c.impact.upper()}] {c.headline} ({c.significance} significance{recency})"
                )
            catalysts_text = "\n".join(catalyst_lines)

        parts.append(
            f"\n--- RECENT NEWS CONTEXT ---"
            f"\nSentiment: {sentiment.sentiment_score:+.2f}"
            f" [{sentiment.sentiment_bucket}] ({sentiment.sentiment_label})"
            f"\nSummary: {sentiment.summary}"
        )
        if catalysts_text:
            parts.append(f"Key catalysts:\n{catalysts_text}")
        parts.append(
            "Consider how this news context aligns with or contradicts "
            "the technical signals you observe on the chart."
            "\n--- END NEWS CONTEXT ---"
        )

    if fmp_context:
        parts.append(
            "\n--- FUNDAMENTAL CONTEXT (verified FMP data) ---"
            f"\n{fmp_context}"
            "\nUse this context to weight your technical assessment. A breakout in a "
            "stock with strong insider buying and high Piotroski score is more meaningful "
            "than the same pattern in a low-quality stock. Upcoming earnings dates signal "
            "potential volatility catalysts."
            "\n--- END FUNDAMENTAL CONTEXT ---"
        )

    parts.append("\nReturn your analysis as JSON matching the schema in your instructions.")

    return "\n".join(parts)


def get_prompt_hash() -> str:
    """Return the version hash of the current chart analysis prompt."""
    return prompt_hash(CHART_SYSTEM_PROMPT)
