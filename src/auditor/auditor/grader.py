"""Core grading engine — evaluates pipeline recommendations against historical prices.

Implements four grading dimensions:
1. Active trade grading (BUY/SHORT → TP_HIT / SL_HIT / TIME_EXIT)
2. Watch/entry grading (WATCH → did price reach entry, then what happened?)
3. Direction grading (all actions → did price move the predicted way?)
4. Timing grading (predicted holding_period vs actual bars to resolution)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from auditor.models import (
    AuditRecord,
    DirectionGrade,
    TimingGrade,
    TimingLabel,
    TradeGrade,
    TradeGradeLabel,
    WatchGrade,
    WatchGradeLabel,
)
from auditor.prices import PriceFetcher

logger = logging.getLogger(__name__)

DEFAULT_MAX_HORIZON = 20
DEFAULT_ATR_PROFIT_MULT = 2.0
DEFAULT_ATR_STOP_MULT = 1.0


class GradeEngine:
    """Grades pipeline recommendations against actual price data.

    Args:
        fetcher: PriceFetcher instance for retrieving OHLCV data.
        max_horizon: Maximum bars to look forward for barrier resolution.
    """

    def __init__(
        self,
        fetcher: PriceFetcher,
        max_horizon: int = DEFAULT_MAX_HORIZON,
    ) -> None:
        self._fetcher = fetcher
        self._max_horizon = max_horizon

    def grade_all(self, recs_df: pd.DataFrame) -> list[AuditRecord]:
        """Grade every recommendation row.

        Args:
            recs_df: DataFrame from ``pull.pull_all()``.

        Returns:
            List of AuditRecord objects — one per recommendation.
        """
        records: list[AuditRecord] = []
        total = len(recs_df)

        for i, (_, rec) in enumerate(recs_df.iterrows()):
            if (i + 1) % 25 == 0 or i == 0:
                logger.info("Grading recommendation %d/%d ...", i + 1, total)
            record = self._grade_one(rec)
            records.append(record)

        graded = sum(1 for r in records if r.skip_reason is None)
        logger.info("Grading complete: %d/%d graded, %d skipped", graded, total, total - graded)
        return records

    def _grade_one(self, rec: pd.Series) -> AuditRecord:
        """Grade a single recommendation row."""
        ticker = str(rec.get("ticker", ""))
        action = str(rec.get("action", "")).upper()
        rec_id = str(rec.get("id", ""))

        base = AuditRecord(
            recommendation_id=rec_id,
            ticker=ticker,
            action=action,
            confidence=_safe_float(rec.get("confidence")),
            confidence_label=_safe_str(rec.get("confidence_label")),
            entry_price=_safe_float(rec.get("entry_price")),
            stop_loss=_safe_float(rec.get("stop_loss")),
            take_profit=_safe_float(rec.get("take_profit")),
            holding_period=_safe_str(rec.get("holding_period")),
            price_at_signal=_safe_float(rec.get("price_at_signal")),
            signal_date=_resolve_signal_date(rec),
            strategy_name=_safe_str(rec.get("strategy_name")),
            pipeline_mode=_safe_str(rec.get("pipeline_mode")),
            user_decision=_safe_str(rec.get("user_decision")),
            logged_pnl_pct=_safe_float(rec.get("logged_pnl_pct")),
            audited_at=datetime.now(),
        )

        if base.signal_date is None:
            base.skip_reason = "no_signal_date"
            return base

        prices = self._fetcher.get_prices(ticker)
        if prices.empty:
            base.skip_reason = "no_price_data"
            return base

        entry_idx = _find_entry_index(prices, pd.Timestamp(base.signal_date))
        if entry_idx is None or entry_idx >= len(prices) - 2:
            base.skip_reason = "signal_date_out_of_range"
            return base

        remaining = len(prices) - entry_idx - 1
        if remaining < 3:
            base.skip_reason = "insufficient_bars"
            return base

        if action in ("BUY", "SHORT"):
            base.trade_grade = self._grade_active_trade(prices, entry_idx, rec, action)
        elif action in ("WATCH", "HOLD"):
            base.watch_grade = self._grade_watch(prices, entry_idx, rec)

        base.direction_grade = self._grade_direction(prices, entry_idx, action, rec)
        base.timing_grade = self._grade_timing(base)

        return base

    # ------------------------------------------------------------------
    # Active trade grading (BUY / SHORT)
    # ------------------------------------------------------------------

    def _grade_active_trade(
        self,
        prices: pd.DataFrame,
        entry_idx: int,
        rec: pd.Series,
        action: str,
    ) -> TradeGrade:
        """Triple-barrier walk-forward using GPT's SL/TP or ATR fallback."""
        close = prices["close"].values
        high = prices["high"].values
        low = prices["low"].values
        entry_price = float(close[entry_idx])
        is_long = action == "BUY"

        sl = _safe_float(rec.get("stop_loss"))
        tp = _safe_float(rec.get("take_profit"))

        sl_level: float
        tp_level: float
        levels_valid = (
            sl is not None
            and tp is not None
            and sl > 0
            and tp > 0
            and _levels_match_direction(entry_price, sl, tp, is_long)
        )
        if levels_valid:
            sl_level = sl  # type: ignore[assignment]
            tp_level = tp  # type: ignore[assignment]
        else:
            atr_pct = _compute_atr_pct(prices, entry_idx)
            if is_long:
                tp_level = entry_price * (1 + DEFAULT_ATR_PROFIT_MULT * atr_pct / 100)
                sl_level = entry_price * (1 - DEFAULT_ATR_STOP_MULT * atr_pct / 100)
            else:
                tp_level = entry_price * (1 - DEFAULT_ATR_PROFIT_MULT * atr_pct / 100)
                sl_level = entry_price * (1 + DEFAULT_ATR_STOP_MULT * atr_pct / 100)

        n = len(close)
        mfe = 0.0
        mae = 0.0

        for bar in range(1, min(self._max_horizon + 1, n - entry_idx)):
            fi = entry_idx + bar
            bar_high = float(high[fi])
            bar_low = float(low[fi])

            if is_long:
                mfe = max(mfe, (bar_high - entry_price) / entry_price * 100)
                mae = min(mae, (bar_low - entry_price) / entry_price * 100)
                if bar_high >= tp_level:
                    ret = (tp_level - entry_price) / entry_price * 100
                    return TradeGrade(
                        label=TradeGradeLabel.TP_HIT,
                        profitable=True,
                        actual_return_pct=round(ret, 4),
                        bars_to_resolution=bar,
                        mfe_pct=round(mfe, 4),
                        mae_pct=round(mae, 4),
                    )
                if bar_low <= sl_level:
                    ret = (sl_level - entry_price) / entry_price * 100
                    return TradeGrade(
                        label=TradeGradeLabel.SL_HIT,
                        profitable=False,
                        actual_return_pct=round(ret, 4),
                        bars_to_resolution=bar,
                        mfe_pct=round(mfe, 4),
                        mae_pct=round(mae, 4),
                    )
            else:
                mfe = max(mfe, (entry_price - bar_low) / entry_price * 100)
                mae = min(mae, (entry_price - bar_high) / entry_price * 100)
                if bar_low <= tp_level:
                    ret = (entry_price - tp_level) / entry_price * 100
                    return TradeGrade(
                        label=TradeGradeLabel.TP_HIT,
                        profitable=True,
                        actual_return_pct=round(ret, 4),
                        bars_to_resolution=bar,
                        mfe_pct=round(mfe, 4),
                        mae_pct=round(mae, 4),
                    )
                if bar_high >= sl_level:
                    ret = (entry_price - sl_level) / entry_price * 100
                    return TradeGrade(
                        label=TradeGradeLabel.SL_HIT,
                        profitable=False,
                        actual_return_pct=round(ret, 4),
                        bars_to_resolution=bar,
                        mfe_pct=round(mfe, 4),
                        mae_pct=round(mae, 4),
                    )

        exit_idx = min(entry_idx + self._max_horizon, n - 1)
        exit_price = float(close[exit_idx])
        if is_long:
            ret = (exit_price - entry_price) / entry_price * 100
        else:
            ret = (entry_price - exit_price) / entry_price * 100
        profitable = ret > 0

        return TradeGrade(
            label=TradeGradeLabel.TIME_EXIT,
            profitable=profitable,
            actual_return_pct=round(ret, 4),
            bars_to_resolution=min(self._max_horizon, n - entry_idx - 1),
            mfe_pct=round(mfe, 4),
            mae_pct=round(mae, 4),
        )

    # ------------------------------------------------------------------
    # Watch / entry-trigger grading
    # ------------------------------------------------------------------

    def _grade_watch(
        self,
        prices: pd.DataFrame,
        entry_idx: int,
        rec: pd.Series,
    ) -> WatchGrade:
        """Grade a WATCH/HOLD rec: did price reach entry_price, then what?"""
        target = _safe_float(rec.get("entry_price"))
        if target is None or target <= 0:
            return WatchGrade(label=WatchGradeLabel.ENTRY_NEVER_REACHED)

        close = prices["close"].values
        low = prices["low"].values
        high = prices["high"].values
        n = len(close)

        window = _parse_holding_period(rec.get("entry_valid_window")) or self._max_horizon

        for bar in range(1, min(window + 1, n - entry_idx)):
            fi = entry_idx + bar
            if float(low[fi]) <= target <= float(high[fi]):
                remaining_bars = min(self._max_horizon, n - fi - 1)
                if remaining_bars < 2:
                    return WatchGrade(
                        label=WatchGradeLabel.ENTRY_REACHED_PROFITABLE,
                        entry_price_target=target,
                        price_reached=float(close[fi]),
                        bars_to_entry=bar,
                        hypothetical_return_pct=0.0,
                    )

                exit_idx = min(fi + remaining_bars, n - 1)
                exit_price = float(close[exit_idx])
                hypo_return = (exit_price - target) / target * 100

                label = (
                    WatchGradeLabel.ENTRY_REACHED_PROFITABLE
                    if hypo_return > 0
                    else WatchGradeLabel.ENTRY_REACHED_UNPROFITABLE
                )
                return WatchGrade(
                    label=label,
                    entry_price_target=target,
                    price_reached=float(close[fi]),
                    bars_to_entry=bar,
                    hypothetical_return_pct=round(hypo_return, 4),
                )

        return WatchGrade(
            label=WatchGradeLabel.ENTRY_NEVER_REACHED,
            entry_price_target=target,
        )

    # ------------------------------------------------------------------
    # Direction grading (all actions)
    # ------------------------------------------------------------------

    def _grade_direction(
        self,
        prices: pd.DataFrame,
        entry_idx: int,
        action: str,
        rec: pd.Series,
    ) -> DirectionGrade:
        """Did the price move in the direction the pipeline predicted?"""
        close = prices["close"].values
        n = len(close)

        horizon = _parse_holding_period(rec.get("holding_period")) or self._max_horizon
        exit_idx = min(entry_idx + horizon, n - 1)
        entry_price = float(close[entry_idx])
        exit_price = float(close[exit_idx])
        actual_return = (exit_price - entry_price) / entry_price * 100

        if actual_return > 1.0:
            actual_dir = "UP"
        elif actual_return < -1.0:
            actual_dir = "DOWN"
        else:
            actual_dir = "FLAT"

        if action == "BUY":
            predicted = "UP"
        elif action == "SHORT":
            predicted = "DOWN"
        else:
            predicted = "FLAT"

        correct = predicted == actual_dir or (predicted == "FLAT" and abs(actual_return) <= 2.0)

        return DirectionGrade(
            predicted_direction=predicted,
            actual_direction=actual_dir,
            actual_return_pct=round(actual_return, 4),
            correct=correct,
            horizon_bars=exit_idx - entry_idx,
        )

    # ------------------------------------------------------------------
    # Timing grading
    # ------------------------------------------------------------------

    def _grade_timing(self, record: AuditRecord) -> TimingGrade:
        """Compare predicted holding period to actual bars-to-resolution."""
        predicted_bars = _parse_holding_period(record.holding_period)

        actual_bars: int | None = None
        if record.trade_grade:
            actual_bars = record.trade_grade.bars_to_resolution
        elif record.watch_grade and record.watch_grade.bars_to_entry is not None:
            actual_bars = record.watch_grade.bars_to_entry

        if predicted_bars is None or actual_bars is None:
            return TimingGrade(
                label=TimingLabel.UNKNOWN,
                predicted_bars=predicted_bars,
                actual_bars=actual_bars,
            )

        ratio = actual_bars / predicted_bars if predicted_bars > 0 else 999.0
        if ratio <= 0.6:
            label = TimingLabel.EARLY
        elif ratio <= 1.4:
            label = TimingLabel.ON_TIME
        elif actual_bars >= self._max_horizon:
            label = TimingLabel.EXPIRED
        else:
            label = TimingLabel.LATE

        return TimingGrade(
            label=label,
            predicted_bars=predicted_bars,
            actual_bars=actual_bars,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_signal_date(rec: pd.Series) -> datetime | None:
    """Extract the signal date from a recommendation row."""
    for col in ("signal_generated_at", "created_at"):
        val = rec.get(col)
        if val is not None and pd.notna(val):
            try:
                ts = pd.Timestamp(val)
                return ts.to_pydatetime().replace(tzinfo=None)
            except Exception:
                continue
    return None


def _find_entry_index(prices: pd.DataFrame, signal_date: pd.Timestamp) -> int | None:
    """Find the price bar index at or just after the signal date."""
    if prices.empty:
        return None

    dates = (
        prices["date"].dt.tz_localize(None) if prices["date"].dt.tz is not None else prices["date"]
    )
    target = signal_date.normalize()

    on_date = dates == target
    if on_date.any():
        return int(on_date.idxmax())

    after = dates >= target
    if after.any():
        return int(after.idxmax())

    before = dates <= target
    if before.any():
        return int(before[::-1].idxmax())

    return None


def _compute_atr_pct(prices: pd.DataFrame, idx: int, period: int = 14) -> float:
    """Compute ATR as a percentage of price at a given index."""
    if idx < period:
        return 2.0

    close = prices["close"].values
    high = prices["high"].values
    low = prices["low"].values

    trs: list[float] = []
    for i in range(max(1, idx - period + 1), idx + 1):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        trs.append(float(tr))

    if not trs:
        return 2.0

    atr = float(np.mean(trs))
    price = float(close[idx])
    return (atr / price * 100) if price > 0 else 2.0


def _parse_holding_period(val: Any) -> int | None:
    """Parse a holding_period string like '5 days' or '2-3 weeks' into bars (trading days)."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().lower()
    if not s:
        return None

    match = re.search(r"(\d+)", s)
    if not match:
        return None
    num = int(match.group(1))

    if "week" in s:
        return num * 5
    if "month" in s:
        return num * 21
    return num


def _levels_match_direction(entry: float, sl: float, tp: float, is_long: bool) -> bool:
    """Check that SL/TP make sense for the trade direction.

    For BUY:  SL should be below entry, TP above entry.
    For SHORT: SL should be above entry, TP below entry.
    Returns False if GPT set them backwards (e.g. long-style levels on a short).
    """
    if is_long:
        return sl < entry < tp
    return tp < entry < sl


def _safe_float(val: Any) -> float | None:
    """Convert a value to float, returning None on failure."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if not pd.isna(f) else None
    except (ValueError, TypeError):
        return None


def _safe_str(val: Any) -> str | None:
    """Convert a value to str, returning None for NaN/None."""
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    s = str(val)
    return s if s else None
