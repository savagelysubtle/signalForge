"""Load trained model artifacts and run predictions.

Supports per-strategy models with automatic fallback to a combined model
when no strategy-specific artifact is available.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from ml.schemas import MLPrediction

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path("ml/artifacts")
ACTIVE_MODEL_NAME = "model_active.joblib"

DIRECTION_CLASSES = ["DOWN", "FLAT", "UP"]

_strategy_models: dict[str, dict[str, Any]] = {}
_fallback_model: dict[str, Any] | None = None
_loaded = False


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
      - ``model_{strategy_type}_active.joblib`` → per-strategy models
      - ``model_active.joblib`` → combined fallback model
    """
    global _strategy_models, _fallback_model, _loaded
    _strategy_models = {}
    _fallback_model = None

    if not ARTIFACTS_DIR.exists():
        logger.debug("Artifacts directory does not exist: %s", ARTIFACTS_DIR)
        _loaded = True
        return

    fallback_path = ARTIFACTS_DIR / ACTIVE_MODEL_NAME
    if fallback_path.exists():
        try:
            _fallback_model = _unpack_artifact(joblib.load(fallback_path))
            version = _fallback_model["metadata"].model_version if _fallback_model["metadata"] else "?"
            logger.info("Loaded combined fallback model: %s", version)
        except Exception:
            logger.exception("Failed to load fallback model")

    for p in sorted(ARTIFACTS_DIR.glob("model_*_active.joblib")):
        if p.name == ACTIVE_MODEL_NAME:
            continue
        parts = p.stem.split("_")
        strategy_type = "_".join(parts[1:-1])
        try:
            artifact = joblib.load(p)
            _strategy_models[strategy_type] = _unpack_artifact(artifact)
            version = artifact.metadata.model_version if artifact.metadata else "?"
            logger.info("Loaded strategy model [%s]: %s", strategy_type, version)
        except Exception:
            logger.exception("Failed to load strategy model: %s", p.name)

    _loaded = True
    logger.info(
        "Model loading complete: %d strategy models + %s fallback",
        len(_strategy_models),
        "1" if _fallback_model else "no",
    )


def _get_model(strategy_type: str | None = None) -> dict[str, Any] | None:
    """Get the best available model for a given strategy type.

    Priority: strategy-specific model → combined fallback → None.
    """
    if not _loaded:
        _load_all_models()

    if strategy_type and strategy_type in _strategy_models:
        return _strategy_models[strategy_type]
    return _fallback_model


def ml_model_available(strategy_type: str | None = None) -> bool:
    """Check if a trained ML model is available for inference."""
    return _get_model(strategy_type) is not None


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

    fallback_meta = _fallback_model.get("metadata") if _fallback_model else None

    return {
        "status": "active" if (_strategy_models or _fallback_model) else "inactive",
        "strategy_models": strategy_info,
        "fallback": {
            "model_version": fallback_meta.model_version if fallback_meta else "none",
            "judge_verdict": fallback_meta.judge_verdict if fallback_meta else "none",
        },
        "total_models": len(_strategy_models) + (1 if _fallback_model else 0),
    }


def build_feature_vector(
    ta_features: dict[str, float | None],
    fundamental_features: dict[str, float | None] | None = None,
    context_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a feature vector for inference from live pipeline data.

    Args:
        ta_features: Technical analysis features from TechnicalSnapshot.
        fundamental_features: Fundamental data features (optional).
        context_features: Strategy type, regime, sector (optional).

    Returns:
        Complete feature dict ready for model input.
    """
    features: dict[str, Any] = {}
    features.update(ta_features)
    if fundamental_features:
        features.update(fundamental_features)
    if context_features:
        features.update(context_features)
    return features


def run_prediction(
    ticker: str,
    strategy_type: str,
    features: dict[str, Any],
) -> MLPrediction | None:
    """Run ML prediction for a single ticker using the best available model.

    Automatically selects the strategy-specific model if available,
    falling back to the combined model otherwise.

    Args:
        ticker: Ticker symbol.
        strategy_type: Strategy template type.
        features: Complete feature dict.

    Returns:
        MLPrediction or None if model unavailable.
    """
    model = _get_model(strategy_type)
    if model is None:
        return None

    classifier = model["classifier"]
    regressor = model["regressor"]
    feature_names = model["feature_names"]
    calibrator = model.get("calibrator")
    conformal = model.get("conformal")
    metadata = model.get("metadata")

    feature_vector = np.array([features.get(name, 0.0) or 0.0 for name in feature_names]).reshape(
        1, -1
    )

    try:
        dir_probs = classifier.predict_proba(feature_vector)[0]

        if calibrator is not None:
            dir_probs = calibrator.calibrate(dir_probs.reshape(1, -1))[0]

        predicted_class = int(np.argmax(dir_probs))
        predicted_direction = DIRECTION_CLASSES[predicted_class]

        predicted_return = float(regressor.predict(feature_vector)[0]) if regressor else 0.0

        prediction_set = DIRECTION_CLASSES.copy()
        reliability = 1.0 / 3.0
        if conformal is not None:
            try:
                conf_result = conformal.predict_sets(dir_probs.reshape(1, -1))
                prediction_set = conf_result.prediction_sets[0]
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
            predicted_direction=predicted_direction,
            probability_up=float(dir_probs[DIRECTION_CLASSES.index("UP")]),
            probability_down=float(dir_probs[DIRECTION_CLASSES.index("DOWN")]),
            probability_flat=float(dir_probs[DIRECTION_CLASSES.index("FLAT")]),
            predicted_return_pct=predicted_return,
            prediction_set=prediction_set,
            reliability_score=reliability,
            top_features=top_features,
            model_version=f"{model_version}{'(fallback)' if used_fallback else ''}",
        )
    except Exception:
        logger.exception("ML prediction failed for %s", ticker)
        return None
