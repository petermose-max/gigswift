"""Deduplication against the ``jobs`` table by content hash."""

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Job
from app.schemas.job import RawJobSchema

logger = get_logger(__name__)


def compute_content_hash(title: str, apply_url: str) -> str:
    """Return SHA256(title + apply_url); the dedup key stored as ``Job.content_hash``."""
    return hashlib.sha256(f"{title}{apply_url}".encode()).hexdigest()


async def filter_new_jobs(jobs: list[RawJobSchema], session: AsyncSession) -> list[RawJobSchema]:
    """Return only the jobs whose content hash is not already in the database.

    Duplicates within the incoming batch are also collapsed (first occurrence wins),
    so a single run never yields the same listing twice.
    """
    if not jobs:
        return []

    hashes = [compute_content_hash(job.title, job.apply_url) for job in jobs]

    result = await session.execute(
        select(Job.content_hash).where(Job.content_hash.in_(set(hashes)))
    )
    existing: set[str] = set(result.scalars().all())

    new_jobs: list[RawJobSchema] = []
    seen_in_batch: set[str] = set()
    for job, content_hash in zip(jobs, hashes, strict=True):
        if content_hash in existing or content_hash in seen_in_batch:
            continue
        seen_in_batch.add(content_hash)
        new_jobs.append(job)

    logger.info("Dedup: %d incoming -> %d new", len(jobs), len(new_jobs))
    return new_jobs
