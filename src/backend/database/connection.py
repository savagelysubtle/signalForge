"""Async PostgreSQL database connection management using asyncpg."""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

from config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def get_db() -> asyncpg.Pool:
    """Get the database connection pool.

    Returns:
        The asyncpg connection pool.

    Raises:
        RuntimeError: If database not initialized.
    """
    if _pool is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _pool


async def init_db() -> None:
    """Initialize the database connection pool and run migrations.

    Creates a connection pool with min_size=2, max_size=10.
    Runs all pending migrations from the migrations directory.
    """
    global _pool
    logger.info("Creating database connection pool for %s", settings.database_url)
    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=2,
        max_size=10,
    )
    await _run_migrations(_pool)


async def close_db() -> None:
    """Close the database connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed.")


async def _run_migrations(pool: asyncpg.Pool) -> None:
    """Run pending database migrations.

    Creates a schema_migrations table if it doesn't exist, checks which
    migrations have already been applied, and runs only new migrations.

    Args:
        pool: The asyncpg connection pool.
    """
    async with pool.acquire() as conn:
        # Create schema_migrations table if not exists
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )

        # Get list of applied migrations
        applied = await conn.fetch("SELECT name FROM schema_migrations")
        applied_names = {row["name"] for row in applied}

        # Get all migration files
        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

        for migration in migration_files:
            migration_name = migration.name

            # Skip if already applied
            if migration_name in applied_names:
                logger.debug("Skipping already applied migration: %s", migration_name)
                continue

            logger.info("Running migration: %s", migration_name)

            # Read migration file
            sql = migration.read_text(encoding="utf-8")

            # Split on semicolons and execute each statement
            # asyncpg doesn't have executescript, so we split manually
            statements = [stmt.strip() for stmt in sql.split(";") if stmt.strip()]

            async with conn.transaction():
                for stmt in statements:
                    await conn.execute(stmt)

                # Record migration as applied
                await conn.execute(
                    "INSERT INTO schema_migrations (name) VALUES ($1)",
                    migration_name,
                )

            logger.info("Migration completed: %s", migration_name)
