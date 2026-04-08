"""Risk gate engine — all checks must pass before any order is placed."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from mcp_server.config import settings

ET = ZoneInfo("America/New_York")

# Track recent order timestamps for rate limiting
_recent_order_times: list[float] = []


@dataclass(frozen=True)
class RiskCheck:
    """Result of a single risk gate check.

    Attributes:
        name: Short identifier for the check.
        passed: Whether the check passed.
        message: Human-readable explanation.
        value: Current value being checked.
        limit: Configured limit for the check.
    """

    name: str
    passed: bool
    message: str
    value: float | str | bool | None = None
    limit: float | str | bool | None = None


@dataclass
class RiskCheckResult:
    """Aggregated result of all risk gate checks.

    Attributes:
        passed: True only if ALL individual checks passed.
        checks: List of individual check results.
    """

    passed: bool = True
    checks: list[RiskCheck] = field(default_factory=list)

    def add(self, check: RiskCheck) -> None:
        """Add a check result and update the overall pass/fail status.

        Args:
            check: Individual risk check result.
        """
        self.checks.append(check)
        if not check.passed:
            self.passed = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON response.

        Returns:
            Dict with passed flag and list of check details.
        """
        return {
            "passed": self.passed,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "message": c.message,
                    "value": c.value,
                    "limit": c.limit,
                }
                for c in self.checks
            ],
        }


async def run_risk_gates(
    recommendation: dict[str, Any],
    account_summary: dict[str, Any],
    positions: list[dict[str, Any]],
) -> RiskCheckResult:
    """Run all risk gates against a recommendation.

    All checks are run regardless of individual failures so the user gets
    a complete picture of what passed and what didn't.

    Args:
        recommendation: The recommendation dict from the backend.
        account_summary: Account summary from IBKR (net_liquidation, etc.).
        positions: Current portfolio positions from IBKR.

    Returns:
        RiskCheckResult with all individual check results.
    """
    result = RiskCheckResult()
    equity = account_summary.get("net_liquidation", 0.0)

    result.add(_check_required_fields(recommendation))
    result.add(_check_confidence(recommendation))
    result.add(_check_ml_blocked(recommendation))
    result.add(_check_daily_loss(account_summary, equity))
    result.add(_check_portfolio_exposure(positions, equity))
    result.add(_check_market_hours())
    result.add(_check_rate_limit())

    return result


def record_order_placed() -> None:
    """Record that an order was just placed for rate limiting."""
    _recent_order_times.append(time.monotonic())


# ------------------------------------------------------------------
# Individual risk checks
# ------------------------------------------------------------------


def _check_required_fields(rec: dict[str, Any]) -> RiskCheck:
    missing = [f for f in ("entry_price", "stop_loss", "take_profit") if rec.get(f) is None]
    if missing:
        return RiskCheck(
            name="required_fields",
            passed=False,
            message=f"Missing: {', '.join(missing)}",
            value=", ".join(missing),
        )
    return RiskCheck(name="required_fields", passed=True, message="All price fields present")


def _check_confidence(rec: dict[str, Any]) -> RiskCheck:
    confidence = rec.get("confidence", 0.0)
    min_conf = settings.min_confidence
    if confidence < min_conf:
        return RiskCheck(
            name="confidence",
            passed=False,
            message=f"Confidence {confidence:.2f} below minimum {min_conf:.2f}",
            value=confidence,
            limit=min_conf,
        )
    return RiskCheck(
        name="confidence",
        passed=True,
        message=f"Confidence {confidence:.2f} meets minimum {min_conf:.2f}",
        value=confidence,
        limit=min_conf,
    )


def _check_ml_blocked(rec: dict[str, Any]) -> RiskCheck:
    blocked = rec.get("ml_blocked", False)
    if blocked:
        return RiskCheck(
            name="ml_blocked",
            passed=False,
            message="ML model has blocked this recommendation",
            value=True,
        )
    return RiskCheck(name="ml_blocked", passed=True, message="Not ML-blocked")


