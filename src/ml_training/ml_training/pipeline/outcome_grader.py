"""Grade historical recommendations against actual price data.

For each recommendation pulled from Supabase, walks forward through OHLCV
price bars to determine whether the recommendation's TP or SL was hit,
or if the position timed out. Uses GPT's own stop-loss and take-profit
levels when available, falling back to ATR-based barriers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from ml_training.data.storage import ParquetStore

logger = logging.getLogger(__name__)

DEFAULT_MAX_HORIZON = 20
DEFAULT_ATR_PROFIT_MULT = 2.0
DEFAULT_ATR_STOP_MULT = 1.0


@dataclass
class GradeResult:
    """Summary of a grading run."""

    total: int = 0
    graded: int = 0
    skipped_no_prices: int = 0
    skipped_no_entry_date: int = 0
    skipped_insufficient_bars: int = 0
    tp_hit: int = 0
    sl_hit: int = 0
    time_exit: int = 0
    no_trade_correct: int = 0
    no_trade_missed: int = 0


def grade_recommendations(
    recs_df: pd.DataFrame,
    store: ParquetStore,
    max_horizon: int = DEFAULT_MAX_HORIZON,
) -> tuple[pd.DataFrame, GradeResult]:
    """Grade each recommendation against local price data.

    For BUY/SHORT recommendations, walks forward from the signal date
    checking GPT's SL/TP barriers. For NO_TRADE/HOLD/WATCH, checks
    whether standing aside was the right call.

    Args:
        recs_df: DataFrame from supabase_provider.pull_recommendations().
        store: ParquetStore with local OHLCV data.
        max_horizon: Maximum bars to look forward for barrier resolution.

    Returns:
        Tuple of (graded DataFrame, GradeResult summary).
    """
    result = GradeResult(total=len(recs_df))

    graded_rows: list[dict[str, Any]] = []

    from ml_training.data.supabase_provider import normalize_ticker

    for _, rec in recs_df.iterrows():
        ticker = normalize_ticker(rec.get("ticker", ""))
        action = rec.get("action", "")

        signal_date = _resolve_signal_date(rec)
        if signal_date is None:
            result.skipped_no_entry_date += 1
            continue

        prices = store.load_prices(ticker, "D")
        if prices.empty:
            result.skipped_no_prices += 1
            continue

        prices = prices.copy()
        prices["date"] = pd.to_datetime(prices["date"])

        entry_idx = _find_entry_index(prices, signal_date)
        if entry_idx is None or entry_idx >= len(prices) - 2:
            result.skipped_no_entry_date += 1
            continue

        remaining_bars = len(prices) - entry_idx - 1
        if remaining_bars < 3:
            result.skipped_insufficient_bars += 1
            continue

        if action in ("NO_TRADE", "HOLD", "WATCH"):
            grade = _grade_no_trade(prices, entry_idx, max_horizon)
        else:
            grade = _grade_active_trade(prices, entry_idx, rec, max_horizon)

        grade["recommendation_id"] = rec.get("id", "")
        grade["graded_at"] = datetime.now().isoformat()

        graded_rows.append(grade)
        result.graded += 1

        label = grade["graded_label"]
        if label == "TP_HIT":
            result.tp_hit += 1
        elif label == "SL_HIT":
            result.sl_hit += 1
        elif label == "TIME_EXIT":
            result.time_exit += 1
        elif label == "NO_TRADE_CORRECT":
            result.no_trade_correct += 1
        elif label == "NO_TRADE_MISSED":
            result.no_trade_missed += 1

    if not graded_rows:
        logger.warning("No recommendations could be graded")
        return recs_df, result

    grades_df = pd.DataFrame(graded_rows)

    merged = recs_df.merge(
        grades_df,
        left_on="id",
        right_on="recommendation_id",
        how="left",
        suffixes=("", "_grade"),
    )
    merged.drop(columns=["recommendation_id"], errors="ignore", inplace=True)

    logger.info(
        "Graded %d/%d recommendations: TP=%d SL=%d TIME=%d NO_TRADE_OK=%d NO_TRADE_MISS=%d",
        result.graded,
        result.total,
        result.tp_hit,
        result.sl_hit,
        result.time_exit,
        result.no_trade_correct,
        result.no_trade_missed,
    )

    return merged, result


def _resolve_signal_date(rec: pd.Series) -> pd.Timestamp | None:
    """Extract the signal date from a recommendation row."""
    for col in ("signal_generated_at", "created_at"):
        val = rec.get(col)
        if val is not None and pd.notna(val):
            try:
                ts = pd.Timestamp(val)
                if ts.tzinfo is not None:
                    ts = ts.tz_localize(None)
                return ts
            except Exception:
                continue
    return None


def _find_entry_index(prices: pd.DataFrame, signal_date: pd.Timestamp) -> int | None:
    """Find the price bar index at or just after the signal date."""
    if prices.empty:
        return None

    prices_dates = (
        prices["date"].dt.tz_localize(None) if prices["date"].dt.tz is not None else prices["date"]
    )

    on_date = prices_dates == signal_date.normalize()
    if on_date.any():
        return int(on_date.idxmax())

    after = prices_dates >= signal_date.normalize()
    if after.any():
        return int(after.idxmax())

    before = prices_dates <= signal_date.normalize()
    if before.any():
        return int(before[::-1].idxmax())

    return None


def _grade_active_trade(
    prices: pd.DataFrame,
    entry_idx: int,
    rec: pd.Series,
    max_horizon: int,
) -> dict[str, Any]:
    """Grade a BUY or SHORT recommendation using triple barrier logic.

    Uses GPT's own SL/TP when available, otherwise falls back to ATR-based barriers.
    """
    close = prices["close"].values
    high = prices["high"].values if "high" in prices.columns else close
    low = prices["low"].values if "low" in prices.columns else close

    entry_price = close[entry_idx]
    action = rec.get("action", "BUY")
    is_long = action == "BUY"

    sl = rec.get("stop_loss")
    tp = rec.get("take_profit")
    has_gpt_levels = (
        sl is not None
        and tp is not None
        and pd.notna(sl)
        and pd.notna(tp)
        and float(sl) > 0
        and float(tp) > 0
    )

    if has_gpt_levels:
        sl_level = float(sl)
        tp_level = float(tp)
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

    for bar in range(1, min(max_horizon + 1, n - entry_idx)):
        future_idx = entry_idx + bar
        bar_high = float(high[future_idx])
        bar_low = float(low[future_idx])

        if is_long:
            excursion_up = (bar_high - entry_price) / entry_price * 100
            excursion_down = (bar_low - entry_price) / entry_price * 100
            mfe = max(mfe, excursion_up)
            mae = min(mae, excursion_down)

            if bar_high >= tp_level:
                actual_return = (tp_level - entry_price) / entry_price * 100
                return _build_grade("TP_HIT", True, actual_return, bar, mfe, mae)
            if bar_low <= sl_level:
                actual_return = (sl_level - entry_price) / entry_price * 100
                return _build_grade("SL_HIT", False, actual_return, bar, mfe, mae)
        else:
            excursion_up = (entry_price - bar_low) / entry_price * 100
            excursion_down = (entry_price - bar_high) / entry_price * 100
            mfe = max(mfe, excursion_up)
            mae = min(mae, excursion_down)

            if bar_low <= tp_level:
                actual_return = (entry_price - tp_level) / entry_price * 100
                return _build_grade("TP_HIT", True, actual_return, bar, mfe, mae)
            if bar_high >= sl_level:
                actual_return = (entry_price - sl_level) / entry_price * 100
                return _build_grade("SL_HIT", False, actual_return, bar, mfe, mae)

    exit_idx = min(entry_idx + max_horizon, n - 1)
    exit_price = close[exit_idx]
    if is_long:
        actual_return = (exit_price - entry_price) / entry_price * 100
    else:
        actual_return = (entry_price - exit_price) / entry_price * 100

    profitable = actual_return > 0
    return _build_grade("TIME_EXIT", profitable, actual_return, max_horizon, mfe, mae)


def _grade_no_trade(
    prices: pd.DataFrame,
    entry_idx: int,
    max_horizon: int,
) -> dict[str, Any]:
    """Grade a NO_TRADE/HOLD/WATCH recommendation.

    NO_TRADE_CORRECT if price dropped >2% (standing aside was correct).
    NO_TRADE_MISSED if price rose >5% (missed a good opportunity).
    Otherwise TIME_EXIT with the actual return.
    """
    close = prices["close"].values
    n = len(close)
    entry_price = close[entry_idx]
    exit_idx = min(entry_idx + max_horizon, n - 1)
    exit_price = close[exit_idx]

    actual_return = (exit_price - entry_price) / entry_price * 100

    if actual_return < -2.0:
        return _build_grade(
            "NO_TRADE_CORRECT", True, actual_return, max_horizon, 0.0, actual_return
        )

    if actual_return > 5.0:
        return _build_grade(
            "NO_TRADE_MISSED", False, actual_return, max_horizon, actual_return, 0.0
        )

    return _build_grade(
        "TIME_EXIT",
        True,
        actual_return,
        max_horizon,
        max(0.0, actual_return),
        min(0.0, actual_return),
    )


def _build_grade(
    label: str,
    profitable: bool,
    actual_return: float,
    bars: int,
    mfe: float,
    mae: float,
) -> dict[str, Any]:
    return {
        "graded_label": label,
        "graded_profitable": 1 if profitable else 0,
        "actual_return_pct": round(actual_return, 4),
        "bars_to_resolution": bars,
        "mfe_pct": round(mfe, 4),
        "mae_pct": round(mae, 4),
    }


def _compute_atr_pct(prices: pd.DataFrame, idx: int, period: int = 14) -> float:
    """Compute ATR as a percentage of price at a given index."""
    if idx < period:
        return 2.0

    close = prices["close"].values
    high = prices["high"].values if "high" in prices.columns else close
    low = prices["low"].values if "low" in prices.columns else close

    trs: list[float] = []
    for i in range(max(1, idx - period + 1), idx + 1):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        trs.append(tr)

    if not trs:
        return 2.0

    atr = float(np.mean(trs))
    price = close[idx]
    if price <= 0:
        return 2.0

    return atr / price * 100
