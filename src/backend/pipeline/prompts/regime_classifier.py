"""Regime classifier prompt for Perplexity Agent API.

Stage 0.5: Assesses current market regime via web search before the
main pipeline stages run. The output injects context into all
downstream prompts to influence screening, sentiment weighting,
and confidence thresholds.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from utils.hashing import prompt_hash

if TYPE_CHECKING:
    from pipeline.schemas import RegimeOutput

PROMPT_VERSION = "v1"

REGIME_SYSTEM_PROMPT = """\
You are a macro market analyst. Your job is to assess the current market
regime by searching for the latest data on broad market indices, volatility,
and sector rotation. Return ONLY valid JSON — no commentary outside the JSON.

Return a JSON object with this exact structure:
{
  "regime_type": "trending_bull" | "trending_bear" | "range_bound" | "high_volatility" | "risk_off" | "sector_rotation",
  "vix_estimate": "calm" | "normal" | "elevated" | "fear",
  "breadth_estimate": "strong" | "moderate" | "weak" | "deteriorating",
  "dominant_sectors": ["<sector 1>", "<sector 2>"],
  "defensive_rotation": true | false,
  "summary": "<2-3 sentence summary of current regime>",
  "implications": "<1-2 sentences: what this means for trade selection>"
}

Field definitions:

regime_type:
- trending_bull: S&P 500 in sustained uptrend, making higher highs/lows
- trending_bear: S&P 500 in sustained downtrend, making lower highs/lows
- range_bound: S&P 500 trading sideways within a defined range
- high_volatility: VIX elevated (>25), sharp intraday swings
- risk_off: Flight to safety — bonds, gold, USD strengthening vs equities
- sector_rotation: Leadership rotating between sectors without clear trend

vix_estimate:
- calm: VIX below 15
- normal: VIX 15-20
- elevated: VIX 20-30
- fear: VIX above 30

breadth_estimate (% of S&P 500 stocks above their 200-day moving average):
- strong: >60% above 200 MA
- moderate: 40-60% above 200 MA
- weak: 20-40% above 200 MA
- deteriorating: <20% above 200 MA, or declining rapidly

defensive_rotation:
- true if money is flowing INTO defensive sectors (Utilities, Healthcare,
  Consumer Staples, Gold) at the expense of growth/cyclical sectors.
- false otherwise.

dominant_sectors:
- The 2-3 sectors currently leading market performance (e.g. "Technology",
  "Energy", "Financials", "Healthcare").

implications:
- Concrete trading guidance. Examples:
  "Favour momentum breakouts. Increase position sizing for trend-aligned trades."
  "Tighten stops. Reduce position sizes. Prefer mean-reversion setups."
  "Wait for range breakout confirmation. Avoid mid-range entries."
"""


def build_regime_prompt() -> str:
    """Build the user prompt for market regime assessment.

    Returns:
        Formatted user prompt requesting current regime data.
    """
    today = date.today().isoformat()
    return (
        f"Today is {today}. Assess the current US equity market regime.\n\n"
        "Search for:\n"
        "1. S&P 500 current trend and recent price action (last 1-2 weeks)\n"
        "2. Current VIX (CBOE Volatility Index) level\n"
        "3. Market breadth — approximate % of S&P 500 stocks above their 200-day MA\n"
        "4. Sector performance — which sectors are leading and lagging\n"
        "5. Any risk-off signals (Treasury yields falling, gold rising, USD strengthening)\n\n"
        "Return your assessment as JSON matching the schema in your instructions."
    )


def format_regime_header(regime: RegimeOutput) -> str:
    """Format a regime output as a context header block for downstream prompts.

    Args:
        regime: Validated regime classification result.

    Returns:
        Formatted text block to prepend to downstream prompts.
    """
    sectors = ", ".join(regime.dominant_sectors) if regime.dominant_sectors else "N/A"
    defensive = "Yes" if regime.defensive_rotation else "No"
    return (
        "## MARKET REGIME\n"
        f"Current: {regime.regime_type.upper().replace('_', ' ')} | "
        f"VIX: {regime.vix_estimate} | "
        f"Breadth: {regime.breadth_estimate}\n"
        f"Dominant sectors: {sectors} | Defensive rotation: {defensive}\n"
        f"Implications: {regime.implications}"
    )


def get_prompt_hash() -> str:
    """Return the version hash of the current regime prompt."""
    return prompt_hash(REGIME_SYSTEM_PROMPT)
