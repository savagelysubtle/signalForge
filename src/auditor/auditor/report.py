"""Report builder — console summary (Rich), JSON export, parquet export."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from auditor.models import (
    AuditRecord,
    AuditReport,
    BucketStats,
    CalibrationBucket,
)

logger = logging.getLogger(__name__)
console = Console()


# ---------------------------------------------------------------------------
# Build aggregate report from graded records
# ---------------------------------------------------------------------------


def build_report(records: list[AuditRecord]) -> AuditReport:
    """Build an aggregated AuditReport from individual graded records.

    Args:
        records: List of AuditRecord objects from GradeEngine.grade_all().

    Returns:
        Populated AuditReport with stats by action, strategy, confidence, etc.
    """
    graded = [r for r in records if r.skip_reason is None]
    skipped = [r for r in records if r.skip_reason is not None]

    report = AuditReport(
        total_recommendations=len(records),
        total_graded=len(graded),
        total_skipped=len(skipped),
    )

    if not graded:
        return report

    wins = _count_wins(graded)
    returns = _collect_returns(graded)
    direction_correct = sum(1 for r in graded if r.direction_grade and r.direction_grade.correct)
    direction_total = sum(1 for r in graded if r.direction_grade is not None)

    report.overall_win_rate = wins / len(graded) if graded else 0.0
    report.overall_avg_return_pct = sum(returns) / len(returns) if returns else 0.0
    report.overall_direction_accuracy = (
        direction_correct / direction_total if direction_total > 0 else 0.0
    )

    report.by_action = _bucket_by(graded, lambda r: r.action)
    report.by_strategy = _bucket_by(graded, lambda r: r.strategy_name or "unknown")
    report.by_confidence_bucket = _bucket_by(graded, _confidence_bucket_label)

    report.calibration = _compute_calibration(graded)
    if report.calibration:
        report.calibration_error_mean = sum(b.calibration_error for b in report.calibration) / len(
            report.calibration
        )

    report.timing_breakdown = _timing_breakdown(graded)

    sorted_by_return = sorted(
        [r for r in graded if _get_return(r) is not None],
        key=lambda r: _get_return(r) or 0.0,
    )
    report.top_losers = [_summary_dict(r) for r in sorted_by_return[:5]]
    report.top_winners = [_summary_dict(r) for r in sorted_by_return[-5:][::-1]]

    return report


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------


def print_report(report: AuditReport) -> None:
    """Print a formatted audit report to the console using Rich."""
    console.print()
    console.print(
        Panel(
            f"[bold]Pipeline Audit Report[/bold]\n"
            f"Generated: {report.generated_at:%Y-%m-%d %H:%M}\n"
            f"Recommendations: {report.total_recommendations}  "
            f"Graded: {report.total_graded}  "
            f"Skipped: {report.total_skipped}",
            title="SignalForge Auditor",
            border_style="blue",
        )
    )

    overview = Table(title="Overview", show_header=False, border_style="dim")
    overview.add_column("Metric", style="cyan")
    overview.add_column("Value", style="bold")
    overview.add_row("Win Rate", f"{report.overall_win_rate:.1%}")
    overview.add_row("Avg Return", f"{report.overall_avg_return_pct:+.2f}%")
    overview.add_row("Direction Accuracy", f"{report.overall_direction_accuracy:.1%}")
    overview.add_row("Calibration Error (mean)", f"{report.calibration_error_mean:.3f}")
    console.print(overview)

    if report.by_action:
        _print_bucket_table("By Action", report.by_action)

    if report.by_strategy:
        _print_bucket_table("By Strategy", report.by_strategy)

    if report.by_confidence_bucket:
        _print_bucket_table("By Confidence Bucket", report.by_confidence_bucket)

    if report.calibration:
        cal_table = Table(title="Confidence Calibration", border_style="dim")
        cal_table.add_column("Bucket", style="cyan")
        cal_table.add_column("Count", justify="right")
        cal_table.add_column("Predicted", justify="right")
        cal_table.add_column("Actual Win%", justify="right")
        cal_table.add_column("Error", justify="right")
        for b in report.calibration:
            err_style = "red" if b.calibration_error > 0.15 else "green"
            cal_table.add_row(
                b.range_label,
                str(b.count),
                f"{b.predicted_confidence:.0%}",
                f"{b.actual_win_rate:.0%}",
                f"[{err_style}]{b.calibration_error:.3f}[/{err_style}]",
            )
        console.print(cal_table)

    if report.timing_breakdown:
        timing_table = Table(title="Timing Accuracy", border_style="dim")
        timing_table.add_column("Label", style="cyan")
        timing_table.add_column("Count", justify="right")
        for label, count in sorted(report.timing_breakdown.items()):
            timing_table.add_row(label, str(count))
        console.print(timing_table)

    if report.top_winners:
        console.print("\n[bold green]Top Winners:[/bold green]")
        for w in report.top_winners:
            console.print(
                f"  {w['ticker']:>8}  {w['action']:>8}  {w['return']:>+8.2f}%  {w.get('strategy', '')}"
            )

    if report.top_losers:
        console.print("\n[bold red]Top Losers:[/bold red]")
        for lo in report.top_losers:
            console.print(
                f"  {lo['ticker']:>8}  {lo['action']:>8}  {lo['return']:>+8.2f}%  {lo.get('strategy', '')}"
            )

    console.print()


def _print_bucket_table(title: str, buckets: dict[str, BucketStats]) -> None:
    """Print a Rich table for a bucket breakdown."""
    table = Table(title=title, border_style="dim")
    table.add_column("Bucket", style="cyan")
    table.add_column("Total", justify="right")
    table.add_column("Wins", justify="right")
    table.add_column("Losses", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("Avg Return", justify="right")
    for name, stats in sorted(buckets.items()):
        wr_style = "green" if stats.win_rate >= 0.5 else "red"
        table.add_row(
            name,
            str(stats.total),
            str(stats.wins),
            str(stats.losses),
            f"[{wr_style}]{stats.win_rate:.0%}[/{wr_style}]",
            f"{stats.avg_return_pct:+.2f}%",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def save_json(report: AuditReport, path: Path) -> None:
    """Save the audit report as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Report JSON saved to %s", path)


