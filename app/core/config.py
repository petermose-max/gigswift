"""Application configuration.

Uses Pydantic ``BaseSettings`` to read configuration from environment variables
(and an optional ``.env`` file). Required secrets have no defaults, so the process
fails fast at startup if anything is missing rather than misbehaving at runtime.
"""

from functools import lru_cache

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated application settings sourced from the environment."""

    # Database
    DATABASE_URL: PostgresDsn

    # X (Twitter)
    X_API_KEY: str
    X_API_SECRET: str
    X_ACCESS_TOKEN: str
    X_ACCESS_SECRET: str

    # Telegram bot (for posting)
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHANNEL_ID: str

    # Telegram client (for reading channels via Telethon)
    TELEGRAM_API_ID: int
    TELEGRAM_API_HASH: str

    # Pipeline tuning
    MIN_SCORE_THRESHOLD: float = 0.5
    MIN_PAY_HOURLY: float = 15.0
    SCHEDULER_INTERVAL_MINUTES: int = 30
    MAX_POSTS_PER_RUN: int = 5

    # RSS sources (comma-separated URLs)
    RSS_FEED_URLS: str

    # Telegram channels to read (comma-separated)
    TELEGRAM_CHANNELS: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Other keys live in .env (e.g. DB_PASSWORD, LOG_FORMAT); ignore them here.
        extra="ignore",
    )

    @staticmethod
    def _split_csv(raw: str) -> list[str]:
        """Split a comma-separated string, trimming whitespace and dropping blanks."""
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def rss_feed_urls(self) -> list[str]:
        """``RSS_FEED_URLS`` parsed into a clean list of feed URLs."""
        return self._split_csv(self.RSS_FEED_URLS)

    @property
    def telegram_channels(self) -> list[str]:
        """``TELEGRAM_CHANNELS`` parsed into a clean list of channel handles."""
        return self._split_csv(self.TELEGRAM_CHANNELS)


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance.

    Instantiation is deferred until first call so importing this module never
    triggers environment validation on its own (useful for tooling and tests).
    """
    return Settings()
