"""GPT debate prompt templates for bull, bear, and judge roles.

Stage 4: GPT synthesizes all upstream data (Perplexity fundamentals,
Gemini news sentiment, Claude chart analysis) through a structured
bull/bear/judge debate to produce final trading recommendations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ml.pre_gpt import format_ml_prior_for_prompt, ml_escalation_user_block
from ml.schemas import GateResult
from pipeline.schemas import (
    ChartAnalysis,
    DebateCase,
    MultiTimeframeTechnical,
    NewsCatalyst,
    RiskAssessment,
    ScreeningResult,
    SentimentAnalysis,
    StrategyConfig,
)
from utils.hashing import prompt_hash

if TYPE_CHECKING:
    from services.fmp_service import FmpEnrichedStock, FmpQuote

BULL_PROMPT_VERSION = "v7"
BEAR_PROMPT_VERSION = "v7"
JUDGE_PROMPT_VERSION = "v24"

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
You are a bullish analyst receiving three INDEPENDENT research reports on the same
ticker(s). These analysts did NOT communicate with each other. Your job is to find
the most optimistic reading across all three tracks and construct the strongest
possible bull case.

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
      "confidence_label": "<one of the allowed labels below>",
      "confidence": <float — will be auto-derived, set to 0.5 as placeholder>
    }
  ]
}

confidence_label must be EXACTLY one of these ordered labels:
  "c0_no_confidence", "c1_very_low", "c2_low", "c3_slightly_low",
  "c4_lean_low", "c5_neutral", "c6_lean_high", "c7_slightly_high",
  "c8_high", "c9_very_high", "c10_max_confidence"

Choose the label that best matches your conviction in the setup:
- c8_high or above: Very confident in this setup
- c6_lean_high to c7_slightly_high: Moderate conviction in this setup
- c5_neutral or below: Not confident in this setup

Guidelines:
- Provide at least 3 key arguments per ticker, drawing from the most bullish
  reading across ALL THREE independent tracks (fundamental, sentiment, technical)
- Be specific — cite actual indicator values, price levels, catalyst details
  from the track data. Quote numbers, not vague claims.
- When tracks disagree, find the strongest bullish evidence and argue it
- The strongest_signal should name which track it comes from and cite numbers
- Note when your bullish reading requires ignoring warnings from other tracks
- If INDEPENDENT ML PRIOR (Track D) appears: it uses only numerical TA, FMP, and
  regime - not LLM narrative. Treat it as a fourth independent signal. You may
  still argue bull if tracks A-C are strong, but explicitly acknowledge ML tension.
"""

BEAR_SYSTEM_PROMPT = """\
You are a bearish devil's advocate analyst receiving three INDEPENDENT research
reports on the same ticker(s). These analysts did NOT communicate with each other.
Your job is to find the most pessimistic reading across all three tracks and
construct the strongest possible bear case.

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
      "confidence_label": "<one of the allowed labels below>",
      "confidence": <float — will be auto-derived, set to 0.5 as placeholder>
    }
  ]
}

confidence_label must be EXACTLY one of these ordered labels:
  "c0_no_confidence", "c1_very_low", "c2_low", "c3_slightly_low",
  "c4_lean_low", "c5_neutral", "c6_lean_high", "c7_slightly_high",
  "c8_high", "c9_very_high", "c10_max_confidence"

Choose the label that best matches your conviction in the bear case:
- c8_high or above: Tracks converge bearishly with compelling risk evidence
- c6_lean_high to c7_slightly_high: Moderate bear case with some caveats
- c5_neutral or below: Weak bear case, bullish signals dominate

Guidelines:
- Provide at least 3 key arguments per ticker, drawing from the most bearish
  reading across ALL THREE independent tracks (fundamental, sentiment, technical)
- Be specific — cite actual indicator values, price levels, risk factors
  from the track data. Quote numbers, not vague claims.
- When tracks disagree, find the strongest bearish evidence and argue it
- The strongest_signal should name which track it comes from and cite numbers
- Note when your bearish reading requires ignoring bullish signals from other tracks
- If INDEPENDENT ML PRIOR (Track D) appears: it uses only numerical TA, FMP, and
  regime - not LLM narrative. Treat it as a fourth independent signal. You may
  still argue bear if tracks A-C justify risk, but explicitly acknowledge ML tension.
"""

