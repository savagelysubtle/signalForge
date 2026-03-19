"""Application configuration and AppData path management.

All persistent data (databases, chart images, logs) is stored in the
OS-standard user data directory in development mode, or uses cloud
services in production mode.

Windows: %LOCALAPPDATA%\\SignalForge\\
macOS:   ~/Library/Application Support/SignalForge/
Linux:   ~/.local/share/SignalForge/
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from platformdirs import user_data_dir
from pydantic import BaseModel, Field

# Load .env before settings are created so env vars are available at import time.
_env_candidates = [Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"]
for _env_path in _env_candidates:
    if _env_path.exists():
        load_dotenv(_env_path, override=True)
        break

APP_NAME = "SignalForge"
APP_VERSION = "0.1.0"


class Settings(BaseModel):
    """Application settings loaded from environment variables.

    Attributes:
        environment: Deployment environment (development or production).
        database_url: PostgreSQL connection string for production; empty for local SQLite.
        supabase_url: Supabase project URL for auth and storage.
        supabase_service_key: Supabase service role key for admin operations.
        supabase_jwt_secret: Secret for JWT verification.
        supabase_anon_key: Supabase anonymous key for client operations.
        allowed_origins: CORS allowed origins for API access.
        port: HTTP server port.
    """

    environment: Literal["development", "production"] = "development"
    database_url: str = ""
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_anon_key: str = ""
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    port: int = 8420

    @classmethod
    def from_env(cls) -> Settings:
        """Load settings from environment variables.

        Returns:
            Settings instance populated from os.environ.
        """
        allowed_origins_str = os.environ.get("ALLOWED_ORIGINS", "")
        allowed_origins = (
            [origin.strip() for origin in allowed_origins_str.split(",") if origin.strip()]
            if allowed_origins_str
            else ["http://localhost:5173"]
        )

        return cls(
            environment=os.environ.get("ENVIRONMENT", "development"),
            database_url=os.environ.get("DATABASE_URL", ""),
            supabase_url=os.environ.get("SUPABASE_URL", ""),
            supabase_service_key=os.environ.get("SUPABASE_SERVICE_KEY", ""),
            supabase_jwt_secret=os.environ.get("SUPABASE_JWT_SECRET", ""),
            supabase_anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
            allowed_origins=allowed_origins,
            port=int(os.environ.get("PORT", "8420")),
        )


class AppDataPaths:
    """Resolves and manages all persistent storage paths under OS AppData.

    Only used in development mode when database_url is empty.
    Follows the cross-platform AppData storage pattern. All paths are derived
    from ``platformdirs.user_data_dir`` at runtime — never hardcoded.
    """

    def __init__(self) -> None:
        self.base_dir = Path(user_data_dir(APP_NAME, appauthor=False))

    @property
    def db_path(self) -> Path:
        """Path to the main SQLite database file."""
        return self.base_dir / "databases" / "signalforge.db"

    @property
    def charts_dir(self) -> Path:
        """Directory for downloaded chart image PNGs."""
        return self.base_dir / "charts"

    @property
    def logs_dir(self) -> Path:
        """Directory for application log files."""
        return self.base_dir / "logs"

    def ensure_directories(self) -> None:
        """Create all required directories if they don't exist.

        Safe to call multiple times — uses ``mkdir(parents=True, exist_ok=True)``.
        Should be called once at application startup.
        """
        for d in [self.db_path.parent, self.charts_dir, self.logs_dir]:
            d.mkdir(parents=True, exist_ok=True)


# Module-level singletons
settings = Settings.from_env()
paths = AppDataPaths()
