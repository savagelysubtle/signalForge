"""Command-line interface for ML training operations.

Basic workflow::

    uv run python -m ml_training.pipeline.cli acquire          # 1. get price data
    uv run python -m ml_training.pipeline.cli build-dataset    # 2. build features
    uv run python -m ml_training.pipeline.cli train --rounds 3 # 3. train models

Default target is ``triple_barrier_label`` (binary: did price hit the
take-profit level before the stop-loss?).  Use ``--three-class`` for
direction-based classification (UP/DOWN/FLAT).

Advanced (meta-label, needs 500+ graded GPT recommendations)::

    uv run python -m ml_training.pipeline.cli retrain-meta

The FMP API key is loaded automatically from your .env file
(FMP_API_KEY). You can override it with --api-key if needed.

Free-threading (Python 3.14+)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

CPU-bound stages (dataset building, hyperparameter tuning, per-strategy
training, SHAP analysis, indicator computation) are parallelised via
``ThreadPoolExecutor`` when the GIL is disabled.  The standard
``python 3.14`` build has the GIL compiled in; you need the
free-threaded variant (``3.14t``)::

    uv python install 3.14t
    uv sync --all-groups --python 3.14t --prerelease=allow
    uv run --python 3.14t python -X gil=0 -m ml_training.pipeline.cli train

Without the ``t`` suffix the pipeline works identically but falls back
to sequential execution for CPU-bound work.  I/O-bound paths (Binance
downloads) always use threads since the GIL is released during I/O.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

if TYPE_CHECKING:
    import pandas as pd

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
    neutralize = getattr(args, "neutralize", False)
    builder = DatasetBuilder(store, neutralize=neutralize)
    augment = getattr(args, "augment", False)
    df = builder.build_all(save=True, augment=augment)

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

    Binary mode defaults to ``triple_barrier_label`` (did price hit TP
    before SL?).  Three-class mode auto-resolves per-strategy horizons
    from strategies.json when using the default target.
    """
    if binary_mode:
        return cli_target, cli_return

    if cli_target == "triple_barrier_label":
        cli_target = "direction_10d"

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

    meta_label = getattr(args, "meta_label", False)

    if strategy_type:
        prefix = "meta_" if meta_label else ""
        dataset_name = f"{prefix}{strategy_type}_features"
        df = store.load_dataset(dataset_name)
        label = strategy_type
    else:
        prefix = "meta_" if meta_label else ""
        dataset_name = f"{prefix}all_features"
        df = store.load_dataset(dataset_name)
        label = "combined"

    if df.empty:
        print(f"  [{label}] No dataset '{dataset_name}' found, skipping.")
        return []

    print(f"  [{label}] Loaded {dataset_name}: {len(df)} samples x {len(df.columns)} features")

    from ml_training.pipeline.training_loop import MIN_STRATEGY_SAMPLES

    if strategy_type and len(df) < MIN_STRATEGY_SAMPLES:
        print(
            f"  [{label}] Only {len(df)} samples (minimum {MIN_STRATEGY_SAMPLES}). "
            "Skipping per-strategy training -- combined model will be used as fallback."
        )
        return []

    classifier_params = None
    if not args.no_tuned:
        classifier_params = load_tuned_params(Path(args.data_dir), strategy_type=strategy_type)
        if classifier_params:
            params_label = f"tuned ({strategy_type})" if strategy_type else "tuned (combined)"
            print(f"  [{label}] Using {params_label} params")

    three_class = getattr(args, "three_class", False)
    binary_mode = not three_class
    target_col, return_col = _resolve_strategy_target(
        strategy_type, args.target, args.return_col, binary_mode
    )

    if target_col != args.target:
        print(f"  [{label}] Auto-selected target: {target_col}")

    model_type = getattr(args, "model", "lgbm")
    model_mode = getattr(args, "model_mode", "both")
    modes = ["independent", "shadow"] if model_mode == "both" else [model_mode]

    all_results: list[TrainingRoundResult] = []
    for mode in modes:
        if len(modes) > 1:
            print(f"\n  [{label}] ── Training {mode.upper()} model ──")

        config = TrainingLoopConfig(
            max_rounds=args.rounds,
            target_col=target_col,
            return_col=return_col,
            n_boost_rounds=args.boost_rounds,
            auto_promote=args.auto_promote,
            classifier_params=classifier_params.copy() if classifier_params else None,
            strategy_type=strategy_type,
            binary_mode=binary_mode,
            model_type=model_type,
            meta_label=meta_label if meta_label else False,
            model_mode=mode,
            inference_only=getattr(args, "inference_only", False),
        )

        loop = TrainingLoop(config)
        results = loop.run(df)
        all_results.extend(results)

        print(f"\n  [{label}/{mode}] Completed {len(results)} round(s)")
        for r in results:
            if r.judge_report:
                print(f"    Round {r.round_num}: {r.judge_report.judge_verdict}")
                print(f"      Accuracy: {r.judge_report.overall_accuracy:.1%}")
                print(f"      Artifact: {r.artifact_path}")

    return all_results


