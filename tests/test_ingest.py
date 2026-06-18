"""Tests for the RSS and Telegram ingestors (external sources mocked)."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import get_settings
from app.ingest.rss import RSSIngestor
from app.ingest.telegram import TelegramIngestor


@pytest.mark.asyncio
async def test_rss_parses_entries_to_raw_jobs(monkeypatch) -> None:
    def fake_parse(url: str, agent: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            bozo=0,
            entries=[
                {
                    "title": "Remote Python Dev ($50/hr)",
                    "link": "https://jobs.example.com/1",
                    "summary": "Great <b>remote</b> role paying $50/hr.",
                },
                {"title": "", "link": "https://jobs.example.com/2", "summary": "skipped"},
            ],
        )

    monkeypatch.setattr("app.ingest.rss.feedparser.parse", fake_parse)

    jobs = await RSSIngestor(get_settings()).fetch()

    assert len(jobs) == 1  # the title-less entry is skipped
    job = jobs[0]
    assert job.title.startswith("Remote Python Dev")
    assert job.apply_url == "https://jobs.example.com/1"
    assert job.pay_min == Decimal("50")
    assert "<b>" not in job.description and "remote" in job.description.lower()
    assert job.source.startswith("rss:")


@pytest.mark.asyncio
async def test_telegram_parses_job_messages() -> None:
    ingestor = TelegramIngestor(get_settings())

    class Msg:
        def __init__(self, mid: int, text: str) -> None:
            self.id = mid
            self.message = text

    def iter_messages(entity, limit):
        async def gen():
            yield Msg(7, "We are hiring a remote developer, pay $40/hr")
            yield Msg(8, "random cat photo with no job signal")  # filtered out

        return gen()

    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.is_user_authorized = AsyncMock(return_value=True)
    client.iter_messages = iter_messages

    with patch.object(ingestor, "_build_client", return_value=client):
        jobs = await ingestor.fetch()

    assert len(jobs) == 1  # only the job-like message survives keyword filtering
    job = jobs[0]
    assert job.pay_min == Decimal("40")
    assert job.source.startswith("telegram:")
    assert job.apply_url.startswith("https://t.me/")
    client.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_telegram_unauthorized_returns_empty() -> None:
    ingestor = TelegramIngestor(get_settings())
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.is_user_authorized = AsyncMock(return_value=False)

    with patch.object(ingestor, "_build_client", return_value=client):
        assert await ingestor.fetch() == []
