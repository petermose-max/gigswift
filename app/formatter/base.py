"""Abstract formatter interface and shared formatting helpers.

This module deliberately does not import ``image`` (the card generator imports
helpers from here, so importing it back would create a cycle).
"""

import uuid
from abc import ABC, abstractmethod
from decimal import Decimal

from app.pipeline.dedup import compute_content_hash
from app.pipeline.scorer import ENTRY_LEVEL_KEYWORDS, REMOTE_KEYWORDS
from app.schemas.job import RawJobSchema
from app.schemas.post import PostCreateSchema

_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}

# Mirror the scorer's heuristic so displayed pay matches how it was scored:
# values over $1000 are treated as annual and divided by 2080 (52 weeks × 40 hours).
_ANNUAL_THRESHOLD = Decimal(1000)
_ANNUAL_HOURS = Decimal(2080)

# Stable namespace for deriving placeholder job ids (see ``placeholder_job_id``).
_JOB_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "gigswift.jobs")


def _currency_symbol(currency: str) -> str:
    """Map a currency code to a symbol, falling back to the code itself."""
    return _CURRENCY_SYMBOLS.get(currency.upper(), f"{currency.upper()} ")


def _to_hourly(value: Decimal) -> Decimal:
    """Convert an apparent annual figure (> $1000) to an hourly rate; else as-is."""
    return value / _ANNUAL_HOURS if value > _ANNUAL_THRESHOLD else value


def format_pay_range(job: RawJobSchema, *, unit: str = "hr") -> str | None:
    """Render pay as e.g. ``$45–$85/hr``, or ``None`` when no pay is known."""
    if job.pay_min is None and job.pay_max is None:
        return None
    symbol = _currency_symbol(job.pay_currency)
    low = _to_hourly(job.pay_min) if job.pay_min is not None else None
    high = _to_hourly(job.pay_max) if job.pay_max is not None else None
    if low is not None and high is not None:
        return f"{symbol}{low:.0f}–{symbol}{high:.0f}/{unit}"
    value = low if low is not None else high
    return f"{symbol}{value:.0f}/{unit}"


def is_entry_level(job: RawJobSchema) -> bool:
    """True if the job's title or description signals entry-level work."""
    text = f"{job.title}\n{job.description}".lower()
    return any(keyword in text for keyword in ENTRY_LEVEL_KEYWORDS)


def mentions_remote(job: RawJobSchema) -> bool:
    """True if the job's title or description mentions remote/worldwide work."""
    text = f"{job.title}\n{job.description}".lower()
    return any(keyword in text for keyword in REMOTE_KEYWORDS)


def placeholder_job_id(job: RawJobSchema) -> uuid.UUID:
    """Derive a deterministic placeholder ``job_id`` from the job's content hash.

    ``RawJobSchema`` has no database id at format time, so we mint a stable id
    (same for a given listing across platforms and runs). The scheduler MUST
    replace this with the real ``Job.id`` after persistence before saving posts.
    """
    return uuid.uuid5(_JOB_ID_NAMESPACE, compute_content_hash(job.title, job.apply_url))


class BaseFormatter(ABC):
    """Common interface: render a job into a platform-specific post."""

    platform: str

    @abstractmethod
    def format(self, job: RawJobSchema) -> PostCreateSchema:
        """Render ``job`` into a :class:`PostCreateSchema` for this platform."""
        ...
