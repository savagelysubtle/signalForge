"""Reflection engine for the self-learning feedback loop.

Loads the latest injection prompt from the reflections table (for GPT
judge context), and generates new reflections from trade decision and
outcome data. The hybrid approach uses pure Python for metrics + an
LLM call for strategic self-advice.

FinMem architecture: Two-layer memory (short-term 14d + long-term all-time)
with pattern accuracy, sector win rates, timeframe alignment, and
suppression logic for underperforming patterns/sectors.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from database.connection import get_db
from pipeline.model_config import REFLECTION_MODEL
from pipeline.schemas import ReflectionResponse, StructuredOutcomeAnalysis

logger = logging.getLogger(__name__)

FINMEM_SHORT_TERM_DAYS = 14
FINMEM_MIN_SAMPLE = 3


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


async def load_reflection_metrics(user_id: str = "") -> dict[str, Any] | None:
    """Load structured metrics from the latest reflection for calibration.

    Unlike ``load_reflection_context`` (which returns the text injection prompt),
    this returns the raw metrics dict containing ``confidence_calibration``,
    ``pattern_stats``, and other fields consumed by
    ``confidence_calibration._score_historical_pattern``.

    Args:
        user_id: Filter reflections by user. Empty string returns any user's latest.

    Returns:
        Metrics dict if available, or None.
    """
    try:
        client = await get_db()
        query = client.table("reflections").select("metrics").order("generated_at", desc=True)
        if user_id:
            query = query.eq("user_id", user_id)
        response = await query.limit(1).execute()

        if response and response.data and response.data[0].get("metrics"):
            raw = response.data[0]["metrics"]
            metrics = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(metrics, dict):
                logger.info("Loaded reflection metrics (%d keys)", len(metrics))
                return metrics
    except Exception:
        logger.exception("Failed to load reflection metrics")

    return None


def _parse_stage_json(row: dict) -> dict | None:
    """Extract parsed JSON from a stage_outputs row.

    Tries ``parsed_output`` first, then falls back to ``raw_response``
    for historical rows where ``parsed_output`` was not populated.

    Args:
        row: A stage_outputs database row.

    Returns:
        Parsed dict, or ``None`` if neither field contains valid JSON.
    """
    for field in ("parsed_output", "raw_response"):
        value = row.get(field)
        if not value:
            continue
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                result = json.loads(value)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError, TypeError:
                continue
    return None


async def _fetch_stage_context(
    client: Any,
    rec_map: dict[str, dict],
) -> dict[tuple[str, str], dict]:
    """Fetch stage_outputs to extract pattern/sector/bias context per ticker.

    Joins recommendation.run_id -> stage_outputs to get Claude chart
    patterns and Perplexity sector data for each recommendation.

    Args:
        client: Supabase async client.
        rec_map: Recommendation ID -> recommendation dict (must include run_id, ticker).

    Returns:
        Mapping of (run_id, ticker) -> context dict with keys:
        patterns (list[str]), biases (dict[str, str]), sector (str).
    """
    run_ids = list({r["run_id"] for r in rec_map.values() if r.get("run_id")})
    if not run_ids:
        return {}

    try:
        stage_resp = (
            await client.table("stage_outputs")
            .select("run_id, ticker, stage, parsed_output, raw_response")
            .in_("run_id", run_ids)
            .in_("stage", ["claude", "perplexity"])
            .execute()
        )
    except Exception:
        logger.exception("Failed to fetch stage_outputs for FinMem context")
        return {}

    context: dict[tuple[str, str], dict] = {}

    for row in stage_resp.data or []:
        key = (row["run_id"], row.get("ticker", ""))
        if key not in context:
            context[key] = {"patterns": [], "biases": {}, "sector": ""}

        parsed = _parse_stage_json(row)
        if parsed is None:
            continue

        if row["stage"] == "claude":
            patterns = parsed.get("patterns_detected") or []
            if isinstance(patterns, list):
                context[key]["patterns"].extend(patterns)
            bias = parsed.get("overall_bias", "")
            tf = parsed.get("timeframe", "")
            if bias and tf:
                context[key]["biases"][tf] = bias

        elif row["stage"] == "perplexity":
            tickers_list = parsed.get("tickers") or []
            for td in tickers_list:
                if isinstance(td, dict) and (td.get("ticker") or "").endswith(
                    row.get("ticker") or ""
                ):
                    context[key]["sector"] = td.get("sector", "")
                    break

    return context


def classify_failure_mode(
    outcome: dict,
    rec: dict,
    stage_ctx: dict,
) -> str:
    """Deterministically classify why a losing trade failed.

    Uses the recommendation's signal data, outcome results, and stage
    context to assign a failure mode category. Only meaningful for
    losses — wins and breakevens return "unknown".

    Args:
        outcome: Outcome record from the database.
        rec: Recommendation record (action, confidence, etc.).
        stage_ctx: Stage context dict with patterns, biases, sector, and
            optional v2 fields (track_agreement, ema_cross_age, adx, etc.).

    Returns:
        A failure mode string literal.
    """
    pnl = outcome.get("pnl_dollars") or 0.0
    if pnl >= 0:
        return "unknown"

    action = rec.get("action", "")
    structured = outcome.get("structured_analysis") or {}

    track_agreement_score = structured.get("track_agreement_score", 1.0)
    if track_agreement_score < 0.5:
        return "low_agreement_taken"

    ema_cross_age = structured.get("ema_cross_age_at_signal", -1)
    if ema_cross_age > 5:
        return "late_entry"

    rsi_at_signal = structured.get("rsi_at_signal", 50.0)
    if action == "BUY" and rsi_at_signal > 70:
        return "false_breakout"
    if action == "SHORT" and rsi_at_signal < 30:
        return "false_breakout"

    adx_at_signal = structured.get("adx_at_signal", 25.0)
    momentum_at_signal = structured.get("momentum_score_at_signal", 0.0)
    momentum_at_outcome = structured.get("momentum_score_at_outcome", 0.0)

    if abs(momentum_at_signal) > 0.3 and (momentum_at_signal * momentum_at_outcome) < 0:
        return "sentiment_reversal"

    if adx_at_signal < 15:
        return "correct_direction_bad_timing"

    holding_days = outcome.get("holding_days") or 0
    pnl_pct = outcome.get("pnl_percent") or 0.0
    if holding_days > 0 and abs(pnl_pct) < 2.0:
        return "correct_direction_bad_timing"

    if action == "BUY" and pnl < 0:
        return "wrong_direction"
    if action == "SHORT" and pnl < 0:
        return "wrong_direction"

    return "unknown"


def build_structured_outcome_analysis(
    outcome: dict,
    rec: dict,
    stage_ctx: dict,
    outcome_stage_ctx: dict | None = None,
) -> StructuredOutcomeAnalysis:
    """Build a rich StructuredOutcomeAnalysis from outcome and context data.

    Captures the state of analysis tracks and numerical TA at signal time
    vs outcome time for pattern learning.

    Args:
        outcome: Outcome record from the database.
        rec: Recommendation record (includes action, confidence, run_id).
        stage_ctx: Stage context at signal time (patterns, biases, etc.).
        outcome_stage_ctx: Optional stage context at outcome time (for
            comparing RSI/momentum at entry vs exit).

    Returns:
        Populated StructuredOutcomeAnalysis instance.
    """
    pnl = outcome.get("pnl_dollars") or 0.0
    pnl_pct = outcome.get("pnl_percent") or 0.0

    if pnl > 0:
        actual_outcome = "win"
    elif pnl < 0:
        actual_outcome = "loss"
    else:
        actual_outcome = "breakeven"

    action = rec.get("action", "")
    signal_direction = "long" if action == "BUY" else "short" if action == "SHORT" else "neutral"

    structured = outcome.get("structured_analysis") or {}
    track_agreement = rec.get("track_agreement") or {}

    agreement_score = 0.0
    if isinstance(track_agreement, dict):
        agreement_score = track_agreement.get("agreement_score", 0.0)

    tracks_agreed: list[str] = []
    tracks_disagreed: list[str] = []
    if isinstance(track_agreement, dict):
        for track_name in ("perplexity", "gemini", "claude"):
            direction = track_agreement.get(f"{track_name}_direction", "neutral")
            if (signal_direction == "long" and direction == "bullish") or (
                signal_direction == "short" and direction == "bearish"
            ):
                tracks_agreed.append(track_name)
            elif direction == "neutral":
                pass
            else:
                tracks_disagreed.append(track_name)

    failure_mode = classify_failure_mode(outcome, rec, stage_ctx)

    return StructuredOutcomeAnalysis(
        ticker=rec.get("ticker", outcome.get("ticker", "")),
        signal_direction=signal_direction,
        actual_outcome=actual_outcome,
        pnl_pct=pnl_pct,
        track_agreement_score=agreement_score,
        tracks_that_agreed_with_outcome=tracks_agreed,
        tracks_that_disagreed_with_outcome=tracks_disagreed,
        ema_cross_age_at_signal=structured.get("ema_cross_age_at_signal", -1),
        rsi_at_signal=structured.get("rsi_at_signal", 50.0),
        rsi_at_outcome=structured.get("rsi_at_outcome", 50.0),
        adx_at_signal=structured.get("adx_at_signal", 0.0),
        momentum_score_at_signal=structured.get("momentum_score_at_signal", 0.0),
        momentum_score_at_outcome=structured.get("momentum_score_at_outcome", 0.0),
        failure_mode=failure_mode,
        lesson=structured.get("lesson", ""),
        slippage_pct=outcome.get("slippage_pct"),
        time_to_execution_minutes=outcome.get("time_to_execution_minutes"),
        trader_followed_signal=structured.get("trader_followed_signal"),
    )


async def generate_reflection(
    user_id: str,
    strategy_id: str | None = None,
) -> ReflectionResponse:
    """Generate a reflection from the user's trade history.

    Computes performance metrics from decisions + outcomes, fetches
    stage_outputs for pattern/sector/TF data, builds a two-layer
    memory injection (short-term + long-term), calls GPT for strategic
    advice, and stores the result in the reflections table.

    Args:
        user_id: The user to generate a reflection for.
        strategy_id: Optional strategy UUID to scope the reflection to a
            single strategy. When provided, only recommendations from runs
            using this strategy are included.

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
            .select("id, ticker, action, confidence, run_id")
            .in_("id", rec_ids)
            .execute()
        )
        rec_map = {r["id"]: r for r in rec_resp.data}

    # Strategy-scoped filtering: keep only recs from matching pipeline runs
    if strategy_id and rec_map:
        run_ids = list({r["run_id"] for r in rec_map.values() if r.get("run_id")})
        if run_ids:
            run_resp = (
                await client.table("pipeline_runs")
                .select("id")
                .eq("strategy_id", strategy_id)
                .in_("id", run_ids)
                .execute()
            )
            valid_run_ids = {r["id"] for r in (run_resp.data or [])}
            rec_map = {k: v for k, v in rec_map.items() if v.get("run_id") in valid_run_ids}
            valid_rec_ids = set(rec_map.keys())
            decisions = [d for d in decisions if d["recommendation_id"] in valid_rec_ids]
            outcomes = [o for o in outcomes if o["recommendation_id"] in valid_rec_ids]

    stage_context = await _fetch_stage_context(client, rec_map)

    metrics = _compute_metrics(outcomes, decisions, rec_map, stage_context)

    date_range_start: str | None = None
    date_range_end: str | None = None
    if outcomes:
        dates = [o["logged_at"] for o in outcomes if o.get("logged_at")]
        if dates:
            date_range_start = str(min(dates))
            date_range_end = str(max(dates))

    memory_injection = build_memory_injection(metrics, outcomes, len(outcomes))

    strategic_advice = await _get_strategic_advice(metrics)

    injection_prompt = f"{memory_injection}\n\n{strategic_advice}"

    summary_text = _build_summary(metrics, len(decisions), len(outcomes))

    reflection_id = uuid.uuid4().hex
    now = datetime.now(tz=UTC).isoformat()

    # Phase 6: Build pattern_statistics from v2 analytics
    pattern_statistics = {
        "track_agreement_stats": metrics.get("track_agreement_stats", {}),
        "ema_cross_age_stats": metrics.get("ema_cross_age_stats", {}),
        "failure_mode_stats": metrics.get("failure_mode_stats", []),
        "slippage_stats": metrics.get("slippage_stats", {}),
    }

    # Phase 6: Backfill failure_mode on outcomes that don't have one
    for o in outcomes:
        if o.get("failure_mode"):
            continue
        pnl = o.get("pnl_dollars") or 0.0
        if pnl >= 0:
            continue
        rec = rec_map.get(o.get("recommendation_id", ""), {})
        run_id_o = rec.get("run_id", "")
        ticker_o = rec.get("ticker", o.get("ticker", ""))
        ctx = stage_context.get((run_id_o, ticker_o), {})
        fm = classify_failure_mode(o, rec, ctx)
        if fm != "unknown":
            try:
                await (
                    client.table("outcomes")
                    .update({"failure_mode": fm})
                    .eq("id", o["id"])
                    .execute()
                )
            except Exception:
                logger.debug("Failed to backfill failure_mode for outcome %s", o.get("id"))

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
        "pattern_statistics": json.dumps(pattern_statistics),
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
    stage_context: dict[tuple[str, str], dict] | None = None,
) -> dict:
    """Compute performance metrics including FinMem pattern/sector/TF stats.

    Args:
        outcomes: List of outcome records from the database.
        decisions: List of decision records from the database.
        rec_map: Recommendation ID -> recommendation dict lookup.
        stage_context: Mapping of (run_id, ticker) -> context dict with
            patterns, biases, and sector from stage_outputs.

    Returns:
        Dictionary of computed metrics including pattern_stats,
        sector_stats, alignment_stats, and recent_streak.
    """
    stage_context = stage_context or {}

    short_cutoff = (datetime.now(tz=UTC) - timedelta(days=FINMEM_SHORT_TERM_DAYS)).isoformat()

    wins = 0
    losses = 0
    breakeven = 0
    total_pnl = 0.0
    pnl_percents: list[float] = []
    holding_days_list: list[int] = []
    best_trade: dict | None = None
    worst_trade: dict | None = None

    pattern_stats: dict[str, dict] = {}
    sector_stats: dict[str, dict] = {}
    short_sector_stats: dict[str, dict] = {}
    alignment_buckets: dict[str, dict] = {
        "all_agree": {"wins": 0, "losses": 0},
        "partial": {"wins": 0, "losses": 0},
        "single_tf": {"wins": 0, "losses": 0},
    }
    recent_streak: list[dict] = []

    for o in outcomes:
        pnl = o.get("pnl_dollars") or 0.0
        total_pnl += pnl
        is_win = pnl > 0

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

        rec = rec_map.get(o.get("recommendation_id", ""), {})
        run_id = rec.get("run_id", "")
        ticker = rec.get("ticker", o.get("ticker", ""))
        ctx = stage_context.get((run_id, ticker), {})

        for pattern in ctx.get("patterns", []):
            p_lower = pattern.lower().strip()
            if not p_lower:
                continue
            if p_lower not in pattern_stats:
                pattern_stats[p_lower] = {"wins": 0, "losses": 0}
            if is_win:
                pattern_stats[p_lower]["wins"] += 1
            else:
                pattern_stats[p_lower]["losses"] += 1

        sector = ctx.get("sector", "")
        if sector:
            if sector not in sector_stats:
                sector_stats[sector] = {"wins": 0, "losses": 0}
            if is_win:
                sector_stats[sector]["wins"] += 1
            else:
                sector_stats[sector]["losses"] += 1

            is_recent = (o.get("logged_at") or "") >= short_cutoff
            if is_recent:
                if sector not in short_sector_stats:
                    short_sector_stats[sector] = {"wins": 0, "losses": 0}
                if is_win:
                    short_sector_stats[sector]["wins"] += 1
                else:
                    short_sector_stats[sector]["losses"] += 1

        biases = ctx.get("biases", {})
        if biases:
            unique_biases = set(biases.values())
            all_bullish = all("bullish" in b for b in unique_biases)
            all_bearish = all("bearish" in b for b in unique_biases)
            tf_count = len(biases)

            if tf_count <= 1:
                bucket = "single_tf"
            elif all_bullish or all_bearish:
                bucket = "all_agree"
            else:
                bucket = "partial"

            if is_win:
                alignment_buckets[bucket]["wins"] += 1
            else:
                alignment_buckets[bucket]["losses"] += 1

        recent_streak.append(
            {
                "ticker": ticker,
                "pnl_percent": o.get("pnl_percent"),
                "pnl_dollars": pnl,
                "patterns": ctx.get("patterns", [])[:3],
                "logged_at": o.get("logged_at", ""),
                "what_went_wrong": o.get("notes", ""),
            }
        )

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
        if rec_map.get(o.get("recommendation_id", ""), {}).get("action") == "SHORT"
    ]
    buy_wins = sum(1 for o in buy_outcomes if (o.get("pnl_dollars") or 0) > 0)
    sell_wins = sum(1 for o in sell_outcomes if (o.get("pnl_dollars") or 0) > 0)
    buy_win_rate = round((buy_wins / len(buy_outcomes)) * 100, 1) if buy_outcomes else None
    sell_win_rate = round((sell_wins / len(sell_outcomes)) * 100, 1) if sell_outcomes else None

    for p_key in pattern_stats:
        s = pattern_stats[p_key]
        total = s["wins"] + s["losses"]
        s["total"] = total
        s["win_rate"] = round((s["wins"] / total) * 100, 1) if total > 0 else 0.0

    for s_key in sector_stats:
        s = sector_stats[s_key]
        total = s["wins"] + s["losses"]
        s["total"] = total
        s["win_rate"] = round((s["wins"] / total) * 100, 1) if total > 0 else 0.0

    for s_key in short_sector_stats:
        s = short_sector_stats[s_key]
        total = s["wins"] + s["losses"]
        s["total"] = total
        s["win_rate"] = round((s["wins"] / total) * 100, 1) if total > 0 else 0.0

    alignment_stats: dict[str, dict] = {}
    for a_key, a_val in alignment_buckets.items():
        total = a_val["wins"] + a_val["losses"]
        if total > 0:
            alignment_stats[a_key] = {
                "wins": a_val["wins"],
                "losses": a_val["losses"],
                "total": total,
                "win_rate": round((a_val["wins"] / total) * 100, 1),
            }

    recent_streak.sort(key=lambda x: x.get("logged_at", ""), reverse=True)
    recent_streak = recent_streak[:5]

    # ── Phase 6 v2 analytics ──────────────────────────────────────────────

    # Track agreement win rates (from outcomes with structured_analysis)
    agreement_buckets: dict[str, dict[str, int]] = {
        "3_of_3": {"wins": 0, "losses": 0},
        "2_of_3": {"wins": 0, "losses": 0},
        "disagree": {"wins": 0, "losses": 0},
    }

    # EMA cross age buckets
    ema_age_buckets: dict[str, dict[str, int]] = {
        "fresh": {"wins": 0, "losses": 0},
        "recent": {"wins": 0, "losses": 0},
        "stale": {"wins": 0, "losses": 0},
    }

    # Failure mode frequency
    failure_mode_counts: dict[str, int] = {}

    # Slippage tracking
    slippage_values: list[float] = []

    for o in outcomes:
        is_win = (o.get("pnl_dollars") or 0.0) > 0
        structured = o.get("structured_analysis")
        if not isinstance(structured, dict):
            if isinstance(structured, str):
                try:
                    structured = json.loads(structured)
                except json.JSONDecodeError, TypeError:
                    structured = None
            else:
                structured = None

        if structured:
            agreement_score = structured.get("track_agreement_score", -1.0)
            if agreement_score >= 0:
                if agreement_score >= 0.9:
                    bucket = "3_of_3"
                elif agreement_score >= 0.4:
                    bucket = "2_of_3"
                else:
                    bucket = "disagree"

                if is_win:
                    agreement_buckets[bucket]["wins"] += 1
                else:
                    agreement_buckets[bucket]["losses"] += 1

            ema_age = structured.get("ema_cross_age_at_signal", -1)
            if ema_age >= 0:
                if ema_age <= 2:
                    age_bucket = "fresh"
                elif ema_age <= 5:
                    age_bucket = "recent"
                else:
                    age_bucket = "stale"

                if is_win:
                    ema_age_buckets[age_bucket]["wins"] += 1
                else:
                    ema_age_buckets[age_bucket]["losses"] += 1

        fm = o.get("failure_mode")
        if fm and fm != "unknown":
            failure_mode_counts[fm] = failure_mode_counts.get(fm, 0) + 1

        slip = o.get("slippage_pct")
        if slip is not None:
            slippage_values.append(slip)

    # Finalize agreement stats
    track_agreement_stats: dict[str, dict] = {}
    for label, bucket_data in agreement_buckets.items():
        total = bucket_data["wins"] + bucket_data["losses"]
        if total > 0:
            track_agreement_stats[label] = {
                "wins": bucket_data["wins"],
                "losses": bucket_data["losses"],
                "total": total,
                "win_rate": round((bucket_data["wins"] / total) * 100, 1),
            }

    # Finalize EMA cross age stats
    ema_cross_age_stats: dict[str, dict] = {}
    for label, bucket_data in ema_age_buckets.items():
        total = bucket_data["wins"] + bucket_data["losses"]
        if total > 0:
            ema_cross_age_stats[label] = {
                "wins": bucket_data["wins"],
                "losses": bucket_data["losses"],
                "total": total,
                "win_rate": round((bucket_data["wins"] / total) * 100, 1),
            }

    # Sort failure modes by frequency
    sorted_failure_modes = sorted(failure_mode_counts.items(), key=lambda x: -x[1])

    # Slippage summary
    slippage_stats: dict[str, float] = {}
    if slippage_values:
        slippage_stats = {
            "avg_pct": round(sum(slippage_values) / len(slippage_values), 3),
            "max_pct": round(max(slippage_values), 3),
            "min_pct": round(min(slippage_values), 3),
            "count": len(slippage_values),
        }

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
        "pattern_stats": pattern_stats,
        "sector_stats": sector_stats,
        "short_sector_stats": short_sector_stats,
        "alignment_stats": alignment_stats,
        "recent_streak": recent_streak,
        "track_agreement_stats": track_agreement_stats,
        "ema_cross_age_stats": ema_cross_age_stats,
        "failure_mode_stats": sorted_failure_modes,
        "slippage_stats": slippage_stats,
    }


