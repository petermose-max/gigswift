"""Telegram ingestor.

Uses a Telethon user client to read the last 50 messages from each channel in
``config.TELEGRAM_CHANNELS``, keeps messages that look like job postings, and
normalizes them to :class:`RawJobSchema`. Each channel is isolated: a failure on
one channel is logged and skipped.

The Telethon session is read from ``TELETHON_SESSION_PATH`` (default
``/app/data/telethon.session``, a Docker volume). If the session is not authorized
the ingestor logs a warning and returns nothing rather than blocking on a prompt.
"""

import os
import re

from telethon import TelegramClient

from app.core.config import Settings
from app.core.logging import get_logger
from app.ingest.base import BaseIngestor
from app.ingest.rss import extract_pay_range
from app.schemas.job import RawJobSchema

logger = get_logger(__name__)

_DEFAULT_SESSION_PATH = "/app/data/telethon.session"
_MESSAGE_LIMIT = 50

# A message is considered a job posting if it mentions money or any of these.
_JOB_KEYWORDS = ("hire", "salary", "remote", "apply", "pay", "opportunity")

_NUMERIC_CHANNEL_RE = re.compile(r"-?\d+")
_USERNAME_RE = re.compile(r"[A-Za-z0-9_]{4,}")


def _looks_like_job(text: str) -> bool:
    """True if the message text contains job-like signals."""
    lowered = text.lower()
    return "$" in text or any(keyword in lowered for keyword in _JOB_KEYWORDS)


def _first_line(text: str, limit: int = 120) -> str:
    """Use the first non-empty line as a title, truncated to ``limit`` chars."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:limit]
    return text.strip()[:limit]


def _post_link(handle: str, message_id: int | None) -> str:
    """Build a public t.me permalink, or '' if the channel has no username."""
    username = handle.lstrip("@")
    if message_id and _USERNAME_RE.fullmatch(username):
        return f"https://t.me/{username}/{message_id}"
    return ""


class TelegramIngestor(BaseIngestor):
    """Ingests job-like messages from configured public Telegram channels."""

    source_name = "telegram"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._session_path = os.getenv("TELETHON_SESSION_PATH", _DEFAULT_SESSION_PATH)

    async def fetch(self) -> list[RawJobSchema]:
        channels = self.settings.telegram_channels
        if not channels:
            return []

        client = self._build_client()
        jobs: list[RawJobSchema] = []
        try:
            await client.connect()
            if not await client.is_user_authorized():
                logger.warning(
                    "Telethon session at %s is not authorized; skipping Telegram ingestion",
                    self._session_path,
                )
                return []

            for channel in channels:
                try:
                    jobs.extend(await self._read_channel(client, channel))
                except Exception:
                    logger.exception("Failed reading Telegram channel %s", channel)
        finally:
            try:
                await client.disconnect()
            except Exception:
                logger.debug("Error disconnecting Telethon client", exc_info=True)

        return jobs

    def _build_client(self) -> TelegramClient:
        # Telethon appends '.session'; pass the base name so the file lands at the
        # configured path exactly (default /app/data/telethon.session).
        session_name = self._session_path.removesuffix(".session")
        parent = os.path.dirname(session_name)
        if parent:
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError:
                logger.debug("Could not create Telethon session dir %s", parent, exc_info=True)
        return TelegramClient(
            session_name,
            self.settings.TELEGRAM_API_ID,
            self.settings.TELEGRAM_API_HASH,
        )

    async def _read_channel(self, client: TelegramClient, channel: str) -> list[RawJobSchema]:
        handle = channel.strip()
        entity: str | int = handle
        if _NUMERIC_CHANNEL_RE.fullmatch(handle.lstrip("@")):
            entity = int(handle.lstrip("@"))

        source = f"telegram:{handle.lstrip('@')}"[:50]
        jobs: list[RawJobSchema] = []
        async for message in client.iter_messages(entity, limit=_MESSAGE_LIMIT):
            text = (getattr(message, "message", None) or "").strip()
            if not text or not _looks_like_job(text):
                continue
            try:
                jobs.append(self._message_to_job(message, handle, source, text))
            except Exception:
                logger.debug(
                    "Skipping unparseable Telegram message %s in %s",
                    getattr(message, "id", "?"),
                    handle,
                    exc_info=True,
                )
        return jobs

    def _message_to_job(self, message: object, handle: str, source: str, text: str) -> RawJobSchema:
        # TODO: pay_min/pay_max may be annual figures (k-suffix). Normalise in
        # pipeline/scorer.py before comparing against MIN_PAY_HOURLY.
        pay_min, pay_max, currency = extract_pay_range(text)
        return RawJobSchema(
            source=source,
            title=_first_line(text),
            description=text,
            apply_url=_post_link(handle, getattr(message, "id", None)),
            pay_min=pay_min,
            pay_max=pay_max,
            pay_currency=currency,
        )
