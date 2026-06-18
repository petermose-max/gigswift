"""X (Twitter) publisher using tweepy's async client.

Media (the branded card) is uploaded via the v1.1 ``media_upload`` endpoint —
run in a worker thread because that client is synchronous — and the resulting
media id is attached to the v2 tweet created by ``AsyncClient``.
"""

import asyncio

import tweepy
from sqlalchemy.ext.asyncio import AsyncSession
from tweepy.asynchronous import AsyncClient

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.publisher.base import BasePublisher, PublishResult
from app.schemas.post import PostSchema

logger = get_logger(__name__)


class XPublisher(BasePublisher):
    """Posts to X: optional media upload, then a tweet with the media id."""

    platform = "x"
    # Rate-limit (HTTP 429) retries wait far longer than ordinary failures.
    rate_limit_backoff: float = 60.0

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        client: AsyncClient | None = None,
        api: tweepy.API | None = None,
    ) -> None:
        super().__init__(session)
        settings = settings or get_settings()
        self._client = client or AsyncClient(
            consumer_key=settings.X_API_KEY,
            consumer_secret=settings.X_API_SECRET,
            access_token=settings.X_ACCESS_TOKEN,
            access_token_secret=settings.X_ACCESS_SECRET,
        )
        self._api = api or self._build_api(settings)

    @staticmethod
    def _build_api(settings: Settings) -> tweepy.API:
        auth = tweepy.OAuth1UserHandler(
            settings.X_API_KEY,
            settings.X_API_SECRET,
            settings.X_ACCESS_TOKEN,
            settings.X_ACCESS_SECRET,
        )
        return tweepy.API(auth)

    async def publish(self, post: PostSchema) -> PublishResult:
        media_ids: list[int] | None = None
        if post.image_path:
            media = await asyncio.to_thread(self._api.media_upload, post.image_path)
            media_ids = [media.media_id]

        response = await self._client.create_tweet(text=post.content, media_ids=media_ids)
        if not response or not response.data:
            raise RuntimeError("create_tweet returned no data")

        tweet_id = str(response.data["id"])
        logger.info("Posted tweet %s", tweet_id)
        return PublishResult(success=True, platform_post_id=tweet_id)

    def _backoff_seconds(self, attempt: int, exc: Exception) -> float:
        if isinstance(exc, tweepy.TooManyRequests):
            return self.rate_limit_backoff * attempt
        return super()._backoff_seconds(attempt, exc)