JUDGE_SYSTEM_PROMPT = """\
You are an experienced trader evaluating three INDEPENDENT research reports
to build actionable trade plans. You think in setups, triggers, and
risk/reward — not research summaries. Your job is to identify the highest-
quality setups and deliver clear playbooks the user can execute in TradingView.

Be decisive. When the evidence supports a trade, say so with conviction. When
it doesn't, say NO_TRADE clearly and move on. Do not hedge with vague
qualifications — either you see a setup or you don't.

CRITICAL: You MUST produce EXACTLY ONE recommendation per ticker listed in the
request. Every ticker gets a recommendation — use NO_TRADE if you see no edge.
Do NOT skip any ticker.

Track disagreements provide nuance, not automatic downgrades. Weigh each track
by its relevance to the strategy type and current market context.

You must return ONLY valid JSON — no commentary outside the JSON structure.

Return a JSON object with this exact structure:
{
  "recommendations": [
    {
      "ticker": "<SYMBOL>",
      "action": "BUY" | "SHORT" | "HOLD" | "NO_TRADE" | "WATCH",
      "confidence_label": "<one of the allowed labels below>",
      "confidence": <float — auto-derived from label, set to 0.5 as placeholder>,
      "llm_conviction": "low" | "medium" | "high",
      "setup_type": "<setup archetype label, e.g. 'vwap_reclaim_long', 'ema_pullback_continuation', 'breakout_retest'>",
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
        "confidence_label": "<label>",
        "confidence": 0.5
      },
      "bear_case": {
        "ticker": "<SYMBOL>",
        "stance": "bear",
        "key_arguments": ["..."],
        "strongest_signal": "...",
        "weakest_counter": "...",
        "confidence_label": "<label>",
        "confidence": 0.5
      },
      "judge_reasoning": "<3-5 sentence setup playbook: (1) name the setup and why this ticker fits it, (2) list the specific triggers/levels to monitor, (3) state the upgrade or invalidation path>",
      "key_factors": ["<monitorable condition with threshold, e.g. 'RSI crosses above 55'>", ...],
      "warnings": ["<risk warning 1>", ...],
      "track_agreement": {
        "perplexity_direction": "bullish" | "bearish" | "neutral",
        "gemini_direction": "bullish" | "bearish" | "neutral",
        "claude_direction": "bullish" | "bearish" | "neutral",
        "agreement_score": <float from 0.0 to 1.0>,
        "conflicts": ["<conflict description 1>", ...]
      },
      "confidence_adjustment": "<why confidence was raised or lowered>",
      "entry_trigger": "<how to enter: 'market', 'limit', 'breakout', 'pullback', or custom>",
      "scaling_plan": "<position scaling instructions, e.g. '50% now, add 50% on pullback to $187', or null>",
      "invalidation_conditions": ["<condition that voids this signal before entry>", ...],
      "entry_valid_window": "<how long this entry signal remains actionable, e.g. '1-2 hours', '1 trading day', '2-3 trading days'>"
    }
  ]
}

entry_valid_window guidance:
- This tells the user how long after receiving this signal the entry price is still valid.
- Scalp / intraday setups (15m, 1H charts): "1-2 hours" or "rest of session"
- Swing setups (4H, D charts): "1-2 trading days"
- Position / trend setups (D, W charts): "3-5 trading days"
- If price is extended and a pullback entry is required: "valid on pullback to $X — no time limit but may not trigger"
- Be specific. The user needs to know whether to act now or set an alert.

entry_trigger guidance (REQUIRED for BUY, SHORT, and WATCH):
- "market": enter at current price immediately (price is at or near ideal entry)
- "limit": set a limit order at entry_price (price is away from ideal entry)
- "breakout": enter when price breaks above/below a key level (specify in scaling_plan)
- "pullback": wait for a retracement to a specific level before entering
- For WATCH: the trigger that would convert this to an actionable trade
- For NO_TRADE / HOLD: null

scaling_plan guidance:
- How to build the position over time. Examples:
  "Enter full position at market" (simple)
  "50% at current price, add 50% on pullback to $187" (scaling in)
  "25% on breakout above $195, add 75% on successful retest" (confirmation scaling)
- For NO_TRADE: null
- For WATCH: the position plan to execute IF the trigger fires

invalidation_conditions guidance (REQUIRED for BUY, SHORT, and WATCH):
- What conditions would make this trade idea invalid BEFORE entry.
- At minimum include a price level: "Price drops below $X before entry"
- Include time-based: "Signal not triggered within entry_valid_window"
- Include event-based when relevant: "Earnings report changes fundamentals"
- For WATCH: what would kill the developing setup entirely
- For NO_TRADE: empty array []

VERDICT REQUIREMENTS — judge_reasoning MUST cover all four elements:
1. SETUP THESIS: Name the setup archetype and explain why this ticker fits it,
   citing specific data (e.g. "BB squeeze breakout: weekly trend bullish, daily
   BBands contracting, orderly pullback on declining volume to EMA-20 support")
2. MONITORING PLAN: List 2-3 specific, measurable triggers the user should
   watch for in TradingView (e.g. "Watch for price to break $9.43 with volume
   >1.5x avg, RSI to clear 55, and ADX to cross above 25")
3. TRACK SYNTHESIS: Which track(s) drove your conviction and what the key
   tension was — keep this brief, one sentence max
4. UPGRADE/DOWNGRADE PATH: For WATCH — what converts it to BUY (be specific).
   For BUY — what would invalidate before entry. For NO_TRADE — what would
   need to change for this to become watchable

The user reads judge_reasoning as a SETUP PLAYBOOK, not a legal brief. Lead
with the trade thesis and what to watch for, not reasons to avoid the trade.
Frame gaps as "what needs to happen" not "what is missing."

Decision framework:
- BUY: Bull case outweighs bear case. Prefer R:R >= 2:1 but do not auto-downgrade
  to WATCH if R:R is 1.5:1+ and track agreement is high (agreement_score >= 0.7).
  Flag lower R:R as a risk factor and reduce position_size_pct instead.
- SHORT: Bear case outweighs bull case with favorable short setup. Same R:R
  flexibility as BUY when track agreement is high.
- NO_TRADE: Tracks fundamentally disagree on direction with no resolution
- WATCH: Setup is developing but needs a specific trigger. You MUST provide:
  setup_type (the specific setup archetype, e.g. "vwap_reclaim_long", "ema_pullback_continuation"),
  entry_price (trigger level), entry_trigger (the exact event or price condition,
  e.g. "Break above $184.50 with volume > 1.5x average"),
  invalidation_conditions (what cancels the setup entirely),
  entry_valid_window (when the setup expires, e.g. "next 2 trading sessions").
  judge_reasoning MUST describe the developing setup as a playbook: name the
  setup, explain why this ticker fits it, then list the specific conditions
  that would convert this WATCH to a BUY/SHORT. Frame as "what to watch for"
  not "what is missing." Example: "BB squeeze breakout developing — weekly
  trend bullish, daily BBands contracting. Upgrades to BUY on a volume-
  confirmed break above $9.43 with RSI > 55 and ADX > 25."
  key_factors MUST be a monitoring checklist of specific, measurable conditions
  the user can track in TradingView. Each item should have a concrete threshold:
    GOOD: "Price breaks above $9.43 on volume > 1.5x 20-day average"
    GOOD: "RSI crosses above 55 on daily timeframe"
    GOOD: "ADX rises above 25 confirming trend strength"
    BAD:  "Volume improves" (no threshold)
    BAD:  "Momentum picks up" (not measurable)
    BAD:  "Sentiment improves" (not chartable)
  Include at minimum: one price-level trigger, one indicator trigger, and one
  volume or momentum trigger.
  A WATCH is a developing setup with a clearly defined path to entry. If you
  cannot explain what you are waiting for with a specific trigger, level, and
  invalidation, output NO_TRADE instead.
  WATCH is NOT a trash bin — it means "I see a trade forming, here is exactly
  what to look for."

AFFIRMATIVE BUY/SHORT MANDATE:
When all three tracks agree directionally (agreement_score >= 0.7), Claude's
technical assessment is bullish/bearish, and the FMP composite score is >= 70
OR no FMP data is available, you MUST issue BUY/SHORT unless you can name a
specific invalidation that applies NOW (not "might happen"). Converting a
high-agreement setup to WATCH requires a concrete blocker — not vague
uncertainty, but a named risk (e.g., earnings in 2 days, broken structure).

CRITICAL — BUY/SHORT signals are CONDITIONAL, not immediate:
Every BUY or SHORT must specify a tactical entry plan with:
  1. Entry trigger: the price action condition (e.g., "wait for pullback to
     $142 support zone and reversal candle" or "short on rejection at $185
     resistance with bearish engulfing")
  2. Entry price zone: specific level or range, not "current price" unless
     price is already at the ideal entry level (support for BUY, resistance
     for SHORT)
  3. Invalidation level: where the setup fails (stop loss)
  4. Target level(s): where to take profit

The purpose is NOT to say "buy now at market" — it is to say "buy THIS stock
at THIS price WHEN this condition triggers." The user trades manually in
TradingView and needs a setup to wait for, not an instruction to chase. A BUY
signal that says "enter at current price" without a pullback/trigger condition
is only valid when price is at or near the ideal entry zone.

INDEPENDENT ML PRIOR (Track D) — when present:
- This is a statistical model on TA/FMP/regime only (no LLM text). Consider it
  as additional evidence alongside Tracks A-C. Strong ML agreement with your
  thesis reinforces conviction. ML disagreement warrants acknowledgment but is
  not an automatic downgrade.
- Name ML explicitly in confidence_adjustment when it influenced your verdict.

For track_agreement: assess each upstream analysis (Perplexity fundamentals,
Gemini sentiment, Claude technicals) and classify its directional lean as
"bullish", "bearish", or "neutral". The agreement_score should reflect how
aligned the three tracks are (1.0 = all same direction, 0.5 = 2/3 agree,
0.0 = all disagree). List specific conflicts in the conflicts array.

confidence_adjustment must explain WHY you raised or lowered confidence from
what the raw signal strength would suggest. Reference track agreement,
risk flags, or historical patterns as justification. You MUST name which
track(s) drove the adjustment.

RISK FLAGS: When RISK ASSESSMENT data is present, risk_approved=false means the
deterministic risk screener flagged this ticker as high-risk. You MAY override
this if the qualitative evidence is compelling, but you MUST acknowledge the
flag and explain your reasoning.

confidence_label must be EXACTLY one of these ordered labels:
  "c0_no_confidence", "c1_very_low", "c2_low", "c3_slightly_low",
  "c4_lean_low", "c5_neutral", "c6_lean_high", "c7_slightly_high",
  "c8_high", "c9_very_high", "c10_max_confidence"

The backend maps these labels to numeric values deterministically — you do NOT
choose a float. The final probability is computed by the backend using regime
priors, evidence boosters, and ML agreement. Focus on picking the label that
best matches your qualitative conviction.

llm_conviction guidance (DIRECTIONAL EDGE strength, separate from confidence):
- "high": strong directional edge, textbook setup, ready or nearly ready
- "medium": moderate directional edge, some conditions not yet met
- "low": weak or unclear directional edge

confidence_label = ANALYTICAL CERTAINTY in your assessment. This measures how
sure you are about your analysis, NOT whether the trade is ready to execute.
Confidence is INDEPENDENT of the action type. Examples:
- BUY at c8_high: "I'm very confident this is a strong setup"
- BUY at c4_lean_low: "This is technically actionable but I'm uncertain"
- WATCH at c8_high: "I'm very confident this setup is developing and will trigger"
- WATCH at c3_slightly_low: "I see something forming but it's unclear"
- NO_TRADE at c9_very_high: "I'm very confident there is no setup here"
- NO_TRADE at c2_low: "Unclear situation, defaulting to no trade"
A high-confidence WATCH is perfectly valid — it means you are certain about the
developing setup, not that it is ready to trade now.

setup_type: Label each recommendation with a descriptive setup archetype string
(e.g. "vwap_reclaim_long", "ema_pullback_continuation", "breakout_retest",
"gap_fill_short", "range_bound_no_trade"). Use the strategy's allowed archetypes
when available. For NO_TRADE, use a descriptive label like "no_setup_identified".

Entry price rules (CRITICAL — MANDATORY for BUY and SHORT):
- entry_price, stop_loss, and take_profit are REQUIRED (non-null) for ALL BUY
  and SHORT recommendations. NEVER return null for these fields on BUY or SHORT.
- Target R:R >= 2:1. If R:R is between 1.5:1 and 2:1 but track agreement is high
  (agreement_score >= 0.7), the trade is still actionable — reduce position size
  and flag the lower R:R in warnings. Only use WATCH if R:R < 1.5:1 or there is
  a genuine technical reason to wait.
- Use the live market price from LIVE MARKET DATA as the anchor for price levels.
- If recommending BUY and price is at or near support, set entry_price at or
  close to current price — this is an actionable NOW entry.
- If recommending BUY but price is extended from support, set entry_price at
  the nearest realistic pullback level and note a limit order is required.
- For SHORT: entry_price near resistance, same anchoring logic.
- For HOLD: entry_price = trigger price to convert to BUY. stop/take = null.
- For WATCH: entry_price = the trigger level to monitor. stop_loss and
  take_profit = null. position_size_pct = 0.

ATR-based stop loss (PREFERRED method when ATR data is available):
- Use ATR from the RAW NUMERICAL DATA section.
- For BUY: stop_loss = entry_price - (1.5 x ATR). Adjust tighter (1.0x) for
  scalp/intraday or wider (2.0x) for swing/position.
- For SHORT: stop_loss = entry_price + (1.5 x ATR), same adjustments.
- Cross-check the ATR-derived stop against key levels from Claude's analysis.
  If a structural support/resistance sits between entry and ATR stop, prefer
  the structural level.
- If ATR is not available, fall back to nearest key support/resistance.

Weighted bias score (multi-timeframe alignment metric):
- The RAW NUMERICAL DATA section may include a multi-timeframe alignment status.
- Full alignment across timeframes supports full position sizing.
- Mixed alignment → consider reduced position sizing.

Historical performance memory (when HISTORICAL PERFORMANCE section is present):
- SHORT-TERM MEMORY (last 14 days): active streaks, temporary suppressions.
  Treat suppressions as cautionary context — factor them in proportionally.
- LONG-TERM MEMORY: statistical baseline. Use for calibration.
- When short-term and long-term conflict, note the discrepancy as a warning.

Risk management rules:
- Position sizes should respect the provided risk parameters
- entry_price, stop_loss, and take_profit MUST be set (non-null) for BUY and SHORT
- risk_reward_ratio = (take_profit - entry) / (entry - stop_loss) — REQUIRED for BUY/SHORT
- Target R:R >= 2:1. If R:R is 1.5:1 to 2:1 with high track agreement, reduce
  position size and flag in warnings — do NOT auto-downgrade to WATCH.
- Flag warnings for any unusual risks (earnings, low liquidity, etc.)

The output schema is enforced by the API — follow it exactly. Focus on quality
of analysis, not formatting.
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

    if screening.screening_summary:
        parts.append(f"**Screening Overview:** {screening.screening_summary}\n")

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
    """Format a single ChartAnalysis / TechnicalAssessment into text for GPT."""
    lines = [
        f"\n#### {ca.ticker} ({ca.timeframe} timeframe)",
    ]
    if ca.current_price is not None:
        lines.append(f"**Current/Last Price: ${ca.current_price:.2f}**")

    confidence_str = (
        f"{ca.confidence:.0%}" if isinstance(ca.confidence, float) else str(ca.confidence)
    )
    lines.extend(
        [
            f"Trend: {ca.trend_direction} ({ca.trend_strength})",
            f"Overall bias: {ca.overall_bias} | Confidence: {confidence_str}",
        ]
    )

    if ca.ema_assessment:
        lines.append(f"EMA assessment: {ca.ema_assessment}")
    if ca.momentum_assessment:
        lines.append(f"Momentum: {ca.momentum_assessment}")
    if ca.volume_assessment:
        lines.append(f"Volume assessment: {ca.volume_assessment}")
    if ca.trend_assessment:
        lines.append(f"Trend assessment: {ca.trend_assessment}")

    if ca.nearest_support is not None or ca.nearest_resistance is not None:
        level_parts: list[str] = []
        if ca.nearest_support is not None:
            level_parts.append(f"Support: ${ca.nearest_support:.2f}")
        if ca.nearest_resistance is not None:
            level_parts.append(f"Resistance: ${ca.nearest_resistance:.2f}")
        lines.append(f"Nearest levels: {' | '.join(level_parts)}")
    if ca.suggested_stop_zone:
        lines.append(f"Suggested stop zone: {ca.suggested_stop_zone}")

    if not ca.chart_confirms_data:
        lines.append("⚠ CHART DISCREPANCY — chart does NOT confirm numerical data")
        for disc in ca.chart_discrepancies:
            lines.append(f"  - {disc}")

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
    if ca.summary:
        lines.append(f"Summary: {ca.summary}")

    if ca.timeframe_alignment_note:
        lines.append(f"Timeframe alignment: {ca.timeframe_alignment_note}")
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
            (
                f"Sentiment: {sa.sentiment_score:+.2f} [{sa.sentiment_bucket}] "
                f"({sa.sentiment_label}) (confidence: {sa.confidence:.2f})"
            ),
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


def _format_live_quotes(
    live_quotes: dict[str, FmpQuote] | None,
    tickers: list[str],
) -> str:
    """Format real-time FMP quote data for GPT prompts.

    Args:
        live_quotes: Mapping of symbol → FmpQuote, or None.
        tickers: List of tickers being analyzed.

    Returns:
        Formatted live market data block, or a note that data is unavailable.
    """
    if not live_quotes:
        return "No real-time quote data available."

    lines: list[str] = []
    for ticker in tickers:
        quote = live_quotes.get(ticker)
        if not quote or quote.price is None:
            continue
        parts = [f"**{ticker}**: ${quote.price:.2f}"]
        if quote.changesPercentage is not None:
            parts.append(f"({quote.changesPercentage:+.2f}%)")
        if quote.dayLow is not None and quote.dayHigh is not None:
            parts.append(f"Range: ${quote.dayLow:.2f}-${quote.dayHigh:.2f}")
        if quote.open is not None:
            parts.append(f"Open: ${quote.open:.2f}")
        if quote.volume is not None and quote.avgVolume:
            rvol = quote.volume / quote.avgVolume
            parts.append(f"Vol: {quote.volume:,} (RVOL: {rvol:.1f}x)")
        lines.append(" | ".join(parts))

    return "\n".join(lines) if lines else "No real-time quote data available."


def _format_fmp_data(
    fmp_context: dict[str, FmpEnrichedStock] | None,
    tickers: list[str],
) -> str:
    """Format structured FMP data for GPT prompts."""
    if not fmp_context:
        return "No FMP pre-screening data available."

    from pipeline.fmp_context import format_fmp_for_gpt

    return format_fmp_for_gpt(fmp_context, tickers)


# ---------------------------------------------------------------------------
# Formatters (track-aware)
# ---------------------------------------------------------------------------


def _format_numerical_ta(
    ta_snapshots: list[MultiTimeframeTechnical],
    tickers: list[str],
) -> str:
    """Format raw numerical TA data for GPT to verify Claude's interpretation.

    GPT receives both Claude's TechnicalAssessment AND the raw numbers, so it
    can sanity-check Claude's conclusions independently.

    Args:
        ta_snapshots: Numerical TA results from Phase 1.
        tickers: Ordered ticker list for consistent output.

    Returns:
        Formatted text block with raw indicator values per ticker.
    """
    if not ta_snapshots:
        return "No numerical TA data available."

    from pipeline.stages.numerical_ta import format_ta_for_prompt

    ta_map = {t.ticker: t for t in ta_snapshots}
    parts: list[str] = []

    for ticker in tickers:
        snapshot = ta_map.get(ticker)
        if not snapshot:
            parts.append(f"\n### {ticker}\nNo numerical TA data available.")
            continue

        parts.append(f"\n### {ticker}")
        parts.append(format_ta_for_prompt(snapshot))

    return "\n".join(parts)


def _format_risk_assessments(
    risk_assessments: list[RiskAssessment],
    tickers: list[str],
) -> str:
    """Format deterministic risk assessments for GPT.

    Args:
        risk_assessments: Per-ticker risk flags from the post-filter.
        tickers: Ordered ticker list.

    Returns:
        Formatted risk flag text block.
    """
    if not risk_assessments:
        return "No risk assessment data available."

    risk_map = {r.ticker: r for r in risk_assessments}
    parts: list[str] = []

    for ticker in tickers:
        ra = risk_map.get(ticker)
        if not ra:
            parts.append(f"- **{ticker}**: No risk data")
            continue

        status = "APPROVED" if ra.risk_approved else "FLAGGED — HIGH RISK"
        line = f"- **{ticker}**: {status} (risk score: {ra.risk_score:.2f})"
        if ra.risk_flags:
            flags = "; ".join(ra.risk_flags)
            line += f"\n  Flags: {flags}"
        parts.append(line)

    return "\n".join(parts)


def _format_ml_injection_for_gpt(
    pre_gpt_ml: dict[str, GateResult] | None,
    ml_escalation: bool,
) -> str:
    """Append independent ML prior (Track D) and optional escalation copy."""
    if not pre_gpt_ml:
        return ""
    parts = [f"\n{format_ml_prior_for_prompt(pre_gpt_ml)}"]
    if ml_escalation:
        parts.append(ml_escalation_user_block())
    return "".join(parts)


# ---------------------------------------------------------------------------
# Builder Functions (track-aware parallel architecture)
# ---------------------------------------------------------------------------


def _build_debate_side_prompt(
    side: str,
    tickers: list[str],
    screening: ScreeningResult | None,
    charts: list[ChartAnalysis],
    sentiments: list[SentimentAnalysis],
    config: StrategyConfig,
    ta_snapshots: list[MultiTimeframeTechnical] | None = None,
    risk_assessments: list[RiskAssessment] | None = None,
    fmp_context: dict[str, FmpEnrichedStock] | None = None,
    live_quotes: dict[str, FmpQuote] | None = None,
    pre_gpt_ml: dict[str, GateResult] | None = None,
    ml_escalation: bool = False,
) -> str:
    """Build bull or bear analyst user prompt with shared track-aware framing.

    Args:
        side: ``"bull"`` or ``"bear"`` — selects optimistic vs pessimistic framing.
        tickers: List of ticker symbols to analyze.
        screening: Perplexity screening result (Track A).
        charts: ChartAnalysis from Claude (Track C).
        sentiments: SentimentAnalysis from Gemini (Track B).
        config: Strategy configuration.
        ta_snapshots: Raw numerical TA data for verification.
        risk_assessments: Risk flags from deterministic post-filter.
        fmp_context: FMP enriched stock data keyed by ticker.
        live_quotes: Real-time FMP quotes keyed by ticker.
        pre_gpt_ml: Per-ticker independent ML gate output before GPT.
        ml_escalation: Add deeper-reconciliation instructions (gray ML / ambiguous).

    Returns:
        Formatted user prompt string.
    """
    if side == "bull":
        reading_phrase = "MOST OPTIMISTIC"
        case_word = "bull"
    else:
        reading_phrase = "MOST PESSIMISTIC"
        case_word = "bear"

    parts = [
        f"Analyze the following {len(tickers)} tickers and build your {case_word} case "
        f"using the {reading_phrase} reading across all three tracks: "
        f"{', '.join(tickers)}",
    ]

    if config.trading_style:
        parts.append(f"\nTrading context: {config.trading_style}")

    # Active strategy contract — forces bull/bear to evaluate under this strategy
    archetypes_str = ", ".join(config.setup_archetypes) if config.setup_archetypes else "any"
    contract_lines = [
        "\n## ACTIVE STRATEGY CONTRACT",
        f"Strategy: {config.name or 'Unnamed'}",
        f"Type: {config.strategy_type or 'general'}",
        f"Style: {config.trading_style or 'unspecified'}",
        f"Setup Archetypes: {archetypes_str}",
    ]
    if config.ta_focus:
        contract_lines.append(f"TA Focus: {config.ta_focus}")
    contract_lines.extend(
        [
            "",
            "IMPORTANT: Evaluate each ticker under this specific strategy.",
            "- Only argue for setups that match the strategy's archetypes",
            "- If the ticker does not fit this strategy's playbook, acknowledge it",
        ]
    )
    parts.extend(contract_lines)

    parts.append(f"\n{_format_data_availability(tickers, screening, charts, sentiments)}")
    parts.append(f"\n## LIVE MARKET DATA (real-time)\n{_format_live_quotes(live_quotes, tickers)}")

    parts.append(
        f"\n## === TRACK A: FUNDAMENTAL ANALYSIS (Perplexity) ===\n"
        f"{_format_screening_data(screening, tickers)}"
    )
    parts.append(
        f"\n## === TRACK B: SENTIMENT ANALYSIS (Gemini) ===\n"
        f"{_format_sentiment_data(sentiments, tickers)}"
    )
    parts.append(
        f"\n## === TRACK C: TECHNICAL ANALYSIS (Claude) ===\n{_format_chart_data(charts, tickers)}"
    )

    if ta_snapshots:
        parts.append(
            f"\n## RAW NUMERICAL DATA (for verification)\n"
            f"{_format_numerical_ta(ta_snapshots, tickers)}"
        )

    if fmp_context:
        parts.append(f"\n## QUANTITATIVE DATA (FMP)\n{_format_fmp_data(fmp_context, tickers)}")

    if risk_assessments:
        parts.append(f"\n## RISK ASSESSMENT\n{_format_risk_assessments(risk_assessments, tickers)}")

    parts.append(_format_ml_injection_for_gpt(pre_gpt_ml, ml_escalation))

    parts.append(
        f"\nReturn your {case_word} case as JSON matching the schema in your instructions."
    )
    return "\n".join(parts)


def build_bull_prompt(
    tickers: list[str],
    screening: ScreeningResult | None,
    charts: list[ChartAnalysis],
    sentiments: list[SentimentAnalysis],
    config: StrategyConfig,
    ta_snapshots: list[MultiTimeframeTechnical] | None = None,
    risk_assessments: list[RiskAssessment] | None = None,
    fmp_context: dict[str, FmpEnrichedStock] | None = None,
    live_quotes: dict[str, FmpQuote] | None = None,
    pre_gpt_ml: dict[str, GateResult] | None = None,
    ml_escalation: bool = False,
) -> str:
    """Build the user prompt for the bull analyst with track-aware framing.

    Structures data as three independent tracks (A/B/C) so the bull analyst
    can draw the most optimistic reading from each.

    Args:
        tickers: List of ticker symbols to analyze.
        screening: Perplexity screening result (Track A).
        charts: ChartAnalysis from Claude (Track C).
        sentiments: SentimentAnalysis from Gemini (Track B).
        config: Strategy configuration.
        ta_snapshots: Raw numerical TA data for verification.
        risk_assessments: Risk flags from deterministic post-filter.
        fmp_context: FMP enriched stock data keyed by ticker.
        live_quotes: Real-time FMP quotes keyed by ticker.
        pre_gpt_ml: Per-ticker independent ML gate output before GPT.
        ml_escalation: Add deeper-reconciliation instructions (gray ML / ambiguous).

    Returns:
        Formatted user prompt string.
    """
    return _build_debate_side_prompt(
        "bull",
        tickers,
        screening,
        charts,
        sentiments,
        config,
        ta_snapshots=ta_snapshots,
        risk_assessments=risk_assessments,
        fmp_context=fmp_context,
        live_quotes=live_quotes,
        pre_gpt_ml=pre_gpt_ml,
        ml_escalation=ml_escalation,
    )


def build_bear_prompt(
    tickers: list[str],
    screening: ScreeningResult | None,
    charts: list[ChartAnalysis],
    sentiments: list[SentimentAnalysis],
    config: StrategyConfig,
    ta_snapshots: list[MultiTimeframeTechnical] | None = None,
    risk_assessments: list[RiskAssessment] | None = None,
    fmp_context: dict[str, FmpEnrichedStock] | None = None,
    live_quotes: dict[str, FmpQuote] | None = None,
    pre_gpt_ml: dict[str, GateResult] | None = None,
    ml_escalation: bool = False,
) -> str:
    """Build the user prompt for the bear analyst with track-aware framing.

    Structures data as three independent tracks (A/B/C) so the bear analyst
    can draw the most pessimistic reading from each.

    Args:
        tickers: List of ticker symbols to analyze.
        screening: Perplexity screening result (Track A).
        charts: ChartAnalysis from Claude (Track C).
        sentiments: SentimentAnalysis from Gemini (Track B).
        config: Strategy configuration.
        ta_snapshots: Raw numerical TA data for verification.
        risk_assessments: Risk flags from deterministic post-filter.
        fmp_context: FMP enriched stock data keyed by ticker.
        live_quotes: Real-time FMP quotes keyed by ticker.
        pre_gpt_ml: Per-ticker independent ML gate output before GPT.
        ml_escalation: Add deeper-reconciliation instructions (gray ML / ambiguous).

    Returns:
        Formatted user prompt string.
    """
    return _build_debate_side_prompt(
        "bear",
        tickers,
        screening,
        charts,
        sentiments,
        config,
        ta_snapshots=ta_snapshots,
        risk_assessments=risk_assessments,
        fmp_context=fmp_context,
        live_quotes=live_quotes,
        pre_gpt_ml=pre_gpt_ml,
        ml_escalation=ml_escalation,
    )


def build_judge_prompt(
    tickers: list[str],
    screening: ScreeningResult | None,
    charts: list[ChartAnalysis],
    sentiments: list[SentimentAnalysis],
    bull_cases: list[DebateCase] | None,
    bear_cases: list[DebateCase] | None,
    reflection_context: str,
    config: StrategyConfig,
    ta_snapshots: list[MultiTimeframeTechnical] | None = None,
    risk_assessments: list[RiskAssessment] | None = None,
    fmp_context: dict[str, FmpEnrichedStock] | None = None,
    regime_context: str = "",
    sector_consensus: str = "",
    live_quotes: dict[str, FmpQuote] | None = None,
    track_conflicts: str = "",
    pre_gpt_ml: dict[str, GateResult] | None = None,
    ml_escalation: bool = False,
) -> str:
    """Build the judge prompt with track-aware conflict resolution.

    The judge receives three clearly-labeled independent track outputs plus
    raw numerical TA data for verification. The prompt structure forces the
    judge to address track disagreements and explain which tracks it weighted.

    Args:
        tickers: List of ticker symbols to analyze.
        screening: Perplexity screening result (Track A).
        charts: ChartAnalysis from Claude (Track C).
        sentiments: SentimentAnalysis from Gemini (Track B).
        bull_cases: Bull debate cases (or None if debate disabled/failed).
        bear_cases: Bear debate cases (or None if debate disabled/failed).
        reflection_context: Historical performance injection prompt.
        config: Strategy configuration with risk params.
        ta_snapshots: Raw numerical TA data for verification.
        risk_assessments: Deterministic risk flags per ticker.
        fmp_context: FMP enriched stock data keyed by ticker.
        regime_context: Pre-formatted market regime header, or empty.
        sector_consensus: Pre-formatted sector sentiment consensus, or empty.
        live_quotes: Real-time FMP quotes keyed by ticker.
        track_conflicts: Pre-formatted directional conflict summary per ticker.
        pre_gpt_ml: Per-ticker independent ML gate output before GPT.
        ml_escalation: Add deeper-reconciliation instructions (gray ML / ambiguous).

    Returns:
        Formatted user prompt string.
    """
    rp = config.risk_params
    parts = [
        f"Produce EXACTLY {len(tickers)} recommendations, one for each ticker: "
        f"{', '.join(tickers)}",
        "",
        "You are receiving THREE INDEPENDENT analysis reports. The analysts did "
        "NOT communicate with each other. Assess all evidence on its merits.",
    ]

    # Strategy contract — grounds GPT in the active strategy
    archetypes_str = ", ".join(config.setup_archetypes) if config.setup_archetypes else "any"
    contract_lines = ["\n## ACTIVE STRATEGY CONTRACT"]
    strategy_label = config.name or "Unnamed"
    if config.strategy_type:
        strategy_label += f" ({config.strategy_type})"
    contract_lines.append(f"Strategy: {strategy_label}")
    if config.description:
        contract_lines.append(f"Description: {config.description}")
    if config.trading_style:
        contract_lines.append(f"Style: {config.trading_style}")
    contract_lines.append(f"Setup Archetypes: {archetypes_str}")
    if config.ta_focus:
        contract_lines.append(f"TA Focus: {config.ta_focus}")
    contract_lines.extend(
        [
            "",
            "Only recommend setups matching the archetypes above.",
            "Label setup_type from the allowed list. If no fit, output NO_TRADE.",
        ]
    )
    parts.extend(contract_lines)

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

    if reflection_context:
        parts.append(f"\n## HISTORICAL PERFORMANCE CONTEXT\n{reflection_context}")

    parts.append(f"\n{_format_data_availability(tickers, screening, charts, sentiments)}")
    live_block = _format_live_quotes(live_quotes, tickers)
    if live_quotes:
        parts.append(
            f"\n## LIVE MARKET DATA (real-time)\n{live_block}"
            "\nIMPORTANT: Use these LIVE prices for entry, stop-loss, and take-profit levels."
        )
    else:
        parts.append(
            "\n## LIVE MARKET DATA\nNo real-time quotes available. "
            "Derive entry, stop-loss, and take-profit from the chart analysis "
            "and numerical TA data above."
        )

    if track_conflicts:
        parts.append(
            f"\n## TRACK CONFLICT SUMMARY\n"
            f"The following directional disagreements were detected between the "
            f"independent tracks. You MUST explicitly address each conflict in "
            f"your recommendation rationale.\n{track_conflicts}"
        )

    # Three independent tracks — clearly labeled
    parts.append(
        f"\n## === TRACK A: FUNDAMENTAL ANALYSIS (Perplexity) ===\n"
        f"This analyst conducted independent fundamental research.\n"
        f"{_format_screening_data(screening, tickers)}"
    )
    parts.append(
        f"\n## === TRACK B: SENTIMENT ANALYSIS (Gemini) ===\n"
        f"This analyst conducted independent news/sentiment research.\n"
        f"{_format_sentiment_data(sentiments, tickers)}"
    )
    parts.append(
        f"\n## === TRACK C: TECHNICAL ANALYSIS (Claude) ===\n"
        f"This analyst interpreted numerical indicators and chart images.\n"
        f"{_format_chart_data(charts, tickers)}"
    )

    if ta_snapshots:
        parts.append(
            f"\n## === RAW NUMERICAL DATA (for your verification) ===\n"
            f"Use this to sanity-check Claude's technical interpretation.\n"
            f"{_format_numerical_ta(ta_snapshots, tickers)}"
        )

    if fmp_context:
        parts.append(f"\n## QUANTITATIVE DATA (FMP)\n{_format_fmp_data(fmp_context, tickers)}")

    if risk_assessments:
        parts.append(
            f"\n## RISK ASSESSMENT (deterministic pre-filter)\n"
            f"Tickers flagged here have structural risk concerns.\n"
            f"{_format_risk_assessments(risk_assessments, tickers)}"
        )

    parts.append(_format_ml_injection_for_gpt(pre_gpt_ml, ml_escalation))

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
                    f"\n### {ticker} (conviction: {bc.confidence_label})\n"
                    f"Arguments:\n{args}\n"
                    f"Strongest signal: {bc.strongest_signal}\n"
                    f"Weakest counter: {bc.weakest_counter}"
                )
        if bull_parts:
            parts.append(f"\n## BULL CASE ARGUMENTS\n{''.join(bull_parts)}")
    else:
        parts.append(
            "\n## BULL CASE ARGUMENTS\n"
            "Analyze all evidence with balanced perspective. In your bull_case output, "
            "present the strongest bullish arguments drawn from the track data above."
        )

    if bear_cases:
        bear_map = {bc.ticker: bc for bc in bear_cases}
        bear_parts: list[str] = []
        for ticker in tickers:
            bc = bear_map.get(ticker)
            if bc:
                args = "\n".join(f"  - {a}" for a in bc.key_arguments)
                bear_parts.append(
                    f"\n### {ticker} (conviction: {bc.confidence_label})\n"
                    f"Arguments:\n{args}\n"
                    f"Strongest signal: {bc.strongest_signal}\n"
                    f"Weakest counter: {bc.weakest_counter}"
                )
        if bear_parts:
            parts.append(f"\n## BEAR CASE ARGUMENTS\n{''.join(bear_parts)}")
    else:
        parts.append(
            "\n## BEAR CASE ARGUMENTS\n"
            "In your bear_case output, present the strongest risks and concerns "
            "drawn from the track data above."
        )

    parts.append(
        "\nWeigh all evidence, address track disagreements explicitly, and produce "
        "your final recommendations as JSON matching the schema in your instructions."
    )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Hash Functions
# ---------------------------------------------------------------------------


def get_bull_hash() -> str:
    """Return the version hash of the bull prompt."""
    return prompt_hash(f"{BULL_PROMPT_VERSION}\n{BULL_SYSTEM_PROMPT}")


def get_bear_hash() -> str:
    """Return the version hash of the bear prompt."""
    return prompt_hash(f"{BEAR_PROMPT_VERSION}\n{BEAR_SYSTEM_PROMPT}")


def get_judge_hash() -> str:
    """Return the version hash of the judge prompt."""
    return prompt_hash(f"{JUDGE_PROMPT_VERSION}\n{JUDGE_SYSTEM_PROMPT}")
