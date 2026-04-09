"""Strategy CRUD service.

Strategies are the core configuration unit. Each strategy defines how
every pipeline stage behaves — from Perplexity screening to GPT synthesis.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Literal, cast

from database.connection import get_db
from pipeline.schemas import FmpScreenerConfig, RiskParams, StrategyConfig

logger = logging.getLogger(__name__)


def _apply_listing_currency_to_screener(
    fmp: FmpScreenerConfig | None, listing_currency: str
) -> FmpScreenerConfig | None:
    """Align FMP stock screener country/exchange with listing currency.

    Crypto screeners are left unchanged. USD maps to US-listed equities without
    a single-exchange constraint; CAD maps to Canada with TSX as default venue.

    Args:
        fmp: Existing screener config (may be None).
        listing_currency: ``\"USD\"`` or ``\"CAD\"`` (case-insensitive).

    Returns:
        Updated config or None.
    """
    if fmp is None or fmp.is_crypto:
        return fmp
    lc = (listing_currency or "CAD").strip().upper()
    if lc == "USD":
        return fmp.model_copy(update={"country": "US", "exchange": None})
    if lc == "CAD":
        ex = fmp.exchange if fmp.exchange else "TSX"
        return fmp.model_copy(update={"country": "CA", "exchange": ex})
    return fmp


def _infer_listing_currency(
    row: dict[str, Any], fmp: FmpScreenerConfig | None
) -> Literal["USD", "CAD"]:
    """Resolve listing currency from DB column or FMP country fallback."""
    raw = row.get("listing_currency")
    if isinstance(raw, str) and raw.strip().upper() in ("USD", "CAD"):
        return cast(Literal["USD", "CAD"], raw.strip().upper())
    if fmp and not fmp.is_crypto and fmp.country:
        c = fmp.country.strip().upper()
        if c == "US":
            return "USD"
    return "CAD"


def _sync_equity_screener_with_listing_currency(config: StrategyConfig) -> StrategyConfig:
    """Return a copy with FMP screener matched to ``listing_currency``."""
    updated = _apply_listing_currency_to_screener(config.fmp_screener, config.listing_currency)
    if updated is config.fmp_screener:
        return config
    return config.model_copy(update={"fmp_screener": updated})


_UUID_HEX_RE = re.compile(r"^[0-9a-f]{32}$")
_UUID_DASHED_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _validate_user_id(user_id: str) -> str:
    """Validate that a user_id is a safe UUID before using it in filters.

    Args:
        user_id: The user ID from JWT claims.

    Returns:
        The validated user_id string.

    Raises:
        ValueError: If user_id does not match a UUID pattern.
    """
    if _UUID_HEX_RE.match(user_id) or _UUID_DASHED_RE.match(user_id) or user_id == "dev-user-local":
        return user_id
    raise ValueError(f"Invalid user_id format: {user_id!r}")


TEMPLATES_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "templates" / "strategies.json"
)


def _row_to_config(row: dict[str, Any]) -> StrategyConfig:
    """Convert a database row to a StrategyConfig model."""
    chart_indicators = row.get("chart_indicators")
    if isinstance(chart_indicators, str):
        chart_indicators = json.loads(chart_indicators)
    chart_indicators = chart_indicators or []

    risk_params_raw = row.get("risk_params")
    if isinstance(risk_params_raw, str):
        risk_params_raw = json.loads(risk_params_raw) if risk_params_raw else {}
    risk_params = RiskParams(**risk_params_raw) if risk_params_raw else RiskParams()

    additional_tf_raw = row.get("additional_timeframes")
    if isinstance(additional_tf_raw, str):
        additional_tf = json.loads(additional_tf_raw)
    elif isinstance(additional_tf_raw, list):
        additional_tf = additional_tf_raw
    else:
        secondary = row.get("secondary_timeframe", "4H")
        additional_tf = [secondary] if secondary else ["4H"]

    short_tf_raw = row.get("short_timeframes")
    if isinstance(short_tf_raw, str):
        short_tf = json.loads(short_tf_raw)
    elif isinstance(short_tf_raw, list):
        short_tf = short_tf_raw
    else:
        short_tf = []

    short_tf_ind_raw = row.get("short_tf_indicators")
    if isinstance(short_tf_ind_raw, str):
        short_tf_ind = json.loads(short_tf_ind_raw)
    elif isinstance(short_tf_ind_raw, list):
        short_tf_ind = short_tf_ind_raw
    else:
        short_tf_ind = ["VWAP", "Stochastic", "EMA_20", "ATR", "Volume"]

    fmp_raw = row.get("fmp_screener")
    fmp_screener: FmpScreenerConfig | None = None
    if fmp_raw:
        if isinstance(fmp_raw, str):
            fmp_raw = json.loads(fmp_raw)
        if isinstance(fmp_raw, dict):
            fmp_screener = FmpScreenerConfig(**fmp_raw)

    listing_currency = _infer_listing_currency(row, fmp_screener)

    return StrategyConfig(
        id=row["id"],
        name=row["name"],
        description=row.get("description") or "",
        fmp_screener=fmp_screener,
        screening_prompt=row["screening_prompt"],
        constraint_style=row["constraint_style"],
        max_tickers=row["max_tickers"],
        chart_indicators=chart_indicators,
        chart_timeframe=row["chart_timeframe"],
        secondary_timeframe=row.get("secondary_timeframe", "4H"),
        additional_timeframes=additional_tf,
        short_timeframes=short_tf,
        short_tf_indicators=short_tf_ind,
        ta_focus=row.get("ta_focus"),
        news_recency=row["news_recency"],
        news_scope=row["news_scope"],
        trading_style=row.get("trading_style") or "",
        risk_params=risk_params,
        enable_debate=bool(row.get("enable_debate", True)),
        is_template=bool(row.get("is_template", False)),
        recommended=bool(row.get("recommended", False)),
        strategy_type=row.get("strategy_type") or "swing",
        listing_currency=listing_currency,
    )


async def list_strategies(user_id: str) -> list[StrategyConfig]:
    """List all user-created strategies (excludes templates)."""
    safe_id = _validate_user_id(user_id)
    client = await get_db()
    response = await (
        client.table("strategies")
        .select("*")
        .eq("is_template", False)
        .in_("user_id", [safe_id, "system"])
        .order("name")
        .execute()
    )
    rows = response.data or []
    return [_row_to_config(r) for r in rows]


async def list_templates() -> list[StrategyConfig]:
    """List all strategy templates."""
    client = await get_db()
    response = await (
        client.table("strategies").select("*").eq("is_template", True).order("name").execute()
    )
    rows = response.data or []
    return [_row_to_config(r) for r in rows]


async def get_strategy(strategy_id: str, user_id: str) -> StrategyConfig | None:
    """Get a strategy by ID if it belongs to the user or is a system template."""
    safe_id = _validate_user_id(user_id)
    client = await get_db()
    response = await (
        client.table("strategies")
        .select("*")
        .eq("id", strategy_id)
        .in_("user_id", [safe_id, "system"])
        .maybe_single()
        .execute()
    )
    row = response.data
    return _row_to_config(row) if row else None


async def create_strategy(config: StrategyConfig, user_id: str) -> StrategyConfig:
    """Create a new strategy."""
    client = await get_db()
    strategy_id = config.id or uuid.uuid4().hex
    config = _sync_equity_screener_with_listing_currency(config)

    payload = {
        "id": strategy_id,
        "user_id": user_id,
        "name": config.name,
        "description": config.description,
        "fmp_screener": (
            json.dumps(config.fmp_screener.model_dump()) if config.fmp_screener else None
        ),
        "screening_prompt": config.screening_prompt,
        "constraint_style": config.constraint_style,
        "max_tickers": config.max_tickers,
        "chart_indicators": json.dumps(config.chart_indicators),
        "chart_timeframe": config.chart_timeframe,
        "secondary_timeframe": config.secondary_timeframe,
        "additional_timeframes": json.dumps(config.additional_timeframes),
        "short_timeframes": json.dumps(config.short_timeframes),
        "short_tf_indicators": json.dumps(config.short_tf_indicators),
        "ta_focus": config.ta_focus,
        "news_recency": config.news_recency,
        "news_scope": config.news_scope,
        "trading_style": config.trading_style,
        "risk_params": json.dumps(config.risk_params.model_dump()),
        "enable_debate": config.enable_debate,
        "is_template": config.is_template,
        "recommended": config.recommended,
        "strategy_type": config.strategy_type,
        "listing_currency": config.listing_currency,
    }
    await client.table("strategies").insert(payload).execute()
    config.id = strategy_id
    return config


async def update_strategy(strategy_id: str, config: StrategyConfig, user_id: str) -> StrategyConfig:
    """Update an existing strategy owned by the user.

    Templates cannot be updated. The strategy must belong to the user.

    Args:
        strategy_id: UUID of the strategy to update.
        config: Updated strategy configuration.
        user_id: Owner user UUID.

    Returns:
        The updated strategy configuration.

    Raises:
        ValueError: If the strategy doesn't exist, isn't owned by user, or is a template.
    """
    safe_id = _validate_user_id(user_id)
    client = await get_db()

    existing_resp = await (
        client.table("strategies")
        .select("id, user_id, is_template")
        .eq("id", strategy_id)
        .maybe_single()
        .execute()
    )
    row_data = existing_resp.data if existing_resp else None
    if not row_data or not isinstance(row_data, dict):
        raise ValueError(f"Strategy '{strategy_id}' not found")
    if row_data.get("is_template"):
        raise ValueError("Cannot update a template strategy")
    if row_data.get("user_id") not in (safe_id, "system"):
        raise ValueError("Strategy does not belong to this user")

    config = _sync_equity_screener_with_listing_currency(config)

    payload = {
        "name": config.name,
        "description": config.description,
        "fmp_screener": (
            json.dumps(config.fmp_screener.model_dump()) if config.fmp_screener else None
        ),
        "screening_prompt": config.screening_prompt,
        "constraint_style": config.constraint_style,
        "max_tickers": config.max_tickers,
        "chart_indicators": json.dumps(config.chart_indicators),
        "chart_timeframe": config.chart_timeframe,
        "secondary_timeframe": config.secondary_timeframe,
        "additional_timeframes": json.dumps(config.additional_timeframes),
        "short_timeframes": json.dumps(config.short_timeframes),
        "short_tf_indicators": json.dumps(config.short_tf_indicators),
        "ta_focus": config.ta_focus,
        "news_recency": config.news_recency,
        "news_scope": config.news_scope,
        "trading_style": config.trading_style,
        "risk_params": json.dumps(config.risk_params.model_dump()),
        "enable_debate": config.enable_debate,
        "listing_currency": config.listing_currency,
    }
    await client.table("strategies").update(payload).eq("id", strategy_id).execute()
    config.id = strategy_id
    return config


async def delete_strategy(strategy_id: str, user_id: str) -> None:
    """Delete a strategy owned by the user.

    Templates cannot be deleted.

    Args:
        strategy_id: UUID of the strategy to delete.
        user_id: Owner user UUID.

    Raises:
        ValueError: If the strategy doesn't exist, isn't owned by user, or is a template.
    """
    safe_id = _validate_user_id(user_id)
    client = await get_db()

    existing_resp = await (
        client.table("strategies")
        .select("id, user_id, is_template")
        .eq("id", strategy_id)
        .maybe_single()
        .execute()
    )
    row_data = existing_resp.data if existing_resp else None
    if not row_data or not isinstance(row_data, dict):
        raise ValueError(f"Strategy '{strategy_id}' not found")
    if row_data.get("is_template"):
        raise ValueError("Cannot delete a template strategy")
    if row_data.get("user_id") not in (safe_id, "system"):
        raise ValueError("Strategy does not belong to this user")

    await client.table("strategies").delete().eq("id", strategy_id).execute()
    logger.info("Deleted strategy %s for user %s", strategy_id, safe_id)


async def ensure_defaults() -> None:
    """Sync strategy templates from JSON file into the database.

    Inserts new templates and updates existing ones (matched by name).
    Preserves IDs of existing templates so pipeline run history stays intact.
    """
    if not TEMPLATES_PATH.exists():
        logger.info("No templates file found — skipping template sync")
        return

    client = await get_db()

    existing_resp = await (
        client.table("strategies").select("id, name").eq("is_template", True).execute()
    )
    existing_by_name: dict[str, str] = {
        row["name"]: row["id"] for row in (existing_resp.data or [])
    }

    templates = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    inserted = 0
    updated = 0

    for tmpl in templates:
        tmpl.setdefault("id", uuid.uuid4().hex)
        tmpl.setdefault("is_template", True)
        risk = tmpl.pop("risk_params", {})
        fmp_raw = tmpl.pop("fmp_screener", None)
        listing_raw = str(tmpl.pop("listing_currency", "CAD")).strip().upper()
        listing_currency = listing_raw if listing_raw in ("USD", "CAD") else "CAD"
        fmp = FmpScreenerConfig(**fmp_raw) if isinstance(fmp_raw, dict) else None
        fmp = _apply_listing_currency_to_screener(fmp, listing_currency)
        config = StrategyConfig(
            **tmpl,
            risk_params=RiskParams(**risk),
            fmp_screener=fmp,
            listing_currency=cast(Literal["USD", "CAD"], listing_currency),
        )

        existing_id = existing_by_name.get(config.name)
        if existing_id:
            config.id = existing_id
            payload = {
                "description": config.description,
                "fmp_screener": (
                    json.dumps(config.fmp_screener.model_dump()) if config.fmp_screener else None
                ),
                "screening_prompt": config.screening_prompt,
                "constraint_style": config.constraint_style,
                "max_tickers": config.max_tickers,
                "chart_indicators": json.dumps(config.chart_indicators),
                "chart_timeframe": config.chart_timeframe,
                "secondary_timeframe": config.secondary_timeframe,
                "additional_timeframes": json.dumps(config.additional_timeframes),
                "short_timeframes": json.dumps(config.short_timeframes),
                "short_tf_indicators": json.dumps(config.short_tf_indicators),
                "ta_focus": config.ta_focus,
                "news_recency": config.news_recency,
                "news_scope": config.news_scope,
                "trading_style": config.trading_style,
                "risk_params": json.dumps(config.risk_params.model_dump()),
                "enable_debate": config.enable_debate,
                "recommended": config.recommended,
                "strategy_type": config.strategy_type,
                "listing_currency": config.listing_currency,
            }
            await client.table("strategies").update(payload).eq("id", existing_id).execute()
            updated += 1
        else:
            await create_strategy(config, user_id="system")
            inserted += 1

    logger.info(
        "Template sync complete: %d inserted, %d updated (from %s)",
        inserted,
        updated,
        TEMPLATES_PATH,
    )
