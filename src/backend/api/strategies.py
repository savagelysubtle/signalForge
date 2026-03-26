"""Strategy API endpoints for listing and managing strategies."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from middleware.auth import CurrentUser
from pipeline.schemas import StrategyConfig
from services.strategy import (
    create_strategy,
    delete_strategy,
    get_strategy,
    list_strategies,
    list_templates,
    update_strategy,
)

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("", response_model=list[StrategyConfig])
async def get_strategies(user_id: CurrentUser) -> list[StrategyConfig]:
    """List all saved strategies (excluding templates)."""
    return await list_strategies(user_id)


@router.get("/templates", response_model=list[StrategyConfig])
async def get_templates() -> list[StrategyConfig]:
    """List all built-in strategy templates."""
    return await list_templates()


@router.get("/{strategy_id}", response_model=StrategyConfig)
async def get_strategy_by_id(strategy_id: str, user_id: CurrentUser) -> StrategyConfig:
    """Get a single strategy by ID."""
    config = await get_strategy(strategy_id, user_id)
    if not config:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_id}' not found")
    return config


@router.post("", response_model=StrategyConfig, status_code=201)
async def create_new_strategy(config: StrategyConfig, user_id: CurrentUser) -> StrategyConfig:
    """Create a new strategy from the provided configuration."""
    return await create_strategy(config, user_id)


@router.put("/{strategy_id}", response_model=StrategyConfig)
async def update_existing_strategy(
    strategy_id: str, config: StrategyConfig, user_id: CurrentUser
) -> StrategyConfig:
    """Update an existing strategy configuration."""
    try:
        return await update_strategy(strategy_id, config, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{strategy_id}", status_code=204)
async def delete_existing_strategy(strategy_id: str, user_id: CurrentUser) -> None:
    """Delete a strategy. Templates cannot be deleted."""
    try:
        await delete_strategy(strategy_id, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
