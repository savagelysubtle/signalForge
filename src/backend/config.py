"""Application configuration and AppData path management.

All persistent data (databases, chart images, logs) is stored in the
OS-standard user data directory, never in the project tree.

Windows: %LOCALAPPDATA%\\SignalForge\\
macOS:   ~/Library/Application Support/SignalForge/
Linux:   ~/.local/share/SignalForge/
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "SignalForge"
APP_VERSION = "0.1.0"
DEFAULT_PORT = 8420


class AppDataPaths:
    """Resolves and manages all persistent storage paths under OS AppData.

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


paths = AppDataPaths()
