"""MCP tools for SignalForge pipeline operations.

These tools call the existing FastAPI backend over HTTP to trigger analysis
runs, monitor progress, and retrieve results.
"""

from __future__ import annotations

import json
from typing import Any

from mcp_server.backend.client import get_backend_client


async def run_pipeline(
    strategy_id: str | None = None,
    tickers: str | None = None,
    prompt: str | None = None,
    sector: str | None = None,
    industry: str | None = None,
    market_cap_min: int | None = None,
    market_cap_max: int | None = None,
) -> str:
    """Run the SignalForge analysis pipeline.

    Triggers a new pipeline run and returns the run_id for polling progress.
    Provide either a strategy_id, explicit tickers, or a free-form prompt.
    Use sector/industry/market_cap filters to control the FMP pre-screener.

    Args:
        strategy_id: Strategy ID to use (call list_strategies to see available).
        tickers: Comma-separated ticker symbols to analyze (e.g. "AAPL,MSFT,NVDA").
        prompt: Free-form prompt for discovery mode (e.g. "find undervalued tech stocks").
        sector: FMP sector filter (e.g. "Technology", "Healthcare", "Energy",
            "Consumer Cyclical", "Industrials", "Financial Services",
            "Basic Materials", "Communication Services", "Consumer Defensive",
            "Real Estate", "Utilities").
        industry: FMP industry filter (e.g. "Semiconductors", "Software—Application",
            "Biotechnology", "Oil & Gas E&P", "Banks—Regional").
        market_cap_min: Minimum market cap in dollars (e.g. 1000000000 for $1B).
        market_cap_max: Maximum market cap in dollars.
    """
    client = get_backend_client()
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()] if tickers else None

    overrides: dict[str, Any] = {"country": "US", "exchange": "NASDAQ"}
    if sector:
        overrides["sector"] = sector
    if industry:
        overrides["industry"] = industry
    if market_cap_min is not None:
        overrides["market_cap_min"] = market_cap_min
    if market_cap_max is not None:
        overrides["market_cap_max"] = market_cap_max

    # Only send overrides if we have filters beyond the US default
    screener_overrides = overrides if len(overrides) > 2 or not tickers else None

    run_id = await client.trigger_pipeline(
        strategy_id=strategy_id,
        manual_tickers=ticker_list,
        user_prompt=prompt,
        screener_overrides=screener_overrides,
    )
    return json.dumps({"run_id": run_id, "status": "running"})


async def get_pipeline_progress(run_id: str) -> str:
    """Check the progress of a running pipeline.

    Returns stage-by-stage status. Poll this until run_status is "completed" or "error".

    Args:
        run_id: The pipeline run ID returned by run_pipeline.
    """
    client = get_backend_client()
    progress = await client.get_pipeline_progress(run_id)
    return json.dumps(progress, indent=2)


async def get_pipeline_result(run_id: str) -> str:
    """Get the full result of a completed pipeline run.

    Returns all recommendations with entry prices, stop losses, take profits,
    confidence scores, and analysis details. Call this after the pipeline
    completes (check with get_pipeline_progress first).

    Args:
        run_id: The pipeline run ID returned by run_pipeline.
    """
    client = get_backend_client()
    result = await client.get_pipeline_result(run_id)

    recs = result.get("recommendations", [])
    summary = _summarize_result(result, recs)
    return json.dumps(summary, indent=2)


async def list_strategies() -> str:
    """List all available trading strategies.

    Returns strategy names, IDs, modes, and descriptions. Use the strategy_id
    with run_pipeline to trigger analysis using a specific strategy.
    """
    client = get_backend_client()
    strategies = await client.list_strategies()
    summary = [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "mode": s.get("mode"),
            "description": s.get("description", ""),
            "enable_debate": s.get("enable_debate", False),
        }
        for s in strategies
    ]
    return json.dumps(summary, indent=2)


async def list_recent_runs(limit: int = 20) -> str:
    """List recent pipeline runs.

    Shows run history with status, strategy, and tickers analyzed.

    Args:
        limit: Maximum number of runs to return (default 20).
    """
    client = get_backend_client()
    runs = await client.list_pipeline_runs(limit=limit)
    return json.dumps(runs, indent=2)


def _summarize_result(result: dict[str, Any], recs: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a concise summary of pipeline results for Claude.

    Args:
        result: Full pipeline result dict.
        recs: List of recommendation dicts.

    Returns:
        Summary dict with key fields for each recommendation.
    """
    rec_summaries = []
    for r in recs:
        rec_summaries.append(
            {
                "id": r.get("id"),
                "ticker": r.get("ticker"),
                "action": r.get("action"),
                "confidence": r.get("confidence"),
                "entry_price": r.get("entry_price"),
                "stop_loss": r.get("stop_loss"),
                "take_profit": r.get("take_profit"),
                "position_size_pct": r.get("position_size_pct"),
                "risk_reward_ratio": r.get("risk_reward_ratio"),
                "holding_period": r.get("holding_period"),
                "key_factors": r.get("key_factors", []),
                "warnings": r.get("warnings", []),
                "judge_reasoning": r.get("judge_reasoning", ""),
                "ml_blocked": r.get("ml_blocked", False),
                "ml_probability": r.get("ml_probability"),
            }
        )

    return {
        "run_id": result.get("run_id"),
        "mode": result.get("mode"),
        "total_duration_seconds": result.get("total_duration_seconds"),
        "stage_errors": result.get("stage_errors", []),
        "recommendation_count": len(rec_summaries),
        "recommendations": rec_summaries,
    }
