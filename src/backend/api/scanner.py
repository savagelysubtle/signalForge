"""Scanner API — market heartbeat + strategy prescreener endpoints."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.market_heartbeat import get_heartbeat
from services.strategy_scanner import ScanResult, get_scanner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scanner", tags=["scanner"])

_background_scans: set[asyncio.Task[Any]] = set()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ScannerRunRequest(BaseModel):
    country: str | None = None
    exchange: str | None = None
    sector: str | None = None
    market_cap_min: int | None = None
    market_cap_max: int | None = None
    limit: int = 400


class ScanTriggerResponse(BaseModel):
    scan_run_id: str
    status: str


class MarketStateResponse(BaseModel):
    regime_type: str
    regime_confidence: float
    vix_spot: float | None
    vix_structure: str
    vix_estimate: str
    pc_ratio: float | None
    pc_signal: str
    spy_price: float | None
    spy_above_50ma: bool | None
    spy_5d_return: float | None
    spy_20d_return: float | None
    breadth_score: float | None
    breadth_estimate: str
    leading_sectors: list[str]
    lagging_sectors: list[str]
    market_session: str
    next_macro_event: str | None
    last_updated: str | None


class ScannerResultItem(BaseModel):
    ticker: str
    combined_score: float
    ml_probability: float | None
    rule_score: float
    rsi: float | None
    volume_ratio: float | None
    momentum_score: float | None
    atr_pct: float | None
    ema_alignment: str | None
    matched_rules: list[str]
    earnings_within_5d: bool
    is_actionable: bool


class ScannerLatestResponse(BaseModel):
    strategies: dict[str, list[ScannerResultItem]]
    total_setups: int
    strategies_with_setups: list[str]
    regime_type: str | None
    last_scan_at: str | None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/run", response_model=ScanTriggerResponse)
async def trigger_scan(body: ScannerRunRequest | None = None) -> ScanTriggerResponse:
    """Manually trigger a strategy scan with optional filters. Returns immediately."""
    from datetime import UTC, datetime

    scanner = get_scanner()
    scan_run_id = f"scan_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    filters = body or ScannerRunRequest()

    async def _run() -> None:
        try:
            await scanner.run_scan(
                triggered_by="manual",
                scan_run_id=scan_run_id,
                country=filters.country,
                exchange=filters.exchange,
                sector=filters.sector,
                market_cap_min=filters.market_cap_min,
                market_cap_max=filters.market_cap_max,
                limit=filters.limit,
            )
        except Exception as exc:
            logger.error("Manual scan failed: %s", exc, exc_info=True)

    task = asyncio.create_task(_run())
    _background_scans.add(task)
    task.add_done_callback(_background_scans.discard)

    return ScanTriggerResponse(scan_run_id=scan_run_id, status="started")


@router.get("/status/{scan_run_id}")
async def get_scan_status(scan_run_id: str) -> dict[str, Any]:
    """Poll scan progress by run ID."""
    scanner = get_scanner()
    return await scanner.get_scan_status(scan_run_id)


@router.get("/latest", response_model=ScannerLatestResponse)
async def get_latest(
    strategy_type: str | None = None,
    min_score: float = 0.50,
    actionable_only: bool = False,
) -> ScannerLatestResponse:
    """Return latest scan results grouped by strategy."""
    scanner = get_scanner()
    results: list[ScanResult] = await scanner.get_latest_results(
        strategy_type=strategy_type,
        min_combined_score=min_score,
    )

    if actionable_only:
        results = [r for r in results if r.is_actionable]

    by_strategy: dict[str, list[ScannerResultItem]] = {}
    for r in results:
        item = ScannerResultItem(
            ticker=r.ticker,
            combined_score=r.combined_score,
            ml_probability=r.ml_probability,
            rule_score=r.rule_score,
            rsi=r.rsi,
            volume_ratio=r.volume_ratio,
            momentum_score=r.momentum_score,
            atr_pct=r.atr_pct,
            ema_alignment=r.ema_alignment,
            matched_rules=r.matched_rules,
            earnings_within_5d=r.earnings_within_5d,
            is_actionable=r.is_actionable,
        )
        by_strategy.setdefault(r.strategy_type, []).append(item)

    regime = results[0].regime_type if results else None
    last_scan: str | None = None
    try:
        from database.connection import get_db

        db = await get_db()
        runs = (
            await db.table("scan_runs")
            .select("started_at")
            .eq("status", "completed")
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        if runs.data:
            last_scan = runs.data[0]["started_at"]
    except Exception:
        pass

    return ScannerLatestResponse(
        strategies=by_strategy,
        total_setups=len(results),
        strategies_with_setups=list(by_strategy.keys()),
        regime_type=regime,
        last_scan_at=last_scan,
    )


@router.get("/heartbeat", response_model=MarketStateResponse)
async def get_market_state() -> MarketStateResponse:
    """Return current market state from the heartbeat."""
    try:
        heartbeat = get_heartbeat()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    state = await heartbeat.get_current_state()
    return MarketStateResponse(
        regime_type=state.regime_type,
        regime_confidence=state.regime_confidence,
        vix_spot=state.vix_spot,
        vix_structure=state.vix_structure,
        vix_estimate=state.vix_estimate,
        pc_ratio=state.pc_ratio,
        pc_signal=state.pc_signal,
        spy_price=state.spy_price,
        spy_above_50ma=state.spy_above_50ma,
        spy_5d_return=state.spy_5d_return,
        spy_20d_return=state.spy_20d_return,
        breadth_score=state.breadth_score,
        breadth_estimate=state.breadth_estimate,
        leading_sectors=state.leading_sectors,
        lagging_sectors=state.lagging_sectors,
        market_session=state.market_session,
        next_macro_event=state.next_macro_event,
        last_updated=state.last_updated.isoformat() if state.last_updated else None,
    )
