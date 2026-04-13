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
    holdout_metrics: dict[str, float] | None = None


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
        self._artifacts_root = artifacts_dir or ARTIFACTS_DIR
        self._backend_dir = backend_dir or BACKEND_ARTIFACTS_DIR
        self._artifacts_root.mkdir(parents=True, exist_ok=True)

    def _strategy_dir(self, strategy_type: str | None = None) -> Path:
        """Return the per-strategy subfolder, creating it if needed."""
        subdir = self._artifacts_root / (strategy_type or "combined")
        subdir.mkdir(parents=True, exist_ok=True)
        return subdir

    def _next_version(self, strategy_type: str | None = None) -> str:
        """Generate the next model version string.

        Args:
            strategy_type: If provided, version is scoped to that strategy.
        """
        target_dir = self._strategy_dir(strategy_type)
        existing = list(target_dir.glob("model_v*.joblib"))
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

        Artifacts are stored in per-strategy subdirectories under the
        artifacts root: ``artifacts/{strategy_type}/model_v{N}_{date}.joblib``.
        Combined (non-strategy) models go into ``artifacts/combined/``.

        Args:
            artifact: Complete model artifact with all components.
            version: Explicit version string. Auto-generated if None.
            strategy_type: Strategy type key (e.g. "momentum_breakout").

        Returns:
            Path to the saved .joblib file.
        """
        version = version or self._next_version(strategy_type)
        date_str = datetime.now(tz=UTC).strftime("%Y%m%d")
        filename = f"model_{version}_{date_str}.joblib"

        target_dir = self._strategy_dir(strategy_type)
        path = target_dir / filename

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

    def list_versions(self, strategy_type: str | None = None) -> list[dict[str, Any]]:
        """List all available model versions with metadata.

        Args:
            strategy_type: Scope to a specific strategy. If None, lists
                across all strategy subdirectories.

        Returns:
            List of dicts with version, path, and metadata for each model.
        """
        versions: list[dict[str, Any]] = []
        if strategy_type is not None:
            dirs = [self._strategy_dir(strategy_type)]
        else:
            dirs = [d for d in self._artifacts_root.iterdir() if d.is_dir() and d.name != "archive"]
        for d in dirs:
            for p in sorted(d.glob("model_v*.joblib")):
                meta_path = p.with_suffix("").with_name(p.stem + "_meta.json")
                meta = {}
                if meta_path.exists():
                    meta = json.loads(meta_path.read_text())
                versions.append(
                    {"path": str(p), "filename": p.name, "strategy_dir": d.name, **meta}
                )
        return versions

    def get_latest(self, strategy_type: str | None = None) -> Path | None:
        """Get the path to the latest (highest version) model artifact.

        Args:
            strategy_type: If provided, returns the latest for that strategy.
                If None, returns the latest combined model.

        Returns:
            Path to the most recent .joblib file, or None if none exist.
        """
        target_dir = self._strategy_dir(strategy_type)
        artifacts = list(target_dir.glob("model_v*.joblib"))
        if not artifacts:
            return None

        def _version_key(p: Path) -> int:
            for part in p.stem.split("_"):
                if part.startswith("v") and part[1:].isdigit():
                    return int(part[1:])
            return 0

        return max(artifacts, key=_version_key)

    def list_strategy_models(self) -> dict[str, Path]:
        """List the latest model artifact for each strategy type.

        Scans subdirectories of the artifacts root (excluding ``archive``
        and ``combined``) for per-strategy models.

        Returns:
            Mapping of strategy_type → Path for each available per-strategy model.
        """
        models: dict[str, Path] = {}
        for d in self._artifacts_root.iterdir():
            if not d.is_dir() or d.name in ("archive", "combined"):
                continue
            latest = list(d.glob("model_v*.joblib"))
            if not latest:
                continue

            def _version_key(p: Path) -> int:
                for part in p.stem.split("_"):
                    if part.startswith("v") and part[1:].isdigit():
                        return int(part[1:])
                return 0

            models[d.name] = max(latest, key=_version_key)
        return models

    def promote_to_shadow(
        self,
        artifact_path: Path,
        strategy_type: str | None = None,
    ) -> Path:
        """Copy a model artifact and its metadata to the backend for shadow mode.

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

        src_meta = artifact_path.with_suffix("").with_name(artifact_path.stem + "_meta.json")
        if src_meta.exists():
            dest_meta = dest.with_suffix("").with_name(dest.stem + "_meta.json")
            shutil.copy2(src_meta, dest_meta)
            logger.info("Promoted metadata: %s -> %s", src_meta, dest_meta)

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
