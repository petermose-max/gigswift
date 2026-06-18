"""Telegram publisher using python-telegram-bot's async ``Bot``.

Sends the branded card as a photo with the formatted text as caption when an
image is present, otherwise a plain text message. Content is MarkdownV2 (see the
Telegram formatter), so it is sent with ``parse_mode=MarkdownV2``.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import RetryAfter

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.publisher.base import BasePublisher, PublishResult
from app.schemas.post import PostSchema

logger = get_logger(__name__)


class TelegramPublisher(BasePublisher):
    """Posts to a Telegram channel as a photo+caption or a text message."""

    platform = "telegram"

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        bot: Bot | None = None,
    ) -> None:
        super().__init__(session)
        settings = settings or get_settings()
        self._channel_id = settings.TELEGRAM_CHANNEL_ID
        self._bot = bot or Bot(token=settings.TELEGRAM_BOT_TOKEN)

    async def publish(self, post: PostSchema) -> PublishResult:
        async with self._bot:
            if post.image_path:
                with open(post.image_path, "rb") as photo:
                    message = await self._bot.send_photo(
                        chat_id=self._channel_id,
                        photo=photo,
                        caption=post.content,
                        parse_mode=ParseMode.MARKDOWN_V2,
                    )
            else:
                message = await self._bot.send_message(
                    chat_id=self._channel_id,
                    text=post.content,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )

        logger.info("Sent Telegram message %s", message.message_id)
        return PublishResult(success=True, platform_post_id=str(message.message_id))

    def _backoff_seconds(self, attempt: int, exc: Exception) -> float:
        # Telegram tells us exactly how long to wait on a flood/rate limit.
        if isinstance(exc, RetryAfter):
            return float(exc.retry_after) + 1.0
        return super()._backoff_seconds(attempt, exc)
