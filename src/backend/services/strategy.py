"""Strategy CRUD service.

Strategies are the core configuration unit. Each strategy defines how
every pipeline stage behaves — from Perplexity screening to GPT synthesis.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from database.connection import get_db
from pipeline.schemas import RiskParams, StrategyConfig

logger = logging.getLogger(__name__)

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

    return StrategyConfig(
        id=row["id"],
        name=row["name"],
        description=row.get("description") or "",
        screening_prompt=row["screening_prompt"],
        constraint_style=row["constraint_style"],
        max_tickers=row["max_tickers"],
        chart_indicators=chart_indicators,
        chart_timeframe=row["chart_timeframe"],
        ta_focus=row.get("ta_focus"),
        news_recency=row["news_recency"],
        news_scope=row["news_scope"],
        trading_style=row.get("trading_style") or "",
        risk_params=risk_params,
        enable_debate=bool(row.get("enable_debate", True)),
        is_template=bool(row.get("is_template", False)),
    )


async def list_strategies(user_id: str) -> list[StrategyConfig]:
    """List all user-created strategies (excludes templates)."""
    client = await get_db()
    response = await (
        client.table("strategies")
        .select("*")
        .eq("is_template", False)
        .or_(f"user_id.eq.{user_id},user_id.eq.system")
        .order("name")
        .execute()
    )
    rows = response.data or []
    return [_row_to_config(r) for r in rows]


async def list_templates() -> list[StrategyConfig]:
    """List all strategy templates."""
    client = await get_db()
    response = await (
        client.table("strategies")
        .select("*")
        .eq("is_template", True)
        .order("name")
        .execute()
    )
    rows = response.data or []
    return [_row_to_config(r) for r in rows]


async def get_strategy(strategy_id: str, user_id: str) -> StrategyConfig | None:
    """Get a strategy by ID if it belongs to the user or is a system template."""
    client = await get_db()
    response = await (
        client.table("strategies")
        .select("*")
        .eq("id", strategy_id)
        .or_(f"user_id.eq.{user_id},user_id.eq.system")
        .maybe_single()
        .execute()
    )
    row = response.data
    return _row_to_config(row) if row else None


async def create_strategy(config: StrategyConfig, user_id: str) -> StrategyConfig:
    """Create a new strategy."""
    client = await get_db()
    strategy_id = config.id or uuid.uuid4().hex

    payload = {
        "id": strategy_id,
        "user_id": user_id,
        "name": config.name,
        "description": config.description,
        "screening_prompt": config.screening_prompt,
        "constraint_style": config.constraint_style,
        "max_tickers": config.max_tickers,
        "chart_indicators": json.dumps(config.chart_indicators),
        "chart_timeframe": config.chart_timeframe,
        "ta_focus": config.ta_focus,
        "news_recency": config.news_recency,
        "news_scope": config.news_scope,
        "trading_style": config.trading_style,
        "risk_params": json.dumps(config.risk_params.model_dump()),
        "enable_debate": config.enable_debate,
        "is_template": config.is_template,
    }
    await client.table("strategies").insert(payload).execute()
    config.id = strategy_id
    return config


async def ensure_defaults() -> None:
    """Load strategy templates if the strategies table is empty."""
    client = await get_db()
    response = await (
        client.table("strategies")
        .select("*", count="exact")
        .limit(0)
        .execute()
    )
    if response.count and response.count > 0:
        return

    if TEMPLATES_PATH.exists():
        logger.info("Loading strategy templates from %s", TEMPLATES_PATH)
        templates = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
        for tmpl in templates:
            tmpl.setdefault("id", uuid.uuid4().hex)
            tmpl.setdefault("is_template", True)
            risk = tmpl.pop("risk_params", {})
            config = StrategyConfig(**tmpl, risk_params=RiskParams(**risk))
            await create_strategy(config, user_id="system")
    else:
        logger.info("No templates file found — inserting default screener strategy")
        default = StrategyConfig(
            id=uuid.uuid4().hex,
            name="Default Screener",
            description="General-purpose stock and crypto screener",
            screening_prompt=(
                "Find stocks and cryptocurrencies showing strong momentum: "
                "rising relative volume, positive earnings revisions, "
                "and bullish technical setups. Include both US equities and "
                "top crypto assets if they meet the criteria."
            ),
            constraint_style="loose",
            max_tickers=10,
            chart_indicators=["RSI", "MACD", "Volume"],
            chart_timeframe="D",
            news_recency="week",
            news_scope="company",
            trading_style="Swing trader, 3-10 day holds, max 5% position size",
            risk_params=RiskParams(),
            enable_debate=True,
            is_template=True,
        )
        await create_strategy(default, user_id="system")

    logger.info("Default strategies loaded.")
