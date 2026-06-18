"""Ingestor registry.

Builds the list of active ingestors from configuration. An ingestor is only
included when its source is configured (non-empty), so a deployment that uses only
RSS does not spin up a Telegram client and vice versa.
"""

from app.core.config import Settings, get_settings
from app.ingest.base import BaseIngestor
from app.ingest.rss import RSSIngestor
from app.ingest.telegram import TelegramIngestor


def get_all_ingestors(settings: Settings | None = None) -> list[BaseIngestor]:
    """Return all active ingestor instances based on the current configuration."""
    settings = settings or get_settings()

    ingestors: list[BaseIngestor] = []
    if settings.rss_feed_urls:
        ingestors.append(RSSIngestor(settings))
    if settings.telegram_channels:
        ingestors.append(TelegramIngestor(settings))
    return ingestors
