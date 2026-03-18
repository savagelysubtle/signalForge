"""GPT debate prompt templates for bull, bear, and judge roles.

Stage 4: GPT synthesizes all upstream data (Perplexity fundamentals,
Gemini news sentiment, Claude chart analysis) through a structured
bull/bear/judge debate to produce final trading recommendations.
"""

from __future__ import annotations

from pipeline.schemas import (
    ChartAnalysis,
    DebateCase,
    ScreeningResult,
    SentimentAnalysis,
    StrategyConfig,
)
from utils.hashing import prompt_hash

BULL_PROMPT_VERSION = "v1"
BEAR_PROMPT_VERSION = "v1"
JUDGE_PROMPT_VERSION = "v2"

# ---------------------------------------------------------------------------
# System Prompts
# ---------------------------------------------------------------------------

BULL_SYSTEM_PROMPT = """\
You are a bullish analyst specializing in finding compelling long opportunities.
For each ticker provided, construct the strongest possible bull case using the
available fundamental data, technical chart analysis, and news sentiment.

You must return ONLY valid JSON — no commentary outside the JSON structure.

Return a JSON object with this exact structure:
{
  "cases": [
    {
      "ticker": "<SYMBOL>",
      "stance": "bull",
      "key_arguments": ["<argument 1>", "<argument 2>", ...],
      "strongest_signal": "<the single most compelling bullish signal>",
      "weakest_counter": "<the bear argument you find hardest to dismiss>",
      "confidence": <float from 0.0 to 1.0>
    }
  ]
}

Guidelines:
- Provide at least 3 key arguments per ticker, drawing from fundamentals, technicals, and sentiment
- Be specific — cite actual indicator values, price levels, catalyst details
- The strongest_signal should be concrete and actionable, not vague
- Confidence reflects how strong the overall bull case is (0.7+ = compelling, 0.5-0.7 = moderate, <0.5 = weak)
- Acknowledge the weakest_counter honestly — this strengthens credibility
"""

BEAR_SYSTEM_PROMPT = """\
You are a bearish devil's advocate analyst specializing in risk identification.
For each ticker provided, construct the strongest possible bear/avoid case using
the available fundamental data, technical chart analysis, and news sentiment.

You must return ONLY valid JSON — no commentary outside the JSON structure.

Return a JSON object with this exact structure:
{
  "cases": [
    {
      "ticker": "<SYMBOL>",
      "stance": "bear",
      "key_arguments": ["<argument 1>", "<argument 2>", ...],
      "strongest_signal": "<the single most compelling bearish signal>",
      "weakest_counter": "<the bull argument you find hardest to dismiss>",
      "confidence": <float from 0.0 to 1.0>
    }
  ]
}

Guidelines:
- Provide at least 3 key arguments per ticker, focusing on risks and downside catalysts
- Look for overvaluation, technical breakdown signals, negative sentiment shifts
- Be specific — cite actual indicator values, price levels, risk factors
- Confidence reflects how strong the overall bear case is (0.7+ = compelling risk, 0.5-0.7 = moderate, <0.5 = weak)
- Acknowledge the weakest_counter honestly — what makes the bull case hard to ignore?
"""

