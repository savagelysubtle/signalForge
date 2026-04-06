"""Market Heartbeat — persistent background service maintaining live MarketState.

Fast loop (every 15 min): VIX, SPY price/MAs, put/call ratio.
Slow loop (every 2 hours): sector rotation, breadth, macro calendar.

All data persisted to the ``market_state`` Supabase singleton row so it
survives restarts and is available to the pipeline orchestrator without
a Perplexity call.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from database.connection import get_db
from services.fmp_service import (
    FmpSectorPerformance,
    fetch_quotes,
    fetch_sector_performance,
    fetch_vix_quote,
)

logger = logging.getLogger(__name__)

FAST_INTERVAL_SEC = 15 * 60
SLOW_INTERVAL_SEC = 2 * 60 * 60
MAX_CACHE_AGE_MINUTES = 120

SECTOR_ETFS = ["XLK", "XLY", "XLF", "XLE", "XLV", "XLI", "XLB", "XLU", "XLRE", "XLC", "XLP"]
_DEFENSIVE_SECTORS = {"XLU", "XLP", "XLRE", "XLV"}
_CYCLICAL_SECTORS = {"XLK", "XLY", "XLF", "XLI"}


@dataclass
class MarketState:
    """Mirrors the ``market_state`` Supabase table columns."""

    vix_spot: float | None = None
    vix_3m: float | None = None
    vix_structure: str = "flat"
    vix_percentile_1y: float | None = None
    vix_estimate: str = "normal"

    regime_type: str = "trending_bull"
    regime_confidence: float = 0.5
    breadth_estimate: str = "moderate"
    breadth_score: float | None = None
    dominant_sectors: list[str] = field(default_factory=list)
    defensive_rotation: bool = False
    summary: str = ""
    implications: str = ""

    pc_ratio: float | None = None
    pc_ratio_5d_avg: float | None = None
    pc_signal: str = "neutral"

    spy_price: float | None = None
    spy_above_50ma: bool | None = None
    spy_above_200ma: bool | None = None
    spy_5d_return: float | None = None
    spy_20d_return: float | None = None

    leading_sectors: list[str] = field(default_factory=list)
    lagging_sectors: list[str] = field(default_factory=list)
    sector_scores: dict[str, float] = field(default_factory=dict)

    market_session: str = "regular"
    next_macro_event: str | None = None

    hmm_regime: str | None = None
    hmm_probs: dict[str, float] = field(default_factory=dict)

    last_updated: datetime | None = None

    def to_regime_output_dict(self) -> dict[str, Any]:
        """Convert to RegimeOutput-compatible dict for backward compat."""
        return {
            "regime_type": self.regime_type,
            "vix_estimate": self.vix_estimate,
            "breadth_estimate": self.breadth_estimate,
            "dominant_sectors": self.dominant_sectors,
            "defensive_rotation": self.defensive_rotation,
            "summary": self.summary,
            "implications": self.implications,
        }

    def is_fresh(self, max_age_minutes: int = MAX_CACHE_AGE_MINUTES) -> bool:
        if not self.last_updated:
            return False
        age = datetime.now(UTC) - self.last_updated
        return age < timedelta(minutes=max_age_minutes)

    def is_market_open(self) -> bool:
        return self.market_session == "regular"


# ---------------------------------------------------------------------------
# Module-level singleton (mirrors database/connection.py pattern)
# ---------------------------------------------------------------------------

_instance: MarketHeartbeat | None = None


async def init_heartbeat() -> MarketHeartbeat:
    """Create and return the heartbeat singleton. Call from lifespan."""
    global _instance
    _instance = MarketHeartbeat()
    return _instance


def get_heartbeat() -> MarketHeartbeat:
    """Return the heartbeat singleton. Raises if not initialized."""
    if _instance is None:
        raise RuntimeError("Heartbeat not initialized. Call init_heartbeat() first.")
    return _instance


async def close_heartbeat() -> None:
    """Stop the heartbeat and clear the singleton."""
    global _instance
    if _instance is not None:
        _instance._running = False
        _instance = None
        logger.info("Market heartbeat released.")


# ---------------------------------------------------------------------------
# MarketHeartbeat class
# ---------------------------------------------------------------------------


class MarketHeartbeat:
    """Background service that maintains a persistent MarketState.

    Wire into lifespan::

        heartbeat = await init_heartbeat()
        asyncio.create_task(heartbeat.run_forever())

    Consume in orchestrator::

        state = await get_heartbeat().get_current_state()
    """

    def __init__(self) -> None:
        self._state: MarketState | None = None
        self._fast_lock = asyncio.Lock()
        self._slow_lock = asyncio.Lock()
        self._running = False

    async def run_forever(self) -> None:
        """Main entry point — call once from lifespan."""
        self._running = True
        logger.info("Market heartbeat starting…")

        try:
            await self._refresh_fast()
        except Exception as exc:
            logger.warning("Heartbeat initial fast refresh failed: %s", exc)
        try:
            await self._refresh_slow()
        except Exception as exc:
            logger.warning("Heartbeat initial slow refresh failed: %s", exc)

        fast_task = asyncio.create_task(self._fast_loop())
        slow_task = asyncio.create_task(self._slow_loop())

        try:
            await asyncio.gather(fast_task, slow_task)
        except asyncio.CancelledError:
            self._running = False
            logger.info("Market heartbeat stopped.")

    async def get_current_state(self) -> MarketState:
        """Non-blocking accessor. Returns cached state or loads from Supabase."""
        if self._state and self._state.is_fresh():
            return self._state

        db_state = await self._load_from_db()
        if db_state and db_state.is_fresh():
            self._state = db_state
            return self._state

        return self._state or MarketState()

    # ── Fast loop ───────────────────────────────────────────────────────

    async def _fast_loop(self) -> None:
        while self._running:
            await asyncio.sleep(FAST_INTERVAL_SEC)
            try:
                await self._refresh_fast()
            except Exception as exc:
                logger.warning("Heartbeat fast refresh failed: %s", exc)

    async def _refresh_fast(self) -> None:
        async with self._fast_lock:
            state = self._state or await self._load_from_db() or MarketState()

            vix_spot, vix_label = await fetch_vix_quote()
            state.vix_spot = vix_spot
            state.vix_estimate = vix_label

            spy_data = await self._fetch_spy()
            state.spy_price = spy_data.get("price")
            state.spy_above_50ma = spy_data.get("above_50ma")
            state.spy_above_200ma = spy_data.get("above_200ma")
            state.spy_5d_return = spy_data.get("return_5d")
            state.spy_20d_return = spy_data.get("return_20d")

            state.market_session = self._get_market_session()
            state.regime_type = self._classify_regime(state)
            state.regime_confidence = self._score_regime_confidence(state)
            state.summary = self._build_summary(state)
            state.implications = self._build_implications(state)
            state.last_updated = datetime.now(UTC)

            self._state = state
            await self._save_to_db(state, mode="fast")
            logger.info(
                "Heartbeat fast: regime=%s VIX=%s session=%s",
                state.regime_type,
                state.vix_spot,
                state.market_session,
            )

    # ── Slow loop ───────────────────────────────────────────────────────

    async def _slow_loop(self) -> None:
        while self._running:
            await asyncio.sleep(SLOW_INTERVAL_SEC)
            try:
                await self._refresh_slow()
            except Exception as exc:
                logger.warning("Heartbeat slow refresh failed: %s", exc)

    async def _refresh_slow(self) -> None:
        async with self._slow_lock:
            state = self._state or MarketState()

            sector_data = await self._fetch_sector_rotation()
            state.leading_sectors = sector_data.get("leading", [])
            state.lagging_sectors = sector_data.get("lagging", [])
            state.sector_scores = sector_data.get("scores", {})
            state.breadth_score = sector_data.get("breadth_score")
            state.breadth_estimate = self._classify_breadth(state.breadth_score)
            state.dominant_sectors = state.leading_sectors[:3]
            state.defensive_rotation = self._detect_defensive_rotation(state.sector_scores)

            macro_event = await self._fetch_next_macro_event()
            state.next_macro_event = macro_event
            state.last_updated = datetime.now(UTC)

            self._state = state
            await self._save_to_db(state, mode="slow")
            logger.info(
                "Heartbeat slow: leading=%s breadth=%s",
                state.leading_sectors[:2],
                f"{state.breadth_score:.2f}" if state.breadth_score is not None else "N/A",
            )

    # ── Data fetchers ───────────────────────────────────────────────────

    async def _fetch_spy(self) -> dict[str, Any]:
        """Fetch SPY price and moving-average data via FMP stable OHLCV."""
        try:
            from services.technical_analysis import fetch_ohlcv_stable

            quotes = await fetch_quotes(["SPY"])
            spy_quote = quotes.get("SPY")
            if not spy_quote or not spy_quote.price:
                return {}

            price = spy_quote.price

            candles = await fetch_ohlcv_stable("SPY", limit=250)
            above_50ma: bool | None = None
            above_200ma: bool | None = None
            return_20d: float | None = None

            if candles and len(candles) >= 50:
                import numpy as np

                chrono = list(reversed(candles))
                closes = np.array(
                    [float(c.get("adjClose") or c.get("close") or 0) for c in chrono],
                    dtype=np.float64,
                )
                sma50 = float(np.mean(closes[-50:]))
                above_50ma = price > sma50
                if len(closes) >= 200:
                    sma200 = float(np.mean(closes[-200:]))
                    above_200ma = price > sma200
                if len(closes) >= 20:
                    return_20d = round((closes[-1] - closes[-20]) / closes[-20] * 100, 2)

            prev_close = spy_quote.previousClose or price
            return_5d = ((price - prev_close) / prev_close * 100) if prev_close else 0.0

            return {
                "price": price,
                "above_50ma": above_50ma,
                "above_200ma": above_200ma,
                "return_5d": round(return_5d, 2),
                "return_20d": return_20d,
            }
        except Exception as exc:
            logger.warning("SPY fetch failed: %s", exc)
            return {}

    async def _fetch_sector_rotation(self) -> dict[str, Any]:
        """Fetch sector performance from FMP and compute relative strength."""
        try:
            sectors: list[FmpSectorPerformance] = await fetch_sector_performance()
            if not sectors:
                return {}

            scores: dict[str, float] = {}
            for s in sectors:
                if s.changesPercentage is not None:
                    scores[s.sector] = round(s.changesPercentage, 4)

            sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            leading = [name for name, pct in sorted_scores if pct > 0][:4]
            lagging = [name for name, pct in sorted_scores if pct < 0][-4:]

            positive_count = sum(1 for _, pct in sorted_scores if pct > 0)
            breadth = positive_count / len(sorted_scores) if sorted_scores else 0.5

            return {
                "leading": leading,
                "lagging": lagging,
                "scores": scores,
                "breadth_score": round(breadth, 3),
            }
        except Exception as exc:
            logger.warning("Sector rotation fetch failed: %s", exc)
            return {}

    async def _fetch_next_macro_event(self) -> str | None:
        """Best-effort fetch of upcoming macro events."""
        try:
            from services.fmp_service import fetch_economic_calendar

            events = await fetch_economic_calendar(days_ahead=7)
            if events:
                next_event = events[0]
                event_date = next_event.get("date")
                if event_date:
                    if isinstance(event_date, str):
                        event_date = datetime.fromisoformat(event_date)
                    days = (event_date - datetime.now(UTC)).days
                    event_name = next_event.get("event", "Unknown")
                    return f"{event_name} in {days} day{'s' if days != 1 else ''}"
        except Exception:
            pass
        return None

    # ── Classification helpers ──────────────────────────────────────────

    @staticmethod
    def _classify_regime(state: MarketState) -> str:
        """Deterministic regime from VIX + SPY data. No LLM needed."""
        vix = state.vix_spot or 20
        spy_5d = state.spy_5d_return or 0
        spy_20d = state.spy_20d_return or 0

        if vix > 35:
            return "risk_off"
        if vix > 25:
            return "high_volatility"
        if spy_20d is not None and spy_20d > 3 and vix < 20 and state.spy_above_50ma:
            return "trending_bull"
        if spy_20d is not None and spy_20d < -3 and not state.spy_above_50ma:
            return "trending_bear"
        if spy_20d is not None and abs(spy_20d) < 1.5:
            return "range_bound"
        if state.defensive_rotation:
            return "sector_rotation"
        return "trending_bull" if spy_5d > 0 else "trending_bear"

    @staticmethod
    def _score_regime_confidence(state: MarketState) -> float:
        score = 0.5
        vix = state.vix_spot or 20
        if vix < 15 or vix > 30:
            score += 0.2
        if state.spy_above_200ma is not None:
            score += 0.15
        if state.breadth_score is not None:
            score += 0.15
        return min(score, 1.0)

    @staticmethod
    def _classify_breadth(breadth: float | None) -> str:
        if breadth is None:
            return "moderate"
        if breadth >= 0.7:
            return "strong"
        if breadth >= 0.5:
            return "moderate"
        if breadth >= 0.3:
            return "weak"
        return "deteriorating"

    @staticmethod
    def _detect_defensive_rotation(scores: dict[str, float]) -> bool:
        def_score = sum(scores.get(s, 0) for s in _DEFENSIVE_SECTORS)
        cyc_score = sum(scores.get(s, 0) for s in _CYCLICAL_SECTORS)
        return def_score > cyc_score + 0.02

    @staticmethod
    def _get_market_session() -> str:
        now = datetime.now(UTC)
        et_offset = -4
        et_hour = now.hour + now.minute / 60 + et_offset
        if et_hour < 0:
            et_hour += 24
        if 4.0 <= et_hour < 9.5:
            return "pre_market"
        if 9.5 <= et_hour < 16.0:
            return "regular"
        if 16.0 <= et_hour < 20.0:
            return "after_hours"
        return "closed"

    @staticmethod
    def _build_summary(state: MarketState) -> str:
        vix_str = f"VIX {state.vix_spot:.1f}" if state.vix_spot else "VIX unknown"
        spy_str = f"SPY ${state.spy_price:.2f}" if state.spy_price else "SPY unknown"
        return (
            f"Market regime: {state.regime_type.replace('_', ' ')}. "
            f"{vix_str} ({state.vix_estimate}). {spy_str}."
        )

    @staticmethod
    def _build_implications(state: MarketState) -> str:
        parts: list[str] = []
        if state.regime_type == "risk_off":
            parts.append("Extreme caution warranted — favor cash and hedges.")
        elif state.regime_type == "high_volatility":
            parts.append("Elevated vol — reduce position sizes, tighten stops.")
        elif state.regime_type == "trending_bull":
            parts.append("Bullish trend — favor momentum and breakout strategies.")
        elif state.regime_type == "trending_bear":
            parts.append("Bearish trend — favor mean reversion and defensive plays.")
        elif state.regime_type == "range_bound":
            parts.append("Range-bound — favor mean reversion, avoid breakout chases.")
        if state.defensive_rotation:
            parts.append("Defensive rotation detected — risk appetite declining.")
        if state.next_macro_event:
            parts.append(f"Upcoming: {state.next_macro_event}.")
        return " ".join(parts)

    # ── Supabase persistence ────────────────────────────────────────────

    async def _save_to_db(self, state: MarketState, mode: str = "fast") -> None:
        try:
            db = await get_db()
            now = datetime.now(UTC).isoformat()
            payload: dict[str, Any] = {
                "id": "singleton",
                "vix_spot": state.vix_spot,
                "vix_3m": state.vix_3m,
                "vix_structure": state.vix_structure,
                "vix_percentile_1y": state.vix_percentile_1y,
                "vix_estimate": state.vix_estimate,
                "regime_type": state.regime_type,
                "regime_confidence": state.regime_confidence,
                "breadth_estimate": state.breadth_estimate,
                "breadth_score": state.breadth_score,
                "dominant_sectors": state.dominant_sectors,
                "defensive_rotation": state.defensive_rotation,
                "summary": state.summary,
                "implications": state.implications,
                "pc_ratio": state.pc_ratio,
                "pc_ratio_5d_avg": state.pc_ratio_5d_avg,
                "pc_signal": state.pc_signal,
                "spy_price": state.spy_price,
                "spy_above_50ma": state.spy_above_50ma,
                "spy_above_200ma": state.spy_above_200ma,
                "spy_5d_return": state.spy_5d_return,
                "spy_20d_return": state.spy_20d_return,
                "leading_sectors": state.leading_sectors,
                "lagging_sectors": state.lagging_sectors,
                "sector_scores": state.sector_scores,
                "market_session": state.market_session,
                "next_macro_event": state.next_macro_event,
                "hmm_regime": state.hmm_regime,
                "hmm_probs": state.hmm_probs,
                "last_updated": now,
                f"{mode}_refresh_at": now,
            }
            await db.table("market_state").upsert(payload).execute()
        except Exception as exc:
            logger.warning("Heartbeat DB save failed: %s", exc)

    async def _load_from_db(self) -> MarketState | None:
        try:
            db = await get_db()
            result = await db.table("market_state").select("*").eq("id", "singleton").execute()
            if result.data:
                row = result.data[0]
                state = MarketState()
                for fld in MarketState.__dataclass_fields__:
                    if fld in row and row[fld] is not None:
                        val = row[fld]
                        if fld == "last_updated" and isinstance(val, str):
                            val = datetime.fromisoformat(val)
                        setattr(state, fld, val)
                return state
        except Exception as exc:
            logger.warning("Heartbeat DB load failed: %s", exc)
        return None
