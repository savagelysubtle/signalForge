"""Regime-aware prior probability service for the confidence engine v2.

Loads empirical base rates from ``prior_table.json`` (produced by the ML
training pipeline's ``compute-priors`` command) and exposes a simple
lookup: ``get_prior(strategy_type, regime, direction) -> float``.

Fallback hierarchy when a specific cell is missing:
  1. strategy_type x regime x direction (exact match)
  2. strategy_type x direction (ignore regime)
  3. global base rate across all data
  4. hardcoded 0.50 if no prior table is loaded
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_PRIOR = 0.50

_prior_table: list[dict[str, Any]] = []
_strategy_marginals: dict[tuple[str, str], float] = {}
_global_rate: float = _DEFAULT_PRIOR
_loaded = False


def load_prior_table(path: str | Path | None = None) -> bool:
    """Load the prior table JSON from disk.

    Args:
        path: Path to ``prior_table.json``. If None, tries the default
            model artifacts location.

    Returns:
        True if the table loaded successfully, False otherwise.
    """
    global _prior_table, _strategy_marginals, _global_rate, _loaded

    if path is None:
        candidates = [
            Path("data/prior_table.json"),
            Path("src/ml_training/data/prior_table.json"),
            Path(__file__).resolve().parents[2] / "ml_training" / "data" / "prior_table.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                path = candidate
                break

    if path is None or not Path(path).exists():
        logger.warning("Prior table not found — using default prior %.2f", _DEFAULT_PRIOR)
        _loaded = False
        return False

    try:
        with open(path) as f:
            _prior_table = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load prior table from %s: %s", path, exc)
        _loaded = False
        return False

    _strategy_marginals = {}
    total_weighted = 0.0
    total_samples = 0
    for row in _prior_table:
        key = (row["strategy_type"], row["direction"])
        if key not in _strategy_marginals:
            _strategy_marginals[key] = row["base_rate"]
        total_weighted += row["base_rate"] * row["sample_size"]
        total_samples += row["sample_size"]

    _global_rate = total_weighted / total_samples if total_samples > 0 else _DEFAULT_PRIOR

    _loaded = True
    logger.info(
        "Loaded prior table: %d cells, global rate=%.3f from %s",
        len(_prior_table),
        _global_rate,
        path,
    )
    return True


def get_prior(strategy_type: str, regime: str, direction: str) -> float:
    """Look up the empirical base rate for a strategy/regime/direction cell.

    Args:
        strategy_type: E.g. "swing", "intraday", "mean_reversion".
        regime: Market regime string, e.g. "normal", "high_volatility".
        direction: Trade direction -- "long" or "short".

    Returns:
        Empirical win probability prior (0.0-1.0).
    """
    if not _loaded:
        return _DEFAULT_PRIOR

    for row in _prior_table:
        if (
            row["strategy_type"] == strategy_type
            and row["regime"] == regime
            and row["direction"] == direction
        ):
            return row["base_rate"]

    marginal = _strategy_marginals.get((strategy_type, direction))
    if marginal is not None:
        return marginal

    return _global_rate


def is_loaded() -> bool:
    """Return True if a prior table has been successfully loaded."""
    return _loaded


def get_global_rate() -> float:
    """Return the global base rate across all strategies and regimes."""
    return _global_rate
