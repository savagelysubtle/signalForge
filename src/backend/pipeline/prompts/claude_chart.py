"""Claude Vision chart analysis prompt template.

Stage 3: Claude analyzes a TradingView chart screenshot using numerical TA data
as the primary input. The chart image serves as a visual sanity check. Claude
performs independent technical analysis — no sentiment or fundamental data is
injected here; other pipeline stages handle those concerns.
"""

from __future__ import annotations

from pipeline.schemas import StrategyConfig
from utils.hashing import prompt_hash

PROMPT_VERSION = "v12"

CHART_SYSTEM_PROMPT = """\
You are a technical analyst. Your PRIMARY data source is the precise numerical
indicator data provided below. The attached chart image is a VISUAL SANITY
CHECK — use it to confirm the numbers, spot chart patterns the numbers miss,
and flag any discrepancies.

IMPORTANT: You are performing an INDEPENDENT technical analysis. You have NOT
been given fundamental data, sentiment scores, or news. Other analysts handle
those. Focus purely on price action, indicators, and technical structure.

You must return ONLY valid JSON — no commentary outside the JSON structure.

Return a JSON object with this exact structure:
{
  "ticker": "<SYMBOL>",
  "timeframe": "<timeframe, e.g. D, 4H, W>",
  "current_price": <float — from the numerical data>,
  "trend_direction": "bullish" | "bearish" | "neutral" | "transitioning",
  "trend_strength": "<free-form: e.g. 'ADX 28 confirms trending conditions'>",
  "overall_bias": "strongly_bullish" | "bullish" | "neutral" | "bearish" | "strongly_bearish",
  "confidence": <float from 0.0 to 1.0>,
  "summary": "<2-3 sentence synthesis of the technical picture>",

  "ema_assessment": "<e.g. 'Bullish alignment, 9/21 cross confirmed and widening'>",
  "momentum_assessment": "<e.g. 'RSI healthy at 64, MACD expanding, no divergence'>",
  "volume_assessment": "<e.g. 'Elevated 1.3x avg, confirms directional move'>",
  "trend_assessment": "<e.g. 'ADX 28 confirms trending conditions, slope rising'>",

  "chart_confirms_data": true | false,
  "chart_discrepancies": ["<discrepancy description if chart contradicts numbers>"],

  "nearest_support": <float — nearest EMA or structural level below price>,
  "nearest_resistance": <float — nearest EMA or structural level above price>,
  "suggested_stop_zone": "<e.g. 'Below 21 EMA at $185.21'>",

  "key_levels": [
    {
      "price": <float>,
      "level_type": "support" | "resistance",
      "strength": "strong" | "moderate" | "weak"
    }
  ],
  "patterns_detected": ["<pattern name — from the chart image>"],
  "indicator_readings": [
    {
      "indicator": "<name>",
      "value": "<current reading>",
      "signal": "bullish" | "bearish" | "neutral",
      "notes": "<brief explanation>"
    }
  ],
  "volume_analysis": "<brief legacy volume field>",
  "timeframe_alignment_note": "<if multiple timeframes provided, note alignment>"
}

Confidence calibration:
- 0.85+: Overwhelming alignment — EMAs stacked, MACD expanding, ADX trending, volume confirms
- 0.70-0.85: Strong setup with minor caveats (e.g. RSI nearing overbought)
- 0.55-0.70: Moderate — trend present but mixed momentum signals
- 0.40-0.55: Weak — conflicting signals, likely range-bound
- <0.40: Very weak — numerical data contradicts itself or chart flags concerns

Your analysis MUST:
1. INTERPRET the numerical EMA, RSI, MACD, ADX, and volume data — don't just repeat it
2. Derive nearest_support from the closest EMA below price or visible chart support
3. Derive nearest_resistance from the closest EMA above price or visible chart resistance
4. Set chart_confirms_data to false and list discrepancies if the chart contradicts numbers
5. Provide at least 2 key_levels (support + resistance)
6. Include ATR in indicator_readings for downstream stop-loss calculation
7. Look at the chart for patterns (H&S, flags, wedges, etc.) the numbers can't detect
"""


