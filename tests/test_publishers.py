"""Tests for the publishers (LinkedIn member posting)."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.publisher.linkedin_publisher import LinkedInPublisher
from app.schemas.post import PostSchema


def _settings(**overrides: object) -> Settings:
    """Hermetic Settings (no .env, no environment leakage)."""
    base: dict[str, object] = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@h:5432/d",
        "X_API_KEY": "k",
        "X_API_SECRET": "s",
        "X_ACCESS_TOKEN": "t",
        "X_ACCESS_SECRET": "ts",
        "TELEGRAM_BOT_TOKEN": "1:a",
        "TELEGRAM_CHANNEL_ID": "@c",
        "TELEGRAM_API_ID": 1,
        "TELEGRAM_API_HASH": "h",
        "RSS_FEED_URLS": "https://example.com/feed.rss",
        "TELEGRAM_CHANNELS": "@example",
        "LINKEDIN_ACCESS_TOKEN": "tok",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _post() -> PostSchema:
    return PostSchema(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        platform="linkedin",
        content="Remote Opportunity: Data Entry",
        image_path=None,
    )


def _mock_client(person_id: str = "abc123", post_id: str = "urn:li:share:99") -> MagicMock:
    userinfo = SimpleNamespace(json=lambda: {"sub": person_id}, raise_for_status=lambda: None)
    ugc = SimpleNamespace(headers={"x-restli-id": post_id}, raise_for_status=lambda: None)
    client = MagicMock()
    client.get = AsyncMock(return_value=userinfo)
    client.post = AsyncMock(return_value=ugc)
    return client


@pytest.mark.asyncio
async def test_linkedin_posts_as_person_urn() -> None:
    client = _mock_client(person_id="abc123", post_id="urn:li:share:99")
    publisher = LinkedInPublisher(session=MagicMock(), settings=_settings(), client=client)

    result = await publisher.publish(_post())

    assert result.success is True
    assert result.platform_post_id == "urn:li:share:99"

    # userinfo was queried for the member's person URN
    client.get.assert_awaited_once()
    assert "userinfo" in client.get.call_args.args[0]

    # the ugcPosts payload is authored as the member, not an organization
    body = client.post.call_args.kwargs["json"]
    assert body["author"] == "urn:li:person:abc123"
    assert "organization" not in body["author"]
    assert (
        body["specificContent"]["com.linkedin.ugc.ShareContent"]["shareCommentary"]["text"]
        == "Remote Opportunity: Data Entry"
    )


@pytest.mark.asyncio
async def test_linkedin_caches_person_urn_across_posts() -> None:
    client = _mock_client()
    publisher = LinkedInPublisher(session=MagicMock(), settings=_settings(), client=client)

    await publisher.publish(_post())
    await publisher.publish(_post())

    # userinfo is fetched once and cached; two posts still go out
    assert client.get.await_count == 1
    assert client.post.await_count == 2
