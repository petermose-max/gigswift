"""``run_log`` table — one row per scheduler run."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RunLog(Base):
    __tablename__ = "run_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    jobs_ingested: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    jobs_new: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    jobs_posted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    errors: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
