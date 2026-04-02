"""Load trained model artifact and run predictions.

Thin inference-only layer -- loads a .joblib file and runs .predict().
No training code, no heavy dependencies beyond lightgbm + joblib + numpy.
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
ACTIVE_MODEL = "model_active.joblib"

DIRECTION_CLASSES = ["DOWN", "FLAT", "UP"]

_loaded_model: dict[str, Any] | None = None


def _get_model() -> dict[str, Any] | None:
    """Load or return cached model artifact.

    Returns:
        Dict with model components, or None if no artifact exists.
    """
    global _loaded_model

    if _loaded_model is not None:
        return _loaded_model

    model_path = ARTIFACTS_DIR / ACTIVE_MODEL
    if not model_path.exists():
        logger.debug("No active model at %s", model_path)
        return None

    try:
        artifact = joblib.load(model_path)
        _loaded_model = {
            "classifier": artifact.classifier,
            "regressor": artifact.regressor,
            "label_encoder": artifact.label_encoder,
            "calibrator": artifact.calibrator,
            "conformal": artifact.conformal,
            "feature_names": artifact.metadata.feature_names if artifact.metadata else [],
            "metadata": artifact.metadata,
        }
        version = artifact.metadata.model_version if artifact.metadata else "unknown"
        logger.info("Loaded ML model: %s", version)
        return _loaded_model
    except Exception:
        logger.exception("Failed to load model artifact")
        return None


def ml_model_available() -> bool:
    """Check if a trained ML model is available for inference."""
    return _get_model() is not None


def reload_model() -> bool:
    """Force reload the model artifact (hot-reload for new versions).

    Returns:
        True if model loaded successfully.
    """
    global _loaded_model
    _loaded_model = None
    return _get_model() is not None


def get_model_info() -> dict[str, Any]:
    """Get information about the currently loaded model.

    Returns:
        Dict with model version, accuracy, status, etc.
    """
    model = _get_model()
    if model is None:
        return {"status": "inactive", "model_version": "none"}

    meta = model.get("metadata")
    if meta is None:
        return {"status": "active", "model_version": "unknown"}

    return {
        "status": "active",
        "model_version": meta.model_version,
        "training_date": meta.training_date,
        "overall_accuracy": meta.metrics.get("overall_accuracy", 0),
        "judge_verdict": meta.judge_verdict or "unknown",
        "approved_strategies": meta.approved_strategies,
        "feature_count": len(meta.feature_names),
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
    """Run ML prediction for a single ticker.

    Args:
        ticker: Ticker symbol.
        strategy_type: Strategy template type.
        features: Complete feature dict.

    Returns:
        MLPrediction or None if model unavailable.
    """
    model = _get_model()
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
            model_version=model_version,
        )
    except Exception:
        logger.exception("ML prediction failed for %s", ticker)
        return None
