"""Strategy Scanner — pre-pipeline discovery layer.

Pulls a universe from FMP, fetches TA snapshots, applies deterministic
strategy rules, scores with LightGBM, and persists ranked results to
Supabase for the frontend dashboard and pipeline orchestrator.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from database.connection import get_db
from services.market_heartbeat import MarketHeartbeat, MarketState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feature container — maps directly from TechnicalSnapshot fields
# ---------------------------------------------------------------------------


@dataclass
class TickerFeatures:
    """Normalized features for rule matching and ML scoring."""

    ticker: str = ""
    price: float = 0.0
    rsi: float = 50.0
    ema9_vs_price: float = 0.0
    ema21_vs_price: float = 0.0
    ema50_vs_price: float = 0.0
    ema200_vs_price: float = 0.0
    ema_alignment: str = "mixed"
    ema_stack_score: float = 2.0
    ema_spread_pct: float = 0.0
    macd_histogram: float = 0.0
    macd_slope: float = 0.0
    adx: float = 0.0
    volume_ratio: float = 1.0
    volume_trend: float = 0.0
    atr_pct: float = 2.0
    momentum_score: float = 0.0
    distance_from_20d_high: float = 50.0
    distance_from_20d_low: float = 50.0
    earnings_within_5d: bool = False
    market_cap: float = 0.0
    strategy_type: str = "swing"
    regime: str = "trending_bull"
    # Extra daily features (computed from raw candles)
    price_change_1d: float | None = None
    price_change_5d: float | None = None
    price_change_20d: float | None = None
    bollinger_width: float | None = None
    volatility_20d: float | None = None
    high_low_range: float | None = None
    gap_pct: float | None = None
    # Multi-timeframe features
    tf_W_rsi_14: float | None = None
    tf_W_price_vs_ema_200: float | None = None
    tf_W_ema_stack_score: float | None = None
    tf_W_momentum_score: float | None = None
    tf_4H_rsi_14: float | None = None
    tf_4H_price_vs_ema_200: float | None = None
    tf_4H_ema_stack_score: float | None = None
    tf_4H_momentum_score: float | None = None


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------


def _score_rule(conditions: list[tuple[bool, float]]) -> float:
    """Score 0-1 based on weighted rule conditions."""
    total_weight = sum(w for _, w in conditions)
    if total_weight == 0:
        return 0.0
    passed_weight = sum(w for passed, w in conditions if passed)
    return passed_weight / total_weight


STRATEGY_RULES: dict[str, Any] = {
    "swing": lambda f: _score_rule(
        [
            (45 < f.rsi < 65, 2.0),
            (f.ema_alignment in ("all_bullish", "mixed"), 2.0),
            (-1 < f.ema9_vs_price < 3, 1.5),
            (f.volume_ratio > 1.1, 1.5),
            (f.momentum_score > 0.1, 1.0),
            (not f.earnings_within_5d, 1.0),
        ]
    ),
    "mean_reversion": lambda f: _score_rule(
        [
            (f.rsi < 35 or f.rsi > 72, 3.0),
            (f.distance_from_20d_low < 3 or f.distance_from_20d_high < 3, 2.0),
            (f.volume_ratio > 1.3, 1.5),
            (f.atr_pct < 4.0, 1.0),
        ]
    ),
    "momentum_breakout": lambda f: _score_rule(
        [
            (f.distance_from_20d_high < 2.0, 3.0),
            (f.volume_ratio > 1.8, 3.0),
            (f.ema_alignment == "all_bullish", 2.0),
            (f.momentum_score > 0.3, 2.0),
            (55 < f.rsi < 80, 1.5),
            (not f.earnings_within_5d, 1.0),
        ]
    ),
    "bollinger_band_squeeze_breakout": lambda f: _score_rule(
        [
            (f.atr_pct < 2.5, 4.0),
            (f.volume_ratio < 0.9, 2.0),
            (f.atr_pct < 3.0, 1.5),
        ]
    ),
    "vwap_reversal_scalp": lambda f: _score_rule(
        [
            (f.rsi < 38 or f.rsi > 65, 2.5),
            (f.volume_ratio > 1.8, 3.0),
            (f.momentum_score < -0.2 or f.momentum_score > 0.2, 1.5),
        ]
    ),
    "earnings_play": lambda f: _score_rule(
        [
            (f.earnings_within_5d, 4.0),
            (f.volume_ratio > 1.2, 2.0),
            (40 < f.rsi < 75, 1.5),
            (f.market_cap > 2e9, 1.5),
        ]
    ),
    "ema_stack_momentum": lambda f: _score_rule(
        [
            (f.ema_alignment == "all_bullish", 4.0),
            (0 < f.ema9_vs_price < 2, 2.0),
            (f.volume_ratio > 1.3, 2.0),
            (f.momentum_score > 0.25, 1.5),
        ]
    ),
    "ema_21_pullback": lambda f: _score_rule(
        [
            (abs(f.ema21_vs_price) < 1.5, 3.0),
            (f.momentum_score > 0, 2.0),
            (42 < f.rsi < 62, 2.0),
            (f.volume_ratio > 0.8, 1.0),
        ]
    ),
    "value_accumulation": lambda f: _score_rule(
        [
            (f.rsi < 45, 2.0),
            (f.distance_from_20d_low < 5, 2.0),
            (f.ema50_vs_price < 5, 1.5),
            (f.volume_ratio > 0.7, 1.0),
        ]
    ),
    "intraday_scalp": lambda f: _score_rule(
        [
            (f.volume_ratio > 2.0, 3.0),
            (0.5 < f.atr_pct < 3.0, 2.0),
            (30 < f.rsi < 70, 1.5),
        ]
    ),
}

REGIME_ACTIVE_STRATEGIES: dict[str, list[str]] = {
    "trending_bull": [
        "swing",
        "momentum_breakout",
        "ema_stack_momentum",
        "ema_21_pullback",
        "earnings_play",
        "bollinger_band_squeeze_breakout",
    ],
    "trending_bear": ["mean_reversion", "vwap_reversal_scalp"],
    "high_volatility": [
        "mean_reversion",
        "bollinger_band_squeeze_breakout",
        "earnings_play",
        "vwap_reversal_scalp",
    ],
    "range_bound": ["mean_reversion", "vwap_reversal_scalp", "swing"],
    "sector_rotation": ["swing", "ema_stack_momentum", "value_accumulation"],
    "risk_off": [],
}

_DEFAULT_ACTIVE = list(STRATEGY_RULES.keys())
MIN_RULE_SCORE = 0.45
MIN_ML_PROB = 0.52
MIN_COMBINED_SCORE = 0.50
_RULE_WEIGHT = 0.4
_ML_WEIGHT = 0.6

_STRATEGY_TO_MODEL: dict[str, str] = {
    "bollinger_band_squeeze_breakout": "bollinger_band_squeeze_breakout_swing",
    "ema_21_pullback": "ema_21_pullback_swing",
    "ema_stack_momentum": "ema_stack_momentum_intraday",
    "ema_50_200_golden_cross": "ema_50_200_golden_cross_swing",
}


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    ticker: str
    strategy_type: str
    rule_score: float
    ml_probability: float | None
    combined_score: float
    matched_rules: list[str]
    regime_type: str
    rsi: float | None = None
    volume_ratio: float | None = None
    momentum_score: float | None = None
    atr_pct: float | None = None
    ema_alignment: str | None = None
    earnings_within_5d: bool = False
    is_actionable: bool = False


@dataclass
class ScanReport:
    scan_run_id: str
    started_at: datetime
    completed_at: datetime | None = None
    duration_seconds: float = 0.0
    universe_size: int = 0
    setups_found: int = 0
    strategies_with_setups: dict[str, int] = field(default_factory=dict)
    results: list[ScanResult] = field(default_factory=list)
    regime_type: str = "trending_bull"
    status: str = "running"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: StrategyScanner | None = None


async def init_scanner(heartbeat: MarketHeartbeat) -> StrategyScanner:
    """Create and return the scanner singleton. Call from lifespan."""
    global _instance
    _instance = StrategyScanner(heartbeat)
    return _instance


def get_scanner() -> StrategyScanner:
    """Return the scanner singleton. Raises if not initialized."""
    if _instance is None:
        raise RuntimeError("Scanner not initialized. Call init_scanner() first.")
    return _instance


# ---------------------------------------------------------------------------
# StrategyScanner
# ---------------------------------------------------------------------------


class StrategyScanner:
    """Pre-pipeline discovery service.

    1. Pulls universe from FMP screener
    2. Fetches primary-timeframe TA for each ticker
    3. Applies deterministic strategy rules
    4. Scores with LightGBM (if models available)
    5. Persists ranked results to Supabase
    """

    def __init__(self, heartbeat: MarketHeartbeat) -> None:
        self.heartbeat = heartbeat
        self._scan_lock = asyncio.Lock()

    async def run_scan(
        self,
        triggered_by: str = "manual",
        scan_run_id: str | None = None,
        *,
        country: str | None = None,
        exchange: str | None = None,
        sector: str | None = None,
        market_cap_min: int | None = None,
        market_cap_max: int | None = None,
        limit: int = 400,
    ) -> ScanReport:
        """Execute a full scan. Serialised by an internal lock."""
        async with self._scan_lock:
            return await self._do_scan(
                triggered_by,
                scan_run_id,
                country=country,
                exchange=exchange,
                sector=sector,
                market_cap_min=market_cap_min,
                market_cap_max=market_cap_max,
                limit=limit,
            )

    async def _do_scan(
        self,
        triggered_by: str,
        scan_run_id: str | None = None,
        *,
        country: str | None = None,
        exchange: str | None = None,
        sector: str | None = None,
        market_cap_min: int | None = None,
        market_cap_max: int | None = None,
        limit: int = 400,
    ) -> ScanReport:
        if scan_run_id is None:
            scan_run_id = f"scan_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
        report = ScanReport(
            scan_run_id=scan_run_id,
            started_at=datetime.now(UTC),
        )
        await self._save_scan_run(report, triggered_by)

        try:
            state = await self.heartbeat.get_current_state()
            report.regime_type = state.regime_type

            active_strategies = REGIME_ACTIVE_STRATEGIES.get(
                state.regime_type,
                _DEFAULT_ACTIVE,
            )
            if not active_strategies:
                logger.info("Scanner: regime %s — no active strategies", state.regime_type)
                report.status = "completed"
                report.completed_at = datetime.now(UTC)
                await self._finalize_report(report)
                return report

            universe = await self._fetch_universe(
                country=country,
                exchange=exchange,
                sector=sector,
                market_cap_min=market_cap_min,
                market_cap_max=market_cap_max,
                limit=limit,
            )
            report.universe_size = len(universe)
            logger.info(
                "Scanner: %d tickers, strategies=%s",
                len(universe),
                active_strategies,
            )

            features_map = await self._fetch_all_ta(universe, state)

            results: list[ScanResult] = []
            for ticker, features in features_map.items():
                for strategy in active_strategies:
                    rule_fn = STRATEGY_RULES.get(strategy)
                    if not rule_fn:
                        continue
                    features.strategy_type = strategy
                    features.regime = state.regime_type
                    rule_score = rule_fn(features)
                    if rule_score < MIN_RULE_SCORE:
                        continue

                    ml_prob = await self._quick_ml_score(
                        ticker,
                        strategy,
                        features,
                        state,
                    )
                    if ml_prob is not None:
                        combined = _RULE_WEIGHT * rule_score + _ML_WEIGHT * ml_prob
                    else:
                        combined = rule_score

                    if combined >= MIN_COMBINED_SCORE:
                        actionable = combined >= 0.70 and (ml_prob is None or ml_prob >= 0.65)
                        results.append(
                            ScanResult(
                                ticker=ticker,
                                strategy_type=strategy,
                                rule_score=round(rule_score, 4),
                                ml_probability=round(ml_prob, 4) if ml_prob else None,
                                combined_score=round(combined, 4),
                                matched_rules=self._get_matched_rules(strategy, features),
                                regime_type=state.regime_type,
                                rsi=round(features.rsi, 1),
                                volume_ratio=round(features.volume_ratio, 2),
                                momentum_score=round(features.momentum_score, 3),
                                atr_pct=round(features.atr_pct, 2),
                                ema_alignment=features.ema_alignment,
                                earnings_within_5d=features.earnings_within_5d,
                                is_actionable=actionable,
                            )
                        )

            results.sort(key=lambda r: r.combined_score, reverse=True)
            report.results = results
            report.setups_found = len(results)
            for r in results:
                report.strategies_with_setups[r.strategy_type] = (
                    report.strategies_with_setups.get(r.strategy_type, 0) + 1
                )

            report.status = "completed"
            report.completed_at = datetime.now(UTC)
            report.duration_seconds = (report.completed_at - report.started_at).total_seconds()

            await self._save_results(report)
            await self._finalize_report(report)

            logger.info(
                "Scanner complete: %d setups across %d strategies in %.1fs",
                report.setups_found,
                len(report.strategies_with_setups),
                report.duration_seconds,
            )
            return report

        except Exception as exc:
            logger.error("Scanner failed: %s", exc, exc_info=True)
            report.status = "failed"
            report.completed_at = datetime.now(UTC)
            report.duration_seconds = (report.completed_at - report.started_at).total_seconds()
            await self._finalize_report(report)
            return report

    # ── Public query API ────────────────────────────────────────────────

    async def get_latest_results(
        self,
        strategy_type: str | None = None,
        min_combined_score: float = MIN_COMBINED_SCORE,
        max_age_minutes: int = 90,
    ) -> list[ScanResult]:
        """Return results from the most recent completed scan only."""
        try:
            db = await get_db()

            latest_run = (
                await db.table("scan_runs")
                .select("id")
                .eq("status", "completed")
                .order("started_at", desc=True)
                .limit(1)
                .execute()
            )
            if not latest_run.data:
                return []

            run_id = latest_run.data[0]["id"]
            cutoff = (datetime.now(UTC) - timedelta(minutes=max_age_minutes)).isoformat()

            query = (
                db.table("scanner_results")
                .select("*")
                .eq("scan_run_id", run_id)
                .gte("scanned_at", cutoff)
                .gte("combined_score", min_combined_score)
                .order("combined_score", desc=True)
            )
            if strategy_type:
                query = query.eq("strategy_type", strategy_type)

            result = await query.execute()
            return [self._row_to_scan_result(r) for r in (result.data or [])]
        except Exception as exc:
            logger.warning("Scanner get_latest_results failed: %s", exc)
            return []

    async def get_scan_status(self, scan_run_id: str) -> dict[str, Any]:
        """Return progress for a specific scan run."""
        try:
            db = await get_db()
            result = await db.table("scan_runs").select("*").eq("id", scan_run_id).execute()
            if result.data:
                return result.data[0]
        except Exception as exc:
            logger.warning("Scanner get_scan_status failed: %s", exc)
        return {"id": scan_run_id, "status": "unknown"}

    # ── Internal: universe + TA ─────────────────────────────────────────

    # FMP `country` filters by headquarters, not listing exchange.
    # Post-filter to the country's primary exchanges when no explicit exchange is set.
    _COUNTRY_EXCHANGES: ClassVar[dict[str, set[str]]] = {
        "CA": {"TSX", "TSXV", "TSX-V", "NEO", "CSE"},
        "US": {"NYSE", "NASDAQ", "AMEX", "NYSEArca", "CBOE"},
        "GB": {"LSE", "LON"},
        "DE": {"XETRA", "XETR", "FRA"},
        "AU": {"ASX"},
    }

    async def _fetch_universe(
        self,
        *,
        country: str | None = None,
        exchange: str | None = None,
        sector: str | None = None,
        market_cap_min: int | None = None,
        market_cap_max: int | None = None,
        limit: int = 600,
    ) -> list[str]:
        """Pull ~200-400 tickers from FMP screener with optional filters."""
        try:
            from pipeline.schemas import FmpScreenerConfig
            from services.fmp_service import screen_stocks

            config = FmpScreenerConfig(
                enabled=True,
                market_cap_min=market_cap_min or 500_000_000,
                market_cap_max=market_cap_max,
                volume_min=500_000,
                price_min=5.0,
                limit=limit,
                country=country,
                exchange=exchange,
                sector=sector,
            )
            logger.info(
                "Universe filters: country=%s exchange=%s sector=%s cap=[%s,%s] limit=%d",
                country,
                exchange,
                sector,
                market_cap_min,
                market_cap_max,
                limit,
            )
            stocks = await screen_stocks(config)

            if country and not exchange:
                allowed = self._COUNTRY_EXCHANGES.get(country, set())
                if allowed:
                    before = len(stocks)
                    stocks = [s for s in stocks if s.exchangeShortName in allowed]
                    logger.info(
                        "Exchange post-filter for country=%s: %d → %d (kept: %s)",
                        country,
                        before,
                        len(stocks),
                        allowed,
                    )

            return [s.symbol for s in stocks]
        except Exception as exc:
            logger.warning("Universe fetch failed: %s", exc)
            return []

    async def _fetch_all_ta(
        self,
        tickers: list[str],
        state: MarketState,
    ) -> dict[str, TickerFeatures]:
        """Fetch daily TA and compute weekly + 4H features for all tickers."""
        import httpx

        from pipeline.stages.numerical_ta import run_ta_for_scanner
        from services.technical_analysis import (
            aggregate_daily_to_weekly,
            compute_extra_daily_features,
            compute_tf_features,
            fetch_intraday_ohlcv,
        )

        snapshots, raw_candles = await run_ta_for_scanner(tickers, timeframe="D")

        weekly_features: dict[str, dict[str, float | None]] = {}
        extra_daily: dict[str, dict[str, float | None]] = {}
        for ticker, candles in raw_candles.items():
            weekly_bars = aggregate_daily_to_weekly(candles)
            weekly_features[ticker] = compute_tf_features(weekly_bars, "W")
            extra_daily[ticker] = compute_extra_daily_features(candles)

        intraday_features: dict[str, dict[str, float | None]] = {}
        batch_size = 20
        batch_delay = 0.5
        intraday_tickers = list(snapshots.keys())
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                for batch_start in range(0, len(intraday_tickers), batch_size):
                    batch = intraday_tickers[batch_start : batch_start + batch_size]
                    tasks = [
                        fetch_intraday_ohlcv(t, timeframe="4hour", limit=200, client=client)
                        for t in batch
                    ]
                    results_4h = await asyncio.gather(*tasks, return_exceptions=True)
                    for ticker, result in zip(batch, results_4h, strict=False):
                        if isinstance(result, Exception) or not result:
                            continue
                        intraday_features[ticker] = compute_tf_features(result, "4H")

                    if batch_start + batch_size < len(intraday_tickers):
                        await asyncio.sleep(batch_delay)
        except Exception as exc:
            logger.warning("4H feature fetch failed (non-fatal): %s", exc)

        logger.info(
            "Multi-TF features: %d weekly, %d 4H out of %d snapshots",
            len(weekly_features),
            len(intraday_features),
            len(snapshots),
        )

        result: dict[str, TickerFeatures] = {}
        for ticker, snap in snapshots.items():
            feat = self._snapshot_to_features(snap, state)
            wf = weekly_features.get(ticker, {})
            feat.tf_W_rsi_14 = wf.get("tf_W_rsi_14")
            feat.tf_W_price_vs_ema_200 = wf.get("tf_W_price_vs_ema_200")
            feat.tf_W_ema_stack_score = wf.get("tf_W_ema_stack_score")
            feat.tf_W_momentum_score = wf.get("tf_W_momentum_score")
            hf = intraday_features.get(ticker, {})
            feat.tf_4H_rsi_14 = hf.get("tf_4H_rsi_14")
            feat.tf_4H_price_vs_ema_200 = hf.get("tf_4H_price_vs_ema_200")
            feat.tf_4H_ema_stack_score = hf.get("tf_4H_ema_stack_score")
            feat.tf_4H_momentum_score = hf.get("tf_4H_momentum_score")
            ed = extra_daily.get(ticker, {})
            feat.price_change_1d = ed.get("price_change_1d")
            feat.price_change_5d = ed.get("price_change_5d")
            feat.price_change_20d = ed.get("price_change_20d")
            feat.bollinger_width = ed.get("bollinger_width")
            feat.volatility_20d = ed.get("volatility_20d")
            feat.high_low_range = ed.get("high_low_range")
            feat.gap_pct = ed.get("gap_pct")
            result[ticker] = feat
        return result

    @staticmethod
    def _snapshot_to_features(snap: Any, state: MarketState) -> TickerFeatures:
        """Map TechnicalSnapshot -> TickerFeatures."""
        rsi_val = snap.rsi.current if snap.rsi else 50.0
        ema_map = {e.period: e.current_value for e in (snap.emas or [])}
        price = snap.price_current or 0

        def pct_from_ema(period: int) -> float:
            ema = ema_map.get(period)
            return ((price - ema) / ema * 100) if ema and ema > 0 else 0.0

        alignment = snap.trend_alignment or "mixed"
        stack_score_map = {"all_bullish": 4.0, "all_bearish": 0.0, "mixed": 2.0}

        sorted_emas = sorted((snap.emas or []), key=lambda e: e.period)
        spread = 0.0
        if len(sorted_emas) >= 2:
            fastest = sorted_emas[0].current_value
            slowest = sorted_emas[-1].current_value
            spread = abs(fastest - slowest) / slowest * 100 if slowest > 0 else 0.0

        vol_trend_map = {"increasing": 1.0, "stable": 0.0, "decreasing": -1.0}
        macd_slope_map = {"expanding": 1.0, "contracting": 0.0}

        return TickerFeatures(
            ticker=snap.ticker,
            price=price,
            rsi=rsi_val,
            ema9_vs_price=pct_from_ema(9),
            ema21_vs_price=pct_from_ema(21),
            ema50_vs_price=pct_from_ema(50),
            ema200_vs_price=pct_from_ema(200),
            ema_alignment=alignment,
            ema_stack_score=stack_score_map.get(alignment, 2.0),
            ema_spread_pct=round(spread, 4),
            macd_histogram=snap.macd.histogram if snap.macd else 0.0,
            macd_slope=macd_slope_map.get(snap.macd.histogram_slope if snap.macd else "", 0.0),
            adx=snap.adx or 0.0,
            volume_ratio=snap.volume.ratio if snap.volume else 1.0,
            volume_trend=vol_trend_map.get(snap.volume.trend if snap.volume else "", 0.0),
            atr_pct=snap.atr_pct or 2.0,
            momentum_score=snap.momentum_score or 0.0,
            regime=state.regime_type,
        )

    # ── Internal: ML scoring ────────────────────────────────────────────

    @staticmethod
    async def _quick_ml_score(
        ticker: str,
        strategy: str,
        features: TickerFeatures,
        state: MarketState,
    ) -> float | None:
        """Run LightGBM independent model — fast, non-blocking."""
        try:
            from ml.gate import quick_score

            now = datetime.now(UTC)
            rsi_zone = 0 if features.rsi < 30 else (2 if features.rsi > 70 else 1)

            ta_dict: dict[str, float | None] = {
                "rsi_14": features.rsi,
                "rsi_zone": float(rsi_zone),
                "price_vs_ema_9": features.ema9_vs_price,
                "price_vs_ema_21": features.ema21_vs_price,
                "price_vs_ema_50": features.ema50_vs_price,
                "price_vs_ema_200": features.ema200_vs_price,
                "ema_stack_score": features.ema_stack_score,
                "ema_spread_pct": features.ema_spread_pct,
                "macd_histogram": features.macd_histogram,
                "macd_slope": features.macd_slope,
                "adx": features.adx,
                "atr_pct": features.atr_pct,
                "volume_ratio": features.volume_ratio,
                "volume_trend": features.volume_trend,
                "momentum_score": features.momentum_score,
                "distance_from_20d_high": features.distance_from_20d_high,
                "distance_from_20d_low": features.distance_from_20d_low,
                "day_of_week": float(now.weekday()),
                "month": float(now.month),
                "hmm_regime": 1.0
                if state.hmm_regime == "bull"
                else (0.0 if state.hmm_regime == "bear" else 0.5),
                "hmm_regime_prob_bull": (state.hmm_probs or {}).get("bull", 0.33),
                "hmm_regime_prob_neutral": (state.hmm_probs or {}).get("neutral", 0.34),
                "hmm_regime_prob_bear": (state.hmm_probs or {}).get("bear", 0.33),
                # Extra daily features
                "price_change_1d": features.price_change_1d,
                "price_change_5d": features.price_change_5d,
                "price_change_20d": features.price_change_20d,
                "bollinger_width": features.bollinger_width,
                "volatility_20d": features.volatility_20d,
                "high_low_range": features.high_low_range,
                "gap_pct": features.gap_pct,
                # Weekly timeframe features
                "tf_W_rsi_14": features.tf_W_rsi_14,
                "tf_W_price_vs_ema_200": features.tf_W_price_vs_ema_200,
                "tf_W_ema_stack_score": features.tf_W_ema_stack_score,
                "tf_W_momentum_score": features.tf_W_momentum_score,
                # 4H timeframe features
                "tf_4H_rsi_14": features.tf_4H_rsi_14,
                "tf_4H_price_vs_ema_200": features.tf_4H_price_vs_ema_200,
                "tf_4H_ema_stack_score": features.tf_4H_ema_stack_score,
                "tf_4H_momentum_score": features.tf_4H_momentum_score,
            }
            regime_ctx: dict[str, Any] = {
                "regime_type": state.regime_type,
                "vix_estimate": state.vix_estimate,
            }
            model_key = _STRATEGY_TO_MODEL.get(strategy, strategy)
            return await quick_score(ticker, model_key, ta_dict, regime_context=regime_ctx)
        except Exception:
            return None

    # ── Internal: rule labels ───────────────────────────────────────────

    @staticmethod
    def _get_matched_rules(strategy: str, f: TickerFeatures) -> list[str]:
        """Return human-readable labels for passing conditions."""
        labels: dict[str, list[tuple[bool, str]]] = {
            "swing": [
                (45 < f.rsi < 65, f"RSI {f.rsi:.0f}"),
                (f.ema_alignment in ("all_bullish", "mixed"), "EMA aligned"),
                (f.volume_ratio > 1.1, f"Vol {f.volume_ratio:.1f}x"),
                (f.momentum_score > 0.1, f"Mom {f.momentum_score:+.2f}"),
            ],
            "mean_reversion": [
                (f.rsi < 35, f"RSI oversold {f.rsi:.0f}"),
                (f.rsi > 72, f"RSI overbought {f.rsi:.0f}"),
                (f.volume_ratio > 1.3, f"Vol {f.volume_ratio:.1f}x"),
            ],
            "momentum_breakout": [
                (f.distance_from_20d_high < 2.0, "Near 20d high"),
                (f.volume_ratio > 1.8, f"Vol {f.volume_ratio:.1f}x breakout"),
                (f.ema_alignment == "all_bullish", "Full EMA stack"),
                (f.momentum_score > 0.3, f"Strong mom {f.momentum_score:+.2f}"),
            ],
            "bollinger_band_squeeze_breakout": [
                (f.atr_pct < 2.5, f"ATR squeeze {f.atr_pct:.1f}%"),
                (f.volume_ratio < 0.9, "Vol drying up"),
            ],
            "ema_stack_momentum": [
                (f.ema_alignment == "all_bullish", "Full EMA stack"),
                (0 < f.ema9_vs_price < 2, "Price near 9EMA"),
                (f.volume_ratio > 1.3, f"Vol {f.volume_ratio:.1f}x"),
            ],
            "ema_21_pullback": [
                (abs(f.ema21_vs_price) < 1.5, "Price at 21EMA"),
                (f.momentum_score > 0, "Uptrend"),
                (42 < f.rsi < 62, f"RSI neutral {f.rsi:.0f}"),
            ],
            "vwap_reversal_scalp": [
                (f.rsi < 38 or f.rsi > 65, f"RSI extreme {f.rsi:.0f}"),
                (f.volume_ratio > 1.8, f"Vol spike {f.volume_ratio:.1f}x"),
            ],
            "earnings_play": [
                (f.earnings_within_5d, "Earnings upcoming"),
                (f.volume_ratio > 1.2, f"Vol {f.volume_ratio:.1f}x"),
            ],
            "value_accumulation": [
                (f.rsi < 45, f"RSI low {f.rsi:.0f}"),
                (f.distance_from_20d_low < 5, "Near 20d low"),
            ],
            "intraday_scalp": [
                (f.volume_ratio > 2.0, f"Vol {f.volume_ratio:.1f}x"),
                (0.5 < f.atr_pct < 3.0, f"ATR {f.atr_pct:.1f}%"),
            ],
        }
        rules = labels.get(strategy, [])
        return [label for passed, label in rules if passed]

    # ── Supabase persistence ────────────────────────────────────────────

    async def _save_scan_run(self, report: ScanReport, triggered_by: str) -> None:
        try:
            db = await get_db()
            await (
                db.table("scan_runs")
                .insert(
                    {
                        "id": report.scan_run_id,
                        "triggered_by": triggered_by,
                        "started_at": report.started_at.isoformat(),
                        "status": "running",
                    }
                )
                .execute()
            )
        except Exception as exc:
            logger.warning("Scanner save_scan_run failed: %s", exc)

    async def _save_results(self, report: ScanReport) -> None:
        if not report.results:
            return
        try:
            db = await get_db()
            rows = [
                {
                    "id": str(uuid.uuid4()),
                    "scan_run_id": report.scan_run_id,
                    "scanned_at": datetime.now(UTC).isoformat(),
                    "strategy_type": r.strategy_type,
                    "ticker": r.ticker,
                    "rule_score": r.rule_score,
                    "ml_probability": r.ml_probability,
                    "combined_score": r.combined_score,
                    "matched_rules": r.matched_rules,
                    "regime_type": r.regime_type,
                    "rsi": r.rsi,
                    "ema_alignment": r.ema_alignment,
                    "volume_ratio": r.volume_ratio,
                    "momentum_score": r.momentum_score,
                    "atr_pct": r.atr_pct,
                    "earnings_within_5d": r.earnings_within_5d,
                    "is_actionable": r.is_actionable,
                }
                for r in report.results
            ]
            await db.table("scanner_results").insert(rows).execute()
        except Exception as exc:
            logger.warning("Scanner save_results failed: %s", exc)

    async def _finalize_report(self, report: ScanReport) -> None:
        try:
            db = await get_db()
            await (
                db.table("scan_runs")
                .update(
                    {
                        "completed_at": (report.completed_at or datetime.now(UTC)).isoformat(),
                        "duration_seconds": report.duration_seconds,
                        "universe_size": report.universe_size,
                        "setups_found": report.setups_found,
                        "strategies_with_setups": report.strategies_with_setups,
                        "regime_type": report.regime_type,
                        "status": report.status,
                    }
                )
                .eq("id", report.scan_run_id)
                .execute()
            )
        except Exception as exc:
            logger.warning("Scanner finalize_report failed: %s", exc)

    @staticmethod
    def _row_to_scan_result(row: dict[str, Any]) -> ScanResult:
        return ScanResult(
            ticker=row.get("ticker", ""),
            strategy_type=row.get("strategy_type", ""),
            rule_score=row.get("rule_score", 0.0),
            ml_probability=row.get("ml_probability"),
            combined_score=row.get("combined_score", 0.0),
            matched_rules=row.get("matched_rules", []),
            regime_type=row.get("regime_type", ""),
            rsi=row.get("rsi"),
            volume_ratio=row.get("volume_ratio"),
            momentum_score=row.get("momentum_score"),
            atr_pct=row.get("atr_pct"),
            ema_alignment=row.get("ema_alignment"),
            earnings_within_5d=row.get("earnings_within_5d", False),
            is_actionable=row.get("is_actionable", False),
        )
