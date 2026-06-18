"""Shared pytest fixtures.

DB-backed tests run against an in-memory SQLite database using a ``StaticPool`` so
the whole test shares one connection (``:memory:`` is per-connection otherwise).
The production Postgres engine is never used: the FastAPI ``get_db`` dependency is
overridden to the SQLite sessionmaker, and the ``@lru_cache`` on
``get_engine``/``get_sessionmaker`` is cleared at the end of the session.

Note: ``Settings.DATABASE_URL`` is a ``PostgresDsn`` and cannot literally hold a
sqlite URL, so we set a dummy Postgres DSN (never connected to) purely to satisfy
settings validation and route every real query to SQLite.
"""

import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from decimal import Decimal

# Required settings must exist before any get_settings() call; use dummy values.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("X_API_KEY", "test-key")
os.environ.setdefault("X_API_SECRET", "test-secret")
os.environ.setdefault("X_ACCESS_TOKEN", "test-token")
os.environ.setdefault("X_ACCESS_SECRET", "test-token-secret")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:test-bot-token")
os.environ.setdefault("TELEGRAM_CHANNEL_ID", "@gigswift_test")
os.environ.setdefault("TELEGRAM_API_ID", "12345")
os.environ.setdefault("TELEGRAM_API_HASH", "test-hash")
os.environ.setdefault("RSS_FEED_URLS", "https://example.com/feed.rss")
os.environ.setdefault("TELEGRAM_CHANNELS", "@example")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.database import get_db, get_engine, get_sessionmaker
from app.main import create_app
from app.models import Base
from app.schemas.job import RawJobSchema


@pytest.fixture(scope="session", autouse=True)
def _clear_engine_caches() -> Iterator[None]:
    """Constraint #1: clear the cached production engine/sessionmaker after the session."""
    yield
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """Fresh in-memory SQLite engine per test (StaticPool -> one shared connection)."""
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng.sync_engine, "connect")
    def _register_uuid(dbapi_connection, _record):
        # SQLite lacks gen_random_uuid(); supply it for the PK server defaults.
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def sessionmaker_(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def db_session(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with sessionmaker_() as session:
        yield session


@pytest.fixture
async def client(sessionmaker_: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    """Test client with ``get_db`` overridden to the SQLite session (no lifespan)."""
    app = create_app()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with sessionmaker_() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def make_raw_job() -> Callable[..., RawJobSchema]:
    """Factory for RawJobSchema with a unique apply_url.

    Constraint #2: each job gets a distinct apply_url (uuid4), so the derived
    content_hash = SHA256(title + apply_url) is unique across all test functions.
    """

    def _make(**overrides: object) -> RawJobSchema:
        defaults: dict[str, object] = {
            "source": "rss:test",
            "title": "Remote Python Developer",
            "description": "Fully remote role, work from anywhere.",
            "apply_url": f"https://example.com/jobs/{uuid.uuid4().hex}",
            "pay_min": Decimal("45"),
            "pay_max": Decimal("85"),
        }
        defaults.update(overrides)
        return RawJobSchema(**defaults)

    return _make


@pytest.fixture
def sample_raw_jobs(make_raw_job: Callable[..., RawJobSchema]) -> list[RawJobSchema]:
    """A small, varied batch: one entry-level, one senior, one scam, one low-signal."""
    return [
        make_raw_job(
            title="Entry Level Data Labeler - No Experience",
            description="Remote, work from anywhere. Training provided.",
        ),
        make_raw_job(
            title="Senior Backend Engineer",
            description="Remote role.",
            pay_min=Decimal("60"),
            pay_max=Decimal("120"),
        ),
        make_raw_job(
            title="Quick Cash Gig",
            description="Pay via wire transfer to begin.",
            pay_min=None,
            pay_max=None,
        ),
        make_raw_job(
            title="Vague Listing",
            description="See inside.",
            pay_min=None,
            pay_max=None,
        ),
    ]
