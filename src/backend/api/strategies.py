"""Strategy API endpoints for listing and managing strategies."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from pipeline.schemas import StrategyConfig
from services.strategy import (
    create_strategy,
    get_strategy,
    list_strategies,
    list_templates,
)

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("", response_model=list[StrategyConfig])
async def get_strategies() -> list[StrategyConfig]:
    """List all saved strategies (excluding templates)."""
    return await list_strategies()


@router.get("/templates", response_model=list[StrategyConfig])
async def get_templates() -> list[StrategyConfig]:
    """List all built-in strategy templates."""
    return await list_templates()


@router.get("/{strategy_id}", response_model=StrategyConfig)
async def get_strategy_by_id(strategy_id: str) -> StrategyConfig:
    """Get a single strategy by ID."""
    config = await get_strategy(strategy_id)
    if not config:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_id}' not found")
    return config


@router.post("", response_model=StrategyConfig, status_code=201)
async def create_new_strategy(config: StrategyConfig) -> StrategyConfig:
    """Create a new strategy from the provided configuration."""
    return await create_strategy(config)
