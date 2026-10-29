"""
Alembic environment.

Migrations connect the way the app does, with its async driver (aiosqlite or
asyncpg), so they need no driver of their own. Batch mode is on because SQLite
cannot ALTER a column in place.
"""

import asyncio

from alembic import context
from sqlalchemy import inspect, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.database import Base, async_database_url
from app.models import (  # noqa: F401  (registers the tables on Base.metadata)
    Config,
    DeletionHistory,
    DuplicateFile,
    DuplicateSet,
    ScoringRule,
)

target_metadata = Base.metadata


def include_name(name, type_, parent_names) -> bool:
    """Leave out _init, which init_db creates so a new SQLite file has a table"""
    return not (type_ == "table" and name == "_init")


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        tables = inspect(connection).get_table_names()
        if "duplicate_sets" in tables and "alembic_version" not in tables:
            # A release before migrations (0.5.7 or older) built the schema of
            # its first start and never changed it: 0001's tables, and maybe the
            # columns 0002 and 0003 alter, which they can safely alter again
            context.get_context().stamp(context.script, "0001")
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(async_database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
