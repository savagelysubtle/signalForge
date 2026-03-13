"""SignalForge FastAPI backend entry point.

Start with::

    uv run uvicorn main:app --reload --port 8420
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import APP_NAME, APP_VERSION, paths
from database.connection import close_db, init_db
from services.strategy import ensure_defaults


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown lifecycle events."""
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "version": APP_VERSION}


# --- Route registration (imported after app creation) ---
from api.pipeline import router as pipeline_router  # noqa: E402
from api.settings import router as settings_router  # noqa: E402
from api.strategies import router as strategies_router  # noqa: E402

app.include_router(pipeline_router, prefix="/api")
app.include_router(strategies_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
