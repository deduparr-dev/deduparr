"""
Pytest configuration and shared fixtures
"""

import os
import secrets
import time

import pytest
from httpx import AsyncClient, ASGITransport
from itsdangerous import URLSafeSerializer
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.database import Base
from app.models import DuplicateSet, DuplicateFile, DeletionHistory
from app.models.duplicate import MediaType
from app.main import app
from app.api.deps import get_db
from app.services.shared.security import get_or_create_key_file, get_token_manager

# Set a fixed encryption key for tests to ensure consistency
os.environ["ENCRYPTION_KEY_FILE"] = "/tmp/deduparr_test_key"

# Let pytest-asyncio handle the event loop
pytest_plugins = ("pytest_asyncio",)


def encrypt_test_password(plain_password: str) -> str:
    """Helper to encrypt passwords for test fixtures"""
    token_manager = get_token_manager()
    return token_manager.encrypt(plain_password)


def sign_the_old_way(secret: str) -> str:
    """A secret as stored before secrets were encrypted: signed, and readable."""
    return URLSafeSerializer(get_or_create_key_file()).dumps(
        {"token": secret, "salt": secrets.token_hex(16), "timestamp": int(time.time())}
    )


@pytest.fixture
async def test_db():
    """Create an in-memory SQLite database for testing"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    TestSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with TestSessionLocal() as session:

        async def override_get_db():
            yield session

        app.dependency_overrides[get_db] = override_get_db

        yield session

        app.dependency_overrides.clear()
        await session.rollback()

    await engine.dispose()


@pytest.fixture
async def client(test_db):
    """Create an async HTTP client for testing API endpoints"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
def create_duplicate_set(test_db):
    """Factory fixture for creating DuplicateSet instances"""

    async def _create(**kwargs):
        defaults = {
            "item_id": "12345",
            "title": "Test Movie",
            "media_type": MediaType.MOVIE,
        }
        defaults.update(kwargs)
        dup_set = DuplicateSet(**defaults)
        test_db.add(dup_set)
        await test_db.commit()
        await test_db.refresh(dup_set)
        return dup_set

    return _create


@pytest.fixture
def create_duplicate_file(test_db):
    """Factory fixture for creating DuplicateFile instances"""

    async def _create(set_id: int, **kwargs):
        defaults = {
            "set_id": set_id,
            "file_path": "/media/movies/Test Movie.mkv",
            "file_size": 2000000000,
            "score": 50,
            "keep": False,
        }
        defaults.update(kwargs)
        dup_file = DuplicateFile(**defaults)
        test_db.add(dup_file)
        await test_db.commit()
        await test_db.refresh(dup_file)
        return dup_file

    return _create


@pytest.fixture
def create_deletion_history(test_db):
    """Factory fixture for creating DeletionHistory instances"""

    async def _create(file_id: int, **kwargs):
        defaults = {
            "duplicate_file_id": file_id,
            "deleted_from_qbit": False,
            "deleted_from_arr": False,
            "deleted_from_disk": False,
            "media_server_refreshed": False,
        }
        defaults.update(kwargs)
        history = DeletionHistory(**defaults)
        test_db.add(history)
        await test_db.commit()
        await test_db.refresh(history)
        return history

    return _create
