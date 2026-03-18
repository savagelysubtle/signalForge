"""Strategy CRUD service.

Strategies are the core configuration unit. Each strategy defines how
every pipeline stage behaves — from Perplexity screening to GPT synthesis.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import asyncpg

from database.connection import get_db
from pipeline.schemas import RiskParams, StrategyConfig

logger = logging.getLogger(__name__)

TEMPLATES_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "templates" / "strategies.json"
)


def _row_to_config(row: asyncpg.Record) -> StrategyConfig:
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


async def list_strategies(user_id: str) -> list[StrategyConfig]:
    """Return all saved strategies for a user (user's strategies + templates).

    Args:
        user_id: The user ID to filter strategies for.

    Returns:
        List of user's strategies and all templates (user_id = 'system').
    """
    pool = await get_db()
    rows = await pool.fetch(
        "SELECT * FROM strategies WHERE user_id = $1 OR user_id = 'system' ORDER BY name",
        user_id,
    )
    return [_row_to_config(r) for r in rows]


async def list_templates() -> list[StrategyConfig]:
    """Return all strategy templates."""
    pool = await get_db()
    rows = await pool.fetch("SELECT * FROM strategies WHERE is_template = true ORDER BY name")
    return [_row_to_config(r) for r in rows]


async def get_strategy(strategy_id: str, user_id: str) -> StrategyConfig | None:
    """Fetch a single strategy by ID, ensuring user has access.

    Args:
        strategy_id: The strategy ID to fetch.
        user_id: The user ID requesting the strategy.

    Returns:
        The strategy if found and user has access (owns it or it's a template), else None.
    """
    pool = await get_db()
    row = await pool.fetchrow(
        "SELECT * FROM strategies WHERE id = $1 AND (user_id = $2 OR user_id = 'system')",
        strategy_id,
        user_id,
    )
    return _row_to_config(row) if row else None


async def create_strategy(config: StrategyConfig, user_id: str) -> StrategyConfig:
    """Insert a new strategy into the database.

    Args:
        config: The strategy configuration to persist.
        user_id: The user ID that owns this strategy.

    Returns:
        The persisted strategy (with generated ID if needed).
    """
    pool = await get_db()
    strategy_id = config.id or uuid.uuid4().hex

    await pool.execute(
        """
        INSERT INTO strategies (
            id, user_id, name, description, screening_prompt, constraint_style,
            max_tickers, chart_indicators, chart_timeframe, ta_focus,
            news_recency, news_scope, trading_style, risk_params,
            enable_debate, is_template
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
        """,
        strategy_id,
        user_id,
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
    )
    config.id = strategy_id
    return config


async def ensure_defaults() -> None:
    """Load default strategy and templates if the strategies table is empty.

    Called once at startup. Loads from ``templates/strategies.json`` if it
    exists, otherwise inserts a single hardcoded default screener.
    Templates are stored with user_id = 'system'.
    """
    pool = await get_db()
    row = await pool.fetchrow("SELECT COUNT(*) as cnt FROM strategies")
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
