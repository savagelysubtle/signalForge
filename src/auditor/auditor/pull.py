"""Supabase data puller for pipeline audit.

Fetches recommendations, pipeline runs, strategies, decisions, and outcomes
from the SignalForge Supabase database using service-role credentials.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from supabase import create_client

from auditor.config import supabase_key, supabase_url

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

REC_SELECT = (
    "id, run_id, ticker, action, confidence, confidence_label, "
    "entry_price, stop_loss, take_profit, position_size_pct, "
    "risk_reward_ratio, holding_period, entry_valid_window, "
    "bull_case, bear_case, judge_reasoning, key_factors, warnings, "
    "signal_generated_at, price_at_signal, created_at, "
    "track_agreement, expected_value"
)


def normalize_ticker(raw: str) -> str:
    """Convert exchange-prefixed ticker to yfinance-compatible format.

    Mappings:
        TSX:SHOP   -> SHOP.TO
        TSXV:PYR   -> PYR.V
        BTC        -> BTC-USD  (known crypto, yfinance format)
        AAPL       -> AAPL     (US, unchanged)
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
        return base + "-USD"
    if base.endswith("USD") and base[:-3] in KNOWN_CRYPTO:
        return base[:-3] + "-USD"
    return raw


def _get_client() -> Any:
    """Create a Supabase client using service-role credentials."""
    return create_client(supabase_url(), supabase_key())


def _paginated_fetch(
    client: Any,
    table: str,
    select: str,
    page_size: int = PAGE_SIZE,
) -> list[dict[str, Any]]:
    """Fetch all rows from a table using offset-based pagination."""
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


def pull_all(
    since: str | None = None,
    until: str | None = None,
    tickers: list[str] | None = None,
) -> pd.DataFrame:
    """Pull all recommendations with enriched context from Supabase.

    Args:
        since: ISO date string — only include recs created on or after this date.
        until: ISO date string — only include recs created on or before this date.
        tickers: If provided, only include these tickers.

    Returns:
        DataFrame with recommendation + strategy + decision + outcome columns.
    """
    client = _get_client()

    logger.info("Fetching recommendations from Supabase...")
    rec_rows = _paginated_fetch(client, "recommendations", REC_SELECT)
    if not rec_rows:
        logger.warning("No recommendations found in Supabase")
        return pd.DataFrame()
    logger.info("Fetched %d recommendations", len(rec_rows))

    logger.info("Fetching pipeline runs for strategy mapping...")
    run_rows = _paginated_fetch(client, "pipeline_runs", "id, strategy_id, mode")
    run_map: dict[str, dict[str, Any]] = {r["id"]: r for r in run_rows}

    strategy_ids = {r["strategy_id"] for r in run_rows if r.get("strategy_id")}
    strat_name_map: dict[str, str] = {}
    if strategy_ids:
        strat_rows = _paginated_fetch(client, "strategies", "id, name")
        strat_name_map = {s["id"]: s["name"] for s in strat_rows}

    logger.info("Fetching decisions...")
    dec_rows = _paginated_fetch(client, "decisions", "recommendation_id, decision, decided_at")
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
        row["strategy_name"] = strat_name_map.get(sid, "") if sid else ""
        row["pipeline_mode"] = run_data.get("mode", "")

        dec = dec_map.get(rec["id"], {})
        row["user_decision"] = dec.get("decision")

        out = out_map.get(rec["id"], {})
        row["logged_pnl_pct"] = out.get("pnl_percent")
        row["logged_exit_reason"] = out.get("exit_reason")
        row["logged_holding_days"] = out.get("holding_days")

        enriched.append(row)

    df = pd.DataFrame(enriched)

    if "ticker" in df.columns:
        df["ticker_original"] = df["ticker"]
        df["ticker"] = df["ticker"].apply(normalize_ticker)

    for col in ("created_at", "signal_generated_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True)

    if since and "created_at" in df.columns:
        cutoff = pd.Timestamp(since, tz="UTC")
        df = df[df["created_at"] >= cutoff]

    if until and "created_at" in df.columns:
        cutoff = pd.Timestamp(until, tz="UTC")
        df = df[df["created_at"] <= cutoff]

    if tickers:
        normalized = {normalize_ticker(t) for t in tickers}
        df = df[df["ticker"].isin(normalized)]

    logger.info(
        "Pull complete: %d recommendations after filtering (since=%s, until=%s, tickers=%s)",
        len(df),
        since,
        until,
        tickers,
    )
    return df
