"""SignalForge FastAPI backend entry point.

Start locally with::

    uv run uvicorn main:app --reload --port 8420
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import APP_NAME, APP_VERSION, settings
from database.connection import close_db, init_db
from services.keyring_service import load_env
from services.strategy import ensure_defaults

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s - %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown lifecycle events."""
    load_env()
    if settings.environment == "development" and not settings.database_url:
        from config import paths

        paths.ensure_directories()
    await init_db()
    await ensure_defaults()
    yield
    await close_db()


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint (no auth required)."""
    return {"status": "ok", "version": APP_VERSION}


# --- Route registration (imported after app creation) ---
from api.charts import router as charts_router  # noqa: E402
from api.pipeline import router as pipeline_router  # noqa: E402
from api.settings import router as settings_router  # noqa: E402
from api.strategies import router as strategies_router  # noqa: E402

app.include_router(charts_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")
app.include_router(strategies_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