def _split_short_long_outcomes(
    outcomes: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Split outcomes into short-term (last 14 days) and all.

    Args:
        outcomes: All outcome records (should have ``logged_at``).

    Returns:
        Tuple of (short_term outcomes, all outcomes).
    """
    cutoff = (datetime.now(tz=UTC) - timedelta(days=FINMEM_SHORT_TERM_DAYS)).isoformat()
    short = [o for o in outcomes if (o.get("logged_at") or "") >= cutoff]
    return short, outcomes


def _format_short_term_memory(
    metrics: dict,
    short_outcomes: list[dict],
) -> list[str]:
    """Format the short-term memory section (last 14 days).

    Includes recent trades, active streaks, and temporary suppression
    flags for underperforming patterns/sectors.

    Args:
        metrics: Full computed metrics dictionary.
        short_outcomes: Outcomes from the last 14 days only.

    Returns:
        List of formatted lines.
    """
    lines = [f"### SHORT-TERM MEMORY (Last {FINMEM_SHORT_TERM_DAYS} days)"]

    streak = metrics.get("recent_streak", [])
    if streak:
        trade_strs = []
        for t in streak[:5]:
            pnl = t.get("pnl_percent")
            if pnl is not None:
                trade_strs.append(f"{t['ticker']} {pnl:+.1f}%")
            else:
                pnl_d = t.get("pnl_dollars", 0)
                trade_strs.append(f"{t['ticker']} ${pnl_d:+,.0f}")
        lines.append(f"Last {len(trade_strs)} trades: {', '.join(trade_strs)}")

    if not short_outcomes:
        lines.append("No trades in the last 14 days.")
        return lines

    short_pattern_stats: dict[str, dict] = {}
    short_sector_stats: dict[str, dict] = metrics.get("short_sector_stats", {})

    for t in streak:
        is_win = (t.get("pnl_dollars") or 0) > 0
        for p in t.get("patterns", []):
            p_lower = p.lower().strip()
            if not p_lower:
                continue
            if p_lower not in short_pattern_stats:
                short_pattern_stats[p_lower] = {"wins": 0, "losses": 0}
            if is_win:
                short_pattern_stats[p_lower]["wins"] += 1
            else:
                short_pattern_stats[p_lower]["losses"] += 1

    suppression_lines: list[str] = []

    for pattern, stats in short_pattern_stats.items():
        total = stats["wins"] + stats["losses"]
        if total >= 2 and stats["wins"] == 0:
            suppression_lines.append(
                f"Pattern alert: {pattern} 0/{total} in last 2 weeks -- reduce confidence by 40%"
            )

    for sector, s in short_sector_stats.items():
        total = s.get("total", s["wins"] + s["losses"])
        if total >= FINMEM_MIN_SAMPLE and s.get("win_rate", 100) < 33:
            suppression_lines.append(
                f"Sector alert: {sector} {s['wins']}/{total} wins "
                "-- suppress sector signals this week"
            )

    if suppression_lines:
        lines.extend(suppression_lines)

    return lines


def _format_long_term_memory(metrics: dict, total_trades: int) -> list[str]:
    """Format the long-term memory section (all-time statistics).

    Includes pattern accuracy, sector win rates, timeframe alignment,
    and confidence calibration.

    Args:
        metrics: Full computed metrics dictionary.
        total_trades: Total number of outcomes analyzed.

    Returns:
        List of formatted lines.
    """
    lines = [f"### LONG-TERM MEMORY ({total_trades} trades, all time)"]

    pattern_stats = metrics.get("pattern_stats", {})
    reportable = {k: v for k, v in pattern_stats.items() if v.get("total", 0) >= FINMEM_MIN_SAMPLE}
    if reportable:
        lines.append("PATTERN ACCURACY:")
        for pattern, stats in sorted(reportable.items(), key=lambda x: -x[1]["total"]):
            wr = stats["win_rate"]
            annotation = ""
            if wr >= 70:
                annotation = " -- increase confidence"
            elif wr <= 35:
                annotation = " -- reduce confidence by 40%"
            else:
                annotation = " -- neutral"
            lines.append(f"  {pattern}: {stats['wins']}/{stats['total']} ({wr:.0f}%){annotation}")

    sector_stats = metrics.get("sector_stats", {})
    reportable_sectors = {
        k: v for k, v in sector_stats.items() if v.get("total", 0) >= FINMEM_MIN_SAMPLE
    }
    if reportable_sectors:
        lines.append("SECTOR WIN RATES:")
        sector_parts = []
        for sector, stats in sorted(reportable_sectors.items(), key=lambda x: -x[1]["win_rate"]):
            sector_parts.append(
                f"  {sector}: {stats['wins']}/{stats['total']} ({stats['win_rate']:.0f}%)"
            )
        lines.extend(sector_parts)

    alignment = metrics.get("alignment_stats", {})
    if alignment:
        lines.append("TIMEFRAME ALIGNMENT:")
        labels = {
            "all_agree": "All TFs agree",
            "partial": "Partial agreement",
            "single_tf": "Single TF only",
        }
        annotations = {
            "all_agree": " -- HIGH confidence",
            "partial": " -- moderate confidence",
            "single_tf": " -- DO NOT FIRE",
        }
        for key in ("all_agree", "partial", "single_tf"):
            if key in alignment:
                a = alignment[key]
                lines.append(
                    f"  {labels[key]}: {a['wins']}/{a['total']} "
                    f"({a['win_rate']:.0f}%){annotations[key]}"
                )

    cal = metrics.get("confidence_calibration", {})
    if cal:
        lines.append("CONFIDENCE CALIBRATION:")
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

    # Phase 6: Track agreement win rates
    ta_stats = metrics.get("track_agreement_stats", {})
    if ta_stats:
        lines.append("SIGNAL ACCURACY BY TRACK AGREEMENT:")
        labels = {
            "3_of_3": "3/3 agree",
            "2_of_3": "2/3 agree",
            "disagree": "Full disagree",
        }
        for key in ("3_of_3", "2_of_3", "disagree"):
            if key in ta_stats:
                s = ta_stats[key]
                lines.append(
                    f"  {labels[key]}: {s['win_rate']:.0f}% win rate ({s['total']} trades)"
                )

    # Phase 6: EMA cross age win rates
    ema_stats = metrics.get("ema_cross_age_stats", {})
    if ema_stats:
        lines.append("SIGNAL ACCURACY BY EMA CROSS AGE:")
        labels = {
            "fresh": "Cross within last 2 candles",
            "recent": "Cross 3-5 candles ago",
            "stale": "Cross 6+ candles ago",
        }
        for key in ("fresh", "recent", "stale"):
            if key in ema_stats:
                s = ema_stats[key]
                lines.append(
                    f"  {labels[key]}: {s['win_rate']:.0f}% win rate ({s['total']} trades)"
                )

    # Phase 6: Failure mode frequency (losses only)
    fm_stats = metrics.get("failure_mode_stats", [])
    if fm_stats:
        total_failures = sum(count for _, count in fm_stats)
        lines.append("MOST COMMON FAILURE MODES:")
        for i, (mode, count) in enumerate(fm_stats[:3]):
            pct = round((count / total_failures) * 100) if total_failures > 0 else 0
            label = mode.replace("_", " ").title()
            rank = ["Most common", "Second most common", "Third"][i] if i < 3 else f"#{i + 1}"
            lines.append(f"  {rank}: {label} ({pct}% of losses, {count} trades)")

    # Phase 6: Slippage stats
    slip_stats = metrics.get("slippage_stats", {})
    if slip_stats:
        lines.append(
            f"EXECUTION SLIPPAGE: avg {slip_stats['avg_pct']:+.3f}%, "
            f"range [{slip_stats['min_pct']:+.3f}%, {slip_stats['max_pct']:+.3f}%] "
            f"({int(slip_stats['count'])} trades)"
        )

    return lines


def build_memory_injection(
    metrics: dict,
    outcomes: list[dict],
    total_trades: int,
) -> str:
    """Build the two-layer FinMem injection for GPT Judge.

    Replaces the old ``_build_data_section()`` with structured
    short-term (14 days) and long-term (all history) memory.

    Args:
        metrics: Full computed metrics dictionary.
        outcomes: All outcome records.
        total_trades: Total number of outcomes.

    Returns:
        Formatted memory injection string for GPT Judge.
    """
    lines = ["## HISTORICAL PERFORMANCE (Live Trades)"]

    short_outcomes, _all = _split_short_long_outcomes(outcomes)
    lines.extend(_format_short_term_memory(metrics, short_outcomes))
    lines.append("")
    lines.extend(_format_long_term_memory(metrics, total_trades))

    action_parts: list[str] = []
    if metrics.get("buy_win_rate") is not None:
        action_parts.append(f"BUY {metrics['buy_win_rate']}%")
    if metrics.get("sell_win_rate") is not None:
        action_parts.append(f"SHORT {metrics['sell_win_rate']}%")
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
            model=REFLECTION_MODEL,
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
