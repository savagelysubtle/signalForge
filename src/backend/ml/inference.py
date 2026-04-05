"""Load trained model artifacts and run predictions.

Supports per-strategy models with automatic fallback to a combined model
when no strategy-specific artifact is available.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np

from ml.schemas import MLPrediction

# ---------------------------------------------------------------------------
# Pickle compatibility: the .joblib artifacts were serialized by the
# ml_training package which doesn't exist in the backend environment.
# Add the ml_training source tree to sys.path so pickle can import
# the original classes (ModelArtifact, ProbabilityCalibrator, etc.)
# directly when deserializing .joblib files.
# ---------------------------------------------------------------------------
_ML_TRAINING_ROOT = Path(__file__).resolve().parents[2] / "ml_training"
if _ML_TRAINING_ROOT.is_dir() and str(_ML_TRAINING_ROOT) not in sys.path:
    sys.path.insert(0, str(_ML_TRAINING_ROOT))

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path("ml/artifacts")
ACTIVE_MODEL_NAME = "model_active.joblib"

DIRECTION_CLASSES = ["DOWN", "FLAT", "UP"]

LLM_FEATURES: frozenset[str] = frozenset(
    {
        "llm_action_encoded",
        "llm_confidence",
        "llm_rr_ratio",
        "llm_sl_distance_pct",
        "llm_tp_distance_pct",
        "llm_key_factor_count",
        "llm_warning_count",
    }
)

_strategy_models: dict[str, dict[str, Any]] = {}
_independent_models: dict[str, dict[str, Any]] = {}
_fallback_model: dict[str, Any] | None = None
_loaded = False


def _to_float(val: Any) -> float:
    """Coerce a feature value to float, returning 0.0 for non-numeric types."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _unpack_artifact(artifact: Any) -> dict[str, Any]:
    """Convert a ModelArtifact into a plain dict for runtime use."""
    return {
        "classifier": artifact.classifier,
        "regressor": artifact.regressor,
        "label_encoder": artifact.label_encoder,
        "calibrator": artifact.calibrator,
        "conformal": artifact.conformal,
        "feature_names": artifact.metadata.feature_names if artifact.metadata else [],
        "metadata": artifact.metadata,
    }


def _load_all_models() -> None:
    """Discover and load all active models from the artifacts directory.

    Looks for:
      - ``model_{strategy}_active.joblib`` → per-strategy shadow models
      - ``model_{strategy}_independent_active.joblib`` → per-strategy gate models
      - ``model_active.joblib`` → combined fallback model
    """
    global _strategy_models, _independent_models, _fallback_model, _loaded
    _strategy_models = {}
    _independent_models = {}
    _fallback_model = None

    if not ARTIFACTS_DIR.exists():
        logger.debug("Artifacts directory does not exist: %s", ARTIFACTS_DIR)
        _loaded = True
        return

    fallback_path = ARTIFACTS_DIR / ACTIVE_MODEL_NAME
    if fallback_path.exists():
        try:
            _fallback_model = _unpack_artifact(joblib.load(fallback_path))
            version = (
                _fallback_model["metadata"].model_version if _fallback_model["metadata"] else "?"
            )
            logger.info("Loaded combined fallback model: %s", version)
        except Exception:
            logger.exception("Failed to load fallback model")

    for p in sorted(ARTIFACTS_DIR.glob("model_*_active.joblib")):
        if p.name == ACTIVE_MODEL_NAME:
            continue
        parts = p.stem.split("_")
        # model_{strategy_type}_independent_active → independent model
        # model_{strategy_type}_active → shadow/default model
        strategy_key = "_".join(parts[1:-1])
        is_independent = strategy_key.endswith("_independent")
        if is_independent:
            strategy_type = strategy_key.removesuffix("_independent")
            target_dict = _independent_models
            label = "independent"
        else:
            strategy_type = strategy_key
            target_dict = _strategy_models
            label = "shadow"
        try:
            artifact = joblib.load(p)
            if is_independent:
                feat_names = set(artifact.metadata.feature_names) if artifact.metadata else set()
                llm_leak = feat_names & LLM_FEATURES
                if llm_leak:
                    logger.warning(
                        "Independent model %s contains LLM features %s — refusing to load as gate",
                        p.name,
                        llm_leak,
                    )
                    continue
            target_dict[strategy_type] = _unpack_artifact(artifact)
            version = artifact.metadata.model_version if artifact.metadata else "?"
            logger.info("Loaded %s model [%s]: %s", label, strategy_type, version)
        except Exception:
            logger.exception("Failed to load model: %s", p.name)

    _loaded = True
    logger.info(
        "Model loading complete: %d shadow + %d independent + %s fallback",
        len(_strategy_models),
        len(_independent_models),
        "1" if _fallback_model else "no",
    )


