"""
Database configuration and initialization
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.core.config import settings


def async_database_url() -> str:
    """The configured database URL with the async driver the app connects through"""
    if settings.database_type == "sqlite":
        return settings.database_url.replace("sqlite://", "sqlite+aiosqlite://")
    return settings.database_url.replace("postgresql://", "postgresql+asyncpg://")


# Create async engine
if settings.database_type == "sqlite":
    # SQLite async engine
    engine = create_async_engine(
        async_database_url(),
        echo=settings.debug,
        future=True,
        connect_args={"check_same_thread": False},
    )
else:
    # PostgreSQL async engine
    engine = create_async_engine(
        async_database_url(),
        echo=settings.debug,
        future=True,
        pool_pre_ping=True,
    )

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Base class for models
Base = declarative_base()


def utc_now():
    """Get current UTC timestamp for database defaults"""
    return datetime.now(timezone.utc)


async def init_db():
    """Initialize database - create all tables"""
    from sqlalchemy import text
    import sqlite3

    # Ensure the config directory and database file exist for SQLite
    if settings.database_type == "sqlite":
        import os
        from urllib.parse import urlparse

        # Parse the database URL to extract the file path
        parsed = urlparse(settings.database_url)
        db_path = parsed.path  # With 4 slashes: //config/deduparr.db

        # Remove leading double slash from absolute paths
        if db_path.startswith("//"):
            db_path = db_path[1:]  # //config/deduparr.db -> /config/deduparr.db

        db_dir = os.path.dirname(db_path)

        # Create directory if it doesn't exist
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        # Create empty database file if it doesn't exist
        # This prevents "unable to open database file" errors with aiosqlite
        if not os.path.exists(db_path):
            # Create a proper SQLite database (not just an empty file)
            conn = sqlite3.connect(db_path)
            # Initialize the database with a minimal schema
            conn.execute("CREATE TABLE IF NOT EXISTS _init (id INTEGER PRIMARY KEY)")
            conn.commit()
            conn.close()
            print(f"✅ Created SQLite database at {db_path}")

    # Alembic owns the schema; it creates it on a fresh database and upgrades an
    # existing one. It is synchronous, so it runs in a worker thread.
    await asyncio.to_thread(_upgrade_schema)

    async with engine.begin() as conn:
        # Apply SQLite optimizations
        if settings.database_type == "sqlite":
            await conn.execute(text("PRAGMA journal_mode = WAL"))
            await conn.execute(text("PRAGMA synchronous = NORMAL"))
            await conn.execute(text("PRAGMA cache_size = -64000"))
            await conn.execute(text("PRAGMA temp_store = MEMORY"))
            await conn.execute(text("PRAGMA mmap_size = 268435456"))

            print("✅ SQLite optimizations applied (WAL mode, caching, mmap)")


async def get_db():
    """Dependency to get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def _upgrade_schema() -> None:
    """Run every pending Alembic migration."""
    from alembic import command
    from alembic.config import Config as AlembicConfig

    backend_dir = Path(__file__).resolve().parents[2]
    config = AlembicConfig(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(config, "head")
    print("✅ Database schema is up to date")
