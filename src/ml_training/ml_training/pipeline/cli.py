"""Command-line interface for ML training operations.

Usage::

    uv run python -m ml_training.pipeline.cli acquire
    uv run python -m ml_training.pipeline.cli build-dataset
    uv run python -m ml_training.pipeline.cli train --rounds 3
    uv run python -m ml_training.pipeline.cli tune
    uv run python -m ml_training.pipeline.cli verify
    uv run python -m ml_training.pipeline.cli promote

The FMP API key is loaded automatically from your .env file
(FMP_API_KEY). You can override it with --api-key if needed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from ml_training.data.storage import ParquetStore
    from ml_training.pipeline.training_loop import TrainingRoundResult

logger = logging.getLogger("ml_training")

ENV_CANDIDATES = [
    Path.cwd() / ".env",
    Path(__file__).resolve().parents[3] / ".env",
    Path(__file__).resolve().parents[4] / ".env",
]


def _load_env() -> None:
    """Load .env file from the project root."""
    for env_file in ENV_CANDIDATES:
        if env_file.exists():
            load_dotenv(env_file, override=True)
            logger.debug("Loaded .env from %s", env_file)
            return
    logger.debug("No .env file found -- using existing environment variables")


def _get_fmp_key(cli_override: str | None = None) -> str:
    """Get the FMP API key from CLI arg, env var, or .env file.

    Args:
        cli_override: Explicit key passed via --api-key.

    Returns:
        The FMP API key.

    Raises:
        SystemExit: If no key is found anywhere.
    """
    if cli_override:
        return cli_override
    key = os.environ.get("FMP_API_KEY")
    if key:
        return key
    print("Error: FMP_API_KEY not found in .env or environment.")
    print("Either set FMP_API_KEY in your .env file or pass --api-key.")
    sys.exit(1)


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Suppress noisy/leaky HTTP debug logs (they print API keys in URLs)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def cmd_acquire(args: argparse.Namespace) -> None:
    """Run data acquisition from FMP."""
    from ml_training.data.acquisition import AcquisitionConfig, DataAcquisitionPipeline

    api_key = _get_fmp_key(getattr(args, "api_key", None))

    config = AcquisitionConfig(
        api_key=api_key,
        data_dir=Path(args.data_dir),
        timeframes=args.timeframes.split(","),
        daily_lookback_days=args.lookback_days,
    )
    pipeline = DataAcquisitionPipeline(config)
    results = asyncio.run(pipeline.run(category=args.category))
    print(f"\nAcquisition complete: {results}")


def cmd_build_dataset(args: argparse.Namespace) -> None:
    """Build feature datasets from acquired data."""
    from ml_training.data.storage import ParquetStore
    from ml_training.features.dataset_builder import DatasetBuilder

    store = ParquetStore(Path(args.data_dir))
    builder = DatasetBuilder(store)
    df = builder.build_all(save=True)

    if df.empty:
        print("No samples generated. Check that data has been acquired first.")
        sys.exit(1)

    print(f"\nDataset built: {len(df)} samples, {len(df.columns)} features")
    print(f"Strategy distribution:\n{df['strategy_type'].value_counts().to_string()}")


def cmd_validate(args: argparse.Namespace) -> None:
    """Validate the training dataset."""
    from ml_training.data.storage import ParquetStore
    from ml_training.features.validator import DatasetValidator

    store = ParquetStore(Path(args.data_dir))
    df = store.load_dataset("all_features")

    if df.empty:
        print("No dataset found. Run build-dataset first.")
        sys.exit(1)

    validator = DatasetValidator(df)
    report = validator.validate()
    print(report.summary())

    if not report.is_valid:
        sys.exit(1)


def _resolve_strategy_target(
    strategy_key: str | None,
    cli_target: str,
    cli_return: str,
    binary_mode: bool,
) -> tuple[str, str]:
    """Determine the target and return columns for a strategy.

    When per-strategy training is used with default target, the horizon
    is looked up from strategies.json so each strategy predicts over its
    natural time-frame.
    """
    if binary_mode:
        return "profitable", cli_return

    if strategy_key is None or cli_target != "direction_10d":
        return cli_target, cli_return

    from ml_training.features.dataset_builder import load_strategies

    for s in load_strategies():
        if s.id == strategy_key:
            return s.target_col, s.return_col

    return cli_target, cli_return


def _train_single(
    store: ParquetStore,
    strategy_type: str | None,
    args: argparse.Namespace,
) -> list[TrainingRoundResult]:
    """Train a single model (combined or per-strategy).

    Args:
        store: Parquet data store.
        strategy_type: Strategy key or None for combined.
        args: CLI namespace with training config.

    Returns:
        List of round results.
    """
    from ml_training.pipeline.hyperparameter_tuning import load_tuned_params
    from ml_training.pipeline.training_loop import TrainingLoop, TrainingLoopConfig

    if strategy_type:
        df = store.load_dataset(f"{strategy_type}_features")
        label = strategy_type
    else:
        df = store.load_dataset("all_features")
        label = "combined"

    if df.empty:
        print(f"  [{label}] No dataset found, skipping.")
        return []

    classifier_params = None
    if not args.no_tuned:
        classifier_params = load_tuned_params(Path(args.data_dir), strategy_type=strategy_type)
        if classifier_params:
            params_label = f"tuned ({strategy_type})" if strategy_type else "tuned (combined)"
            print(f"  [{label}] Using {params_label} params")

    binary_mode = getattr(args, "binary", False)
    target_col, return_col = _resolve_strategy_target(
        strategy_type, args.target, args.return_col, binary_mode
    )

    if target_col != args.target:
        print(f"  [{label}] Auto-selected target: {target_col}")

    config = TrainingLoopConfig(
        max_rounds=args.rounds,
        target_col=target_col,
        return_col=return_col,
        n_boost_rounds=args.boost_rounds,
        auto_promote=args.auto_promote,
        classifier_params=classifier_params,
        strategy_type=strategy_type,
        binary_mode=binary_mode,
    )

    loop = TrainingLoop(config)
    results = loop.run(df)

    print(f"\n  [{label}] Completed {len(results)} round(s)")
    for r in results:
        if r.judge_report:
            print(f"    Round {r.round_num}: {r.judge_report.judge_verdict}")
            print(f"      Accuracy: {r.judge_report.overall_accuracy:.1%}")
            print(f"      Artifact: {r.artifact_path}")

    return results


def cmd_train(args: argparse.Namespace) -> None:
    """Run the training loop, optionally per-strategy."""
    from ml_training.data.storage import ParquetStore

    store = ParquetStore(Path(args.data_dir))

    if args.per_strategy:
        strategies = [args.strategy] if args.strategy else store.list_strategy_datasets()
        if not strategies:
            print("No per-strategy datasets found. Run build-dataset first.")
            sys.exit(1)
        print(f"Training per-strategy models for: {strategies}")
        for st in strategies:
            print(f"\n{'=' * 60}")
            print(f"STRATEGY: {st}")
            print("=" * 60)
            _train_single(store, st, args)
    else:
        _train_single(store, None, args)


def _tune_single(
    store: ParquetStore,
    strategy_type: str | None,
    args: argparse.Namespace,
) -> None:
    """Tune hyperparameters for a single dataset (combined or per-strategy)."""
    from ml_training.pipeline.hyperparameter_tuning import HyperparameterTuner

    if strategy_type:
        df = store.load_dataset(f"{strategy_type}_features")
        label = strategy_type
    else:
        df = store.load_dataset("all_features")
        label = "combined"

    if df.empty:
        print(f"  [{label}] No dataset found, skipping.")
        return

    target_col, _return_col = _resolve_strategy_target(
        strategy_type, args.target, "return_10d", binary_mode=False
    )

    if target_col != args.target:
        print(f"  [{label}] Auto-selected target: {target_col}")

    tuner = HyperparameterTuner(target_col=target_col)
    n_trials = getattr(args, "n_trials", 0)
    result = tuner.search_optuna(df, n_trials=n_trials) if n_trials > 0 else tuner.search(df)

    saved_path = HyperparameterTuner.save_best_params(
        result, Path(args.data_dir), strategy_type=strategy_type
    )

    print(f"\n  [{label}] Best score: {result.best_score:.4f}")
    print(f"  [{label}] Best params: {json.dumps(result.best_params, indent=2)}")
    print(f"  [{label}] Saved to {saved_path}")


def cmd_tune(args: argparse.Namespace) -> None:
    """Run hyperparameter tuning, optionally per-strategy."""
    from ml_training.data.storage import ParquetStore

    store = ParquetStore(Path(args.data_dir))

    if args.per_strategy:
        strategies = [args.strategy] if args.strategy else store.list_strategy_datasets()
        if not strategies:
            print("No per-strategy datasets found. Run build-dataset first.")
            sys.exit(1)
        print(f"Tuning per-strategy for: {strategies}")
        for st in strategies:
            print(f"\n{'=' * 60}")
            print(f"STRATEGY: {st}")
            print("=" * 60)
            _tune_single(store, st, args)
    else:
        _tune_single(store, None, args)


def cmd_verify(args: argparse.Namespace) -> None:
    """Verify acquired data quality."""
    from ml_training.data.storage import ParquetStore

    store = ParquetStore(Path(args.data_dir))
    results = store.verify_data()
    print(json.dumps(results["summary"], indent=2))

    if results["tickers_with_issues"]:
        print(f"\nIssues ({len(results['tickers_with_issues'])}):")
        for issue in results["tickers_with_issues"][:20]:
            print(f"  - {issue}")

    if results["tickers_with_gaps"]:
        print(f"\nGaps ({len(results['tickers_with_gaps'])}):")
        for gap in results["tickers_with_gaps"][:20]:
            print(f"  - {gap}")


def cmd_promote(args: argparse.Namespace) -> None:
    """Promote models to shadow mode (all strategy models + combined fallback)."""
    from ml_training.models.registry import ModelRegistry

    registry = ModelRegistry()
    promoted = registry.promote_all_strategies()

    if not promoted:
        print("No model artifacts found. Run train first.")
        sys.exit(1)

    print(f"Promoted {len(promoted)} model(s):")
    for p in promoted:
        print(f"  -> {p}")


def cmd_resolve_outcomes(args: argparse.Namespace) -> None:
    """Resolve unresolved predictions against actual price data."""
    from ml_training.data.storage import ParquetStore
    from ml_training.pipeline.outcome_tracker import OutcomeTracker

    store = ParquetStore(Path(args.data_dir))
    tracker = OutcomeTracker(Path(args.data_dir), horizon_days=args.horizon)
    result = tracker.resolve_outcomes(store)

    print(f"Resolved {result.newly_resolved} of {result.total_unresolved} pending predictions")
    print(f"Remaining unresolved: {result.remaining}")


def cmd_report_outcomes(args: argparse.Namespace) -> None:
    """Print rolling accuracy dashboard from resolved predictions."""
    from ml_training.pipeline.outcome_tracker import OutcomeTracker

    tracker = OutcomeTracker(Path(args.data_dir))
    report = tracker.report()
    print(report.summary())


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="ml-train",
        description="SignalForge ML Training Pipeline",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")

    sub = parser.add_subparsers(dest="command", required=True)

    # acquire
    p_acquire = sub.add_parser("acquire", help="Pull historical data from FMP")
    p_acquire.add_argument(
        "--api-key", default=None, help="FMP API key (reads from .env if omitted)"
    )
    p_acquire.add_argument("--data-dir", default="data/raw", help="Output directory")
    p_acquire.add_argument("--timeframes", default="D,4H,1H", help="Comma-separated timeframes")
    p_acquire.add_argument("--lookback-days", type=int, default=730, help="Daily lookback (days)")
    p_acquire.add_argument("--category", choices=["all", "tsx", "us", "crypto"], default="all")
    p_acquire.set_defaults(func=cmd_acquire)

    # build-dataset
    p_build = sub.add_parser("build-dataset", help="Build feature datasets")
    p_build.add_argument("--data-dir", default="data/raw")
    p_build.set_defaults(func=cmd_build_dataset)

    # validate
    p_val = sub.add_parser("validate", help="Validate training dataset")
    p_val.add_argument("--data-dir", default="data/raw")
    p_val.set_defaults(func=cmd_validate)

    # train
    p_train = sub.add_parser("train", help="Run training loop")
    p_train.add_argument("--rounds", type=int, default=3, help="Max training rounds")
    p_train.add_argument("--target", default="direction_10d", help="Target column")
    p_train.add_argument("--return-col", default="return_10d", help="Return column")
    p_train.add_argument("--boost-rounds", type=int, default=500, help="Boosting rounds")
    p_train.add_argument("--auto-promote", action="store_true", help="Auto-promote on PASS")
    p_train.add_argument(
        "--no-tuned", action="store_true", help="Ignore tuned params, use defaults"
    )
    p_train.add_argument("--per-strategy", action="store_true", help="Train per-strategy models")
    p_train.add_argument(
        "--strategy", default=None, help="Train a single strategy (requires --per-strategy)"
    )
    p_train.add_argument(
        "--binary",
        action="store_true",
        help="Binary classification (profitable vs not) instead of 3-class direction",
    )
    p_train.add_argument("--data-dir", default="data/raw")
    p_train.set_defaults(func=cmd_train)

    # tune
    p_tune = sub.add_parser("tune", help="Hyperparameter tuning")
    p_tune.add_argument("--target", default="direction_10d", help="Target column")
    p_tune.add_argument("--per-strategy", action="store_true", help="Tune per-strategy")
    p_tune.add_argument(
        "--strategy", default=None, help="Tune a single strategy (requires --per-strategy)"
    )
    p_tune.add_argument(
        "--n-trials",
        type=int,
        default=0,
        help="Optuna Bayesian search trials (0 = grid search fallback)",
    )
    p_tune.add_argument("--data-dir", default="data/raw")
    p_tune.set_defaults(func=cmd_tune)

    # verify
    p_verify = sub.add_parser("verify", help="Verify acquired data")
    p_verify.add_argument("--data-dir", default="data/raw")
    p_verify.set_defaults(func=cmd_verify)

    # promote
    p_promote = sub.add_parser("promote", help="Promote latest model to shadow mode")
    p_promote.set_defaults(func=cmd_promote)

    # resolve-outcomes
    p_resolve = sub.add_parser("resolve-outcomes", help="Resolve prediction outcomes")
    p_resolve.add_argument("--data-dir", default="data/raw")
    p_resolve.add_argument("--horizon", type=int, default=10, help="Days to wait before resolving")
    p_resolve.set_defaults(func=cmd_resolve_outcomes)

    # report-outcomes
    p_report = sub.add_parser("report-outcomes", help="Print outcome accuracy dashboard")
    p_report.add_argument("--data-dir", default="data/raw")
    p_report.set_defaults(func=cmd_report_outcomes)

    args = parser.parse_args()
    _setup_logging(args.verbose)
    _load_env()
    args.func(args)


if __name__ == "__main__":
    main()
