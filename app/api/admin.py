"""Read-only admin API (design section 7.7).

No authentication for v1. The Oracle Cloud VM is not publicly advertised, and the
app port is locked to the operator's IP via the Oracle Cloud security list (VCN
ingress rules). That IP allowlist is the access-control mechanism for v1.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Job, PublishLog, RunLog
from app.schemas.publish_log import PublishLogSchema
from app.schemas.run_log import RunLogSchema

router = APIRouter(prefix="/admin", tags=["admin"])

# Upper bound on how many rows any list endpoint will return.
_MAX_LIMIT = 100


class StatsResponse(BaseModel):
    total_jobs_seen: int
    total_posted: int
    success_rate: float
    sources_active: int


@router.get("/runs", response_model=list[RunLogSchema])
async def list_runs(
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = 20,
) -> list[RunLog]:
    """Most recent scheduler runs, newest first."""
    result = await session.execute(select(RunLog).order_by(RunLog.started_at.desc()).limit(limit))
    return list(result.scalars().all())


@router.get("/errors", response_model=list[PublishLogSchema])
async def list_errors(
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = 50,
) -> list[PublishLog]:
    """Most recent failed publish attempts, newest first."""
    result = await session.execute(
        select(PublishLog)
        .where(PublishLog.status == "failed")
        .order_by(PublishLog.attempted_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/stats", response_model=StatsResponse)
async def stats(session: Annotated[AsyncSession, Depends(get_db)]) -> StatsResponse:
    """Aggregate counters across all jobs seen.

    ``success_rate`` is the fraction of seen jobs that were successfully posted;
    ``sources_active`` is the number of distinct sources that have produced a job.
    """
    total_seen, total_posted, sources_active = (
        await session.execute(
            select(
                func.count(Job.id),
                func.count(Job.posted_at),
                func.count(func.distinct(Job.source)),
            )
        )
    ).one()

    success_rate = round(total_posted / total_seen, 4) if total_seen else 0.0

    return StatsResponse(
        total_jobs_seen=total_seen,
        total_posted=total_posted,
        success_rate=success_rate,
        sources_active=sources_active,
    )