def _check_daily_loss(account: dict[str, Any], equity: float) -> RiskCheck:
    if equity <= 0:
        return RiskCheck(
            name="daily_loss",
            passed=False,
            message="Cannot determine equity — no account data",
        )

    unrealized = account.get("unrealized_pnl", 0.0)
    realized = account.get("realized_pnl", 0.0)
    total_pnl = unrealized + realized
    loss_pct = abs(total_pnl / equity * 100) if total_pnl < 0 else 0.0
    limit = settings.daily_loss_limit_pct

    if loss_pct > limit:
        return RiskCheck(
            name="daily_loss",
            passed=False,
            message=f"Daily loss {loss_pct:.2f}% exceeds limit {limit:.1f}%",
            value=round(loss_pct, 2),
            limit=limit,
        )
    return RiskCheck(
        name="daily_loss",
        passed=True,
        message=f"Daily P&L: ${total_pnl:+,.2f} ({loss_pct:.2f}% loss, limit {limit:.1f}%)",
        value=round(loss_pct, 2),
        limit=limit,
    )


def _check_portfolio_exposure(positions: list[dict[str, Any]], equity: float) -> RiskCheck:
    if equity <= 0:
        return RiskCheck(
            name="portfolio_exposure",
            passed=False,
            message="Cannot determine equity",
        )

    total_exposure = sum(abs(p.get("market_value", 0.0)) for p in positions)
    exposure_pct = total_exposure / equity * 100
    limit = settings.max_portfolio_exposure_pct

    if exposure_pct > limit:
        return RiskCheck(
            name="portfolio_exposure",
            passed=False,
            message=f"Portfolio exposure {exposure_pct:.1f}% exceeds limit {limit:.1f}%",
            value=round(exposure_pct, 1),
            limit=limit,
        )
    return RiskCheck(
        name="portfolio_exposure",
        passed=True,
        message=f"Portfolio exposure {exposure_pct:.1f}% within limit {limit:.1f}%",
        value=round(exposure_pct, 1),
        limit=limit,
    )


def _check_market_hours() -> RiskCheck:
    if not settings.require_market_hours:
        return RiskCheck(name="market_hours", passed=True, message="Market hours check disabled")

    now_et = datetime.now(tz=ET)

    # Weekday check (Mon=0 .. Sun=6)
    if now_et.weekday() >= 5:
        return RiskCheck(
            name="market_hours",
            passed=False,
            message=f"Weekend — US markets closed ({now_et.strftime('%A %H:%M ET')})",
            value=now_et.strftime("%A %H:%M ET"),
        )

    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)

    if now_et < market_open or now_et > market_close:
        return RiskCheck(
            name="market_hours",
            passed=False,
            message=f"Outside market hours ({now_et.strftime('%H:%M ET')}, open 9:30-16:00 ET)",
            value=now_et.strftime("%H:%M ET"),
            limit="9:30-16:00 ET",
        )

    return RiskCheck(
        name="market_hours",
        passed=True,
        message=f"Within market hours ({now_et.strftime('%H:%M ET')})",
        value=now_et.strftime("%H:%M ET"),
    )


def _check_rate_limit() -> RiskCheck:
    limit = settings.max_orders_per_hour
    cutoff = time.monotonic() - 3600

    # Prune old entries
    while _recent_order_times and _recent_order_times[0] < cutoff:
        _recent_order_times.pop(0)

    count = len(_recent_order_times)
    if count >= limit:
        return RiskCheck(
            name="rate_limit",
            passed=False,
            message=f"Rate limit reached: {count}/{limit} orders in the last hour",
            value=count,
            limit=limit,
        )
    return RiskCheck(
        name="rate_limit",
        passed=True,
        message=f"Order rate: {count}/{limit} in the last hour",
        value=count,
        limit=limit,
    )
