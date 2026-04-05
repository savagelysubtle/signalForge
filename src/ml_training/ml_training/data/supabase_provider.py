"""Supabase client for pulling live pipeline data into the ML training pipeline.

Fetches historical recommendations, decisions, outcomes, and shadow predictions
from the SignalForge Supabase database using the service role key (offline access).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

PAGE_SIZE = 1000

KNOWN_CRYPTO = frozenset(
    {
        "BTC",
        "ETH",
        "SOL",
        "BNB",
        "XRP",
        "ADA",
        "DOGE",
        "DOT",
        "AVAX",
        "MATIC",
        "LINK",
        "UNI",
        "ATOM",
        "LTC",
        "FIL",
        "NEAR",
        "APT",
        "ARB",
        "OP",
        "SUI",
        "PEPE",
        "SHIB",
        "TRX",
        "TON",
        "INJ",
        "FET",
        "RNDR",
    }
)


def normalize_ticker(raw: str) -> str:
    """Convert exchange-prefixed ticker to ParquetStore internal format.

    Mappings:
        TSX:SHOP   → SHOP.TO
        TSXV:PYR   → PYR.V
        BTC        → BTCUSD  (known crypto)
        AAPL       → AAPL    (US, unchanged)
    """
    if not raw:
        return raw

    raw = raw.strip()

    if raw.startswith("TSX:"):
        return raw[4:] + ".TO"
    if raw.startswith("TSXV:"):
        return raw[5:] + ".V"

    base = raw.upper()
    if base in KNOWN_CRYPTO:
        return base + "USD"

    return raw


@dataclass
class SupabasePullResult:
    """Summary of a Supabase data pull."""

    recommendations: int = 0
    with_decisions: int = 0
    with_outcomes: int = 0
    strategies_found: list[str] | None = None


def _get_client() -> Any:
    """Create a Supabase client using service role credentials.

    Returns:
        Supabase client instance.

    Raises:
        SystemExit: If SUPABASE_URL or SUPABASE_SERVICE_KEY are not set.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")

    if not url or not key:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_KEY (or SUPABASE_KEY) must be set in .env")
        raise SystemExit(1)

    from supabase import create_client

    return create_client(url, key)


def _paginated_fetch(
    client: Any, table: str, select: str, page_size: int = PAGE_SIZE
) -> list[dict[str, Any]]:
    """Fetch all rows from a table using offset-based pagination.

    Args:
        client: Supabase client.
        table: Table name.
        select: Column selection string.
        page_size: Rows per page.

    Returns:
        List of all row dicts.
    """
    all_rows: list[dict[str, Any]] = []
    offset = 0

    while True:
        result = client.table(table).select(select).range(offset, offset + page_size - 1).execute()
        rows = result.data or []
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size

    return all_rows