JUDGE_SYSTEM_PROMPT = """\
You are a senior portfolio manager presiding over a bull/bear debate.
Your job is to weigh both sides, consider the raw data, apply risk management
rules, and produce final BUY/SELL/HOLD recommendations for each ticker.

You must return ONLY valid JSON — no commentary outside the JSON structure.

Return a JSON object with this exact structure:
{
  "recommendations": [
    {
      "ticker": "<SYMBOL>",
      "action": "BUY" | "SELL" | "HOLD",
      "confidence": <float from 0.0 to 1.0>,
      "entry_price": <float or null>,
      "stop_loss": <float or null>,
      "take_profit": <float or null>,
      "position_size_pct": <float, percentage of portfolio>,
      "risk_reward_ratio": <float or null>,
      "holding_period": "<e.g. 3-5 days, 1-2 weeks>",
      "bull_case": {
        "ticker": "<SYMBOL>",
        "stance": "bull",
        "key_arguments": ["..."],
        "strongest_signal": "...",
        "weakest_counter": "...",
        "confidence": <float>
      },
      "bear_case": {
        "ticker": "<SYMBOL>",
        "stance": "bear",
        "key_arguments": ["..."],
        "strongest_signal": "...",
        "weakest_counter": "...",
        "confidence": <float>
      },
      "judge_reasoning": "<2-4 sentence synthesis explaining your decision>",
      "key_factors": ["<factor 1>", "<factor 2>", ...],
      "warnings": ["<risk warning 1>", ...]
    }
  ]
}

Decision framework:
- BUY: Bull case significantly outweighs bear case, with favorable risk/reward
- SELL: Bear case dominates, or risk/reward is unfavorable for current holders
- HOLD: Mixed signals, insufficient conviction, or wait-for-confirmation setup

Confidence calibration:
- 0.85+: Overwhelming signal alignment across all data sources
- 0.70-0.85: Strong conviction with minor caveats
- 0.55-0.70: Moderate conviction, proceed with caution
- 0.40-0.55: Low conviction, likely HOLD unless specific catalyst
- <0.40: Very weak signal, default to HOLD

Entry price rules (CRITICAL):
- The "Current/Last Price" in the TECHNICAL ANALYSIS section is the live market
  price at the time of chart capture. Use it as the anchor for ALL price targets.
- If recommending BUY and the current price IS at or near a favorable entry
  zone (e.g. near support, pullback within uptrend), set entry_price at or
  very close to the current price — this is an actionable NOW entry.
- If recommending BUY but the current price is NOT at a favorable entry (e.g.
  extended from support, mid-range), set entry_price at the nearest realistic
  pullback level the stock is likely to retrace to, and note in warnings that
  a limit order is required and the stock needs to pull back.
- NEVER set an entry_price the stock has already traded through and is unlikely
  to revisit in the near term. The user cannot enter at a price that's behind
  the market.
- For SELL recommendations, entry_price represents the short entry or exit
  level — same anchoring logic applies.

Risk management rules:
- Position sizes should respect the provided risk parameters
- Always set stop_loss and take_profit when recommending BUY
- risk_reward_ratio = (take_profit - entry) / (entry - stop_loss)
- Reduce position_size_pct when confidence is low
- Flag warnings for any unusual risks (earnings approaching, low liquidity, etc.)
"""


# ---------------------------------------------------------------------------
# Builder Functions
# ---------------------------------------------------------------------------


def _format_data_availability(
    tickers: list[str],
    screening: ScreeningResult | None,
    charts: list[ChartAnalysis],
    sentiments: list[SentimentAnalysis],
) -> str:
    """Build a DATA AVAILABILITY section listing present/missing data per ticker."""
    chart_tickers = {c.ticker for c in charts}
    sentiment_tickers = {s.ticker for s in sentiments}

    lines = ["--- DATA AVAILABILITY ---"]
    lines.append(f"Screening data: {'AVAILABLE' if screening else 'MISSING'}")

    chart_available = [t for t in tickers if t in chart_tickers]
    chart_missing = [t for t in tickers if t not in chart_tickers]
    if chart_available:
        lines.append(f"Chart analysis: AVAILABLE for {', '.join(chart_available)}")
    if chart_missing:
        lines.append(f"Chart analysis: MISSING for {', '.join(chart_missing)}")

    sent_available = [t for t in tickers if t in sentiment_tickers]
    sent_missing = [t for t in tickers if t not in sentiment_tickers]
    if sent_available:
        lines.append(f"News sentiment: AVAILABLE for {', '.join(sent_available)}")
    if sent_missing:
        lines.append(f"News sentiment: MISSING for {', '.join(sent_missing)}")

    lines.append("Adjust your confidence downward for tickers with missing data sources.")
    lines.append("--- END DATA AVAILABILITY ---")
    return "\n".join(lines)


