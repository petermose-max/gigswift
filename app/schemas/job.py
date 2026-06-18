"""Job schemas: the raw ingestor DTO plus DB write/read models for ``jobs``."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RawJobSchema(BaseModel):
    """A normalized raw listing as it flows through the pipeline.

    Ingestors populate the source fields; the pipeline scorer fills in ``score``
    (``None`` until scored). ``content_hash`` and ``is_scam`` are derived during
    persistence.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    source: str
    title: str
    description: str = ""
    apply_url: str = ""
    pay_min: Decimal | None = None
    pay_max: Decimal | None = None
    pay_currency: str = "USD"
    score: float | None = None


class JobCreateSchema(BaseModel):
    """Fields persisted when a new ``jobs`` row is created.

    Optional fields correspond exactly to the model's nullable columns
    (``pay_min``, ``pay_max``, ``score``); every other field is required.
    """

    source: str
    title: str
    description: str
    pay_min: Decimal | None = None
    pay_max: Decimal | None = None
    pay_currency: str
    apply_url: str
    content_hash: str
    score: Decimal | None = None
    is_scam: bool


class JobSchema(BaseModel):
    """Full read model for a ``jobs`` row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: str
    title: str
    description: str
    pay_min: Decimal | None
    pay_max: Decimal | None
    pay_currency: str
    apply_url: str
    content_hash: str
    score: Decimal | None
    is_scam: bool
    first_seen_at: datetime
    posted_at: datetime | None
