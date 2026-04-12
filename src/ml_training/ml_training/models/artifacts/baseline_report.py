"""Generate a baseline report from the latest training artifacts.

Usage::

    cd src/ml_training
    uv run --python 3.14t python -m ml_training.models.artifacts.baseline_report
    uv run --python 3.14t python -m ml_training.models.artifacts.baseline_report --date 20260411
    uv run --python 3.14t python -m ml_training.models.artifacts.baseline_report --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def _find_latest_meta_files(
    artifacts_dir: Path,
    date_filter: str | None = None,
) -> dict[str, dict]:
    """Find the latest _meta.json per strategy+mode combo.

    Args:
        artifacts_dir: Path to the artifacts directory.
        date_filter: If provided, only include artifacts from this date (YYYYMMDD).

    Returns:
        Mapping of ``{strategy}_{mode}`` -> parsed meta dict.
    """
    meta_files = sorted(artifacts_dir.glob("*_meta.json"), key=lambda p: p.stat().st_mtime)

    latest: dict[str, tuple[int, dict, str]] = {}

    for mf in meta_files:
        try:
            meta = json.loads(mf.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        training_date = meta.get("training_date", "")
        if date_filter and training_date != date_filter:
            continue

        strategy = meta.get("strategy_type") or "combined"
        mode = meta.get("training_config", {}).get("model_mode", "shadow")

        version_str = meta.get("model_version", "v0")
        version_num = int(version_str.lstrip("v")) if version_str.lstrip("v").isdigit() else 0

        key = f"{strategy}__{mode}"
        prev_version = latest.get(key, (-1, {}, ""))[0]
        if version_num > prev_version:
            latest[key] = (version_num, meta, mf.name)

    return {k: v[1] for k, v in sorted(latest.items())}


def _shap_summary(shap: dict[str, float]) -> tuple[int, int, str]:
    """Return (total_features, active_features, top3_string)."""
    total = len(shap)
    active = sum(1 for v in shap.values() if abs(v) > 0)
    top = sorted(shap.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
    top_str = ", ".join(f"{k}={v:.4f}" for k, v in top if abs(v) > 0)
    return total, active, top_str


def print_report(artifacts_dir: Path, date_filter: str | None = None) -> list[dict]:
    """Print a formatted baseline report and return structured data."""
    metas = _find_latest_meta_files(artifacts_dir, date_filter)

    if not metas:
        print("No artifacts found.")
        return []

    dates = {m.get("training_date", "?") for m in metas.values()}
    print(f"\n{'=' * 100}")
    print(f"  ML TRAINING BASELINE REPORT  |  Dates: {', '.join(sorted(dates))}")
    print(f"{'=' * 100}\n")

    rows: list[dict] = []
    verdicts: dict[str, int] = defaultdict(int)

    header = (
        f"{'Strategy':<35} {'Mode':<12} {'Acc':>6} {'Brier':>7} "
        f"{'OvfitGap':>9} {'Verdict':<10} {'Feats':>5} {'Active':>6} {'Samples':>8}"
    )
    print(header)
    print("-" * len(header))

    for key, meta in metas.items():
        strategy = meta.get("strategy_type") or "combined"
        config = meta.get("training_config", {})
        mode = config.get("model_mode", "shadow")
        metrics = meta.get("metrics", {})
        verdict = meta.get("judge_verdict", "?")
        shap = meta.get("shap_importance", {})
        features = meta.get("feature_names", [])
        dataset_size = config.get("dataset_size", 0)

        acc = metrics.get("overall_accuracy", 0)
        brier = metrics.get("brier_score", 0)
        overfit = metrics.get("overfit_gap", 0)

        total_f, active_f, top_str = _shap_summary(shap) if shap else (len(features), 0, "")

        verdicts[verdict] += 1

        row = {
            "strategy": strategy,
            "mode": mode,
            "accuracy": round(acc, 4),
            "brier_score": round(brier, 4),
            "overfit_gap": round(overfit, 4),
            "verdict": verdict,
            "total_features": total_f,
            "active_features": active_f,
            "dataset_size": dataset_size,
            "top_shap": top_str,
            "version": meta.get("model_version", "?"),
            "date": meta.get("training_date", "?"),
        }
        rows.append(row)

        print(
            f"{strategy:<35} {mode:<12} {acc:>5.1%} {brier:>7.4f} "
            f"{overfit:>+8.1%} {verdict:<10} {total_f:>5} {active_f:>6} {dataset_size:>8}"
        )
        if top_str:
            print(f"  {'Top SHAP:':<12} {top_str}")

    holdout_rows = [r for r in rows if any("holdout" in k for k in (meta.get("holdout_metrics") or {}))]

    print(f"\n{'─' * 60}")
    print("SUMMARY")
    print(f"{'─' * 60}")
    print(f"  Total models:    {len(rows)}")
    for v, count in sorted(verdicts.items()):
        print(f"  {v}:  {count}")

    accs = [r["accuracy"] for r in rows if r["accuracy"] > 0]
    if accs:
        print(f"  Accuracy range:  {min(accs):.1%} – {max(accs):.1%}  (mean {sum(accs)/len(accs):.1%})")

    active_ratios = [
        r["active_features"] / r["total_features"]
        for r in rows
        if r["total_features"] > 0
    ]
    if active_ratios:
        print(
            f"  Feature usage:   {sum(active_ratios)/len(active_ratios):.0%} of features "
            f"have non-zero SHAP (mean)"
        )

    if holdout_rows:
        print(f"\n  Holdout available for {len(holdout_rows)} model(s)")

    print()
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="ML artifact baseline report")
    parser.add_argument(
        "--dir",
        default=None,
        help="Artifacts directory (auto-detected if omitted)",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Filter by training date (YYYYMMDD)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of table",
    )
    parser.add_argument(
        "--backend",
        action="store_true",
        help="Read from backend artifacts instead of training artifacts",
    )
    args = parser.parse_args()

    if args.dir:
        artifacts_dir = Path(args.dir)
    elif args.backend:
        artifacts_dir = Path(__file__).resolve().parents[3] / "backend" / "ml" / "artifacts"
    else:
        artifacts_dir = Path(__file__).resolve().parent

    if not artifacts_dir.is_dir():
        print(f"Directory not found: {artifacts_dir}", file=sys.stderr)
        sys.exit(1)

    rows = print_report(artifacts_dir, date_filter=args.date)

    if args.json:
        print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
