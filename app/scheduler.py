"""APScheduler-driven pipeline runner.

Two modes:

* **default** (no args): an ``AsyncIOScheduler`` runs :func:`pipeline_run` every
  ``SCHEDULER_INTERVAL_MINUTES`` — used by the Docker container.
* **``--once``**: run :func:`pipeline_run` a single time and exit — used by the
  GitHub Actions backup runner.

A run flows: create a ``run_log`` row, ingest all sources concurrently, run the
dedup/filter/score pipeline, then persist + format + publish each surviving job,
and finally update the ``run_log`` counts. Failures are caught at the top level so
a bad run records its error without crashing the scheduler loop.
"""

import argparse
import asyncio
import contextlib
import signal
import time
import uuid
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import dispose_engine, get_sessionmaker
from app.core.logging import configure_logging, get_logger
from app.formatter.base import BaseFormatter
from app.formatter.linkedin_formatter import LinkedInFormatter
from app.formatter.telegram_formatter import TelegramFormatter
from app.formatter.x_formatter import XFormatter
from app.ingest.registry import get_all_ingestors
from app.models import Job, Post, RunLog
from app.pipeline.dedup import compute_content_hash
from app.pipeline.runner import run as run_pipeline
from app.publisher.base import BasePublisher
from app.publisher.linkedin_publisher import LinkedInPublisher
from app.publisher.telegram_publisher import TelegramPublisher
from app.publisher.x_publisher import XPublisher
from app.schemas.job import JobCreateSchema, RawJobSchema
from app.schemas.post import PostSchema

logger = get_logger(__name__)

Pair = tuple[BaseFormatter, BasePublisher]


def _build_pairs(session: AsyncSession, settings: Settings) -> list[Pair]:
    """Pair each formatter with the publisher for the same platform."""
    pairs: list[Pair] = [
        (XFormatter(), XPublisher(session, settings)),
        (TelegramFormatter(), TelegramPublisher(session, settings)),
    ]
    # LinkedIn is optional: only post when an access token is configured.
    if settings.LINKEDIN_ACCESS_TOKEN:
        pairs.append((LinkedInFormatter(), LinkedInPublisher(session, settings)))
    return pairs


async def _process_job(
    session: AsyncSession, job: RawJobSchema, pairs: list[Pair]
) -> tuple[bool, int]:
    """Persist a job, then format + publish it on each platform.

    Returns ``(posted_to_any_platform, failed_publish_count)``. A failure here is
    isolated: the job's work is rolled back and the run continues with the next job.
    """
    posted_any = False
    errors = 0
    try:
        job_create = JobCreateSchema(
            source=job.source,
            title=job.title,
            description=job.description,
            pay_min=job.pay_min,
            pay_max=job.pay_max,
            pay_currency=job.pay_currency,
            apply_url=job.apply_url,
            content_hash=compute_content_hash(job.title, job.apply_url),
            score=job.score,
            is_scam=False,
        )
        job_model = Job(**job_create.model_dump())
        session.add(job_model)
        await session.flush()

        for formatter, publisher in pairs:
            # format() is sync (Pillow + file I/O); offload so it never blocks the loop.
            post_create = await asyncio.to_thread(formatter.format, job)
            data = post_create.model_dump()
            data["job_id"] = job_model.id  # reconcile the placeholder id -> real Job.id
            post_model = Post(**data)
            session.add(post_model)
            await session.flush()

            result = await publisher.publish_with_retry(PostSchema.model_validate(post_model))
            if result.success:
                posted_any = True
            else:
                errors += 1

        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Failed to process job %r", job.title)
        return False, errors + 1
    return posted_any, errors


async def _record_run_failure(
    sessionmaker: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID | None,
    ingested: int,
    new: int,
    posted: int,
    errors: int,
) -> None:
    """Best-effort update of a run_log row after a top-level failure (fresh session)."""
    if run_id is None:
        return
    try:
        async with sessionmaker() as session:
            await session.execute(
                update(RunLog)
                .where(RunLog.id == run_id)
                .values(
                    jobs_ingested=ingested,
                    jobs_new=new,
                    jobs_posted=posted,
                    errors=errors,
                    finished_at=func.now(),
                )
            )
            await session.commit()
    except Exception:
        logger.exception("Could not record run failure for run_log %s", run_id)


