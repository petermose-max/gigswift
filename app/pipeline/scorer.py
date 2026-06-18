"""Numeric scoring of listings, per design section 7.3.

Each factor adds to or subtracts from a running float; the final score is clamped
to the 0.0–1.0 range. The configured ``MIN_SCORE_THRESHOLD`` decides what posts.
"""

from decimal import Decimal
from urllib.parse import urlparse

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.pipeline.filter import SCAM_FLAGS
from app.schemas.job import RawJobSchema

logger = get_logger(__name__)

ENTRY_LEVEL_KEYWORDS: list[str] = [
    "no experience",
    "no degree",
    "entry level",
    "entry-level",
    "no qualifications",
    "training provided",
    "will train",
]

# Signals that the role is location-independent.
REMOTE_KEYWORDS: list[str] = ["remote", "worldwide", "work from anywhere"]

# Link shorteners / redirect farms that obscure the real apply destination.
REDIRECT_FARMS: frozenset[str] = frozenset(
    {
        "bit.ly",
        "tinyurl.com",
        "t.co",
        "goo.gl",
        "ow.ly",
        "rb.gy",
        "rebrand.ly",
        "cutt.ly",
        "is.gd",
        "buff.ly",
        "shorturl.at",
    }
)

# 2080 = 52 weeks × 40 hours: the number of working hours in a full-time year.
# Used to convert apparent annual figures back to an hourly rate.
_ANNUAL_HOURS = Decimal(2080)
_ANNUAL_THRESHOLD = Decimal(1000)


def _normalise_hourly(value: Decimal | None) -> Decimal | None:
    """Convert an apparent annual pay figure into an hourly rate.

    Heuristic: any value above $1000 is assumed to be annual (or a k-suffixed
    salary captured by the ingestors), so it is divided by 2080
    (52 weeks × 40 hours) to approximate an hourly rate. Smaller values are
    treated as already hourly and returned unchanged.
    """
    if value is None:
        return None
    if value > _ANNUAL_THRESHOLD:
        return value / _ANNUAL_HOURS
    return value


def _is_all_caps(title: str) -> bool:
    """True for shouty titles: at least 4 letters, all uppercase."""
    letters = [char for char in title if char.isalpha()]
    return len(letters) >= 4 and all(char.isupper() for char in letters)


def _has_valid_apply_url(apply_url: str) -> bool:
    """True if ``apply_url`` is present and not a known redirect farm."""
    if not apply_url:
        return False
    host = (urlparse(apply_url).hostname or "").lower().removeprefix("www.")
    return bool(host) and host not in REDIRECT_FARMS


def score_job(job: RawJobSchema, settings: Settings | None = None) -> float:
    """Compute the pipeline score (0.0–1.0) for a single job, per section 7.3."""
    settings = settings or get_settings()

    # Normalise pay to an hourly rate before comparing against MIN_PAY_HOURLY.
    pay_min = _normalise_hourly(job.pay_min)
    pay_max = _normalise_hourly(job.pay_max)
    min_pay_hourly = Decimal(str(settings.MIN_PAY_HOURLY))

    title_lc = job.title.lower()
    description_lc = job.description.lower()

    score = 0.0
    if pay_min is not None and pay_min >= min_pay_hourly:
        score += 0.4  # pay_min meets the hourly floor
    if pay_max is not None:
        score += 0.2  # a pay range is known
    if any(keyword in title_lc for keyword in ENTRY_LEVEL_KEYWORDS):
        score += 0.2  # entry-level / low-barrier role
    if any(keyword in description_lc for keyword in REMOTE_KEYWORDS):
        score += 0.1  # remote / worldwide / work from anywhere
    if _has_valid_apply_url(job.apply_url):
        score += 0.1  # usable apply link, not a redirect farm
    if any(flag in description_lc for flag in SCAM_FLAGS):
        score -= 0.5  # scam phrases present
    if _is_all_caps(job.title):
        score -= 0.3  # shouty all-caps title
    if job.pay_min is None and job.pay_max is None:
        score -= 0.2  # no pay information at all

    clamped = max(0.0, min(1.0, score))
    return round(clamped, 4)


def score_jobs(jobs: list[RawJobSchema], settings: Settings | None = None) -> list[RawJobSchema]:
    """Return copies of each job with its computed ``score`` attached."""
    settings = settings or get_settings()
    return [job.model_copy(update={"score": score_job(job, settings)}) for job in jobs]
