"""Pre-GPT independent ML hints: prompt injection, debate escalation, training export."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from ml.gate import run_ml_gate
from ml.inference import ml_model_available
from ml.schemas import GateResult
from pipeline.schemas import MultiTimeframeTechnical, RegimeOutput
from services.fmp_service import FmpEnrichedStock

logger = logging.getLogger(__name__)

_GRAY_LOW = 0.38
_GRAY_HIGH = 0.62


def build_ml_feature_dicts(
    ta_snapshots: list[MultiTimeframeTechnical] | None,
    fmp_map: dict[str, FmpEnrichedStock] | None,
    regime: RegimeOutput | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any] | None]:
    """Build the same TA/FMP/regime dicts used by the post-GPT ML gate."""
    from ml.feature_mapper import map_fmp_to_features, map_multi_tf_to_features

    ta_dict: dict[str, dict[str, Any]] = {}
    if ta_snapshots:
        for snap in ta_snapshots:
            if hasattr(snap, "ticker"):
                ta_dict[snap.ticker] = map_multi_tf_to_features(snap.model_dump())

    fmp_dict: dict[str, dict[str, Any]] = {}
    if fmp_map:
        for sym, stock in fmp_map.items():
            raw = stock.model_dump() if hasattr(stock, "model_dump") else {}
            fmp_dict[sym] = map_fmp_to_features(raw)

    regime_dict: dict[str, Any] | None = None
    if regime:
        regime_dict = {
            "regime_type": regime.regime_type,
            "vix_estimate": regime.vix_estimate,
            "breadth_estimate": regime.breadth_estimate,
        }
    return ta_dict, fmp_dict, regime_dict


def _is_valid_hint(g: GateResult) -> bool:
    return g.reason not in ("no_independent_model", "prediction_failed")


def ml_uncertainty_escalates_debate(hints: dict[str, GateResult]) -> bool:
    """True when bull/bear debate should run or prompts should stress-test harder.

    Triggers on probability gray zone, ambiguous conformal set, or gate-style block.
    """
    for g in hints.values():
        if not _is_valid_hint(g):
            continue
        if _GRAY_LOW <= g.ml_probability <= _GRAY_HIGH:
            return True
        if len(g.conformal_set) >= 2:
            return True
        if g.blocked:
            return True
    return False


def format_ml_prior_for_prompt(hints: dict[str, GateResult]) -> str:
    """Human-readable ML prior block for GPT user prompts (Track D)."""
    lines = [
        "--- INDEPENDENT ML PRIOR (Track D) ---",
        "Statistical model trained on historical outcomes. Inputs: numerical TA, "
        "FMP ratios, and market regime only - no LLM text from Tracks A-C. "
        "Use as an independent prior: reconcile with tracks; do not ignore clear "
        "multi-track evidence solely because of ML, but flag tension when ML and "
        "tracks disagree.",
        "",
    ]
    any_valid = False
    for ticker in sorted(hints.keys()):
        g = hints[ticker]
        if not _is_valid_hint(g):
            lines.append(f"- **{ticker}**: ML prior unavailable ({g.reason.replace('_', ' ')})")
            continue
        any_valid = True
        cf = ", ".join(g.conformal_set) if g.conformal_set else "n/a"
        blk = " (model suggests insufficient edge - treat as red flag)" if g.blocked else ""
        lines.append(
            f"- **{ticker}**: P(profitable)≈{g.ml_probability:.1%}, "
            f"direction={g.predicted_direction}, conformal set=[{cf}]{blk}"
        )
    if not any_valid:
        lines.append(
            "No independent ML model loaded for this strategy type, or all predictions failed."
        )
    lines.append("--- END INDEPENDENT ML PRIOR ---")
    return "\n".join(lines)


def ml_escalation_user_block() -> str:
    """Extra instructions when ML is uncertain - appended to bull/bear/judge prompts."""
    return (
        "\n## ML UNCERTAINTY ESCALATION\n"
        "The independent ML prior (Track D) is in a gray probability band, has an "
        "ambiguous conformal set, or flags insufficient edge for at least one ticker. "
        "Spend extra effort: stress-test bull and bear arguments with concrete numbers "
        "from the tracks, and in your synthesis explicitly reconcile ML vs Tracks A-C "
        "before choosing BUY, SHORT, HOLD, NO_TRADE, or WATCH.\n"
    )


async def run_pre_gpt_gates(
    tickers: list[str],
    strategy_type: str,
    ta_dict: dict[str, dict[str, Any]],
    fmp_dict: dict[str, dict[str, Any]],
    regime_dict: dict[str, Any] | None,
) -> dict[str, GateResult]:
    """Run the independent ML gate once per ticker before GPT (same logic as Stage 4.8)."""
    out: dict[str, GateResult] = {}
    if not tickers:
        return out

    if not ml_model_available(strategy_type, mode="independent"):
        for t in tickers:
            out[t] = GateResult(
                ticker=t,
                ml_probability=0.0,
                predicted_direction="FLAT",
                size_multiplier=1.0,
                blocked=False,
                reason="no_independent_model",
            )
        return out

    tasks = [
        run_ml_gate(
            ticker=t,
            strategy_type=strategy_type,
            ta_features=ta_dict.get(t, {}),
            fmp_features=fmp_dict.get(t),
            regime_context=regime_dict,
        )
        for t in tickers
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for t, res in zip(tickers, results, strict=True):
        if isinstance(res, Exception):
            logger.warning("Pre-GPT ML gate failed for %s: %s", t, res)
            out[t] = GateResult(
                ticker=t,
                ml_probability=0.0,
                predicted_direction="FLAT",
                size_multiplier=1.0,
                blocked=False,
                reason="prediction_failed",
            )
        else:
            out[t] = res
    return out


def pre_gpt_hints_to_json(hints: dict[str, GateResult]) -> str:
    """JSON for stage_outputs / training export (join with outcomes offline)."""
    payload: dict[str, dict[str, Any]] = {}
    for t, g in hints.items():
        payload[t] = {
            "ml_probability": g.ml_probability,
            "predicted_direction": g.predicted_direction,
            "blocked": g.blocked,
            "conformal_set": g.conformal_set,
            "model_version": g.model_version,
            "reason": g.reason,
        }
    return json.dumps(payload)
