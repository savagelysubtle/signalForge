"""Execution-time helpers for MCP / IBKR (sector concentration)."""

from __future__ import annotations

from fastapi import APIRouter

from middleware.auth import CurrentUser
from pipeline.schemas import SectorConcentrationRequest, SectorConcentrationResponse
from services.fmp_service import equity_symbol_key, fetch_stock_sectors

router = APIRouter(prefix="/execution", tags=["execution"])


@router.post("/sector-concentration", response_model=SectorConcentrationResponse)
async def sector_concentration(
    body: SectorConcentrationRequest,
    _user_id: CurrentUser,
) -> SectorConcentrationResponse:
    """Count open US equity positions sharing the proposed symbol's GICS sector.

    Uses FMP profile data. When FMP is unavailable, returns ``passed=True`` with
    ``skipped=True`` so trading is not blocked.
    """
    proposed = equity_symbol_key(body.proposed_symbol)
    held = {equity_symbol_key(s) for s in body.open_position_symbols if s and s.strip()}
    to_fetch = list(held | {proposed})
    sector_map = await fetch_stock_sectors(to_fetch)

    if not sector_map or proposed not in sector_map:
        return SectorConcentrationResponse(
            passed=True,
            message="Sector concentration check skipped — FMP sector data unavailable",
            proposed_symbol=proposed,
            proposed_sector="Unknown",
            positions_in_sector_after_trade=0,
            max_positions_per_sector=body.max_positions_per_sector,
            skipped=True,
        )

    p_sec = sector_map[proposed]
    in_sector = sum(1 for sym in held if sector_map.get(sym) == p_sec)
    opening_new_line = proposed not in held
    after = in_sector + (1 if opening_new_line else 0)
    limit = body.max_positions_per_sector
    passed = after <= limit

    return SectorConcentrationResponse(
        passed=passed,
        message=(
            f"Sector '{p_sec}': {after} position(s) after trade (limit {limit})"
            if passed
            else f"Sector '{p_sec}' would hold {after} positions (limit {limit})"
        ),
        proposed_symbol=proposed,
        proposed_sector=p_sec,
        positions_in_sector_after_trade=after,
        max_positions_per_sector=limit,
        skipped=False,
    )
