"""Alembic migration environment (async).

Runs migrations through the application's async engine (asyncpg) and points
autogenerate at the metadata registered under ``app/models``. The connection URL
comes from ``app.core.config.Settings`` (DATABASE_URL) so it is defined in exactly
one place rather than duplicated in ``alembic.ini``.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings
from app.models import Base

# Alembic Config object, providing access to values in alembic.ini.
config = context.config

# Configure Python logging from the alembic.ini logging sections.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the runtime database URL (single source of truth) for the engine below.
config.set_main_option("sqlalchemy.url", str(get_settings().DATABASE_URL))

# Target metadata for autogenerate — every model is registered on Base.metadata.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DBAPI connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure the context against a live connection and run migrations."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations within an async connection."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for 'online' mode — drives the async migration runner."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