def build_chart_prompt(
    ticker: str,
    config: StrategyConfig,
    ta_context: str,
    timeframe_override: str | None = None,
    indicators_override: list[str] | None = None,
    regime_context: str = "",
    live_quote_context: str | None = None,
    fmp_context_str: str | None = None,
) -> str:
    """Build the user prompt for independent technical chart analysis.

    Claude receives numerical TA data as its PRIMARY input. The chart image
    is a visual sanity check. Live quotes provide real-time price calibration
    for support/resistance/entry levels. FMP context provides fundamental
    anchors (earnings dates, quality scores, insider activity).

    Args:
        ticker: Stock/crypto ticker symbol.
        config: The active strategy configuration.
        ta_context: Pre-formatted numerical TA text from
            ``format_ta_for_prompt()``.
        timeframe_override: If set, use this timeframe instead of the
            strategy's ``chart_timeframe``.
        indicators_override: If set, use these indicators instead of the
            strategy's ``chart_indicators``.
        regime_context: Pre-formatted market regime header block, or empty.
        live_quote_context: Pre-formatted real-time quote string, or None.
        fmp_context_str: Pre-formatted FMP fundamental context, or None.

    Returns:
        The formatted user prompt string.
    """
    effective_timeframe = timeframe_override or config.chart_timeframe
    effective_indicators = indicators_override or config.chart_indicators
    parts: list[str] = []

    if regime_context:
        parts.append(f"REGIME CONTEXT:\n{regime_context}\n")

    parts.append(
        f"TECHNICAL DATA (PRIMARY — analyze these numbers):\n"
        f"Ticker: {ticker}\n"
        f"Timeframe: {effective_timeframe}\n"
        f"Indicators on chart: {', '.join(effective_indicators)}\n"
        f"\n{ta_context}"
    )

    if live_quote_context:
        parts.append(
            "\n--- LIVE MARKET DATA (real-time) ---"
            f"\n{live_quote_context}"
            "\nThis is the CURRENT intraday snapshot. The numerical TA data above "
            "reflects the latest completed candle, which may lag. Use this live price "
            "to calibrate your current_price, support/resistance, and entry levels. "
            "If the live price diverges significantly from the TA data, note it."
            "\n--- END LIVE MARKET DATA ---"
        )

    if fmp_context_str:
        parts.append(
            "\n--- FUNDAMENTAL CONTEXT (from FMP pre-screening) ---"
            f"\n{fmp_context_str}"
            "\nUse this to contextualize your technical analysis: upcoming earnings "
            "may explain volatility compression, insider buying supports bullish setups, "
            "quality scores anchor conviction. Do NOT override your technical read — "
            "treat this as supplementary evidence."
            "\n--- END FUNDAMENTAL CONTEXT ---"
        )

    if config.ta_focus:
        parts.append(f"\nAnalysis focus: {config.ta_focus}")

    if config.risk_params and config.risk_params.min_risk_reward:
        parts.append(
            f"\nRisk/reward requirement: Only flag as BUY if price structure "
            f"shows R:R >= {config.risk_params.min_risk_reward}. If not "
            f"identifiable, flag as HOLD or WATCH."
        )

    parts.append(
        "\nCHART IMAGE (CONFIRMATION — verify the above data visually):\n"
        "[attached chart image]\n"
        "\nYOUR TASK:\n"
        "1. Interpret the numerical data above. What is the technical picture telling you?\n"
        "2. Look at the chart image. Does it visually confirm what the numbers say?\n"
        "3. If the chart contradicts the numbers, set chart_confirms_data=false and list discrepancies.\n"
        "4. Provide your independent technical assessment: direction, confidence (0.0-1.0), key levels.\n"
        "5. Derive nearest_support and nearest_resistance from the EMA structure.\n"
        "6. Suggest a stop_zone based on the nearest invalidation level.\n"
        "7. Look for chart patterns (H&S, flags, wedges, etc.) the numbers can't detect.\n"
        "8. Do NOT consider fundamentals or sentiment — other analysts handle that.\n"
        "\nReturn your analysis as JSON matching the schema in your instructions."
    )

    return "\n".join(parts)


def get_prompt_hash() -> str:
    """Return the version hash of the current chart analysis prompt."""
    return prompt_hash(CHART_SYSTEM_PROMPT)
