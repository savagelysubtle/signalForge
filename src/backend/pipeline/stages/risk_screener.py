"""Stage 2.5: Lightweight risk screening micro-agent between Gemini and Claude.

Pre-filters tickers based on sentiment + risk_params hard constraints before
expensive Claude chart analysis. Tickers below the threshold are demoted to
HOLD early, saving Claude API credits on structurally ineligible candidates.

Uses OpenAI (GPT-4o-mini) for fast, cheap evaluation. Falls back gracefully
if the call fails — all tickers pass through unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from openai import AsyncOpenAI

from pipeline.schemas import SentimentAnalysis, StrategyConfig
from services.keyring_service import get_api_key

if TYPE_CHECKING:
    from services.fmp_service import FmpEnrichedStock

logger = logging.getLogger(__name__)

RISK_SCREENER_MODEL = "gpt-5.4-nano"

_SYSTEM_PROMPT = """\
You are a risk management analyst. Given a list of tickers with their
sentiment data and fundamental context, evaluate each against the provided
risk constraints. Return ONLY valid JSON.

For each ticker, return:
- ticker: the ticker symbol
- risk_adjusted_score: 0.0 to 1.0 (1.0 = clearly passes risk constraints)
- pass: true/false (true if the ticker should proceed to chart analysis)
- reason: brief explanation if the ticker fails

Return a JSON object: {"results": [{"ticker": "...", "risk_adjusted_score": 0.5, "pass": true, "reason": ""}]}
"""


async def screen_risks(
    tickers: list[str],
    sentiments: list[SentimentAnalysis],
    config: StrategyConfig,
    fmp_context: dict[str, FmpEnrichedStock] | None = None,
) -> tuple[list[str], list[str], dict]:
    """Screen tickers for risk eligibility before Claude chart analysis.

    Args:
        tickers: List of ticker symbols to evaluate.
        sentiments: Gemini sentiment analyses for context.
        config: Strategy configuration with risk_params.
        fmp_context: Optional FMP data for additional context.

    Returns:
        Tuple of (passed_tickers, demoted_tickers, stage_metadata).
        Demoted tickers will skip chart analysis.
    """
    api_key = get_api_key("openai")
    if not api_key:
        logger.info("OpenAI key not configured, skipping risk screener")
        return tickers, [], {"stage": "risk_screener", "status": "skipped"}

    sentiment_map = {sa.ticker: sa for sa in sentiments}
    rp = config.risk_params

    ticker_info = []
    for ticker in tickers:
        info: dict[str, Any] = {"ticker": ticker}
        sa = sentiment_map.get(ticker)
        if sa:
            info["sentiment_score"] = sa.sentiment_score
            info["sentiment_label"] = sa.sentiment_label
            info["confidence"] = sa.confidence
        if fmp_context and ticker in fmp_context:
            stock = fmp_context[ticker]
            info["composite_score"] = stock.composite_score
            info["piotroski_score"] = stock.piotroski_score
            info["altman_z_score"] = stock.altman_z_score
            info["debt_equity"] = stock.debt_equity
        ticker_info.append(info)

    user_prompt = (
        f"Risk constraints:\n"
        f"- Minimum risk/reward ratio: {rp.min_risk_reward}\n"
        f"- Max portfolio risk: {rp.max_portfolio_risk_pct}%\n"
        f"- Trading style: {config.trading_style or 'general'}\n\n"
        f"Ticker data:\n{json.dumps(ticker_info, indent=2)}\n\n"
        f"Evaluate each ticker. Demote to fail if:\n"
        f"- Sentiment is strongly_bearish for a long-only strategy\n"
        f"- Fundamental quality is extremely poor (Altman Z < 1.8 or Piotroski < 3)\n"
        f"- The risk profile clearly violates the constraints above\n\n"
        f"Be lenient — only fail tickers with clear disqualifying factors. "
        f"When in doubt, pass them through for chart analysis."
    )

    metadata: dict[str, Any] = {
        "stage": "risk_screener",
        "model": RISK_SCREENER_MODEL,
        "tickers_evaluated": len(tickers),
    }

    start = time.perf_counter()
    try:
        client = AsyncOpenAI(api_key=api_key)
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=RISK_SCREENER_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=1000,
            ),
            timeout=15.0,
        )

        raw_text = response.choices[0].message.content or ""
        metadata["raw_response"] = raw_text
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)

        try:
            clean = raw_text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1].rsplit("```", 1)[0]
            parsed = json.loads(clean)
        except json.JSONDecodeError, IndexError:
            parsed = None
        if not parsed or not isinstance(parsed, dict):
            logger.warning("Risk screener returned unparseable response, passing all tickers")
            metadata["status"] = "parse_failed"
            return tickers, [], metadata

        results = parsed.get("results", [])
        passed: list[str] = []
        demoted: list[str] = []

        result_map = {r.get("ticker", ""): r for r in results if isinstance(r, dict)}
        for ticker in tickers:
            r = result_map.get(ticker)
            if r and not r.get("pass", True):
                demoted.append(ticker)
                logger.info(
                    "Risk screener demoted %s: %s (score=%.2f)",
                    ticker,
                    r.get("reason", ""),
                    r.get("risk_adjusted_score", 0),
                )
            else:
                passed.append(ticker)

        metadata["status"] = "success"
        metadata["passed"] = len(passed)
        metadata["demoted"] = len(demoted)
        metadata["demoted_tickers"] = demoted

        logger.info(
            "Risk screener: %d/%d tickers passed, %d demoted",
            len(passed),
            len(tickers),
            len(demoted),
        )
        return passed, demoted, metadata

    except TimeoutError:
        metadata["status"] = "timeout"
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        logger.warning("Risk screener timed out, passing all tickers")
        return tickers, [], metadata
    except Exception as exc:
        metadata["status"] = "error"
        metadata["error"] = str(exc)
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        logger.warning("Risk screener failed, passing all tickers: %s", exc)
        return tickers, [], metadata