def pull_recommendations() -> pd.DataFrame:
    """Pull all recommendations from Supabase with joined decisions and outcomes.

    Fetches recommendations, then enriches each with its associated decision
    and outcome data (if any).

    Returns:
        DataFrame with recommendation + decision + outcome columns.
    """
    client = _get_client()

    logger.info("Fetching recommendations from Supabase...")
    rec_rows = _paginated_fetch(
        client,
        "recommendations",
        "id, run_id, ticker, action, confidence, entry_price, stop_loss, "
        "take_profit, risk_reward_ratio, holding_period, judge_reasoning, "
        "key_factors, warnings, created_at, signal_generated_at, "
        "price_at_signal, position_size_pct",
    )

    if not rec_rows:
        logger.warning("No recommendations found in Supabase")
        return pd.DataFrame()

    logger.info("Fetched %d recommendations", len(rec_rows))

    logger.info("Fetching pipeline runs for strategy mapping...")
    run_rows = _paginated_fetch(
        client,
        "pipeline_runs",
        "id, strategy_id, mode",
    )
    run_map: dict[str, dict[str, Any]] = {r["id"]: r for r in run_rows}

    strategy_ids = {r["strategy_id"] for r in run_rows if r.get("strategy_id")}
    strat_name_map: dict[str, str] = {}
    if strategy_ids:
        strat_rows = _paginated_fetch(client, "strategies", "id, name")
        strat_name_map = {s["id"]: s["name"] for s in strat_rows}

    logger.info("Fetching decisions...")
    dec_rows = _paginated_fetch(
        client,
        "decisions",
        "recommendation_id, decision, decided_at",
    )
    dec_map: dict[str, dict[str, Any]] = {d["recommendation_id"]: d for d in dec_rows}

    logger.info("Fetching outcomes...")
    out_rows = _paginated_fetch(
        client,
        "outcomes",
        "recommendation_id, pnl_percent, exit_reason, holding_days, failure_mode",
    )
    out_map: dict[str, dict[str, Any]] = {o["recommendation_id"]: o for o in out_rows}

    enriched: list[dict[str, Any]] = []
    for rec in rec_rows:
        row: dict[str, Any] = {**rec}

        run_data = run_map.get(rec.get("run_id", ""), {})
        sid = run_data.get("strategy_id", "")
        row["strategy_template"] = strat_name_map.get(sid, "") if sid else ""
        row["pipeline_mode"] = run_data.get("mode", "")

        dec = dec_map.get(rec["id"], {})
        row["user_decision"] = dec.get("decision")
        row["decided_at"] = dec.get("decided_at")

        out = out_map.get(rec["id"], {})
        row["outcome_pnl_percent"] = out.get("pnl_percent")
        row["outcome_exit_reason"] = out.get("exit_reason")
        row["outcome_holding_days"] = out.get("holding_days")
        row["outcome_failure_mode"] = out.get("failure_mode")

        enriched.append(row)

    df = pd.DataFrame(enriched)

    if "ticker" in df.columns:
        df["ticker_original"] = df["ticker"]
        df["ticker"] = df["ticker"].apply(normalize_ticker)
        n_changed = (df["ticker"] != df["ticker_original"]).sum()
        if n_changed:
            logger.info(
                "Normalized %d/%d tickers (TSX:/TSXV:/crypto → internal format)", n_changed, len(df)
            )

    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
    if "signal_generated_at" in df.columns:
        df["signal_generated_at"] = pd.to_datetime(df["signal_generated_at"], utc=True)

    strategies = (
        df["strategy_template"].dropna().unique().tolist()
        if "strategy_template" in df.columns
        else []
    )
    with_dec = int(df["user_decision"].notna().sum()) if "user_decision" in df.columns else 0
    with_out = (
        int(df["outcome_pnl_percent"].notna().sum()) if "outcome_pnl_percent" in df.columns else 0
    )

    logger.info(
        "Pull complete: %d recs, %d with decisions, %d with outcomes, %d strategies",
        len(df),
        with_dec,
        with_out,
        len(strategies),
    )

    return df


def pull_shadow_predictions(unresolved_only: bool = False) -> pd.DataFrame:
    """Pull ML shadow predictions from Supabase.

    Args:
        unresolved_only: If True, only fetch rows where actual_direction is null.

    Returns:
        DataFrame of shadow prediction rows.
    """
    client = _get_client()

    select = (
        "id, run_id, ticker, strategy_type, prediction_date, "
        "ml_direction, ml_confidence, ml_reliability, "
        "gpt_action, gpt_confidence, model_version, "
        "actual_direction, actual_return_10d, ml_correct, gpt_correct, updated_at"
    )

    if unresolved_only:
        all_rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            result = (
                client.table("ml_shadow_predictions")
                .select(select)
                .is_("actual_direction", "null")
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
            )
            rows = result.data or []
            if not rows:
                break
            all_rows.extend(rows)
            if len(rows) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    else:
        all_rows = _paginated_fetch(client, "ml_shadow_predictions", select)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    if "prediction_date" in df.columns:
        df["prediction_date"] = pd.to_datetime(df["prediction_date"], utc=True)
    return df


def update_shadow_outcomes(updates: list[dict[str, Any]]) -> int:
    """Batch-update resolved shadow prediction outcomes in Supabase.

    Args:
        updates: List of dicts with 'id' plus outcome fields to update.

    Returns:
        Number of rows updated.
    """
    if not updates:
        return 0

    client = _get_client()
    updated = 0

    for batch_start in range(0, len(updates), 50):
        batch = updates[batch_start : batch_start + 50]
        for row in batch:
            row_id = row.pop("id", None)
            if not row_id:
                continue
            try:
                client.table("ml_shadow_predictions").update(row).eq("id", row_id).execute()
                updated += 1
            except Exception:
                logger.warning("Failed to update shadow prediction %s", row_id, exc_info=True)

    logger.info("Updated %d shadow predictions in Supabase", updated)
    return updated