def save_parquet(records: list[AuditRecord], path: Path) -> None:
    """Save graded audit records as a parquet file for downstream analysis."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for rec in records:
        row: dict[str, Any] = {
            "recommendation_id": rec.recommendation_id,
            "ticker": rec.ticker,
            "action": rec.action,
            "confidence": rec.confidence,
            "confidence_label": rec.confidence_label,
            "entry_price": rec.entry_price,
            "stop_loss": rec.stop_loss,
            "take_profit": rec.take_profit,
            "holding_period": rec.holding_period,
            "signal_date": rec.signal_date,
            "strategy_name": rec.strategy_name,
            "pipeline_mode": rec.pipeline_mode,
            "user_decision": rec.user_decision,
            "logged_pnl_pct": rec.logged_pnl_pct,
            "skip_reason": rec.skip_reason,
            "audited_at": rec.audited_at,
        }
        if rec.trade_grade:
            row["trade_label"] = rec.trade_grade.label
            row["trade_profitable"] = rec.trade_grade.profitable
            row["trade_return_pct"] = rec.trade_grade.actual_return_pct
            row["trade_bars"] = rec.trade_grade.bars_to_resolution
            row["trade_mfe_pct"] = rec.trade_grade.mfe_pct
            row["trade_mae_pct"] = rec.trade_grade.mae_pct
        if rec.watch_grade:
            row["watch_label"] = rec.watch_grade.label
            row["watch_entry_target"] = rec.watch_grade.entry_price_target
            row["watch_bars_to_entry"] = rec.watch_grade.bars_to_entry
            row["watch_hypo_return_pct"] = rec.watch_grade.hypothetical_return_pct
        if rec.direction_grade:
            row["direction_predicted"] = rec.direction_grade.predicted_direction
            row["direction_actual"] = rec.direction_grade.actual_direction
            row["direction_return_pct"] = rec.direction_grade.actual_return_pct
            row["direction_correct"] = rec.direction_grade.correct
        if rec.timing_grade:
            row["timing_label"] = rec.timing_grade.label
            row["timing_predicted_bars"] = rec.timing_grade.predicted_bars
            row["timing_actual_bars"] = rec.timing_grade.actual_bars
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_parquet(path, index=False)
    logger.info("Graded records saved to %s (%d rows)", path, len(df))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _count_wins(records: list[AuditRecord]) -> int:
    total = 0
    for r in records:
        if (
            (r.trade_grade and r.trade_grade.profitable)
            or (r.watch_grade and r.watch_grade.label == "ENTRY_REACHED_PROFITABLE")
            or (
                r.direction_grade
                and r.direction_grade.correct
                and r.trade_grade is None
                and r.watch_grade is None
            )
        ):
            total += 1
    return total


def _is_win(r: AuditRecord) -> bool:
    if r.trade_grade:
        return r.trade_grade.profitable
    if r.watch_grade:
        return r.watch_grade.label == "ENTRY_REACHED_PROFITABLE"
    if r.direction_grade:
        return r.direction_grade.correct
    return False


def _get_return(r: AuditRecord) -> float | None:
    if r.trade_grade:
        return r.trade_grade.actual_return_pct
    if r.watch_grade and r.watch_grade.hypothetical_return_pct is not None:
        return r.watch_grade.hypothetical_return_pct
    if r.direction_grade:
        return r.direction_grade.actual_return_pct
    return None


def _collect_returns(records: list[AuditRecord]) -> list[float]:
    return [r for rec in records if (r := _get_return(rec)) is not None]


def _bucket_by(
    records: list[AuditRecord],
    key_fn: Any,
) -> dict[str, BucketStats]:
    buckets: dict[str, list[AuditRecord]] = {}
    for r in records:
        k = str(key_fn(r))
        buckets.setdefault(k, []).append(r)

    result: dict[str, BucketStats] = {}
    for name, recs in buckets.items():
        wins = sum(1 for r in recs if _is_win(r))
        returns = _collect_returns(recs)
        confs = [r.confidence for r in recs if r.confidence is not None]
        result[name] = BucketStats(
            total=len(recs),
            wins=wins,
            losses=len(recs) - wins,
            win_rate=wins / len(recs) if recs else 0.0,
            avg_return_pct=sum(returns) / len(returns) if returns else 0.0,
            avg_confidence=sum(confs) / len(confs) if confs else 0.0,
        )
    return result


def _confidence_bucket_label(r: AuditRecord) -> str:
    c = r.confidence
    if c is None:
        return "unknown"
    if c < 0.4:
        return "0-40%"
    if c < 0.6:
        return "40-60%"
    if c < 0.8:
        return "60-80%"
    return "80-100%"


def _compute_calibration(records: list[AuditRecord]) -> list[CalibrationBucket]:
    """Compute calibration buckets: predicted confidence vs actual win rate."""
    edges = [
        (0.0, 0.4, "0-40%"),
        (0.4, 0.6, "40-60%"),
        (0.6, 0.8, "60-80%"),
        (0.8, 1.01, "80-100%"),
    ]
    result: list[CalibrationBucket] = []

    for lo, hi, label in edges:
        in_bucket = [r for r in records if r.confidence is not None and lo <= r.confidence < hi]
        if not in_bucket:
            continue
        avg_conf = sum(r.confidence for r in in_bucket if r.confidence is not None) / len(in_bucket)
        wins = sum(1 for r in in_bucket if _is_win(r))
        actual_wr = wins / len(in_bucket)
        result.append(
            CalibrationBucket(
                range_label=label,
                predicted_confidence=round(avg_conf, 3),
                actual_win_rate=round(actual_wr, 3),
                count=len(in_bucket),
                calibration_error=round(abs(avg_conf - actual_wr), 3),
            )
        )
    return result


def _timing_breakdown(records: list[AuditRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in records:
        if r.timing_grade:
            label = r.timing_grade.label
            counts[label] = counts.get(label, 0) + 1
    return counts


def _summary_dict(r: AuditRecord) -> dict[str, Any]:
    return {
        "ticker": r.ticker,
        "action": r.action,
        "return": _get_return(r) or 0.0,
        "confidence": r.confidence,
        "strategy": r.strategy_name or "",
    }
