"""FastAPI application factory.

Hosts the read-only admin API and runs the APScheduler pipeline loop in-process:
the Docker container runs ``uvicorn app.main:app``, so the lifespan starts the
scheduler on startup and shuts it down on shutdown.
"""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import admin, health
from app.core.database import dispose_engine
from app.core.logging import configure_logging, get_logger
from app.scheduler import build_scheduler

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Configure logging, start the scheduler, and tear both down on shutdown."""
    configure_logging()
    app.state.started_monotonic = time.monotonic()

    scheduler = build_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("GigSwift started (version %s); scheduler running", __version__)

    try:
        yield
    finally:
        logger.info("GigSwift shutting down")
        scheduler.shutdown(wait=False)
        await dispose_engine()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title="GigSwift Agent",
        version=__version__,
        summary="Ingests remote gig listings, scores them, and posts to X and Telegram.",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(admin.router)
    return app


app = create_app()
