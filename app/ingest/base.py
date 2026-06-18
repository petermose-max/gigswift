"""Abstract ingestor interface shared by every source."""

from abc import ABC, abstractmethod

from app.core.logging import get_logger
from app.schemas.job import RawJobSchema

logger = get_logger(__name__)


class BaseIngestor(ABC):
    """Common interface for all job/gig ingestion sources."""

    source_name: str

    @abstractmethod
    async def fetch(self) -> list[RawJobSchema]:
        """Fetch raw listings from source. Must be idempotent."""
        ...

    async def safe_fetch(self) -> list[RawJobSchema]:
        """Run :meth:`fetch`, logging and swallowing any unexpected error.

        Guarantees that one failing source never aborts the whole pipeline run;
        on failure an empty list is returned so the scheduler can continue with
        the other ingestors.
        """
        try:
            return await self.fetch()
        except Exception:
            logger.exception(
                "Ingestor %r failed", getattr(self, "source_name", type(self).__name__)
            )
            return []
