"""Async SQLite database connection management.

Uses aiosqlite with WAL mode for concurrent read access from
the frontend while the backend writes during pipeline execution.
"""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from config import paths

logger = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def get_db() -> aiosqlite.Connection:
    """Return the active database connection.

    Raises:
        RuntimeError: If the database has not been initialized via ``init_db``.
    """
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db


async def init_db() -> None:
    """Open the database connection, enable WAL mode, and run migrations."""
    global _db

    db_path = paths.db_path
    logger.info("Opening database at %s", db_path)

    _db = await aiosqlite.connect(str(db_path))
    _db.row_factory = aiosqlite.Row

    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")

    await _run_migrations(_db)


async def close_db() -> None:
    """Commit pending transactions and close the database connection."""
    global _db
    if _db is not None:
        await _db.commit()
        await _db.close()
        _db = None
        logger.info("Database connection closed.")


async def _run_migrations(db: aiosqlite.Connection) -> None:
    """Execute all SQL migration files in order."""
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for migration in migration_files:
        logger.info("Running migration: %s", migration.name)
        sql = migration.read_text(encoding="utf-8")
        await db.executescript(sql)
    await db.commit()