def _format_screening_data(screening: ScreeningResult | None, tickers: list[str]) -> str:
    """Format Perplexity screening results for GPT prompts."""
    if not screening:
        return "No screening data available."

    ticker_map = {t.ticker: t for t in screening.tickers}
    parts: list[str] = []
    for ticker in tickers:
        fd = ticker_map.get(ticker)
        if not fd:
            parts.append(f"\n### {ticker}\nNo fundamental data available.")
            continue

        lines = [f"\n### {fd.ticker} — {fd.company_name}"]
        if fd.sector:
            lines.append(f"Sector: {fd.sector}")
        if fd.asset_type != "stock":
            lines.append(f"Asset type: {fd.asset_type}")
        if fd.market_cap:
            lines.append(f"Market cap: {fd.market_cap}")
        if fd.pe_ratio is not None:
            lines.append(f"P/E ratio: {fd.pe_ratio}")
        if fd.revenue_growth:
            lines.append(f"Revenue growth: {fd.revenue_growth}")
        if fd.free_cash_flow:
            lines.append(f"Free cash flow: {fd.free_cash_flow}")
        if fd.key_highlights:
            lines.append("Key highlights: " + "; ".join(fd.key_highlights))
        if fd.risk_factors:
            lines.append("Risk factors: " + "; ".join(fd.risk_factors))
        parts.append("\n".join(lines))

    return "\n".join(parts)


def _format_chart_data(charts: list[ChartAnalysis], tickers: list[str]) -> str:
    """Format Claude chart analysis results for GPT prompts."""
    if not charts:
        return "No chart analysis data available."

    chart_map = {c.ticker: c for c in charts}
    parts: list[str] = []
    for ticker in tickers:
        ca = chart_map.get(ticker)
        if not ca:
            parts.append(f"\n### {ticker}\nNo chart analysis available.")
            continue

        lines = [
            f"\n### {ca.ticker} ({ca.timeframe} timeframe)",
        ]
        if ca.current_price is not None:
            lines.append(f"**Current/Last Price: ${ca.current_price:.2f}**")
        lines.extend(
            [
                f"Trend: {ca.trend_direction} ({ca.trend_strength})",
                f"Overall bias: {ca.overall_bias} | Confidence: {ca.confidence}",
            ]
        )
        if ca.key_levels:
            level_strs = [
                f"  ${lv.price:.2f} ({lv.level_type}, {lv.strength})" for lv in ca.key_levels
            ]
            lines.append("Key levels:\n" + "\n".join(level_strs))
        if ca.patterns_detected:
            lines.append(f"Patterns: {', '.join(ca.patterns_detected)}")
        if ca.indicator_readings:
            ind_strs = [
                f"  {ir.indicator}: {ir.value} ({ir.signal})" for ir in ca.indicator_readings
            ]
            lines.append("Indicators:\n" + "\n".join(ind_strs))
        if ca.volume_analysis:
            lines.append(f"Volume: {ca.volume_analysis}")
        lines.append(f"Summary: {ca.summary}")
        parts.append("\n".join(lines))

    return "\n".join(parts)


def _format_sentiment_data(sentiments: list[SentimentAnalysis], tickers: list[str]) -> str:
    """Format Gemini sentiment analysis results for GPT prompts."""
    if not sentiments:
        return "No news sentiment data available."

    sent_map = {s.ticker: s for s in sentiments}
    parts: list[str] = []
    for ticker in tickers:
        sa = sent_map.get(ticker)
        if not sa:
            parts.append(f"\n### {ticker}\nNo sentiment data available.")
            continue

        lines = [
            f"\n### {sa.ticker}",
            f"Sentiment: {sa.sentiment_score:+.2f} ({sa.sentiment_label})",
        ]
        if sa.key_catalysts:
            catalyst_strs = [
                f"  [{c.impact.upper()}] {c.headline} ({c.significance})"
                for c in sa.key_catalysts[:5]
            ]
            lines.append("Key catalysts:\n" + "\n".join(catalyst_strs))
        if sa.sector_sentiment:
            lines.append(f"Sector sentiment: {sa.sector_sentiment}")
        if sa.summary:
            lines.append(f"Summary: {sa.summary}")
        parts.append("\n".join(lines))

    return "\n".join(parts)


