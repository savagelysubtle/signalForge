"""Reflection engine for the self-learning feedback loop.

Loads the latest injection prompt from the reflections table (for GPT
judge context), and generates new reflections from trade decision and
outcome data. The hybrid approach uses pure Python for metrics + an
LLM call for strategic self-advice.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

from database.connection import get_db
from pipeline.schemas import ReflectionResponse

logger = logging.getLogger(__name__)


async def load_reflection_context(user_id: str = "") -> str:
    """Load the most recent reflection injection prompt from the database.

    Queries the ``reflections`` table for the latest ``injection_prompt``,
    which contains concrete performance stats (win rates, confidence
    calibration, sector performance) that GPT uses to self-correct.

    Args:
        user_id: Filter reflections by user. Empty string returns any user's latest.

    Returns:
        The injection prompt text, or empty string if no reflections exist.
    """
    try:
        client = await get_db()
        query = (
            client.table("reflections").select("injection_prompt").order("generated_at", desc=True)
        )
        if user_id:
            query = query.eq("user_id", user_id)
        response = await query.limit(1).execute()

        if response and response.data and len(response.data) > 0:
            row = response.data[0]
            if row.get("injection_prompt"):
                prompt = row["injection_prompt"]
                logger.info("Loaded reflection context (%d chars)", len(prompt))
                return prompt
    except Exception:
        logger.exception("Failed to load reflection context")

    return ""


async def generate_reflection(user_id: str) -> ReflectionResponse:
    """Generate a reflection from the user's trade history.

    Computes performance metrics from decisions + outcomes, builds a
    data section via string formatting, calls GPT for strategic advice,
    and stores the result in the reflections table.

    Args:
        user_id: The user to generate a reflection for.

    Returns:
        The generated reflection with metrics and injection prompt.
    """
    client = await get_db()

    dec_resp = await client.table("decisions").select("*").eq("user_id", user_id).execute()
    decisions = dec_resp.data

    out_resp = await client.table("outcomes").select("*").eq("user_id", user_id).execute()
    outcomes = out_resp.data

    rec_ids = list({d["recommendation_id"] for d in decisions})
    rec_map: dict[str, dict] = {}
    if rec_ids:
        rec_resp = (
            await client.table("recommendations")
            .select("id, ticker, action, confidence")
            .in_("id", rec_ids)
            .execute()
        )
        rec_map = {r["id"]: r for r in rec_resp.data}

    metrics = _compute_metrics(outcomes, decisions, rec_map)

    date_range_start: str | None = None
    date_range_end: str | None = None
    if outcomes:
        dates = [o["logged_at"] for o in outcomes if o.get("logged_at")]
        if dates:
            date_range_start = str(min(dates))
            date_range_end = str(max(dates))

    data_section = _build_data_section(metrics, len(outcomes), date_range_start, date_range_end)

    strategic_advice = await _get_strategic_advice(metrics)

    injection_prompt = f"{data_section}\n\n{strategic_advice}"

    summary_text = _build_summary(metrics, len(decisions), len(outcomes))

    reflection_id = uuid.uuid4().hex
    now = datetime.now(tz=UTC).isoformat()

    row = {
        "id": reflection_id,
        "user_id": user_id,
        "generated_at": now,
        "recommendations_analyzed": len(rec_ids),
        "decisions_analyzed": len(decisions),
        "outcomes_analyzed": len(outcomes),
        "date_range_start": date_range_start,
        "date_range_end": date_range_end,
        "summary_text": summary_text,
        "injection_prompt": injection_prompt,
        "metrics": json.dumps(metrics),
    }
    await client.table("reflections").insert(row).execute()

    return ReflectionResponse(
        id=reflection_id,
        generated_at=now,
        recommendations_analyzed=len(rec_ids),
        decisions_analyzed=len(decisions),
        outcomes_analyzed=len(outcomes),
        date_range_start=date_range_start,
        date_range_end=date_range_end,
        summary_text=summary_text,
        injection_prompt=injection_prompt,
        metrics=metrics,
    )


def _compute_metrics(
    outcomes: list[dict],
    decisions: list[dict],
    rec_map: dict[str, dict],
) -> dict:
    """Compute performance metrics from outcomes and decisions.

    Args:
        outcomes: List of outcome records from the database.
        decisions: List of decision records from the database.
        rec_map: Recommendation ID → recommendation dict lookup.

    Returns:
        Dictionary of computed metrics.
    """
    wins = 0
    losses = 0
    breakeven = 0
    total_pnl = 0.0
    pnl_percents: list[float] = []
    holding_days_list: list[int] = []
    best_trade: dict | None = None
    worst_trade: dict | None = None

    for o in outcomes:
        pnl = o.get("pnl_dollars") or 0.0
        total_pnl += pnl

        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1
        else:
            breakeven += 1

        if o.get("pnl_percent") is not None:
            pnl_percents.append(o["pnl_percent"])
        if o.get("holding_days") is not None:
            holding_days_list.append(o["holding_days"])

        trade_info = {
            "ticker": o.get("ticker", ""),
            "pnl_dollars": pnl,
            "pnl_percent": o.get("pnl_percent"),
        }
        if best_trade is None or pnl > (best_trade.get("pnl_dollars") or 0.0):
            best_trade = trade_info
        if worst_trade is None or pnl < (worst_trade.get("pnl_dollars") or 0.0):
            worst_trade = trade_info

    win_rate = round((wins / (wins + losses)) * 100, 1) if (wins + losses) > 0 else None
    avg_pnl_pct = round(sum(pnl_percents) / len(pnl_percents), 2) if pnl_percents else None
    avg_holding = (
        round(sum(holding_days_list) / len(holding_days_list), 1) if holding_days_list else None
    )

    total_following = sum(1 for d in decisions if d["decision"] == "following")
    total_passing = sum(1 for d in decisions if d["decision"] == "passing")

    confidence_buckets: dict[str, list[float]] = {"high": [], "medium": [], "low": []}
    for o in outcomes:
        rec = rec_map.get(o.get("recommendation_id", ""), {})
        conf = rec.get("confidence", 0.5)
        pnl = o.get("pnl_dollars") or 0.0
        if conf > 0.75:
            confidence_buckets["high"].append(pnl)
        elif conf >= 0.55:
            confidence_buckets["medium"].append(pnl)
        else:
            confidence_buckets["low"].append(pnl)

    calibration: dict[str, dict] = {}
    for label, trades in confidence_buckets.items():
        if not trades:
            continue
        bucket_wins = sum(1 for p in trades if p > 0)
        calibration[label] = {
            "count": len(trades),
            "win_rate": round((bucket_wins / len(trades)) * 100, 1),
        }

    buy_outcomes = [
        o
        for o in outcomes
        if rec_map.get(o.get("recommendation_id", ""), {}).get("action") == "BUY"
    ]
    sell_outcomes = [
        o
        for o in outcomes
        if rec_map.get(o.get("recommendation_id", ""), {}).get("action") == "SELL"
    ]
    buy_wins = sum(1 for o in buy_outcomes if (o.get("pnl_dollars") or 0) > 0)
    sell_wins = sum(1 for o in sell_outcomes if (o.get("pnl_dollars") or 0) > 0)
    buy_win_rate = round((buy_wins / len(buy_outcomes)) * 100, 1) if buy_outcomes else None
    sell_win_rate = round((sell_wins / len(sell_outcomes)) * 100, 1) if sell_outcomes else None

    return {
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "win_rate": win_rate,
        "total_pnl_dollars": round(total_pnl, 2),
        "avg_pnl_percent": avg_pnl_pct,
        "avg_holding_days": avg_holding,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "total_following": total_following,
        "total_passing": total_passing,
        "confidence_calibration": calibration,
        "buy_win_rate": buy_win_rate,
        "sell_win_rate": sell_win_rate,
    }


def _build_data_section(
    metrics: dict,
    outcome_count: int,
    date_start: str | None,
    date_end: str | None,
) -> str:
    """Build the deterministic data section of the injection prompt.

    Args:
        metrics: Computed metrics dictionary.
        outcome_count: Total number of outcomes analyzed.
        date_start: Start of the date range.
        date_end: End of the date range.

    Returns:
        Formatted data section string for the injection prompt.
    """
    date_range = f"{date_start} to {date_end}" if date_start and date_end else "all time"

    lines = [
        f"=== PERFORMANCE DATA ({outcome_count} trades, {date_range}) ===",
        f"Overall: {metrics['wins']}w/{metrics['losses']}l/{metrics['breakeven']}be"
        + (f", {metrics['win_rate']}% win rate" if metrics["win_rate"] is not None else ""),
        f"Total P&L: ${metrics['total_pnl_dollars']:,.2f}"
        + (
            f", Avg per trade: {metrics['avg_pnl_percent']}%"
            if metrics["avg_pnl_percent"] is not None
            else ""
        ),
    ]

    cal = metrics.get("confidence_calibration", {})
    if cal:
        lines.append("Confidence calibration:")
        for label in ("high", "medium", "low"):
            if label in cal:
                bucket = cal[label]
                threshold = (
                    ">0.75" if label == "high" else "0.55-0.75" if label == "medium" else "<0.55"
                )
                lines.append(
                    f"  {label.capitalize()} ({threshold}): "
                    f"{bucket['win_rate']}% actual win rate ({bucket['count']} trades)"
                )

    action_parts: list[str] = []
    if metrics.get("buy_win_rate") is not None:
        action_parts.append(f"BUY {metrics['buy_win_rate']}%")
    if metrics.get("sell_win_rate") is not None:
        action_parts.append(f"SELL {metrics['sell_win_rate']}%")
    if action_parts:
        lines.append(f"Action accuracy: {', '.join(action_parts)}")

    return "\n".join(lines)


def _build_summary(metrics: dict, decision_count: int, outcome_count: int) -> str:
    """Build a human-readable summary for the Insights view.

    Args:
        metrics: Computed metrics dictionary.
        decision_count: Total decisions analyzed.
        outcome_count: Total outcomes analyzed.

    Returns:
        Human-readable performance summary.
    """
    parts = [
        f"Performance Report: {outcome_count} trades from {decision_count} decisions.",
        f"Record: {metrics['wins']}W / {metrics['losses']}L / {metrics['breakeven']}BE",
    ]
    if metrics["win_rate"] is not None:
        parts.append(f"Win Rate: {metrics['win_rate']}%")
    parts.append(f"Total P&L: ${metrics['total_pnl_dollars']:,.2f}")
    if metrics["avg_pnl_percent"] is not None:
        parts.append(f"Avg Return: {metrics['avg_pnl_percent']}% per trade")
    if metrics["avg_holding_days"] is not None:
        parts.append(f"Avg Hold: {metrics['avg_holding_days']} days")
    if metrics.get("best_trade"):
        bt = metrics["best_trade"]
        parts.append(f"Best: {bt['ticker']} (${bt['pnl_dollars']:+,.2f})")
    if metrics.get("worst_trade"):
        wt = metrics["worst_trade"]
        parts.append(f"Worst: {wt['ticker']} (${wt['pnl_dollars']:+,.2f})")
    return "\n".join(parts)


async def _get_strategic_advice(metrics: dict) -> str:
    """Call GPT to generate strategic self-advice based on metrics.

    Falls back to a generic message if the API call fails, keeping
    the reflection generation non-blocking.

    Args:
        metrics: Computed performance metrics dictionary.

    Returns:
        Strategic advice paragraph from GPT, or fallback text.
    """
    try:
        from openai import AsyncOpenAI

        from services.keyring_service import get_api_key

        api_key = get_api_key("openai")
        if not api_key:
            return "Strategic advice unavailable (OpenAI API key not configured)."

        client = AsyncOpenAI(api_key=api_key)

        system_prompt = (
            "You are reviewing your own trading recommendation history. "
            "Based on these performance metrics, write 2-3 sentences of concrete "
            "self-advice for future recommendations. Focus on specific biases, "
            "blind spots, or calibration issues. Be blunt and data-driven."
        )

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(metrics, indent=2)},
            ],
            max_tokens=300,
            temperature=0.7,
        )

        advice = response.choices[0].message.content
        return advice.strip() if advice else "No strategic advice generated."

    except Exception:
        logger.exception("Failed to generate strategic advice via GPT")
        return "Strategic advice unavailable due to API error."
