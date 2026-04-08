"""SignalForge FastAPI backend entry point.

Start locally with::

    uv run uvicorn main:app --reload --port 8420
"""

from __future__ import annotations

import contextlib
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
from services.market_heartbeat import close_heartbeat, init_heartbeat
from services.strategy import ensure_defaults
from services.strategy_scanner import init_scanner


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


async def _scanner_schedule() -> None:
    """Run the scanner 2-3x/day on a market-aware schedule (ET)."""
    import asyncio as _aio

    from services.strategy_scanner import get_scanner

    schedule_hours_et = [8.5, 12.0, 15.0]
    await _aio.sleep(60)

    while True:
        try:
            now_utc = datetime.now(UTC)
            et_hour = now_utc.hour + now_utc.minute / 60 - 4
            if et_hour < 0:
                et_hour += 24
            weekday = now_utc.weekday()

            if weekday < 5:
                for target in schedule_hours_et:
                    if abs(et_hour - target) < 0.15:
                        logger.info("Scanner schedule: running at ET %.1f", target)
                        scanner = get_scanner()
                        await scanner.run_scan(triggered_by="schedule")
                        break

            next_check = 5 * 60
            await _aio.sleep(next_check)
        except _aio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Scanner schedule error: %s", exc)
            await _aio.sleep(60)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown lifecycle events."""
    import asyncio as _aio

    load_env()
    await init_db()
    await ensure_defaults()

    heartbeat = await init_heartbeat()
    scanner = await init_scanner(heartbeat)
    _app.state.heartbeat = heartbeat
    _app.state.scanner = scanner

    heartbeat_task = _aio.create_task(heartbeat.run_forever())
    scanner_task = _aio.create_task(_scanner_schedule())

    yield

    heartbeat_task.cancel()
    scanner_task.cancel()
    with contextlib.suppress(_aio.CancelledError):
        await heartbeat_task
    with contextlib.suppress(_aio.CancelledError):
        await scanner_task
    await close_heartbeat()
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

from slowapi import Limiter  # noqa: E402
from slowapi.util import get_remote_address  # noqa: E402

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter
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
from api.concentration import router as concentration_router  # noqa: E402
from api.decisions import router as decisions_router  # noqa: E402
from api.ml_predictions import router as ml_router  # noqa: E402
from api.outcomes import router as outcomes_router  # noqa: E402
from api.pipeline import router as pipeline_router  # noqa: E402
from api.questrade import router as questrade_router  # noqa: E402
from api.recommendations import router as recommendations_router  # noqa: E402
from api.reflections import router as reflections_router  # noqa: E402
from api.scanner import router as scanner_router  # noqa: E402
from api.settings import router as settings_router  # noqa: E402
from api.strategies import router as strategies_router  # noqa: E402

app.include_router(charts_router, prefix="/api")
app.include_router(concentration_router, prefix="/api")
app.include_router(decisions_router, prefix="/api")
app.include_router(outcomes_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")
app.include_router(recommendations_router, prefix="/api")
app.include_router(reflections_router, prefix="/api")
app.include_router(strategies_router, prefix="/api")
app.include_router(questrade_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(ml_router, prefix="/api")
app.include_router(scanner_router, prefix="/api")