def _get_model(
    strategy_type: str | None = None,
    mode: str = "shadow",
) -> dict[str, Any] | None:
    """Get the best available model for a given strategy type and mode.

    For ``mode="independent"``: strategy independent → shadow model (if LLM-free) → None.
    For ``mode="shadow"``: strategy shadow → combined fallback → None.
    """
    if not _loaded:
        _load_all_models()

    if mode == "independent":
        if strategy_type and strategy_type in _independent_models:
            return _independent_models[strategy_type]
        # Fall back to shadow model if it contains no LLM features
        shadow = _strategy_models.get(strategy_type) if strategy_type else None
        if shadow is not None:
            feat_set = frozenset(shadow.get("feature_names", []))
            if not (feat_set & LLM_FEATURES):
                logger.info(
                    "No independent model for %s — using LLM-free shadow model as gate",
                    strategy_type,
                )
                return shadow
            logger.debug(
                "Shadow model for %s contains LLM features, cannot use as gate",
                strategy_type,
            )
        return None

    if strategy_type and strategy_type in _strategy_models:
        return _strategy_models[strategy_type]
    return _fallback_model


def ml_model_available(strategy_type: str | None = None, mode: str = "shadow") -> bool:
    """Check if a trained ML model is available for inference."""
    return _get_model(strategy_type, mode=mode) is not None


def reload_model() -> bool:
    """Force reload all model artifacts (hot-reload for new versions).

    Returns:
        True if at least one model loaded successfully.
    """
    global _loaded
    _loaded = False
    _load_all_models()
    return bool(_strategy_models) or _fallback_model is not None


def get_model_info() -> dict[str, Any]:
    """Get information about all currently loaded models.

    Returns:
        Dict with model status, strategy model list, and fallback info.
    """
    if not _loaded:
        _load_all_models()

    strategy_info: dict[str, dict[str, Any]] = {}
    for st, model in _strategy_models.items():
        meta = model.get("metadata")
        strategy_info[st] = {
            "model_version": meta.model_version if meta else "unknown",
            "judge_verdict": meta.judge_verdict if meta else "unknown",
            "accuracy": meta.metrics.get("overall_accuracy", 0) if meta else 0,
        }

    independent_info: dict[str, dict[str, Any]] = {}
    for st, model in _independent_models.items():
        meta = model.get("metadata")
        independent_info[st] = {
            "model_version": meta.model_version if meta else "unknown",
            "judge_verdict": meta.judge_verdict if meta else "unknown",
            "accuracy": meta.metrics.get("overall_accuracy", 0) if meta else 0,
        }

    fallback_meta = _fallback_model.get("metadata") if _fallback_model else None

    return {
        "status": "active"
        if (_strategy_models or _independent_models or _fallback_model)
        else "inactive",
        "strategy_models": strategy_info,
        "independent_models": independent_info,
        "fallback": {
            "model_version": fallback_meta.model_version if fallback_meta else "none",
            "judge_verdict": fallback_meta.judge_verdict if fallback_meta else "none",
        },
        "total_models": len(_strategy_models)
        + len(_independent_models)
        + (1 if _fallback_model else 0),
    }


def build_feature_vector(
    ta_features: dict[str, float | None],
    fundamental_features: dict[str, float | None] | None = None,
    context_features: dict[str, Any] | None = None,
    llm_features: dict[str, float | None] | None = None,
) -> dict[str, Any]:
    """Build a feature vector for inference from live pipeline data.

    Args:
        ta_features: Technical analysis features from TechnicalSnapshot.
        fundamental_features: Fundamental data features (optional).
        context_features: Strategy type, regime, sector (optional).
        llm_features: LLM-derived features for meta-labeling (optional).

    Returns:
        Complete feature dict ready for model input.
    """
    features: dict[str, Any] = {}
    features.update(ta_features)
    if fundamental_features:
        features.update(fundamental_features)
    if context_features:
        features.update(context_features)
    if llm_features:
        features.update(llm_features)
    return features


