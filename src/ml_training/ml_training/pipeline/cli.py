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

from dotenv import load_dotenv

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


def cmd_train(args: argparse.Namespace) -> None:
    """Run the training loop."""
    from ml_training.data.storage import ParquetStore
    from ml_training.pipeline.training_loop import TrainingLoop, TrainingLoopConfig

    store = ParquetStore(Path(args.data_dir))
    df = store.load_dataset("all_features")

    if df.empty:
        print("No dataset found. Run build-dataset first.")
        sys.exit(1)

    config = TrainingLoopConfig(
        max_rounds=args.rounds,
        target_col=args.target,
        return_col=args.return_col,
        n_boost_rounds=args.boost_rounds,
        auto_promote=args.auto_promote,
    )

    loop = TrainingLoop(config)
    results = loop.run(df)

    print(f"\nCompleted {len(results)} round(s)")
    for r in results:
        if r.judge_report:
            print(f"\nRound {r.round_num}: {r.judge_report.judge_verdict}")
            print(f"  Accuracy: {r.judge_report.overall_accuracy:.1%}")
            print(f"  Artifact: {r.artifact_path}")


def cmd_tune(args: argparse.Namespace) -> None:
    """Run hyperparameter tuning."""
    from ml_training.data.storage import ParquetStore
    from ml_training.pipeline.hyperparameter_tuning import HyperparameterTuner

    store = ParquetStore(Path(args.data_dir))
    df = store.load_dataset("all_features")

    if df.empty:
        print("No dataset found. Run build-dataset first.")
        sys.exit(1)

    tuner = HyperparameterTuner(target_col=args.target)
    result = tuner.search(df)

    print(f"\nBest score: {result.best_score:.4f}")
    print(f"Best params: {json.dumps(result.best_params, indent=2)}")
    print(f"Tried {result.n_trials} configurations")


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
    """Promote the latest model to shadow mode."""
    from ml_training.models.registry import ModelRegistry

    registry = ModelRegistry()
    latest = registry.get_latest()

    if latest is None:
        print("No model artifacts found. Run train first.")
        sys.exit(1)

    dest = registry.promote_to_shadow(latest)
    print(f"Promoted {latest.name} -> {dest}")


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
    p_acquire.add_argument(
        "--data-dir", default="src/ml_training/data/raw", help="Output directory"
    )
    p_acquire.add_argument("--timeframes", default="D,4H,1H", help="Comma-separated timeframes")
    p_acquire.add_argument("--lookback-days", type=int, default=730, help="Daily lookback (days)")
    p_acquire.add_argument("--category", choices=["all", "tsx", "us", "crypto"], default="all")
    p_acquire.set_defaults(func=cmd_acquire)

    # build-dataset
    p_build = sub.add_parser("build-dataset", help="Build feature datasets")
    p_build.add_argument("--data-dir", default="src/ml_training/data/raw")
    p_build.set_defaults(func=cmd_build_dataset)

    # validate
    p_val = sub.add_parser("validate", help="Validate training dataset")
    p_val.add_argument("--data-dir", default="src/ml_training/data/raw")
    p_val.set_defaults(func=cmd_validate)

    # train
    p_train = sub.add_parser("train", help="Run training loop")
    p_train.add_argument("--rounds", type=int, default=3, help="Max training rounds")
    p_train.add_argument("--target", default="direction_10d", help="Target column")
    p_train.add_argument("--return-col", default="return_10d", help="Return column")
    p_train.add_argument("--boost-rounds", type=int, default=500, help="Boosting rounds")
    p_train.add_argument("--auto-promote", action="store_true", help="Auto-promote on PASS")
    p_train.add_argument("--data-dir", default="src/ml_training/data/raw")
    p_train.set_defaults(func=cmd_train)

    # tune
    p_tune = sub.add_parser("tune", help="Hyperparameter tuning")
    p_tune.add_argument("--target", default="direction_10d", help="Target column")
    p_tune.add_argument("--data-dir", default="src/ml_training/data/raw")
    p_tune.set_defaults(func=cmd_tune)

    # verify
    p_verify = sub.add_parser("verify", help="Verify acquired data")
    p_verify.add_argument("--data-dir", default="src/ml_training/data/raw")
    p_verify.set_defaults(func=cmd_verify)

    # promote
    p_promote = sub.add_parser("promote", help="Promote latest model to shadow mode")
    p_promote.set_defaults(func=cmd_promote)

    args = parser.parse_args()
    _setup_logging(args.verbose)
    _load_env()
    args.func(args)


if __name__ == "__main__":
    main()
