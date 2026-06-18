"""Health endpoint: GET /health."""

import time
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.database import get_db
from app.models import RunLog

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    uptime_seconds: int
    last_run_at: datetime | None
    version: str


@router.get("/health", response_model=HealthResponse)
async def health(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> HealthResponse:
    """Liveness check with process uptime, the last scheduler run, and app version."""
    started = getattr(request.app.state, "started_monotonic", None)
    uptime_seconds = int(time.monotonic() - started) if started is not None else 0

    last_run_at = (await session.execute(select(func.max(RunLog.started_at)))).scalar_one()

    return HealthResponse(
        status="ok",
        uptime_seconds=uptime_seconds,
        last_run_at=last_run_at,
        version=__version__,
    )
