"""Strategy CRUD service.

Strategies are the core configuration unit. Each strategy defines how
every pipeline stage behaves — from Perplexity screening to GPT synthesis.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import aiosqlite

from database.connection import get_db
from pipeline.schemas import RiskParams, StrategyConfig

logger = logging.getLogger(__name__)

TEMPLATES_PATH = Path(__file__).resolve().parents[3] / "templates" / "strategies.json"


def _row_to_config(row: aiosqlite.Row) -> StrategyConfig:
    """Convert a database row to a StrategyConfig model."""
    return StrategyConfig(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        screening_prompt=row["screening_prompt"],
        constraint_style=row["constraint_style"],
        max_tickers=row["max_tickers"],
        chart_indicators=json.loads(row["chart_indicators"]),
        chart_timeframe=row["chart_timeframe"],
        ta_focus=row["ta_focus"],
        news_recency=row["news_recency"],
        news_scope=row["news_scope"],
        trading_style=row["trading_style"] or "",
        risk_params=RiskParams(**json.loads(row["risk_params"]))
        if row["risk_params"]
        else RiskParams(),
        enable_debate=bool(row["enable_debate"]),
        is_template=bool(row["is_template"]),
    )


async def list_strategies() -> list[StrategyConfig]:
    """Return all saved strategies (excluding templates)."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM strategies WHERE is_template = 0 ORDER BY name")
    rows = await cursor.fetchall()
    return [_row_to_config(r) for r in rows]


async def list_templates() -> list[StrategyConfig]:
    """Return all strategy templates."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM strategies WHERE is_template = 1 ORDER BY name")
    rows = await cursor.fetchall()
    return [_row_to_config(r) for r in rows]


async def get_strategy(strategy_id: str) -> StrategyConfig | None:
    """Fetch a single strategy by ID."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,))
    row = await cursor.fetchone()
    return _row_to_config(row) if row else None


async def create_strategy(config: StrategyConfig) -> StrategyConfig:
    """Insert a new strategy into the database.

    Args:
        config: The strategy configuration to persist.

    Returns:
        The persisted strategy (with generated ID if needed).
    """
    db = await get_db()
    strategy_id = config.id or uuid.uuid4().hex

    await db.execute(
        """
        INSERT INTO strategies (
            id, name, description, screening_prompt, constraint_style,
            max_tickers, chart_indicators, chart_timeframe, ta_focus,
            news_recency, news_scope, trading_style, risk_params,
            enable_debate, is_template
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            strategy_id,
            config.name,
            config.description,
            config.screening_prompt,
            config.constraint_style,
            config.max_tickers,
            json.dumps(config.chart_indicators),
            config.chart_timeframe,
            config.ta_focus,
            config.news_recency,
            config.news_scope,
            config.trading_style,
            json.dumps(config.risk_params.model_dump()),
            config.enable_debate,
            config.is_template,
        ),
    )
    await db.commit()
    config.id = strategy_id
    return config


async def ensure_defaults() -> None:
    """Load default strategy and templates if the strategies table is empty.

    Called once at startup. Loads from ``templates/strategies.json`` if it
    exists, otherwise inserts a single hardcoded default screener.
    """
    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) as cnt FROM strategies")
    row = await cursor.fetchone()
    if row and row["cnt"] > 0:
        return

    if TEMPLATES_PATH.exists():
        logger.info("Loading strategy templates from %s", TEMPLATES_PATH)
        templates = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
        for tmpl in templates:
            tmpl.setdefault("id", uuid.uuid4().hex)
            tmpl.setdefault("is_template", True)
            risk = tmpl.pop("risk_params", {})
            config = StrategyConfig(**tmpl, risk_params=RiskParams(**risk))
            await create_strategy(config)
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
            is_template=False,
        )
        await create_strategy(default)

    logger.info("Default strategies loaded.")