def run_prediction(
    ticker: str,
    strategy_type: str,
    features: dict[str, Any],
    mode: str = "shadow",
) -> MLPrediction | None:
    """Run ML prediction for a single ticker using the best available model.

    Automatically selects the strategy-specific model if available,
    falling back to the combined model otherwise.  Handles both binary
    (profitable / not-profitable) and 3-class (UP / FLAT / DOWN) models.

    Args:
        ticker: Ticker symbol.
        strategy_type: Strategy template type.
        features: Complete feature dict.
        mode: ``"independent"`` for gate model, ``"shadow"`` for full model.

    Returns:
        MLPrediction or None if model unavailable.
    """
    model = _get_model(strategy_type, mode=mode)
    if model is None:
        return None

    classifier = model["classifier"]
    regressor = model["regressor"]
    feature_names = model["feature_names"]
    calibrator = model.get("calibrator")
    conformal = model.get("conformal")
    label_encoder = model.get("label_encoder")
    metadata = model.get("metadata")

    feature_vector = np.array(
        [_to_float(features.get(name)) for name in feature_names], dtype=np.float64
    ).reshape(1, -1)

    try:
        raw_probs = classifier.predict_proba(feature_vector)[0]

        if calibrator is not None:
            raw_probs = calibrator.calibrate(raw_probs.reshape(1, -1))[0]

        n_classes = len(raw_probs)
        is_binary = n_classes == 2

        direction: Literal["UP", "DOWN", "FLAT"]
        if is_binary:
            if label_encoder is not None and hasattr(label_encoder, "classes_"):
                pos_indices = np.where(label_encoder.classes_ == 1)[0]
                pos_idx = int(pos_indices[0]) if len(pos_indices) > 0 else 1
            else:
                pos_idx = 1
            prob_profitable = float(raw_probs[pos_idx])
            direction = "UP" if prob_profitable > 0.5 else "DOWN"
            probability_up = prob_profitable
            probability_down = 1.0 - prob_profitable
            probability_flat = 0.0
        else:
            prob_profitable = None
            predicted_class = int(np.argmax(raw_probs))
            direction = DIRECTION_CLASSES[predicted_class]  # type: ignore[assignment]
            probability_up = float(raw_probs[DIRECTION_CLASSES.index("UP")])
            probability_down = float(raw_probs[DIRECTION_CLASSES.index("DOWN")])
            probability_flat = float(raw_probs[DIRECTION_CLASSES.index("FLAT")])

        predicted_return = float(regressor.predict(feature_vector)[0]) if regressor else 0.0

        default_set: list[str] = (
            ["NOT_PROFITABLE", "PROFITABLE"] if is_binary else DIRECTION_CLASSES.copy()
        )
        reliability = 1.0 / n_classes
        if conformal is not None:
            try:
                conf_result = conformal.predict_sets(raw_probs.reshape(1, -1))
                default_set = [str(s) for s in conf_result.prediction_sets[0]]
                reliability = float(conf_result.reliability_scores[0])
            except Exception:
                logger.debug("Conformal prediction failed, using full set")

        top_features: list[dict[str, float]] = []
        if hasattr(classifier, "feature_importances_"):
            importances = classifier.feature_importances_
            top_idx = np.argsort(importances)[-5:][::-1]
            top_features = [{feature_names[i]: float(importances[i])} for i in top_idx]

        model_version = metadata.model_version if metadata else "unknown"
        model_strategy = metadata.strategy_type if metadata else None
        used_fallback = model_strategy is None or model_strategy != strategy_type

        return MLPrediction(
            ticker=ticker,
            strategy_type=strategy_type,
            predicted_direction=direction,
            probability_up=probability_up,
            probability_down=probability_down,
            probability_flat=probability_flat,
            probability_profitable=prob_profitable,
            predicted_return_pct=predicted_return,
            prediction_set=default_set,
            reliability_score=reliability,
            top_features=top_features,
            model_version=f"{model_version}{'(fallback)' if used_fallback else ''}",
        )
    except Exception:
        logger.exception("ML prediction failed for %s", ticker)
        return None
