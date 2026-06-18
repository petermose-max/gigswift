"""Pipeline runner: orchestrates dedup -> filter -> score -> threshold."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.pipeline.dedup import filter_new_jobs
from app.pipeline.filter import filter_scams
from app.pipeline.scorer import score_jobs
from app.schemas.job import RawJobSchema

logger = get_logger(__name__)


async def run(
    raw_jobs: list[RawJobSchema],
    session: AsyncSession,
    settings: Settings | None = None,
) -> list[RawJobSchema]:
    """Run the full pipeline and return jobs ready for formatting.

    Order of operations:
      1. dedup the batch against the ``jobs`` table (by content hash),
      2. drop scam listings,
      3. score every survivor,
      4. drop anything below ``MIN_SCORE_THRESHOLD``.

    Returned jobs carry their ``score`` and are sorted highest-score first.
    """
    settings = settings or get_settings()

    new_jobs = await filter_new_jobs(raw_jobs, session)
    clean_jobs = filter_scams(new_jobs)
    scored_jobs = score_jobs(clean_jobs, settings)

    threshold = settings.MIN_SCORE_THRESHOLD
    passing = [job for job in scored_jobs if (job.score or 0.0) >= threshold]
    passing.sort(key=lambda job: job.score or 0.0, reverse=True)

    logger.info(
        "Pipeline: %d raw -> %d new -> %d non-scam -> %d above threshold %.2f",
        len(raw_jobs),
        len(new_jobs),
        len(clean_jobs),
        len(passing),
        threshold,
    )
    return passing
