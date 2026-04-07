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

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
BACKEND_ARTIFACTS_DIR = Path(__file__).resolve().parents[3] / "backend" / "ml" / "artifacts"


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
    strategy_type: str | None = None
    shap_importance: dict[str, float] | None = None


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
    meta_labeler: Any | None = None


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

    def _next_version(self, strategy_type: str | None = None) -> str:
        """Generate the next model version string.

        Args:
            strategy_type: If provided, version is scoped to that strategy.
        """
        pattern = f"model_{strategy_type}_v*.joblib" if strategy_type else "model_v*.joblib"
        existing = list(self._artifacts_dir.glob(pattern))
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
        strategy_type: str | None = None,
    ) -> Path:
        """Save a model artifact to disk.

        Args:
            artifact: Complete model artifact with all components.
            version: Explicit version string. Auto-generated if None.
            strategy_type: Strategy type key (e.g. "swing"). If provided,
                the artifact is stored as ``model_{strategy_type}_v{N}_{date}.joblib``.

        Returns:
            Path to the saved .joblib file.
        """
        version = version or self._next_version(strategy_type)
        date_str = datetime.now(tz=UTC).strftime("%Y%m%d")

        if strategy_type:
            filename = f"model_{strategy_type}_{version}_{date_str}.joblib"
        else:
            filename = f"model_{version}_{date_str}.joblib"

        path = self._artifacts_dir / filename

        if artifact.metadata is None:
            artifact.metadata = ModelMetadata(
                model_version=version,
                training_date=date_str,
                feature_names=[],
                strategy_type=strategy_type,
            )
        else:
            artifact.metadata.model_version = version
            artifact.metadata.training_date = date_str
            artifact.metadata.strategy_type = strategy_type

        joblib.dump(artifact, path)
        logger.info("Saved model artifact: %s", path)

        meta_path = path.with_suffix("").with_name(path.stem + "_meta.json")
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

    def get_latest(self, strategy_type: str | None = None) -> Path | None:
        """Get the path to the latest (highest version) model artifact.

        Args:
            strategy_type: If provided, returns the latest per-strategy model.
                If None, returns the latest combined (non-strategy) model.

        Returns:
            Path to the most recent .joblib file, or None if none exist.
        """
        pattern = f"model_{strategy_type}_v*.joblib" if strategy_type else "model_v*.joblib"
        artifacts = list(self._artifacts_dir.glob(pattern))
        if not artifacts:
            return None

        def _version_key(p: Path) -> int:
            for part in p.stem.split("_"):
                if part.startswith("v") and part[1:].isdigit():
                    return int(part[1:])
            return 0

        return max(artifacts, key=_version_key)

    def list_strategy_models(self) -> dict[str, Path]:
        """List the latest (highest version) model artifact for each strategy type.

        Returns:
            Mapping of strategy_type → Path for each available per-strategy model.
        """
        models: dict[str, Path] = {}
        versions: dict[str, int] = {}
        for p in self._artifacts_dir.glob("model_*_v*.joblib"):
            parts = p.stem.split("_")
            v_idx = next(
                (i for i, x in enumerate(parts) if x.startswith("v") and x[1:].isdigit()), None
            )
            if v_idx is not None and v_idx > 1:
                strategy = "_".join(parts[1:v_idx])
                version_num = int(parts[v_idx][1:])
                if version_num > versions.get(strategy, -1):
                    versions[strategy] = version_num
                    models[strategy] = p
        return models

    def promote_to_shadow(
        self,
        artifact_path: Path,
        strategy_type: str | None = None,
    ) -> Path:
        """Copy a model artifact to the backend for shadow mode.

        Args:
            artifact_path: Path to the source .joblib artifact.
            strategy_type: If provided, names the file
                ``model_{strategy_type}_active.joblib``.

        Returns:
            Path to the copied artifact in the backend directory.
        """
        self._backend_dir.mkdir(parents=True, exist_ok=True)
        if strategy_type:
            dest = self._backend_dir / f"model_{strategy_type}_active.joblib"
        else:
            dest = self._backend_dir / "model_active.joblib"
        shutil.copy2(artifact_path, dest)
        logger.info("Promoted model to shadow: %s -> %s", artifact_path, dest)
        return dest

    def promote_all_strategies(self) -> list[Path]:
        """Promote the latest model for every strategy type plus the combined fallback.

        Returns:
            List of paths to promoted artifacts in the backend directory.
        """
        promoted: list[Path] = []

        combined = self.get_latest()
        if combined:
            promoted.append(self.promote_to_shadow(combined))

        for strategy_type, path in self.list_strategy_models().items():
            promoted.append(self.promote_to_shadow(path, strategy_type))

        return promoted

    def get_active_model_path(self, strategy_type: str | None = None) -> Path | None:
        """Get the path to the currently active model in the backend.

        Args:
            strategy_type: If provided, looks for the strategy-specific active model.

        Returns:
            Path to the active .joblib if it exists, None otherwise.
        """
        if strategy_type:
            active = self._backend_dir / f"model_{strategy_type}_active.joblib"
        else:
            active = self._backend_dir / "model_active.joblib"
        return active if active.exists() else None