def build_bull_prompt(
    tickers: list[str],
    screening: ScreeningResult | None,
    charts: list[ChartAnalysis],
    sentiments: list[SentimentAnalysis],
    config: StrategyConfig,
) -> str:
    """Build the user prompt for the bull analyst.

    Args:
        tickers: List of ticker symbols to analyze.
        screening: Perplexity screening result (or None if failed).
        charts: List of ChartAnalysis from Claude (may be empty).
        sentiments: List of SentimentAnalysis from Gemini (may be empty).
        config: Strategy configuration with trading style.

    Returns:
        Formatted user prompt string.
    """
    parts = [
        f"Analyze the following {len(tickers)} tickers and build your bull case: "
        f"{', '.join(tickers)}",
    ]

    if config.trading_style:
        parts.append(f"\nTrading context: {config.trading_style}")

    parts.append(f"\n{_format_data_availability(tickers, screening, charts, sentiments)}")
    parts.append(f"\n## FUNDAMENTALS (Perplexity)\n{_format_screening_data(screening, tickers)}")
    parts.append(f"\n## TECHNICAL ANALYSIS (Claude)\n{_format_chart_data(charts, tickers)}")
    parts.append(f"\n## NEWS SENTIMENT (Gemini)\n{_format_sentiment_data(sentiments, tickers)}")
    parts.append("\nReturn your bull case as JSON matching the schema in your instructions.")

    return "\n".join(parts)


def build_bear_prompt(
    tickers: list[str],
    screening: ScreeningResult | None,
    charts: list[ChartAnalysis],
    sentiments: list[SentimentAnalysis],
    config: StrategyConfig,
) -> str:
    """Build the user prompt for the bear analyst.

    Args:
        tickers: List of ticker symbols to analyze.
        screening: Perplexity screening result (or None if failed).
        charts: List of ChartAnalysis from Claude (may be empty).
        sentiments: List of SentimentAnalysis from Gemini (may be empty).
        config: Strategy configuration with trading style.

    Returns:
        Formatted user prompt string.
    """
    parts = [
        f"Analyze the following {len(tickers)} tickers and build your bear case: "
        f"{', '.join(tickers)}",
    ]

    if config.trading_style:
        parts.append(f"\nTrading context: {config.trading_style}")

    parts.append(f"\n{_format_data_availability(tickers, screening, charts, sentiments)}")
    parts.append(f"\n## FUNDAMENTALS (Perplexity)\n{_format_screening_data(screening, tickers)}")
    parts.append(f"\n## TECHNICAL ANALYSIS (Claude)\n{_format_chart_data(charts, tickers)}")
    parts.append(f"\n## NEWS SENTIMENT (Gemini)\n{_format_sentiment_data(sentiments, tickers)}")
    parts.append("\nReturn your bear case as JSON matching the schema in your instructions.")

    return "\n".join(parts)


