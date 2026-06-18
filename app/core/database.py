"""Async database access.

Builds a single async SQLAlchemy engine backed by asyncpg and an
``async_sessionmaker`` for producing sessions. Both are created lazily and cached
so importing this module has no side effects and there is exactly one engine per
process.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Create (once) and return the process-wide async engine."""
    settings = get_settings()
    return create_async_engine(
        str(settings.DATABASE_URL),
        # Conservative pool sizing — the app runs on a 1 vCPU / 1 GB Oracle VM.
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=1800,
        future=True,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Create (once) and return the async session factory bound to the engine."""
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional session scope.

    Commits on clean exit, rolls back on any exception, and always closes the
    session. Use this anywhere outside the request lifecycle (scheduler, scripts).
    """
    session = get_sessionmaker()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session.

    Delegates to :func:`session_scope`, so the session commits when the request
    handler returns successfully and rolls back if it raises.
    """
    async with session_scope() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose of the engine's connection pool (call on application shutdown)."""
    engine = get_engine()
    await engine.dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
