"""Run-log schemas: DB write/read models for ``run_log``."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field


class RunLogCreateSchema(BaseModel):
    """Fields persisted for a scheduler run (counts updated as it progresses).

    ``status`` is intentionally absent here — it is derived from the timestamps,
    not stored.
    """

    trigger: str
    jobs_ingested: int = 0
    jobs_new: int = 0
    jobs_posted: int = 0
    errors: int = 0
    finished_at: datetime | None = None


class RunLogSchema(RunLogCreateSchema):
    """Full read model for a ``run_log`` row, with a derived ``status``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    started_at: datetime

    @computed_field
    @property
    def status(self) -> str:
        """Derived run state: completed, running, or interrupted.

        A run with no ``finished_at`` is "running" only if it started within the
        last 5 minutes; older unfinished runs were killed mid-run ("interrupted").
        """
        if self.finished_at is None:
            recently_started = self.started_at > (datetime.now(UTC) - timedelta(minutes=5))
            return "running" if recently_started else "interrupted"
        return "completed"