def build_judge_prompt(
    tickers: list[str],
    screening: ScreeningResult | None,
    charts: list[ChartAnalysis],
    sentiments: list[SentimentAnalysis],
    bull_cases: list[DebateCase] | None,
    bear_cases: list[DebateCase] | None,
    reflection_context: str,
    config: StrategyConfig,
) -> str:
    """Build the user prompt for the judge/portfolio manager.

    Args:
        tickers: List of ticker symbols to analyze.
        screening: Perplexity screening result (or None if failed).
        charts: List of ChartAnalysis from Claude (may be empty).
        sentiments: List of SentimentAnalysis from Gemini (may be empty).
        bull_cases: Bull debate cases from GPT (or None if debate disabled/failed).
        bear_cases: Bear debate cases from GPT (or None if debate disabled/failed).
        reflection_context: Historical performance injection prompt (may be empty).
        config: Strategy configuration with risk params.

    Returns:
        Formatted user prompt string.
    """
    rp = config.risk_params
    parts = [
        f"Produce final recommendations for: {', '.join(tickers)}",
        "\n## RISK PARAMETERS",
        f"- Max position size: {rp.max_position_pct}% of portfolio",
        f"- Minimum risk/reward ratio: {rp.min_risk_reward}",
        f"- Max portfolio risk: {rp.max_portfolio_risk_pct}%",
    ]

    if config.trading_style:
        parts.append(f"- Trading style: {config.trading_style}")

    if reflection_context:
        parts.append(f"\n## HISTORICAL PERFORMANCE CONTEXT\n{reflection_context}")

    parts.append(f"\n{_format_data_availability(tickers, screening, charts, sentiments)}")
    parts.append(f"\n## FUNDAMENTALS (Perplexity)\n{_format_screening_data(screening, tickers)}")
    parts.append(f"\n## TECHNICAL ANALYSIS (Claude)\n{_format_chart_data(charts, tickers)}")
    parts.append(f"\n## NEWS SENTIMENT (Gemini)\n{_format_sentiment_data(sentiments, tickers)}")

    if bull_cases:
        bull_map = {bc.ticker: bc for bc in bull_cases}
        bull_parts: list[str] = []
        for ticker in tickers:
            bc = bull_map.get(ticker)
            if bc:
                args = "\n".join(f"  - {a}" for a in bc.key_arguments)
                bull_parts.append(
                    f"\n### {ticker} (confidence: {bc.confidence:.2f})\n"
                    f"Arguments:\n{args}\n"
                    f"Strongest signal: {bc.strongest_signal}\n"
                    f"Weakest counter: {bc.weakest_counter}"
                )
        if bull_parts:
            parts.append(f"\n## BULL CASE ARGUMENTS\n{''.join(bull_parts)}")
    else:
        parts.append(
            "\n## BULL CASE ARGUMENTS\nNo debate was conducted. "
            "Perform your own internal bull analysis."
        )

    if bear_cases:
        bear_map = {bc.ticker: bc for bc in bear_cases}
        bear_parts: list[str] = []
        for ticker in tickers:
            bc = bear_map.get(ticker)
            if bc:
                args = "\n".join(f"  - {a}" for a in bc.key_arguments)
                bear_parts.append(
                    f"\n### {ticker} (confidence: {bc.confidence:.2f})\n"
                    f"Arguments:\n{args}\n"
                    f"Strongest signal: {bc.strongest_signal}\n"
                    f"Weakest counter: {bc.weakest_counter}"
                )
        if bear_parts:
            parts.append(f"\n## BEAR CASE ARGUMENTS\n{''.join(bear_parts)}")
    else:
        parts.append(
            "\n## BEAR CASE ARGUMENTS\nNo debate was conducted. "
            "Perform your own internal bear analysis."
        )

    parts.append(
        "\nWeigh all evidence and produce your final recommendations as JSON "
        "matching the schema in your instructions."
    )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Hash Functions
# ---------------------------------------------------------------------------


def get_bull_hash() -> str:
    """Return the version hash of the bull prompt."""
    return prompt_hash(BULL_SYSTEM_PROMPT)


def get_bear_hash() -> str:
    """Return the version hash of the bear prompt."""
    return prompt_hash(BEAR_SYSTEM_PROMPT)


def get_judge_hash() -> str:
    """Return the version hash of the judge prompt."""
    return prompt_hash(JUDGE_SYSTEM_PROMPT)