def _apply_fresh_reset(data_dir: Path) -> None:
    """Reset training state for a fully fresh training run.

    Clears dead_features.json and archives old model artifacts so the
    new training starts with zero accumulated state.
    """
    import shutil

    dead_path = data_dir / "dead_features.json"
    if dead_path.exists():
        dead_path.unlink()
        print("  [fresh] Cleared dead_features.json")

    tuned_path = data_dir / "tuned_params.json"
    if tuned_path.exists():
        tuned_path.unlink()
        print("  [fresh] Cleared tuned_params.json")

    artifacts_dir = Path(__file__).resolve().parents[1] / "models" / "artifacts"
    if artifacts_dir.exists():
        archive_dir = artifacts_dir / "archive"
        archive_dir.mkdir(exist_ok=True)
        moved = 0
        for f in artifacts_dir.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix not in (".joblib", ".json"):
                continue
            if "archive" in f.parts:
                continue
            if f.name in ("baseline_report.py", "ARTIFACT_TRACKER.md", "__init__.py"):
                continue
            rel = f.relative_to(artifacts_dir)
            dest = archive_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dest))
            moved += 1
        for d in artifacts_dir.iterdir():
            if d.is_dir() and d.name != "archive" and not any(d.iterdir()):
                d.rmdir()
        if moved:
            print(f"  [fresh] Archived {moved} old artifact files to artifacts/archive/")

    print("  [fresh] Training will start from scratch with default hyperparameters\n")


def cmd_train(args: argparse.Namespace) -> None:
    """Run the training loop, optionally per-strategy.

    When ``--per-strategy`` is used and free-threading is active, up to
    4 strategies train concurrently.
    """
    from ml_training.data.storage import ParquetStore
    from ml_training.threading import optimal_workers

    if getattr(args, "fresh", False):
        args.no_tuned = True
        _apply_fresh_reset(Path(args.data_dir))

    store = ParquetStore(Path(args.data_dir))

    if args.per_strategy:
        strategies = (
            [args.strategy] if args.strategy else store.list_strategy_datasets(per_id_only=True)
        )
        if not strategies:
            print("No per-strategy datasets found. Run build-dataset first.")
            sys.exit(1)
        print(f"Training per-strategy models for: {strategies}")

        workers = min(optimal_workers("cpu", max_cap=4), len(strategies))
        if workers > 1:
            print(f"  (parallel: {workers} strategies concurrently)")
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_train_single, store, st, args): st for st in strategies}
                for future in as_completed(futures):
                    st = futures[future]
                    try:
                        future.result()
                    except Exception:
                        logger.exception("Strategy %s failed", st)
        else:
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

    three_class = getattr(args, "three_class", False)
    binary_mode = not three_class
    target_col, _return_col = _resolve_strategy_target(
        strategy_type, args.target, "return_10d", binary_mode=binary_mode
    )

    if target_col != args.target:
        print(f"  [{label}] Auto-selected target: {target_col}")
    if binary_mode:
        print(f"  [{label}] Binary mode (triple barrier: hit TP before SL?)")

    tuner = HyperparameterTuner(
        target_col=target_col,
        binary_mode=binary_mode,
        inference_only=getattr(args, "inference_only", False),
    )
    n_trials = getattr(args, "n_trials", 0)
    result = tuner.search_optuna(df, n_trials=n_trials) if n_trials > 0 else tuner.search(df)

    saved_path = HyperparameterTuner.save_best_params(
        result, Path(args.data_dir), strategy_type=strategy_type
    )

    print(f"\n  [{label}] Best score: {result.best_score:.4f}")
    print(f"  [{label}] Best params: {json.dumps(result.best_params, indent=2)}")
    print(f"  [{label}] Saved to {saved_path}")


def cmd_tune(args: argparse.Namespace) -> None:
    """Run hyperparameter tuning, optionally per-strategy.

    When ``--per-strategy`` is used and free-threading is active, up to
    4 strategies are tuned concurrently.
    """
    from ml_training.data.storage import ParquetStore
    from ml_training.threading import optimal_workers

    store = ParquetStore(Path(args.data_dir))

    if args.per_strategy:
        strategies = (
            [args.strategy] if args.strategy else store.list_strategy_datasets(per_id_only=True)
        )
        if not strategies:
            print("No per-strategy datasets found. Run build-dataset first.")
            sys.exit(1)
        print(f"Tuning per-strategy for: {strategies}")

        workers = min(optimal_workers("cpu", max_cap=4), len(strategies))
        if workers > 1:
            print(f"  (parallel: {workers} strategies concurrently)")
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_tune_single, store, st, args): st for st in strategies}
                for future in as_completed(futures):
                    st = futures[future]
                    try:
                        future.result()
                    except Exception:
                        logger.exception("Tuning strategy %s failed", st)
        else:
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


