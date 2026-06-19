"""LinkedIn publisher: posts to the authenticated member's profile via UGC Posts.

A text-only share is sent to ``POST /v2/ugcPosts`` with the access token in the
Authorization header, authored as the member (``urn:li:person:{id}``). The person
id comes from ``GET /v2/userinfo`` (its ``sub`` field) and is cached after the first
call. Posting as a member needs only ``w_member_social`` (available on a basic
developer app), unlike organization posting which needs ``w_organization_social``.

Images are skipped for v1 (LinkedIn media requires a separate multi-step asset
upload). Retry/backoff and publish_log/posted_at bookkeeping are inherited from
:class:`BasePublisher`.
"""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.publisher.base import BasePublisher, PublishResult
from app.schemas.post import PostSchema

logger = get_logger(__name__)

_UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"
_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
_TIMEOUT = 30.0


class LinkedInPublisher(BasePublisher):
    """Posts a job as a text share on the authenticated member's LinkedIn profile."""

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
        self._client = client
        self._person_urn: str | None = None  # cached after first userinfo lookup

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

    def _payload(self, text: str, author: str) -> dict[str, object]:
        return {
            "author": author,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }

    async def _get_person_urn(self, client: httpx.AsyncClient) -> str:
        """Resolve and cache the authenticated member's ``urn:li:person:{id}``."""
        if self._person_urn is None:
            response = await client.get(
                _USERINFO_URL, headers={"Authorization": f"Bearer {self._access_token}"}
            )
            response.raise_for_status()
            self._person_urn = f"urn:li:person:{response.json()['sub']}"
        return self._person_urn

    async def publish(self, post: PostSchema) -> PublishResult:
        if self._client is not None:
            return await self._publish(self._client, post)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            return await self._publish(client, post)

    async def _publish(self, client: httpx.AsyncClient, post: PostSchema) -> PublishResult:
        author = await self._get_person_urn(client)
        response = await client.post(
            _UGC_POSTS_URL, headers=self._headers(), json=self._payload(post.content, author)
        )
        # Non-2xx raises HTTPStatusError, which BasePublisher's retry loop handles.
        response.raise_for_status()

        post_id = response.headers.get("x-restli-id") or None
        logger.info("Posted to LinkedIn: %s", post_id or "(no id returned)")
        return PublishResult(success=True, platform_post_id=post_id)
