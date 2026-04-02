"""Model versioning, artifact export, and registry management.

Handles serialization of trained models to .joblib artifacts,
version tracking, and model promotion workflow.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path("src/ml_training/models/artifacts")
BACKEND_ARTIFACTS_DIR = Path("src/backend/ml/artifacts")


@dataclass
class ModelMetadata:
    """Metadata stored alongside a model artifact."""

    model_version: str
    training_date: str
    feature_names: list[str]
    training_config: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    judge_verdict: str | None = None
    approved_strategies: list[str] = field(default_factory=list)
    status: str = "trained"


@dataclass
class ModelArtifact:
    """Complete model artifact containing all components needed for inference."""

    classifier: Any
    regressor: Any
    label_encoder: Any
    calibrator: Any | None = None
    conformal: Any | None = None
    feature_encoders: dict[str, Any] = field(default_factory=dict)
    metadata: ModelMetadata | None = None


class ModelRegistry:
    """Manages model versions, artifacts, and promotion.

    Artifacts are stored as .joblib files in the artifacts directory.
    The registry tracks all versions and their metadata.
    """

    def __init__(
        self,
        artifacts_dir: Path | None = None,
        backend_dir: Path | None = None,
    ) -> None:
        self._artifacts_dir = artifacts_dir or ARTIFACTS_DIR
        self._backend_dir = backend_dir or BACKEND_ARTIFACTS_DIR
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)

    def _next_version(self) -> str:
        """Generate the next model version string."""
        existing = list(self._artifacts_dir.glob("model_v*.joblib"))
        if not existing:
            return "v1"

        versions: list[int] = []
        for p in existing:
            parts = p.stem.split("_")
            for part in parts:
                if part.startswith("v") and part[1:].isdigit():
                    versions.append(int(part[1:]))

        next_v = max(versions) + 1 if versions else 1
        return f"v{next_v}"

    def save_artifact(
        self,
        artifact: ModelArtifact,
        version: str | None = None,
    ) -> Path:
        """Save a model artifact to disk.

        Args:
            artifact: Complete model artifact with all components.
            version: Explicit version string. Auto-generated if None.

        Returns:
            Path to the saved .joblib file.
        """
        version = version or self._next_version()
        date_str = datetime.now(tz=UTC).strftime("%Y%m%d")
        filename = f"model_{version}_{date_str}.joblib"
        path = self._artifacts_dir / filename

        if artifact.metadata is None:
            artifact.metadata = ModelMetadata(
                model_version=version,
                training_date=date_str,
                feature_names=[],
            )
        else:
            artifact.metadata.model_version = version
            artifact.metadata.training_date = date_str

        joblib.dump(artifact, path)
        logger.info("Saved model artifact: %s", path)

        meta_path = self._artifacts_dir / f"model_{version}_{date_str}_meta.json"
        meta_path.write_text(json.dumps(asdict(artifact.metadata), indent=2))

        return path

    def load_artifact(self, path: Path) -> ModelArtifact:
        """Load a model artifact from disk.

        Args:
            path: Path to the .joblib file.

        Returns:
            Loaded ModelArtifact.
        """
        artifact = joblib.load(path)
        if not isinstance(artifact, ModelArtifact):
            raise TypeError(f"Expected ModelArtifact, got {type(artifact)}")
        return artifact

    def list_versions(self) -> list[dict[str, Any]]:
        """List all available model versions with metadata.

        Returns:
            List of dicts with version, path, and metadata for each model.
        """
        versions: list[dict[str, Any]] = []
        for p in sorted(self._artifacts_dir.glob("model_v*.joblib")):
            meta_path = p.with_suffix("").with_name(p.stem + "_meta.json")
            meta = {}
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
            versions.append({"path": str(p), "filename": p.name, **meta})
        return versions

    def get_latest(self) -> Path | None:
        """Get the path to the latest model artifact.

        Returns:
            Path to the most recent .joblib file, or None if none exist.
        """
        artifacts = sorted(self._artifacts_dir.glob("model_v*.joblib"))
        return artifacts[-1] if artifacts else None

    def promote_to_shadow(self, artifact_path: Path) -> Path:
        """Copy a model artifact to the backend for shadow mode.

        Args:
            artifact_path: Path to the source .joblib artifact.

        Returns:
            Path to the copied artifact in the backend directory.
        """
        self._backend_dir.mkdir(parents=True, exist_ok=True)
        dest = self._backend_dir / "model_active.joblib"
        shutil.copy2(artifact_path, dest)
        logger.info("Promoted model to shadow: %s -> %s", artifact_path, dest)
        return dest

    def get_active_model_path(self) -> Path | None:
        """Get the path to the currently active model in the backend.

        Returns:
            Path to model_active.joblib if it exists, None otherwise.
        """
        active = self._backend_dir / "model_active.joblib"
        return active if active.exists() else None
