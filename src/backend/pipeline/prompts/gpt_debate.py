"""GPT debate prompt templates for bull, bear, and judge roles.

Stage 4: GPT synthesizes all upstream data (Perplexity fundamentals,
Gemini news sentiment, Claude chart analysis) through a structured
bull/bear/judge debate to produce final trading recommendations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pipeline.schemas import (
    ChartAnalysis,
    DebateCase,
    NewsCatalyst,
    ScreeningResult,
    SentimentAnalysis,
    StrategyConfig,
)
from utils.hashing import prompt_hash

if TYPE_CHECKING:
    from services.fmp_service import FmpEnrichedStock

BULL_PROMPT_VERSION = "v2"
BEAR_PROMPT_VERSION = "v2"
JUDGE_PROMPT_VERSION = "v7"

_BIAS_SCORE: dict[str, int] = {
    "strongly_bullish": 2,
    "bullish": 1,
    "neutral": 0,
    "bearish": -1,
    "strongly_bearish": -2,
}

_TF_WEIGHT: dict[str, float] = {
    "W": 0.40,
    "D": 0.40,
    "4H": 0.15,
    "2H": 0.10,
    "1H": 0.05,
    "15m": 0.05,
}

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
rules, and produce final BUY/SHORT/HOLD recommendations for each ticker.

You must return ONLY valid JSON — no commentary outside the JSON structure.

Return a JSON object with this exact structure:
{
  "recommendations": [
    {
      "ticker": "<SYMBOL>",
      "action": "BUY" | "SHORT" | "HOLD",
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
- SHORT: Bear case dominates; bearish setup with favorable short risk/reward for active shorting
- HOLD: Mixed signals, insufficient conviction, or wait-for-confirmation setup

Confidence calibration:
- 0.85+: Overwhelming signal alignment across all data sources
- 0.70-0.85: Strong conviction with minor caveats
- 0.55-0.70: Moderate conviction, proceed with caution
- 0.40-0.55: Low conviction, likely HOLD unless specific catalyst
- <0.40: Very weak signal, default to HOLD

Entry price rules (CRITICAL — MANDATORY for BUY and SHORT):
- entry_price, stop_loss, and take_profit are REQUIRED (non-null) for ALL BUY
  and SHORT recommendations. NEVER return null for these fields on BUY or SHORT.
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
- For SHORT recommendations, entry_price represents the short entry level —
  same anchoring logic applies. Prefer entries near resistance.
- For HOLD recommendations, set entry_price to the price level at which you
  would convert to BUY (the trigger price). Set stop_loss and take_profit
  to null for HOLD.

Risk management rules:
- Position sizes should respect the provided risk parameters
- entry_price, stop_loss, and take_profit MUST be set (non-null) for BUY and SHORT
- risk_reward_ratio = (take_profit - entry) / (entry - stop_loss) — REQUIRED for BUY/SHORT
- Reduce position_size_pct when confidence is low
- Flag warnings for any unusual risks (earnings approaching, low liquidity, etc.)

ATR-based stop loss (PREFERRED method when ATR data is available):
- Look for the ATR indicator reading in the TECHNICAL ANALYSIS section. It will
  appear as "ATR: <numeric value> (<signal>)" in the indicators list.
- For BUY: stop_loss = entry_price - (1.5 x ATR) as a baseline. Adjust tighter
  (1.0x ATR) for scalp/intraday strategies or wider (2.0x ATR) for swing/position
  trades based on the strategy's trading style and the chart timeframe.
- For SHORT: stop_loss = entry_price + (1.5 x ATR) as a baseline, with the same
  style-based adjustments.
- ALWAYS cross-check the ATR-derived stop against key_levels from the chart
  analysis. If a strong support (for BUY) or resistance (for SHORT) level sits
  between the entry and the ATR-derived stop, prefer the structural level as it
  provides a more meaningful invalidation point.
- If multiple timeframes are available, prefer the ATR from the primary
  (longest swing) timeframe for stop placement.
- If ATR data is not present in any chart analysis, fall back to placing stops
  beyond the nearest key support/resistance level.

Weighted bias score (multi-timeframe alignment metric):
- The TECHNICAL ANALYSIS section includes a "Weighted bias score" for each
  ticker with multiple timeframes analyzed. This is a numeric summary ranging
  from -2.0 (all timeframes strongly bearish) to +2.0 (all strongly bullish).
- Scores above +1.2: strong bullish alignment — supports BUY with elevated
  confidence and full position sizing.
- Scores below -1.2: strong bearish alignment — supports SHORT with conviction.
- Scores between -0.8 and +0.8: mixed or neutral — suggests HOLD, reduced
  position sizing, or wait-for-confirmation.
- Scores between +0.8 and +1.2 or -0.8 and -1.2: moderate alignment — proceed
  with caution, use smaller position size.

Historical performance memory (when HISTORICAL PERFORMANCE section is present):
- SHORT-TERM MEMORY reflects the last 14 days. It reveals active streaks and
  temporary suppressions. Treat suppressions as strong warnings: if a pattern
  is flagged "reduce confidence by 40%", multiply your confidence by 0.6 for
  signals relying on that pattern.
- LONG-TERM MEMORY is the statistical baseline across all history. Pattern
  accuracy, sector win rates, and timeframe alignment stats represent durable
  trends. Use them to calibrate confidence and position sizing.
- When short-term and long-term conflict (e.g. a pattern has 70% long-term
  win rate but 0% in the last 2 weeks), PRIORITIZE short-term for the next
  1-2 recommendations. Recent performance better reflects current market
  conditions. Add a warning noting the conflict.
- "DO NOT FIRE" on single-TF alignment means you should default to HOLD
  unless other data sources provide overwhelming evidence.
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
    chart_counts: dict[str, list[str]] = {}
    for c in charts:
        chart_counts.setdefault(c.ticker, []).append(c.timeframe)
    sentiment_tickers = {s.ticker for s in sentiments}

    lines = ["--- DATA AVAILABILITY ---"]
    lines.append(f"Screening data: {'AVAILABLE' if screening else 'MISSING'}")

    chart_available = [t for t in tickers if t in chart_counts]
    chart_missing = [t for t in tickers if t not in chart_counts]
    if chart_available:
        detail = ", ".join(f"{t} ({'/'.join(chart_counts[t])})" for t in chart_available)
        lines.append(f"Chart analysis: AVAILABLE for {detail}")
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


def _format_single_chart(ca: ChartAnalysis) -> str:
    """Format a single ChartAnalysis into text for GPT."""
    lines = [
        f"\n#### {ca.ticker} ({ca.timeframe} timeframe)",
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
        level_strs = [f"  ${lv.price:.2f} ({lv.level_type}, {lv.strength})" for lv in ca.key_levels]
        lines.append("Key levels:\n" + "\n".join(level_strs))
    if ca.patterns_detected:
        lines.append(f"Patterns: {', '.join(ca.patterns_detected)}")
    if ca.indicator_readings:
        ind_strs = [f"  {ir.indicator}: {ir.value} ({ir.signal})" for ir in ca.indicator_readings]
        lines.append("Indicators:\n" + "\n".join(ind_strs))
    if ca.volume_analysis:
        lines.append(f"Volume: {ca.volume_analysis}")
    lines.append(f"Summary: {ca.summary}")
    return "\n".join(lines)


def _synthesize_timeframes(ticker: str, charts: list[ChartAnalysis]) -> str:
    """Generate a cross-timeframe synthesis section for GPT.

    Identifies convergence (all timeframes agree) or divergence
    (timeframes conflict) and highlights the alignment for GPT
    to factor into its confidence assessment.
    """
    biases = {ca.timeframe: ca.overall_bias for ca in charts}
    all_bullish = all("bullish" in b for b in biases.values())
    all_bearish = all("bearish" in b for b in biases.values())

    lines = [f"\n#### Multi-Timeframe Synthesis for {ticker}"]
    lines.append(f"Timeframes analyzed: {', '.join(biases.keys())}")
    lines.append(f"Bias alignment: {', '.join(f'{tf}={b}' for tf, b in biases.items())}")

    if all_bullish:
        lines.append("CONVERGENCE: All timeframes bullish — HIGH confidence signal.")
    elif all_bearish:
        lines.append("CONVERGENCE: All timeframes bearish — HIGH confidence signal.")
    else:
        lines.append("DIVERGENCE: Timeframes show mixed signals — assess carefully.")
        for tf, bias in biases.items():
            if "bullish" in bias and any("bearish" in b for b in biases.values()):
                lines.append(f"  - {tf} is {bias} while other timeframes are bearish")
            elif "bearish" in bias and any("bullish" in b for b in biases.values()):
                lines.append(f"  - {tf} is {bias} while other timeframes are bullish")

    total_weight = sum(_TF_WEIGHT.get(tf, 0.10) for tf in biases)
    if total_weight > 0:
        weighted = sum(_BIAS_SCORE.get(b, 0) * _TF_WEIGHT.get(tf, 0.10) for tf, b in biases.items())
        normalized = weighted / total_weight
        lines.append(
            f"Weighted bias score: {normalized:+.2f} (threshold: +/-1.2 to fire with conviction)"
        )

    return "\n".join(lines)


def _format_chart_data(charts: list[ChartAnalysis], tickers: list[str]) -> str:
    """Format Claude chart analysis results for GPT prompts.

    Handles multiple chart analyses per ticker (e.g. Daily + 4H) by
    grouping them under the ticker header.
    """
    if not charts:
        return "No chart analysis data available."

    chart_map: dict[str, list[ChartAnalysis]] = {}
    for c in charts:
        chart_map.setdefault(c.ticker, []).append(c)

    parts: list[str] = []
    for ticker in tickers:
        ticker_charts = chart_map.get(ticker)
        if not ticker_charts:
            parts.append(f"\n### {ticker}\nNo chart analysis available.")
            continue

        parts.append(f"\n### {ticker}")
        for ca in ticker_charts:
            parts.append(_format_single_chart(ca))

        if len(ticker_charts) > 1:
            parts.append(_synthesize_timeframes(ticker, ticker_charts))

    return "\n".join(parts)


def _format_catalyst(c: NewsCatalyst) -> str:
    """Format a single catalyst with recency when available."""
    recency = f" — {c.hours_ago}h ago" if c.hours_ago is not None else ""
    return f"  [{c.impact.upper()}] {c.headline} ({c.significance}){recency}"


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
            f"Sentiment: {sa.sentiment_score:+.2f} [{sa.sentiment_bucket}] ({sa.sentiment_label})",
        ]
        if sa.key_catalysts:
            catalyst_strs = [_format_catalyst(c) for c in sa.key_catalysts[:5]]
            lines.append("Key catalysts:\n" + "\n".join(catalyst_strs))
        sect = sa.sector_sentiment
        lines.append(f"Sector sentiment: {sect.score:+.2f} ({sect.label}) — {sect.key_driver}")
        if sa.summary:
            lines.append(f"Summary: {sa.summary}")
        parts.append("\n".join(lines))

    return "\n".join(parts)


def _format_fmp_data(
    fmp_context: dict[str, FmpEnrichedStock] | None,
    tickers: list[str],
) -> str:
    """Format structured FMP data for GPT prompts."""
    if not fmp_context:
        return "No FMP pre-screening data available."

    from pipeline.fmp_context import format_fmp_for_gpt

    return format_fmp_for_gpt(fmp_context, tickers)


def build_bull_prompt(
    tickers: list[str],
    screening: ScreeningResult | None,
    charts: list[ChartAnalysis],
    sentiments: list[SentimentAnalysis],
    config: StrategyConfig,
    fmp_context: dict[str, FmpEnrichedStock] | None = None,
) -> str:
    """Build the user prompt for the bull analyst.

    Args:
        tickers: List of ticker symbols to analyze.
        screening: Perplexity screening result (or None if failed).
        charts: List of ChartAnalysis from Claude (may be empty).
        sentiments: List of SentimentAnalysis from Gemini (may be empty).
        config: Strategy configuration with trading style.
        fmp_context: FMP enriched stock data keyed by ticker (may be None).

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
    parts.append(f"\n## QUANTITATIVE DATA (FMP)\n{_format_fmp_data(fmp_context, tickers)}")
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
    fmp_context: dict[str, FmpEnrichedStock] | None = None,
) -> str:
    """Build the user prompt for the bear analyst.

    Args:
        tickers: List of ticker symbols to analyze.
        screening: Perplexity screening result (or None if failed).
        charts: List of ChartAnalysis from Claude (may be empty).
        sentiments: List of SentimentAnalysis from Gemini (may be empty).
        config: Strategy configuration with trading style.
        fmp_context: FMP enriched stock data keyed by ticker (may be None).

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
    parts.append(f"\n## QUANTITATIVE DATA (FMP)\n{_format_fmp_data(fmp_context, tickers)}")
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
    fmp_context: dict[str, FmpEnrichedStock] | None = None,
    regime_context: str = "",
    sector_consensus: str = "",
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
        fmp_context: FMP enriched stock data keyed by ticker (may be None).
        regime_context: Pre-formatted market regime header block, or empty.
        sector_consensus: Pre-formatted sector sentiment consensus block, or empty.

    Returns:
        Formatted user prompt string.
    """
    rp = config.risk_params
    parts = [
        f"Produce final recommendations for: {', '.join(tickers)}",
    ]

    if regime_context:
        parts.append(f"\n{regime_context}")

    parts.extend(
        [
            "\n## RISK PARAMETERS",
            f"- Max position size: {rp.max_position_pct}% of portfolio",
            f"- Minimum risk/reward ratio: {rp.min_risk_reward}",
            f"- Max portfolio risk: {rp.max_portfolio_risk_pct}%",
        ]
    )

    if config.trading_style:
        parts.append(f"- Trading style: {config.trading_style}")

    if reflection_context:
        parts.append(f"\n## HISTORICAL PERFORMANCE CONTEXT\n{reflection_context}")

    parts.append(f"\n{_format_data_availability(tickers, screening, charts, sentiments)}")
    parts.append(f"\n## FUNDAMENTALS (Perplexity)\n{_format_screening_data(screening, tickers)}")
    parts.append(f"\n## QUANTITATIVE DATA (FMP)\n{_format_fmp_data(fmp_context, tickers)}")
    parts.append(f"\n## TECHNICAL ANALYSIS (Claude)\n{_format_chart_data(charts, tickers)}")
    parts.append(f"\n## NEWS SENTIMENT (Gemini)\n{_format_sentiment_data(sentiments, tickers)}")

    if sector_consensus:
        parts.append(f"\n## SECTOR SENTIMENT CONSENSUS\n{sector_consensus}")

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
