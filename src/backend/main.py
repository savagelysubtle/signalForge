"""SignalForge FastAPI backend entry point.

Start locally with::

    uv run uvicorn main:app --reload --port 8420
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from config import APP_NAME, APP_VERSION, settings
from database.connection import close_db, get_db, init_db
from services.keyring_service import load_env
from services.strategy import ensure_defaults


class _JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line for Railway log parsing."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def _configure_logging() -> None:
    """Set up structured JSON logging for production, plain text for dev."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if settings.environment == "production":
        handler.setFormatter(_JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s: %(name)s - %(message)s"))
    root.addHandler(handler)


_configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown lifecycle events."""
    load_env()
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

from api.pipeline import limiter as pipeline_limiter  # noqa: E402

app.state.limiter = pipeline_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint with database connectivity verification.

    Returns status "ok" if everything is healthy, "degraded" if the
    database is unreachable. Railway uses this for zero-downtime deploys.
    """
    try:
        client = await get_db()
        response = await client.table("strategies").select("id").limit(1).execute()
        _ = response.data
        return {"status": "ok", "version": APP_VERSION}
    except Exception:
        logger.warning("Health check: database unreachable")
        return {"status": "degraded", "version": APP_VERSION}


# --- Route registration (imported after app creation) ---
from api.charts import router as charts_router  # noqa: E402
from api.pipeline import router as pipeline_router  # noqa: E402
from api.settings import router as settings_router  # noqa: E402
from api.strategies import router as strategies_router  # noqa: E402

app.include_router(charts_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")
app.include_router(strategies_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
