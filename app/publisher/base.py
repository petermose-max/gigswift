"""Abstract publisher with retry + logging, per design section 7.5.

``publish_with_retry`` runs the section 7.5 loop: try :meth:`publish`, log the
attempt to ``publish_log``, and back off between retries. On success it stamps
``jobs.posted_at`` (first success only). It always returns a :class:`PublishResult`
rather than raising, so the scheduler can tally results without try/except.
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Job, PublishLog
from app.schemas.post import PostSchema

logger = get_logger(__name__)


@dataclass
class PublishResult:
    """Outcome of a publish attempt."""

    success: bool
    platform_post_id: str | None = None
    error: str | None = None


class BasePublisher(ABC):
    """Base publisher carrying the shared retry, logging, and bookkeeping logic."""

    platform: str
    max_retries: int = 3
    backoff_base: float = 2.0  # seconds

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @abstractmethod
    async def publish(self, post: PostSchema) -> PublishResult:
        """Publish to the platform: return a successful result, or raise on error."""
        ...

    async def publish_with_retry(self, post: PostSchema) -> PublishResult:
        """Publish with retry/backoff, logging every attempt to ``publish_log``."""
        last_error = "unknown error"
        for attempt in range(1, self.max_retries + 1):
            try:
                result = await self.publish(post)
                await self._log(post, attempt, status="success")
                await self._mark_job_posted(post)
                return result
            except Exception as exc:
                last_error = str(exc) or exc.__class__.__name__
                await self._log(post, attempt, status="failed", error=last_error)
                logger.warning(
                    "Publish to %s failed (attempt %d/%d): %s",
                    self.platform,
                    attempt,
                    self.max_retries,
                    last_error,
                )
                if attempt == self.max_retries:
                    break
                await asyncio.sleep(self._backoff_seconds(attempt, exc))

        return PublishResult(success=False, platform_post_id=None, error=last_error)

    def _backoff_seconds(self, attempt: int, exc: Exception) -> float:
        """Seconds to wait before the next retry (overridable per platform)."""
        return self.backoff_base**attempt

    async def _log(
        self, post: PostSchema, attempt: int, status: str, error: str | None = None
    ) -> None:
        """Record one publish attempt in the ``publish_log`` table."""
        self.session.add(
            PublishLog(
                post_id=post.id,
                status=status,
                attempt_number=attempt,
                error_message=error,
            )
        )
        await self.session.flush()

    async def _mark_job_posted(self, post: PostSchema) -> None:
        """Stamp ``jobs.posted_at`` on the first successful publish for the job."""
        await self.session.execute(
            update(Job)
            .where(Job.id == post.job_id, Job.posted_at.is_(None))
            .values(posted_at=func.now())
        )
