"""LinkedIn publisher: posts to an organization page via the UGC Posts REST API.

A text-only share is sent to ``POST /v2/ugcPosts`` with the access token in the
Authorization header. Images are skipped for v1 (LinkedIn media requires a separate
multi-step asset-upload flow). Retry/backoff and publish_log/posted_at bookkeeping
are inherited from :class:`BasePublisher`.
"""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.publisher.base import BasePublisher, PublishResult
from app.schemas.post import PostSchema

logger = get_logger(__name__)

_UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"
_TIMEOUT = 30.0


class LinkedInPublisher(BasePublisher):
    """Posts a job as a text share on the configured LinkedIn organization page."""

    platform = "linkedin"

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(session)
        settings = settings or get_settings()
        self._access_token = settings.LINKEDIN_ACCESS_TOKEN
        self._author_urn = f"urn:li:organization:{settings.LINKEDIN_ORGANIZATION_ID}"
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

    def _payload(self, text: str) -> dict[str, object]:
        return {
            "author": self._author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }

    async def publish(self, post: PostSchema) -> PublishResult:
        payload = self._payload(post.content)
        headers = self._headers()

        if self._client is not None:
            response = await self._client.post(_UGC_POSTS_URL, headers=headers, json=payload)
        else:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(_UGC_POSTS_URL, headers=headers, json=payload)

        # Non-2xx raises HTTPStatusError, which BasePublisher's retry loop handles.
        response.raise_for_status()

        post_id = response.headers.get("x-restli-id") or None
        logger.info("Posted to LinkedIn: %s", post_id or "(no id returned)")
        return PublishResult(success=True, platform_post_id=post_id)
