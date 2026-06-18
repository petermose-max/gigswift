"""Post schemas: DB write/read models for ``posts``."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PostCreateSchema(BaseModel):
    """Fields persisted when a new ``posts`` row is created."""

    job_id: UUID
    platform: str
    content: str
    image_path: str | None = None


class PostSchema(PostCreateSchema):
    """Full read model for a ``posts`` row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
