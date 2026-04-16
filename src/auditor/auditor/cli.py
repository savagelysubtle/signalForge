"""Click CLI for the SignalForge Pipeline Auditor.

Commands:
    audit run     — Pull recommendations, fetch prices, grade, generate report.
    audit report  — Regenerate report from previously saved graded parquet data.
"""

from __future__ import annotations

import logging
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler

from auditor.config import default_output_dir

console = Console()


def _setup_logging(verbose: bool) -> None:
    """Configure logging with Rich handler."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
        force=True,
    )


@click.group()
def cli() -> None:
    """SignalForge Pipeline Auditor — grade recommendations against real prices."""


@cli.command()
@click.option(
    "--since", default=None, help="Only include recs created on or after this date (YYYY-MM-DD)."
)
@click.option(
    "--until", default=None, help="Only include recs created on or before this date (YYYY-MM-DD)."
)
@click.option("--tickers", default=None, help="Comma-separated list of tickers to audit.")
@click.option(
    "--output-dir", default=None, type=click.Path(), help="Directory for output artifacts."
)
@click.option(
    "--max-horizon", default=20, type=int, help="Max bars to look forward for barrier resolution."
)
@click.option(
    "--parquet-data",
    default=None,
    type=click.Path(exists=True),
    help="Path to ml_training data/raw for ParquetStore fallback.",
)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def run(
    since: str | None,
    until: str | None,
    tickers: str | None,
    output_dir: str | None,
    max_horizon: int,
    parquet_data: str | None,
    verbose: bool,
) -> None:
    """Pull recommendations from Supabase, grade against prices, generate report."""
    _setup_logging(verbose)

    from auditor.grader import GradeEngine
    from auditor.prices import PriceFetcher
    from auditor.pull import pull_all
    from auditor.report import build_report, print_report, save_json, save_parquet

    ticker_list = [t.strip() for t in tickers.split(",")] if tickers else None
    out_path = Path(output_dir) if output_dir else default_output_dir()
    out_path.mkdir(parents=True, exist_ok=True)

    console.print("\n[bold blue]Step 1/4:[/bold blue] Pulling recommendations from Supabase...")
    recs_df = pull_all(since=since, until=until, tickers=ticker_list)
    if recs_df.empty:
        console.print("[yellow]No recommendations found. Nothing to audit.[/yellow]")
        return
    console.print(f"  Found [bold]{len(recs_df)}[/bold] recommendations")

    console.print("\n[bold blue]Step 2/4:[/bold blue] Fetching price data...")
    parquet_dir = Path(parquet_data) if parquet_data else None
    fetcher = PriceFetcher(parquet_data_dir=parquet_dir, cache=True)

    unique_tickers = recs_df["ticker"].unique().tolist()
    console.print(f"  Downloading prices for [bold]{len(unique_tickers)}[/bold] tickers...")
    fetch_results = fetcher.prefetch(unique_tickers, start="2024-01-01", end="2026-12-31")
    ok = sum(1 for v in fetch_results.values() if v > 0)
    console.print(f"  Price data available for [bold]{ok}/{len(unique_tickers)}[/bold] tickers")

    console.print("\n[bold blue]Step 3/4:[/bold blue] Grading recommendations...")
    engine = GradeEngine(fetcher=fetcher, max_horizon=max_horizon)
    records = engine.grade_all(recs_df)

    console.print("\n[bold blue]Step 4/4:[/bold blue] Generating report...")
    report = build_report(records)
    print_report(report)

    parquet_path = out_path / "graded_recs.parquet"
    json_path = out_path / "audit_report.json"
    save_parquet(records, parquet_path)
    save_json(report, json_path)

    console.print("\n[bold green]Audit complete![/bold green]")
    console.print(f"  Parquet: {parquet_path}")
    console.print(f"  JSON:    {json_path}\n")


@cli.command()
@click.option(
    "--input",
    "input_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to graded_recs.parquet from a previous run.",
)
@click.option(
    "--output-dir", default=None, type=click.Path(), help="Directory for output artifacts."
)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def report(
    input_path: str,
    output_dir: str | None,
    verbose: bool,
) -> None:
    """Regenerate report from previously saved graded parquet data."""
    _setup_logging(verbose)

    import pandas as pd

    from auditor.models import (
        AuditRecord,
        DirectionGrade,
        TimingGrade,
        TradeGrade,
        WatchGrade,
    )
    from auditor.report import build_report, print_report, save_json

    console.print(f"\n[bold blue]Loading graded data from[/bold blue] {input_path}...")
    df = pd.read_parquet(input_path)

    records: list[AuditRecord] = []
    for _, row in df.iterrows():
        trade_grade = None
        if pd.notna(row.get("trade_label")):
            trade_grade = TradeGrade(
                label=row["trade_label"],
                profitable=bool(row.get("trade_profitable", False)),
                actual_return_pct=float(row.get("trade_return_pct", 0)),
                bars_to_resolution=int(row.get("trade_bars", 0)),
                mfe_pct=float(row.get("trade_mfe_pct", 0)),
                mae_pct=float(row.get("trade_mae_pct", 0)),
            )

        watch_grade = None
        if pd.notna(row.get("watch_label")):
            watch_grade = WatchGrade(
                label=row["watch_label"],
                entry_price_target=row.get("watch_entry_target"),
                bars_to_entry=row.get("watch_bars_to_entry"),
                hypothetical_return_pct=row.get("watch_hypo_return_pct"),
            )

        direction_grade = None
        if pd.notna(row.get("direction_predicted")):
            direction_grade = DirectionGrade(
                predicted_direction=row["direction_predicted"],
                actual_direction=row.get("direction_actual", ""),
                actual_return_pct=float(row.get("direction_return_pct", 0)),
                correct=bool(row.get("direction_correct", False)),
                horizon_bars=0,
            )

        timing_grade = None
        if pd.notna(row.get("timing_label")):
            timing_grade = TimingGrade(
                label=row["timing_label"],
                predicted_bars=row.get("timing_predicted_bars"),
                actual_bars=row.get("timing_actual_bars"),
            )

        records.append(
            AuditRecord(
                recommendation_id=str(row.get("recommendation_id", "")),
                ticker=str(row.get("ticker", "")),
                action=str(row.get("action", "")),
                confidence=row.get("confidence"),
                confidence_label=row.get("confidence_label"),
                entry_price=row.get("entry_price"),
                stop_loss=row.get("stop_loss"),
                take_profit=row.get("take_profit"),
                holding_period=row.get("holding_period"),
                signal_date=row.get("signal_date"),
                strategy_name=row.get("strategy_name"),
                pipeline_mode=row.get("pipeline_mode"),
                user_decision=row.get("user_decision"),
                logged_pnl_pct=row.get("logged_pnl_pct"),
                trade_grade=trade_grade,
                watch_grade=watch_grade,
                direction_grade=direction_grade,
                timing_grade=timing_grade,
                skip_reason=row.get("skip_reason"),
                audited_at=row.get("audited_at"),
            )
        )

    audit_report = build_report(records)
    print_report(audit_report)

    out_path = Path(output_dir) if output_dir else Path(input_path).parent
    json_path = out_path / "audit_report.json"
    save_json(audit_report, json_path)
    console.print(f"\n[bold green]Report regenerated![/bold green]  JSON: {json_path}\n")


if __name__ == "__main__":
    cli()