def cmd_inspect(args: argparse.Namespace) -> None:
    """Print a summary table of active models in the backend artifacts directory."""
    import json

    from ml_training.models.registry import BACKEND_ARTIFACTS_DIR

    raw_dir = getattr(args, "backend_dir", None)
    backend_dir = Path(raw_dir) if raw_dir else BACKEND_ARTIFACTS_DIR
    if not backend_dir.is_dir():
        print(f"Backend artifacts directory not found: {backend_dir}")
        sys.exit(1)

    meta_files = sorted(backend_dir.glob("*_meta.json"))
    if not meta_files:
        joblib_files = list(backend_dir.glob("*.joblib"))
        if joblib_files:
            print(f"Found {len(joblib_files)} .joblib file(s) but no _meta.json companions.")
            print("Re-promote models to generate metadata files.")
        else:
            print("No active models found.")
        return

    header = f"{'Model':<40} {'Version':<8} {'Strategy':<25} {'Accuracy':>9} {'Verdict':<8} {'Features':>8} {'Date':<12}"
    print(header)
    print("-" * len(header))

    for meta_path in meta_files:
        with meta_path.open() as f:
            meta = json.load(f)

        name = meta_path.stem.replace("_meta", "")
        version = meta.get("model_version", "?")
        strategy = meta.get("strategy_type") or "combined"
        metrics = meta.get("metrics", {})
        accuracy = metrics.get("test_accuracy") or metrics.get("overall_accuracy", 0)
        verdict = meta.get("judge_verdict", "?")
        n_features = len(meta.get("feature_names", []))
        date = meta.get("training_date", "?")

        print(
            f"{name:<40} {version:<8} {strategy:<25} {accuracy:>8.1%} {verdict:<8} {n_features:>8} {date:<12}"
        )

        shap_imp = meta.get("shap_importance")
        if shap_imp:
            top_features = sorted(shap_imp.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
            top_str = ", ".join(f"{k}={v:.4f}" for k, v in top_features)
            print(f"  {'Top SHAP:':<12} {top_str}")


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


def cmd_acquire_missing(args: argparse.Namespace) -> None:
    """Download price data for tickers in recommendations but missing from ParquetStore."""
    import pandas as pd

    from ml_training.data.storage import ParquetStore
    from ml_training.data.supabase_provider import KNOWN_CRYPTO, normalize_ticker

    data_dir = Path(args.data_dir)
    recs_path = data_dir / "recommendation_history.parquet"
    if not recs_path.exists():
        print("No recommendation_history.parquet found. Run acquire-recommendations first.")
        sys.exit(1)

    recs_df = pd.read_parquet(recs_path)
    if "ticker" not in recs_df.columns:
        print("No ticker column in recommendations.")
        sys.exit(1)

    all_tickers = sorted(recs_df["ticker"].dropna().unique())
    all_tickers = [normalize_ticker(t) for t in all_tickers]
    all_tickers = sorted(set(all_tickers))

    store = ParquetStore(data_dir)
    existing = set(store.list_tickers("prices", "D"))

    missing = [t for t in all_tickers if t not in existing]
    if not missing:
        print(f"All {len(all_tickers)} tickers already have price data.")
        return

    print(f"Total tickers: {len(all_tickers)}, existing: {len(existing)}, missing: {len(missing)}")

    crypto_missing = [t for t in missing if t.replace("USD", "") in KNOWN_CRYPTO]
    tsx_missing = [t for t in missing if t.endswith(".TO")]
    tsxv_missing = [t for t in missing if t.endswith(".V")]
    us_missing = [t for t in missing if t not in crypto_missing + tsx_missing + tsxv_missing]

    futures_pattern = [t for t in us_missing if any(c.isdigit() for c in t[-4:])]
    us_missing = [t for t in us_missing if t not in futures_pattern]

    if futures_pattern:
        print(
            f"\nSkipping {len(futures_pattern)} commodity futures (unsupported): {futures_pattern}"
        )

    from ml_training.data.yfinance_provider import download_daily_ohlcv

    lookback = getattr(args, "lookback_years", 15)

    if tsx_missing:
        print(f"\nAcquiring {len(tsx_missing)} TSX tickers via yfinance...")
        download_daily_ohlcv(tsx_missing, "tsx", store, set(), lookback_years=lookback)

    if tsxv_missing:
        print(f"\nAcquiring {len(tsxv_missing)} TSXV tickers via yfinance...")
        download_daily_ohlcv(tsxv_missing, "tsx", store, set(), lookback_years=lookback)

    if us_missing:
        print(f"\nAcquiring {len(us_missing)} US tickers via yfinance...")
        download_daily_ohlcv(us_missing, "us", store, set(), lookback_years=lookback)

    if crypto_missing:
        print(f"\nAcquiring {len(crypto_missing)} crypto tickers via Binance...")
        from ml_training.data.binance_provider import download_crypto_ohlcv

        binance_pairs = [t.replace("USD", "USDT") for t in crypto_missing]
        download_crypto_ohlcv(
            timeframes=["D"],
            store=store,
            completed=set(),
            pairs=binance_pairs,
            months_back=lookback * 12,
        )

    new_existing = set(store.list_tickers("prices", "D"))
    newly_acquired = new_existing - existing
    still_missing = [t for t in missing if t not in new_existing and t not in futures_pattern]
    print(f"\nAcquired {len(newly_acquired)} new tickers")
    if still_missing:
        print(f"Still missing {len(still_missing)}: {still_missing[:20]}")


def cmd_acquire_recommendations(args: argparse.Namespace) -> None:
    """Pull historical recommendations from Supabase into local parquet."""
    from ml_training.data.supabase_provider import pull_recommendations

    df = pull_recommendations()
    if df.empty:
        print("No recommendations found in Supabase.")
        sys.exit(1)

    out_dir = Path(args.data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "recommendation_history.parquet"
    df.to_parquet(out_path, index=False)

    print(f"\nPulled {len(df)} recommendations -> {out_path}")
    if "action" in df.columns:
        print(f"Actions: {df['action'].value_counts().to_dict()}")
    if "strategy_template" in df.columns:
        templates = df["strategy_template"].dropna().unique()
        print(f"Strategies: {len(templates)} unique templates")


def cmd_grade_recommendations(args: argparse.Namespace) -> None:
    """Grade recommendations against local price data."""
    from ml_training.data.storage import ParquetStore
    from ml_training.pipeline.outcome_grader import grade_recommendations

    data_dir = Path(args.data_dir)
    recs_path = data_dir / "recommendation_history.parquet"
    if not recs_path.exists():
        print("No recommendation_history.parquet found. Run acquire-recommendations first.")
        sys.exit(1)

    import pandas as pd

    recs_df = pd.read_parquet(recs_path)
    store = ParquetStore(data_dir)

    graded_df, result = grade_recommendations(recs_df, store, max_horizon=args.max_horizon)

    graded_df.to_parquet(recs_path, index=False)

    print("\nGrading complete:")
    print(f"  Total: {result.total}")
    print(f"  Graded: {result.graded}")
    print(f"  TP Hit: {result.tp_hit}")
    print(f"  SL Hit: {result.sl_hit}")
    print(f"  Time Exit: {result.time_exit}")
    print(f"  No Trade Correct: {result.no_trade_correct}")
    print(f"  No Trade Missed: {result.no_trade_missed}")
    print(f"  Skipped (no prices): {result.skipped_no_prices}")
    print(f"  Skipped (no entry date): {result.skipped_no_entry_date}")
    print(f"  Skipped (insufficient bars): {result.skipped_insufficient_bars}")


def cmd_build_meta_dataset(args: argparse.Namespace) -> None:
    """Build meta-label training dataset from graded recommendations."""
    from ml_training.data.storage import ParquetStore
    from ml_training.features.dataset_builder import DatasetBuilder

    data_dir = Path(args.data_dir)
    recs_path = data_dir / "recommendation_history.parquet"
    if not recs_path.exists():
        print("No recommendation_history.parquet found. Run acquire-recommendations first.")
        sys.exit(1)

    import pandas as pd

    recs_df = pd.read_parquet(recs_path)

    if "graded_label" not in recs_df.columns:
        print("Recommendations not graded yet. Run grade-recommendations first.")
        sys.exit(1)

    if args.actions:
        actions = [a.strip().upper() for a in args.actions.split(",")]
        recs_df = recs_df[recs_df["action"].str.upper().isin(actions)]

    if args.min_confidence > 0:
        recs_df = recs_df[recs_df["confidence"] >= args.min_confidence]

    store = ParquetStore(data_dir)
    builder = DatasetBuilder(store)
    df = builder.build_for_recommendations(recs_df, save=True, min_samples=args.min_samples)

    if df.empty:
        print("No meta-label dataset generated.")
        sys.exit(1)

    print(f"\nMeta-label dataset: {len(df)} samples, {len(df.columns)} features")
    if "strategy_type" in df.columns:
        print(f"Strategy distribution:\n{df['strategy_type'].value_counts().to_string()}")


def cmd_retrain_meta(args: argparse.Namespace) -> None:
    """Unified meta-label retraining: acquire -> grade -> build -> train -> verify -> promote."""
    print("=" * 60)
    print("STEP 1: Acquire recommendations from Supabase")
    print("=" * 60)
    cmd_acquire_recommendations(args)

    print("\n" + "=" * 60)
    print("STEP 2: Grade recommendations against price data")
    print("=" * 60)
    cmd_grade_recommendations(args)

    print("\n" + "=" * 60)
    print("STEP 3: Build meta-label dataset")
    print("=" * 60)
    cmd_build_meta_dataset(args)

    print("\n" + "=" * 60)
    print("STEP 4: Train meta-label models")
    print("=" * 60)
    train_args = argparse.Namespace(
        rounds=args.rounds,
        target="triple_barrier_label",
        return_col="return_10d",
        boost_rounds=500,
        auto_promote=False,
        no_tuned=False,
        per_strategy=True,
        strategy=None,
        three_class=False,
        model="lgbm",
        meta_label=True,
        data_dir=args.data_dir,
    )
    cmd_train(train_args)

    print("\n" + "=" * 60)
    print("STEP 5: Verify models")
    print("=" * 60)
    verify_args = argparse.Namespace(data_dir=args.data_dir)
    cmd_verify(verify_args)

    if args.auto_promote:
        print("\n" + "=" * 60)
        print("STEP 6: Promote passing models")
        print("=" * 60)
        promote_args = argparse.Namespace()
        cmd_promote(promote_args)


def cmd_compute_priors(args: argparse.Namespace) -> None:
    """Compute empirical base-rate priors grouped by strategy, regime, and signal direction.

    Produces two JSON artefacts next to the datasets directory:
    - ``prior_table.json`` — per-cell base rates with small-sample fallback
    - ``booster_magnitudes.json`` — conditional lift estimates for key features

    Args:
        args: CLI namespace with ``data_dir``.
    """
    import pandas as pd

    from ml_training.data.storage import ParquetStore

    store = ParquetStore(Path(args.data_dir))
    strategy_names = store.list_strategy_datasets()

    if not strategy_names:
        logger.warning("No per-strategy datasets found. Run build-dataset first.")
        print("No per-strategy datasets found. Run build-dataset first.")
        return

    frames: list[pd.DataFrame] = []
    for name in strategy_names:
        df = store.load_dataset(f"{name}_features")
        if not df.empty:
            frames.append(df)
            logger.debug("Loaded %s: %d rows", name, len(df))

    if not frames:
        print("All strategy datasets are empty. Nothing to compute.")
        return

    combined = pd.concat(frames, ignore_index=True)
    logger.info("Combined %d strategy datasets -> %d total rows", len(frames), len(combined))

    target_col = "triple_barrier_label"
    group_cols = ["strategy_type", "market_regime", "primary_signal"]

    for col in [target_col, *group_cols]:
        if col not in combined.columns:
            print(
                f"Required column '{col}' not found in datasets. Available: {list(combined.columns)[:20]}"
            )
            return

    global_rate = float(combined[target_col].mean())
    global_n = len(combined)

    strategy_marginals = (
        combined.groupby("strategy_type")[target_col]
        .agg(["mean", "count"])
        .rename(columns={"mean": "base_rate", "count": "sample_size"})
    )

    grouped = (
        combined.groupby(group_cols)[target_col]
        .agg(["mean", "count"])
        .rename(columns={"mean": "base_rate", "count": "sample_size"})
        .reset_index()
    )

    fallback_strategy = 0
    fallback_global = 0

    for idx, row in grouped.iterrows():
        n = row["sample_size"]
        if n < 10:
            grouped.at[idx, "base_rate"] = global_rate
            grouped.at[idx, "sample_size"] = global_n
            fallback_global += 1
        elif n < 30:
            st = row["strategy_type"]
            if st in strategy_marginals.index:
                grouped.at[idx, "base_rate"] = strategy_marginals.loc[st, "base_rate"]
                grouped.at[idx, "sample_size"] = int(strategy_marginals.loc[st, "sample_size"])
            else:
                grouped.at[idx, "base_rate"] = global_rate
                grouped.at[idx, "sample_size"] = global_n
                fallback_global += 1
            fallback_strategy += 1

    signal_map = {1: "long", -1: "short", 0: "neutral"}
    grouped["direction"] = grouped["primary_signal"].map(lambda v: signal_map.get(int(v), str(v)))
    grouped.rename(columns={"market_regime": "regime"}, inplace=True)

    prior_records = grouped[
        ["strategy_type", "regime", "direction", "base_rate", "sample_size"]
    ].to_dict(orient="records")
    for rec in prior_records:
        rec["base_rate"] = round(float(rec["base_rate"]), 6)
        rec["sample_size"] = int(rec["sample_size"])

    out_dir = Path(args.data_dir).resolve().parent
    prior_path = out_dir / "prior_table.json"
    prior_path.parent.mkdir(parents=True, exist_ok=True)

    with open(prior_path, "w") as f:
        json.dump(prior_records, f, indent=2)

    total_cells = len(grouped)
    print(f"\nPrior table: {total_cells} cells computed")
    print(f"  Fallback to strategy marginal: {fallback_strategy}")
    print(f"  Fallback to global rate:       {fallback_global}")
    print(f"  Global base rate:              {global_rate:.4f} (n={global_n})")
    print(f"  Saved -> {prior_path}")

    _compute_booster_magnitudes(combined, target_col, global_rate, out_dir)


def _compute_booster_magnitudes(
    df: pd.DataFrame,
    target_col: str,
    global_base_rate: float,
    out_dir: Path,
) -> None:
    """Compute conditional lift for key features and export as JSON.

    For each feature, splits on the median and measures
    ``P(win | above_median) - global_base_rate``, capped at +/- 0.08.

    Args:
        df: Combined training dataframe.
        target_col: Binary target column name.
        global_base_rate: Overall win rate across all data.
        out_dir: Directory to write ``booster_magnitudes.json`` into.
    """
    import numpy as np

    feature_specs: list[tuple[str, str]] = [
        ("volume_ratio", "volume_ratio > median"),
        ("adx", "adx > median"),
        ("rsi", "rsi > median"),
        ("momentum_score", "momentum_score > median"),
        ("trend_alignment", "trend_alignment > median"),
    ]

    magnitude_cap = 0.08
    records: list[dict[str, object]] = []

    for feat, condition_label in feature_specs:
        if feat not in df.columns:
            logger.debug("Feature '%s' not in dataset, skipping booster calc", feat)
            continue

        col = df[feat].dropna()
        if len(col) < 30:
            continue

        threshold = float(np.median(col))
        mask_strong = df[feat] > threshold
        mask_weak = df[feat] <= threshold

        strong_subset = df.loc[mask_strong, target_col]
        weak_subset = df.loc[mask_weak, target_col]

        if len(strong_subset) < 10 or len(weak_subset) < 10:
            continue

        strong_rate = float(strong_subset.mean())
        raw_lift = strong_rate - global_base_rate
        capped = max(-magnitude_cap, min(magnitude_cap, raw_lift))

        records.append(
            {
                "feature": feat,
                "strong_condition": condition_label,
                "estimated_lift": round(capped, 6),
                "capped_at": magnitude_cap if abs(raw_lift) > magnitude_cap else None,
            }
        )

    booster_path = out_dir / "booster_magnitudes.json"
    with open(booster_path, "w") as f:
        json.dump(records, f, indent=2)

    print(f"\nBooster magnitudes: {len(records)} features analysed")
    for rec in records:
        cap_tag = " (capped)" if rec["capped_at"] else ""
        print(f"  {rec['feature']}: lift={rec['estimated_lift']:+.4f}{cap_tag}")
    print(f"  Saved -> {booster_path}")


def cmd_resolve_shadow(args: argparse.Namespace) -> None:
    """Resolve shadow prediction outcomes from Supabase against local price data."""
    import pandas as pd

    from ml_training.data.storage import ParquetStore
    from ml_training.data.supabase_provider import pull_shadow_predictions, update_shadow_outcomes

    shadow_df = pull_shadow_predictions(unresolved_only=True)
    if shadow_df.empty:
        print("No unresolved shadow predictions found.")
        return

    print(f"Found {len(shadow_df)} unresolved shadow predictions")

    store = ParquetStore(Path(args.data_dir))
    updates: list[dict[str, Any]] = []
    from datetime import datetime

    for _, row in shadow_df.iterrows():
        ticker = row.get("ticker", "")
        pred_date = row.get("prediction_date")
        if not ticker or pred_date is None:
            continue

        prices = store.load_prices(ticker, "D")
        if prices.empty:
            continue

        prices = prices.copy()
        prices["date"] = pd.to_datetime(prices["date"])

        pred_ts = pd.Timestamp(pred_date)
        if pred_ts.tzinfo is not None:
            pred_ts = pred_ts.tz_localize(None)

        after = prices[prices["date"] > pred_ts.normalize()]
        if len(after) < args.horizon:
            continue

        entry_row = prices[prices["date"] <= pred_ts.normalize()]
        if entry_row.empty:
            continue

        entry_price = float(entry_row.iloc[-1]["close"])
        exit_price = float(after.iloc[args.horizon - 1]["close"])
        actual_return = (exit_price - entry_price) / entry_price

        if actual_return > 0.02:
            actual_dir = "UP"
        elif actual_return < -0.02:
            actual_dir = "DOWN"
        else:
            actual_dir = "FLAT"

        ml_dir = row.get("ml_direction", "")
        gpt_action = row.get("gpt_action", "")
        gpt_dir_map = {"BUY": "UP", "SHORT": "DOWN"}
        gpt_dir = gpt_dir_map.get(gpt_action, "FLAT")

        updates.append(
            {
                "id": row["id"],
                "actual_direction": actual_dir,
                "actual_return_10d": round(float(actual_return), 6),
                "ml_correct": ml_dir == actual_dir,
                "gpt_correct": gpt_dir == actual_dir,
                "updated_at": datetime.now().isoformat(),
            }
        )

    if updates:
        updated = update_shadow_outcomes(updates)
        print(f"Resolved {updated} shadow predictions")
    else:
        print("No shadow predictions could be resolved (insufficient price data)")


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
    p_acquire.add_argument(
        "--timeframes", default="D,W,4H,1H,15m", help="Comma-separated timeframes"
    )
    p_acquire.add_argument("--lookback-days", type=int, default=5475, help="Daily lookback (days)")
    p_acquire.add_argument("--category", choices=["all", "tsx", "us", "crypto"], default="all")
    p_acquire.set_defaults(func=cmd_acquire)

    # build-dataset
    p_build = sub.add_parser("build-dataset", help="Build feature datasets")
    p_build.add_argument("--data-dir", default="data/raw")
    p_build.add_argument(
        "--augment",
        action="store_true",
        default=False,
        help="Augment small strategies (<15K samples) with synthetic data",
    )
    p_build.add_argument(
        "--neutralize",
        action="store_true",
        default=False,
        help="Z-score normalize features cross-sectionally (for market-neutral factor models)",
    )
    p_build.set_defaults(func=cmd_build_dataset)

    # validate
    p_val = sub.add_parser("validate", help="Validate training dataset")
    p_val.add_argument("--data-dir", default="data/raw")
    p_val.set_defaults(func=cmd_validate)

    # train
    p_train = sub.add_parser("train", help="Run training loop")
    p_train.add_argument("--rounds", type=int, default=3, help="Max training rounds")
    p_train.add_argument(
        "--target",
        default="triple_barrier_label",
        help="Target column (default: triple_barrier_label = hit TP before SL?)",
    )
    p_train.add_argument("--return-col", default="return_10d", help="Return column")
    p_train.add_argument("--boost-rounds", type=int, default=500, help="Boosting rounds")
    p_train.add_argument("--auto-promote", action="store_true", help="Auto-promote on PASS")
    p_train.add_argument(
        "--no-tuned", action="store_true", help="Ignore tuned params, use defaults"
    )
    p_train.add_argument(
        "--fresh",
        action="store_true",
        default=False,
        help="Train from scratch: ignore tuned params, clear dead_features.json, "
        "and archive old model artifacts before training",
    )
    p_train.add_argument("--per-strategy", action="store_true", help="Train per-strategy models")
    p_train.add_argument(
        "--strategy", default=None, help="Train a single strategy (requires --per-strategy)"
    )
    p_train.add_argument(
        "--three-class",
        action="store_true",
        default=False,
        help="Use 3-class direction (UP/DOWN/FLAT) instead of binary triple-barrier (default)",
    )
    p_train.add_argument(
        "--model",
        choices=["lgbm", "tabpfn", "ensemble"],
        default="lgbm",
        help="Model type: lgbm (default), tabpfn (zero-tuning), ensemble (stacked)",
    )
    p_train.add_argument(
        "--model-mode",
        choices=["independent", "shadow", "both"],
        default="independent",
        help="independent = gate model (default), shadow = comparison model, both = train both",
    )
    p_train.add_argument(
        "--inference-only",
        action="store_true",
        default=False,
        help="Exclude training-only features (TSFresh, FFD, HMM) so models use only "
        "features available at live inference",
    )
    p_train.add_argument("--data-dir", default="data/raw")
    p_train.set_defaults(func=cmd_train)

    # tune
    p_tune = sub.add_parser("tune", help="Hyperparameter tuning")
    p_tune.add_argument(
        "--target",
        default="triple_barrier_label",
        help="Target column (default: triple_barrier_label)",
    )
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
    p_tune.add_argument(
        "--three-class",
        action="store_true",
        default=False,
        help="Use 3-class direction (UP/DOWN/FLAT) instead of binary triple-barrier",
    )
    p_tune.add_argument(
        "--inference-only",
        action="store_true",
        default=False,
        help="Exclude training-only features (TSFresh, FFD, HMM) so models use only "
        "features available at live inference",
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

    # acquire-missing
    p_acq_miss = sub.add_parser(
        "acquire-missing",
        help="Download price data for tickers in recommendations but missing locally",
    )
    p_acq_miss.add_argument("--data-dir", default="data/raw")
    p_acq_miss.add_argument(
        "--lookback-years", type=int, default=15, help="Years of history to fetch"
    )
    p_acq_miss.set_defaults(func=cmd_acquire_missing)

    # acquire-recommendations
    p_acq_recs = sub.add_parser(
        "acquire-recommendations", help="Pull recommendations from Supabase"
    )
    p_acq_recs.add_argument("--data-dir", default="data/raw")
    p_acq_recs.set_defaults(func=cmd_acquire_recommendations)

    # grade-recommendations
    p_grade = sub.add_parser(
        "grade-recommendations", help="Grade recommendations against price data"
    )
    p_grade.add_argument("--data-dir", default="data/raw")
    p_grade.add_argument("--max-horizon", type=int, default=20, help="Max bars to look forward")
    p_grade.set_defaults(func=cmd_grade_recommendations)

    # build-meta-dataset
    p_meta = sub.add_parser(
        "build-meta-dataset", help="Build meta-label dataset from graded recommendations"
    )
    p_meta.add_argument("--data-dir", default="data/raw")
    p_meta.add_argument(
        "--min-confidence",
        type=float,
        default=0.0,
        help="Filter recommendations below this confidence",
    )
    p_meta.add_argument(
        "--actions",
        default="BUY,SHORT",
        help="Comma-separated actions to include (default: BUY,SHORT)",
    )
    p_meta.add_argument(
        "--min-samples",
        type=int,
        default=200,
        help="Minimum samples per strategy for viable training",
    )
    p_meta.set_defaults(func=cmd_build_meta_dataset)

    # retrain-meta
    p_retrain = sub.add_parser(
        "retrain-meta",
        help="Full meta-label retraining: acquire -> grade -> build -> train -> verify -> promote",
    )
    p_retrain.add_argument("--data-dir", default="data/raw")
    p_retrain.add_argument("--max-horizon", type=int, default=20, help="Max bars for grading")
    p_retrain.add_argument(
        "--min-confidence",
        type=float,
        default=0.0,
        help="Filter recommendations below this confidence",
    )
    p_retrain.add_argument(
        "--actions",
        default="BUY,SHORT",
        help="Comma-separated actions to include",
    )
    p_retrain.add_argument(
        "--min-samples",
        type=int,
        default=200,
        help="Minimum samples per strategy",
    )
    p_retrain.add_argument("--rounds", type=int, default=3, help="Training rounds")
    p_retrain.add_argument(
        "--auto-promote", action="store_true", help="Auto-promote passing models"
    )
    p_retrain.set_defaults(func=cmd_retrain_meta)

    # compute-priors
    p_priors = sub.add_parser(
        "compute-priors",
        help="Compute regime-aware base rate priors from training data",
    )
    p_priors.add_argument("--data-dir", default="data/raw", help="Root data directory")
    p_priors.set_defaults(func=cmd_compute_priors)

    # inspect
    p_inspect = sub.add_parser("inspect", help="Show summary of active models in backend")
    p_inspect.add_argument(
        "--backend-dir",
        default=None,
        help="Backend artifacts directory (auto-detected if omitted)",
    )
    p_inspect.set_defaults(func=cmd_inspect)

    # resolve-shadow
    p_shadow = sub.add_parser("resolve-shadow", help="Resolve shadow prediction outcomes")
    p_shadow.add_argument("--data-dir", default="data/raw")
    p_shadow.add_argument("--horizon", type=int, default=10, help="Days to wait before resolving")
    p_shadow.set_defaults(func=cmd_resolve_shadow)

    args = parser.parse_args()
    _setup_logging(args.verbose)
    _load_env()

    import warnings

    warnings.filterwarnings("ignore", category=FutureWarning, module="pandas")
    logging.getLogger("tsfresh.feature_extraction.settings").setLevel(logging.ERROR)

    from ml_training.threading import log_threading_status

    log_threading_status()
    args.func(args)


if __name__ == "__main__":
    main()
