"""Abstract formatter interface and shared formatting helpers.

This module deliberately does not import ``image`` (the card generator imports
helpers from here, so importing it back would create a cycle).
"""

import html
import re
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


def format_pay_amounts(job: RawJobSchema) -> str | None:
    """Pay figures with a hyphen-minus and no unit, e.g. ``$45-$85``; None if unknown.

    Unlike :func:`format_pay_range`, this never uses an en dash (cards/posts render
    a plain hyphen) and omits the ``/hr`` suffix so callers can append their own.
    """
    if job.pay_min is None and job.pay_max is None:
        return None
    symbol = _currency_symbol(job.pay_currency)
    low = _to_hourly(job.pay_min) if job.pay_min is not None else None
    high = _to_hourly(job.pay_max) if job.pay_max is not None else None
    if low is not None and high is not None:
        return f"{symbol}{low:.0f}-{symbol}{high:.0f}"
    value = low if low is not None else high
    return f"{symbol}{value:.0f}"


def split_company_title(title: str) -> tuple[str | None, str]:
    """Split a ``"Company: Role"`` title into ``(company, role)``.

    Falls back to ``(None, title)`` when there is no colon, or when the part before
    the first colon is implausibly long to be a company name.
    """
    if ":" in title:
        company, _, role = title.partition(":")
        company, role = company.strip(), role.strip()
        if company and role and len(company) <= 40:
            return company, role
    return None, title.strip()


# --------------------------------------------------------------------------- #
# Intelligent summarisation of free-text job descriptions
# --------------------------------------------------------------------------- #
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_TAG_RE = re.compile(r"</?(?:li|ul|ol|p|div|br|tr|h[1-6])[^>]*>", re.IGNORECASE)
_WS_RE = re.compile(r"[ \t]+")
_LEADING_BULLET_RE = re.compile(r"^[\s·•*\-–—‣◦>]+")
_LEADING_NUMBER_RE = re.compile(r"^\d+[.)]\s*")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

_REQUIREMENT_HEADERS = (
    "requirements",
    "key requirements",
    "what you'll need",
    "what you need",
    "qualifications",
    "you have",
    "you'll need",
    "must have",
)
_TASK_HEADERS = (
    "what you'll do",
    "what you will do",
    "responsibilities",
    "about the role",
    "you will",
    "your role",
    "duties",
)


def _strip_html(text: str) -> str:
    """Convert block-level tags to newlines, drop remaining tags, unescape entities."""
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    return html.unescape(text)


def _clean_line(line: str) -> str:
    """Normalize whitespace and strip leading bullet glyphs / numbering."""
    line = _WS_RE.sub(" ", line).strip()
    line = _LEADING_BULLET_RE.sub("", line)
    line = _LEADING_NUMBER_RE.sub("", line)
    return line.strip()


def _truncate_words(text: str, limit: int) -> str:
    """Trim ``text`` to at most ``limit`` chars at a word boundary (no ellipsis)."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]).rstrip()


def _is_header(line_lower: str, headers: tuple[str, ...]) -> bool:
    """True if a short line looks like one of the given section headers."""
    return len(line_lower) <= 60 and any(header in line_lower for header in headers)


def _extract_items(
    lines: list[str], headers: tuple[str, ...], *, max_items: int, max_len: int
) -> list[str]:
    """Collect short phrases under a matching section header (inline or bulleted)."""
    items: list[str] = []
    capturing = False
    for line in lines:
        lower = line.lower()
        if _is_header(lower, _REQUIREMENT_HEADERS) or _is_header(lower, _TASK_HEADERS):
            capturing = _is_header(lower, headers)
            if capturing and ":" in line:
                # "Requirements: laptop, internet, good English" — split the tail.
                tail = line.split(":", 1)[1]
                for piece in re.split(r"[,;]|\s-\s", tail):
                    cleaned = _clean_line(piece)
                    if cleaned:
                        items.append(_truncate_words(cleaned, max_len))
                        if len(items) >= max_items:
                            return items[:max_items]
            continue
        if capturing:
            cleaned = _clean_line(line)
            if len(cleaned) > 1:
                items.append(_truncate_words(cleaned, max_len))
                if len(items) >= max_items:
                    break
    return items[:max_items]


def _first_sentences(text: str, *, count: int = 2, max_len: int = 160) -> str | None:
    """Return the first ``count`` sentences of ``text``, trimmed to ``max_len``."""
    flat = _WS_RE.sub(" ", text.replace("\n", " ")).strip()
    if not flat:
        return None
    sentences = _SENTENCE_SPLIT_RE.split(flat)
    summary = " ".join(sentences[:count]).strip()
    return _truncate_words(summary, max_len) or None


def _strip_lead_header(text: str) -> str:
    """Drop a leading "About the role:" / "Responsibilities:" style label."""
    head, sep, tail = text.partition(":")
    if (
        sep
        and tail.strip()
        and _is_header(head.strip().lower(), _TASK_HEADERS + _REQUIREMENT_HEADERS)
    ):
        return tail.strip()
    return text


def extract_smart_summary(description: str) -> dict[str, object]:
    """Heuristically parse a job description.

    Returns a dict with ``what_you_do`` (str | None), ``requirements``
    (list[str], up to 4 short phrases) and ``summary_line`` (str | None). HTML is
    stripped first; bullet glyphs and whitespace are normalized.
    """
    cleaned = _strip_html(description or "")
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]

    requirements = _extract_items(lines, _REQUIREMENT_HEADERS, max_items=4, max_len=40)
    tasks = _extract_items(lines, _TASK_HEADERS, max_items=2, max_len=120)
    what_you_do = _truncate_words("; ".join(tasks), 120) if tasks else None

    # With structured sections, one lead sentence is the cleanest summary; without
    # them, fall back to the first two sentences (per the spec).
    structured = bool(requirements or tasks)
    summary_line = _first_sentences(cleaned, count=1 if structured else 2, max_len=160)
    if summary_line:
        summary_line = _strip_lead_header(summary_line)

    return {
        "what_you_do": what_you_do,
        "requirements": requirements,
        "summary_line": summary_line,
    }


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
