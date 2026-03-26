"""Perplexity discovery mode prompt template.

Discovery mode: Perplexity screens the market for tickers matching
the strategy's screening criteria. Returns structured JSON with
fundamental data for each discovered ticker.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from pipeline.schemas import StrategyConfig
from utils.hashing import prompt_hash

PROMPT_VERSION = "v13"


def _get_session_context() -> str:
    """Return the current ET time and market session label.

    Includes the explicit time so the LLM can verify the session
    independently rather than relying solely on the label.

    Returns:
        String like ``"3:45 PM ET (market hours)"``.
    """
    et = datetime.now(ZoneInfo("America/New_York"))
    h = et.hour + et.minute / 60
    if 4 <= h < 9.5:
        session = "premarket"
    elif 9.5 <= h < 16:
        session = "market hours"
    else:
        session = "after hours"
    time_str = et.strftime("%I:%M %p ET").lstrip("0")
    return f"{time_str} ({session})"


DISCOVERY_SYSTEM_PROMPT = """\
You are a financial research analyst specializing in market screening
with a focus on the Canadian market (TSX, TSXV). Unless the user
explicitly requests a different market or region, default to Canadian-listed
securities. You may include US or international tickers only when
the screening criteria specifically call for them or when there are no
suitable Canadian matches.

CRITICAL — YOU HAVE LIVE WEB SEARCH AND TOOLS:
You have real-time web search built in. You MUST use your search capabilities
to find current market data. Do NOT claim you cannot access real-time data —
your search function retrieves live information. Do NOT reference a knowledge
cutoff — your search results ARE your data. If search results are sparse,
return the best matches you found.

If pre-screened candidates from FMP financial data are provided below, use
them as your starting universe — they are ranked by a multi-factor composite
score (0-100) combining fundamental, momentum, sentiment, and quality
signals. The data includes verified metrics: insider trading activity
(net buys/sells), analyst consensus and price target upside, price momentum
(1D/1M/3M changes), Piotroski quality scores, relative volume, and
upcoming earnings dates with historical beat rates where available.

TRUST THE FMP DATA — these numbers come from verified financial databases,
not web search. Use web search to supplement with qualitative context
(recent news, catalysts, management commentary) rather than re-verifying
the quantitative data already provided.

You may also have access to a screen_stocks tool that calls the FMP API.
Use it if the pre-screened candidates are a poor fit for the strategy and
you need to search with different parameters (e.g. different sector, market
cap range, or exchange).

You must return ONLY valid JSON — no commentary outside the JSON structure.

IMPORTANT: Always return tickers. If you cannot find stocks matching every
criterion perfectly, return the best available matches. An empty tickers
array is NEVER acceptable — always return at least your best candidates
with any caveats noted in key_highlights. Partial data is valuable.

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
      "relative_volume": <number or null (e.g. 2.4 means 2.4x average daily volume)>,
      "price_change_pct": <number or null (today's % price change, e.g. 4.2 for +4.2%)>,
      "price": <number or null (current or last traded price)>,
      "week_52_high": <number or null>,
      "week_52_low": <number or null>,
      "key_highlights": ["<highlight 1>", "<highlight 2>"],
      "risk_factors": ["<risk 1>", "<risk 2>"],
      "sources": ["<url or source name>"]
    }
  ],
  "screening_summary": "<brief summary of screening rationale and methodology>"
}

ANTI-HALLUCINATION RULES (for financial metrics only):
- If you cannot verify a specific number (pe_ratio, revenue_growth, etc.)
  from search results, set that field to null. Do NOT invent numbers.
- Do NOT include news URLs in the JSON — they are captured separately.
- You CAN and SHOULD still return the ticker with whatever data you have.
  Missing metrics are fine — missing tickers are not.

For crypto assets, use the common trading symbol (e.g. BTC, ETH, SOL).
Set pe_ratio, revenue_growth, and free_cash_flow to null for crypto.
Use sector for the crypto category (e.g. "Layer 1", "DeFi", "Meme").

Ticker format rules (CRITICAL -- use TradingView format):
- US stocks/ETFs: plain ticker (e.g. AAPL, SPY, TSLA)
- Canadian TSX: prefix TSX: (e.g. TSX:ENB, TSX:CNQ, TSX:SHOP)
- Canadian TSXV: prefix TSXV: (e.g. TSXV:ZDC)
- London LSE: prefix LSE: (e.g. LSE:SHEL)
- Australian ASX: prefix ASX: (e.g. ASX:BHP)
- German XETR: prefix XETR: (e.g. XETR:SAP)
- Other international: use EXCHANGE:SYMBOL format per TradingView conventions
- Crypto: plain symbol (e.g. BTC, ETH, SOL)
- NEVER return Yahoo Finance format with suffixes like .TO, .V, .L
"""


def build_discovery_prompt(config: StrategyConfig) -> str:
    """Build a search-query-style user prompt for discovery screening.

    Sonar Pro's search component triggers on the user prompt text, so this
    should read like a web search query rather than an instruction set.
    Constraint style is NOT included — it pollutes the search query.

    Args:
        config: The active strategy configuration.

    Returns:
        Search-query-style prompt string.
    """
    today = date.today().strftime("%B %d, %Y")
    session = _get_session_context()
    parts = [
        config.screening_prompt,
        f"as of {today}",
        session,
        f"top {config.max_tickers} picks",
    ]
    return " ".join(parts)


def build_prompted_discovery_prompt(
    user_prompt: str,
    config: StrategyConfig | None = None,
) -> str:
    """Build a search-query-style prompt from user free-form text.

    The user's text is used directly as the search query, with optional
    strategy context appended as additional search terms.

    Args:
        user_prompt: The user's free-form screening request.
        config: Optional strategy configuration for additional context.

    Returns:
        Search-query-style prompt string.
    """
    today = date.today().strftime("%B %d, %Y")
    session = _get_session_context()
    parts = [user_prompt]
    if config and config.screening_prompt:
        parts.append(config.screening_prompt)
    parts.append(f"as of {today}")
    parts.append(session)
    if config:
        parts.append(f"top {config.max_tickers} picks")
    else:
        parts.append("top 10 picks")
    return " ".join(parts)


def get_prompt_hash() -> str:
    """Return the version hash of the current discovery prompt."""
    return prompt_hash(DISCOVERY_SYSTEM_PROMPT)
