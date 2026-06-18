"""Publish-log schema: read model for ``publish_log`` (used by the admin API)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PublishLogSchema(BaseModel):
    """Full read model for a ``publish_log`` row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    post_id: UUID
    status: str
    error_message: str | None
    attempt_number: int
    attempted_at: datetime
