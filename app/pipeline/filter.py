"""Scam filtering: drops listings that match known scam phrases."""

from app.core.logging import get_logger
from app.schemas.job import RawJobSchema

logger = get_logger(__name__)

# Phrases that strongly indicate an advance-fee / recruitment scam.
SCAM_FLAGS: list[str] = [
    "wire transfer",
    "pay for training",
    "upfront fee",
    "deposit required",
    "send money",
    "money order",
    "western union",
    "gift card",
    "pyramid",
    "mlm",
    "downline",
]


def is_scam(job: RawJobSchema) -> bool:
    """True if the job's title or description contains any scam phrase."""
    text = f"{job.title}\n{job.description}".lower()
    return any(flag in text for flag in SCAM_FLAGS)


def filter_scams(jobs: list[RawJobSchema]) -> list[RawJobSchema]:
    """Return only the jobs that are not flagged as scams."""
    clean = [job for job in jobs if not is_scam(job)]
    removed = len(jobs) - len(clean)
    if removed:
        logger.info("Filter: removed %d scam listing(s)", removed)
    return clean
