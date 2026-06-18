"""RSS ingestor.

Fetches every URL in ``config.RSS_FEED_URLS`` with feedparser, normalizes each
entry to :class:`RawJobSchema`, and best-effort extracts a pay range from the
title/summary text. Each feed is fetched concurrently and isolated: a single bad
feed is logged and skipped without affecting the others.
"""

import asyncio
import html
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import feedparser

from app.core.config import Settings
from app.core.logging import get_logger
from app.ingest.base import BaseIngestor
from app.schemas.job import RawJobSchema

logger = get_logger(__name__)

_USER_AGENT = "GigSwiftAgent/1.0 (+https://github.com/gigswift)"

# A monetary number: optionally comma-grouped (45,000) or plain (45 / 45.50).
_NUM = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"

# $45-$85, $45-85, $45k-85k, $45 to $85 (max '$' optional, 'k' suffix per side).
_PAY_RANGE_RE = re.compile(
    rf"\$\s*(?P<min>{_NUM})\s*(?P<min_k>[kK])?"
    r"\s*(?:-|–|—|to)\s*"
    rf"\$?\s*(?P<max>{_NUM})\s*(?P<max_k>[kK])?"
)
# A single $ amount: $45, $45.50, $45,000, $45k.
_PAY_SINGLE_RE = re.compile(rf"\$\s*(?P<val>{_NUM})\s*(?P<val_k>[kK])?")
# Currency-word forms: "USD 45" and "45 USD".
_PAY_USD_PREFIX_RE = re.compile(rf"\bUSD\s*(?P<val>{_NUM})\s*(?P<val_k>[kK])?", re.IGNORECASE)
_PAY_USD_SUFFIX_RE = re.compile(rf"(?P<val>{_NUM})\s*(?P<val_k>[kK])?\s*USD\b", re.IGNORECASE)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _to_decimal(num: str, k_flag: str | None) -> Decimal | None:
    """Parse a captured number (stripping commas, applying a 'k' multiplier)."""
    try:
        value = Decimal(num.replace(",", ""))
    except InvalidOperation:
        return None
    if k_flag:
        value *= 1000
    return value


def _detect_currency(text: str) -> str:
    """Detect the currency, defaulting to USD."""
    if "£" in text or re.search(r"\bGBP\b", text, re.IGNORECASE):
        return "GBP"
    if "€" in text or re.search(r"\bEUR\b", text, re.IGNORECASE):
        return "EUR"
    return "USD"


def extract_pay_range(text: str) -> tuple[Decimal | None, Decimal | None, str]:
    """Best-effort extraction of (pay_min, pay_max, currency) from free text.

    Handles ``$45/hr``, ``$45-$85/hr``, ``$45k``, ``$45,000``, ``USD 45`` and
    ``45 USD``. Returns ``(None, None, currency)`` when nothing is found.
    """
    if not text:
        return None, None, "USD"

    currency = _detect_currency(text)

    match = _PAY_RANGE_RE.search(text)
    if match:
        low = _to_decimal(match.group("min"), match.group("min_k"))
        high = _to_decimal(match.group("max"), match.group("max_k"))
        if low is not None and high is not None and low > high:
            low, high = high, low
        return low, high, currency

    match = _PAY_SINGLE_RE.search(text)
    if match:
        return _to_decimal(match.group("val"), match.group("val_k")), None, currency

    for pattern in (_PAY_USD_PREFIX_RE, _PAY_USD_SUFFIX_RE):
        match = pattern.search(text)
        if match:
            return _to_decimal(match.group("val"), match.group("val_k")), None, currency

    return None, None, currency


def _clean_text(text: str) -> str:
    """Strip HTML tags, unescape entities, and collapse whitespace."""
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", text or ""))).strip()


def _feed_slug(feed_url: str) -> str:
    """Derive a short source slug from a feed URL, e.g. weworkremotely."""
    host = (urlparse(feed_url).hostname or feed_url).removeprefix("www.")
    parts = host.split(".")
    return parts[-2] if len(parts) >= 2 else host


class RSSIngestor(BaseIngestor):
    """Ingests listings from every configured RSS feed."""

    source_name = "rss"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def fetch(self) -> list[RawJobSchema]:
        feed_urls = self.settings.rss_feed_urls
        if not feed_urls:
            return []

        results = await asyncio.gather(
            *(self._fetch_one(url) for url in feed_urls),
            return_exceptions=True,
        )

        jobs: list[RawJobSchema] = []
        for feed_url, result in zip(feed_urls, results, strict=True):
            if isinstance(result, BaseException):
                logger.error("RSS feed failed: %s (%s)", feed_url, result)
                continue
            jobs.extend(result)
        return jobs

    async def _fetch_one(self, feed_url: str) -> list[RawJobSchema]:
        parsed = await asyncio.to_thread(feedparser.parse, feed_url, agent=_USER_AGENT)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            reason = getattr(parsed, "bozo_exception", "unknown error")
            raise RuntimeError(f"unparseable feed: {reason}")

        source = f"rss:{_feed_slug(feed_url)}"[:50]
        jobs: list[RawJobSchema] = []
        for entry in parsed.entries:
            try:
                job = self._entry_to_job(entry, source)
            except Exception:
                logger.debug("Skipping malformed RSS entry from %s", source, exc_info=True)
                continue
            if job is not None:
                jobs.append(job)
        return jobs

    def _entry_to_job(self, entry: feedparser.FeedParserDict, source: str) -> RawJobSchema | None:
        title = (entry.get("title") or "").strip()
        if not title:
            return None

        raw_summary = entry.get("summary") or entry.get("description") or ""
        description = _clean_text(raw_summary)
        apply_url = (entry.get("link") or "").strip()

        # TODO: pay_min/pay_max may be annual figures (k-suffix). Normalise in
        # pipeline/scorer.py before comparing against MIN_PAY_HOURLY.
        pay_min, pay_max, currency = extract_pay_range(f"{title}\n{description}")

        return RawJobSchema(
            source=source,
            title=title,
            description=description,
            apply_url=apply_url,
            pay_min=pay_min,
            pay_max=pay_max,
            pay_currency=currency,
        )
