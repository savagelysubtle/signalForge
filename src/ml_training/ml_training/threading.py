"""Free-threading utilities for Python 3.14+ (PEP 703 / PEP 779).

Provides GIL status detection, optimal worker count calculation,
and a ``parallel_map`` helper that gracefully degrades to sequential
execution on GIL-enabled builds — avoiding thread overhead with no
benefit for CPU-bound work.

Usage::

    from ml_training.threading import parallel_map, optimal_workers

    results = parallel_map(process_ticker, tickers, desc="feature build")
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


def is_free_threaded() -> bool:
    """Return True if the GIL is disabled (free-threaded Python 3.14+)."""
    if hasattr(sys, "_is_gil_enabled"):
        return not sys._is_gil_enabled()
    return False


def log_threading_status() -> None:
    """Log the current GIL / free-threading status at startup."""
    version = sys.version.split()[0]
    if hasattr(sys, "_is_gil_enabled"):
        if sys._is_gil_enabled():
            logger.info(
                "Python %s — GIL enabled (run with PYTHON_GIL=0 to enable free-threading)",
                version,
            )
        else:
            logger.info("Python %s — free-threading ACTIVE (GIL disabled)", version)
    else:
        logger.info("Python %s — no free-threading support", version)


def optimal_workers(task_type: str = "cpu", max_cap: int = 16) -> int:
    """Calculate optimal thread pool size.

    Args:
        task_type: ``"cpu"`` for CPU-bound, ``"io"`` for I/O-bound work.
        max_cap: Upper bound on worker count.

    Returns:
        Number of worker threads. Returns 1 for CPU-bound tasks when
        the GIL is active (threads would add overhead only).
    """
    cpu_count = os.cpu_count() or 4

    if task_type == "io":
        return min(cpu_count * 2, max_cap)

    if is_free_threaded():
        return min(cpu_count, max_cap)

    return 1


def parallel_map[T, R](
    fn: Callable[[T], R],
    items: list[T],
    *,
    max_workers: int | None = None,
    task_type: str = "cpu",
    desc: str = "",
) -> list[R]:
    """Map *fn* over *items* using threads when free-threading is active.

    Falls back to sequential execution when the GIL prevents CPU
    parallelism, avoiding thread overhead for no benefit.

    For I/O-bound tasks (``task_type="io"``), threads are always used
    since the GIL is released during I/O regardless.

    Args:
        fn: Function to apply to each item.
        items: Items to process.
        max_workers: Override worker count (``None`` = auto-detect).
        task_type: ``"cpu"`` or ``"io"`` — determines fallback behaviour.
        desc: Description for logging.

    Returns:
        List of results in the same order as *items*.
    """
    if not items:
        return []

    workers = max_workers or optimal_workers(task_type, max_cap=16)

    if workers <= 1 or len(items) <= 1:
        return [fn(item) for item in items]

    if desc:
        logger.info("Parallel %s: %d items across %d threads", desc, len(items), workers)

    results_map: dict[int, R] = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_idx = {pool.submit(fn, item): i for i, item in enumerate(items)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results_map[idx] = future.result()
            except Exception:
                logger.exception("Parallel %s: item %d failed", desc, idx)
                raise

    return [results_map[i] for i in range(len(items))]


def balanced_lgb_njobs(parallel_models: int) -> int:
    """Calculate per-model ``n_jobs`` to avoid OpenMP oversubscription.

    When training multiple LightGBM models in parallel threads, each
    model's internal OpenMP parallelism should be reduced so the total
    thread count stays near the CPU count.

    Args:
        parallel_models: Number of models training concurrently.

    Returns:
        ``n_jobs`` value to pass to each LightGBM model.
    """
    cpu_count = os.cpu_count() or 4
    return max(1, cpu_count // parallel_models)
