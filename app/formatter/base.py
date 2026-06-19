"""Abstract formatter interface and shared formatting helpers.

This module deliberately does not import ``image`` (the card generator imports
helpers from here, so importing it back would create a cycle).
"""

import html
import re
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
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
# Leading numbering: "1." "2)" "(1)" "(a)" "a." etc.
_LEADING_NUMBER_RE = re.compile(r"^\(?(?:\d{1,3}|[a-zA-Z])[.)]\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_URL_LINE_RE = re.compile(r"^(?:https?://|www\.)\S+$|^\S+\.\S{2,}/\S*$", re.IGNORECASE)

_REQUIREMENT_HEADERS = (
    "requirements",
    "key requirements",
    "minimum qualifications",
    "basic qualifications",
    "qualifications",
    "required skills",
    "what you'll need",
    "what you need",
    "you'll need",
    "what we're looking for",
    "we're looking for",
    "must have",
    "nice to have",
    "you have",
    "you bring",
    "what you bring",
    "you are",
    "ideal candidate",
    "about you",
    "who you are",
)
_TASK_HEADERS = (
    "what you'll do",
    "what you will do",
    "responsibilities",
    "your responsibilities",
    "about the role",
    "in this role",
    "the role",
    "you will",
    "you will be",
    "you'll be",
    "your role",
    "duties",
    "day to day",
    "day-to-day",
)

# Noise sections that precede the real job content on some boards (WWR, MyJobMag).
_NON_NOISE_ABOUT = {"the role", "the job", "this role", "the position", "you", "the team"}
_NEXT_LABEL_RE = (
    r"(?:url|website|about|requirements?|responsibilities|qualifications|what\s+you|who\s+you)"
)
_HQ_URL_RE = re.compile(
    rf"^\s*(?:headquarters|hq|url|website)\s*:[^\n]*?(?=\s+{_NEXT_LABEL_RE}\b|\n|$)",
    re.IGNORECASE,
)
_ABOUT_US_RE = re.compile(r"^\s*about\s+(?:us|the\s+company)\b\s*", re.IGNORECASE)
_ABOUT_X_RE = re.compile(r"^\s*about\s+([\w&.\-' ]{1,30}):\s*", re.IGNORECASE)

# Words that hint a sentence/line states a requirement (fallback extraction).
_REQUIREMENT_HINT_WORDS = (
    "experience",
    "degree",
    "skills",
    "knowledge",
    "ability",
    "proficiency",
    "familiarity",
    "understanding",
    "qualification",
    "expertise",
    "fluency",
    "fluent",
)


def _strip_html(text: str) -> str:
    """Convert block-level tags to newlines, drop remaining tags, unescape entities."""
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    return html.unescape(text)


def _is_about_noise(text_lower: str) -> bool:
    """True if a line/sentence is an 'About Us'/'About <Company>:' noise prefix."""
    if text_lower.startswith("about us") or text_lower.startswith("about the company"):
        return True
    match = _ABOUT_X_RE.match(text_lower)
    return bool(match) and match.group(1).strip() not in _NON_NOISE_ABOUT


def _strip_noise_prefix(text: str) -> str:
    """Iteratively remove leading Headquarters/URL/About-Us noise from a description."""
    changed = True
    while changed:
        changed = False
        for pattern in (_HQ_URL_RE, _ABOUT_US_RE):
            match = pattern.match(text)
            if match:
                text = text[match.end() :].lstrip()
                changed = True
                break
        if changed:
            continue
        match = _ABOUT_X_RE.match(text)
        if match and match.group(1).strip().lower() not in _NON_NOISE_ABOUT:
            text = text[match.end() :].lstrip()
            changed = True
    return text


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


def _clean_requirement(item: str) -> str | None:
    """Clean a candidate requirement; drop too-short/too-long/URL items."""
    item = _clean_line(item)
    if not item or item.lower().startswith("http") or _URL_LINE_RE.match(item):
        return None
    if len(item) < 8:  # too short to be meaningful
        return None
    if len(item) > 60:  # trim at last word under 55 chars
        item = _truncate_words(item, 55)
    return item or None


def _clean_task(item: str) -> str | None:
    """Clean a candidate task line."""
    item = _clean_line(item)
    return _truncate_words(item, 120) if len(item) >= 5 else None


def _is_header(line_lower: str, headers: tuple[str, ...]) -> bool:
    """True if the line starts with a section header (optionally followed by ':')."""
    line_lower = line_lower.strip()
    for header in headers:
        if line_lower.startswith(header):
            rest = line_lower[len(header) :].lstrip()
            if rest == "":
                return len(line_lower) <= 60  # bare header line, keep it short
            if rest.startswith(":"):
                return True  # "Header: ..." with inline content, any length
    return False


def _extract_items(
    lines: list[str],
    headers: tuple[str, ...],
    *,
    max_items: int,
    clean: Callable[[str], str | None],
) -> list[str]:
    """Collect cleaned phrases under a matching section header (inline or bulleted)."""
    items: list[str] = []
    capturing = False
    for line in lines:
        lower = line.lower()
        if _is_header(lower, _REQUIREMENT_HEADERS) or _is_header(lower, _TASK_HEADERS):
            capturing = _is_header(lower, headers)
            if capturing and ":" in line:
                # "Requirements: laptop, internet, good English" — split the tail.
                for piece in re.split(r"[,;]|\s[-–]\s", line.split(":", 1)[1]):
                    item = clean(piece)
                    if item:
                        items.append(item)
                        if len(items) >= max_items:
                            return items[:max_items]
            continue
        if capturing:
            item = clean(line)
            if item:
                items.append(item)
                if len(items) >= max_items:
                    break
    return items[:max_items]


def _fallback_requirements(cleaned: str, *, max_items: int = 3) -> list[str]:
    """Pull requirement-like sentences from the first 400 chars when no section exists."""
    items: list[str] = []
    for chunk in re.split(r"[.\n]", cleaned[:400]):
        if any(word in chunk.lower() for word in _REQUIREMENT_HINT_WORDS):
            req = _clean_requirement(chunk)
            if req:
                items.append(req)
                if len(items) >= max_items:
                    break
    return items


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


def _first_substantive_sentence(text: str, *, min_len: int = 30, max_len: int = 160) -> str | None:
    """First meaningful sentence: over ``min_len`` chars and not a noise prefix."""
    flat = _WS_RE.sub(" ", text.replace("\n", " ")).strip()
    fallback: str | None = None
    for sentence in _SENTENCE_SPLIT_RE.split(flat):
        candidate = _strip_lead_header(sentence.strip())
        lower = candidate.lower()
        if not candidate or lower.startswith(("headquarters", "url:")) or _is_about_noise(lower):
            continue
        if fallback is None:
            fallback = candidate
        if len(candidate) >= min_len:
            return _truncate_words(candidate, max_len)
    return _truncate_words(fallback, max_len) if fallback else None


def extract_smart_summary(description: str) -> dict[str, object]:
    """Heuristically parse a job description into summary + requirements.

    Returns ``what_you_do`` (str | None), ``requirements`` (list[str], up to 4 short
    phrases) and ``summary_line`` (str | None). HTML is stripped and common noise
    prefixes (Headquarters/URL/About Us) are removed before parsing. If no section
    yields requirements, requirement-like sentences are used as a fallback.
    """
    cleaned = _strip_noise_prefix(_strip_html(description or ""))
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]

    requirements = _extract_items(
        lines, _REQUIREMENT_HEADERS, max_items=4, clean=_clean_requirement
    )
    tasks = _extract_items(lines, _TASK_HEADERS, max_items=2, clean=_clean_task)
    if not requirements:
        requirements = _fallback_requirements(cleaned, max_items=3)

    what_you_do = _truncate_words("; ".join(tasks), 120) if tasks else None
    summary_line = _first_substantive_sentence(cleaned, min_len=30, max_len=160)

    return {
        "what_you_do": what_you_do,
        "requirements": requirements,
        "summary_line": summary_line,
    }


def clean_description_preview(description: str, *, max_len: int = 100) -> str | None:
    """A de-noised one-line preview of a description for cards (first sentence)."""
    cleaned = _strip_noise_prefix(_strip_html(description or ""))
    preview = _first_substantive_sentence(cleaned, min_len=20, max_len=max_len)
    if preview:
        return preview
    flat = _WS_RE.sub(" ", cleaned.replace("\n", " ")).strip()
    return _truncate_words(flat, max_len) or None


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