async def pipeline_run(trigger: str = "scheduler") -> None:
    """Run one full pipeline cycle. Never raises — failures are logged and recorded."""
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    started = time.monotonic()
    run_id: uuid.UUID | None = None
    ingested = new = posted = errors = 0

    try:
        async with sessionmaker() as session:
            run_log = RunLog(trigger=trigger)
            session.add(run_log)
            await session.commit()  # record the run start up front
            run_id = run_log.id

            # 1. ingest every source concurrently (each isolates its own failures)
            ingestors = get_all_ingestors(settings)
            fetched = await asyncio.gather(*(ingestor.safe_fetch() for ingestor in ingestors))
            raw_jobs: list[RawJobSchema] = [job for batch in fetched for job in batch]
            ingested = len(raw_jobs)

            # 2. dedup -> filter -> score -> threshold
            passing = await run_pipeline(raw_jobs, session, settings)
            new = len(passing)
            to_post = passing[: settings.MAX_POSTS_PER_RUN]

            # 3. persist + format + publish the top jobs
            if to_post:
                pairs = _build_pairs(session, settings)
                for job in to_post:
                    job_posted, job_errors = await _process_job(session, job, pairs)
                    posted += int(job_posted)
                    errors += job_errors

            # 4. finalise the run_log counts
            await session.execute(
                update(RunLog)
                .where(RunLog.id == run_id)
                .values(
                    jobs_ingested=ingested,
                    jobs_new=new,
                    jobs_posted=posted,
                    errors=errors,
                    finished_at=func.now(),
                )
            )
            await session.commit()
    except Exception as exc:
        errors += 1
        logger.exception("Pipeline run failed: %s", exc)
        await _record_run_failure(sessionmaker, run_id, ingested, new, posted, errors)
    finally:
        duration = time.monotonic() - started
        logger.info(
            "Pipeline run complete: trigger=%s ingested=%d new=%d posted=%d errors=%d (%.1fs)",
            trigger,
            ingested,
            new,
            posted,
            errors,
            duration,
            extra={
                "event": "pipeline_run",
                "trigger": trigger,
                "run_id": str(run_id) if run_id else None,
                "jobs_ingested": ingested,
                "jobs_new": new,
                "jobs_posted": posted,
                "errors": errors,
                "duration_seconds": round(duration, 2),
            },
        )


async def run_once(trigger: str = "github_actions") -> None:
    """Run the pipeline a single time, then dispose of the engine and exit."""
    try:
        await pipeline_run(trigger=trigger)
    finally:
        await dispose_engine()


def build_scheduler(settings: Settings | None = None) -> AsyncIOScheduler:
    """Create the AsyncIOScheduler with the pipeline job attached (not started).

    Shared by :func:`run_forever` (standalone) and the FastAPI lifespan in
    ``app.main`` (the Docker container hosts the scheduler inside the web app).
    """
    settings = settings or get_settings()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        pipeline_run,
        "interval",
        minutes=settings.SCHEDULER_INTERVAL_MINUTES,
        kwargs={"trigger": "scheduler"},
        id="gigswift_pipeline",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC),  # fire once immediately, then on the interval
    )
    return scheduler


async def run_forever() -> None:
    """Start the interval scheduler and run until interrupted."""
    settings = get_settings()
    scheduler = build_scheduler(settings)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # signal handlers are unsupported on some platforms (e.g. Windows)
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    scheduler.start()
    logger.info(
        "Scheduler started; running pipeline every %d minute(s)",
        settings.SCHEDULER_INTERVAL_MINUTES,
    )
    try:
        await stop.wait()
    finally:
        logger.info("Scheduler shutting down")
        scheduler.shutdown(wait=False)
        await dispose_engine()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="GigSwift pipeline scheduler")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run the pipeline once and exit (GitHub Actions backup runner).",
    )
    args = parser.parse_args(argv)

    configure_logging()
    if args.once:
        asyncio.run(run_once())
    else:
        asyncio.run(run_forever())


if __name__ == "__main__":
    main()
