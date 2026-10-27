"""
Tests for stats API routes
"""

import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models.duplicate import DuplicateSet, DuplicateFile, DuplicateStatus, MediaType
from app.models.history import DeletionHistory


@pytest.mark.asyncio
async def test_get_dashboard_stats_empty(test_db):
    """Test GET /api/stats/dashboard with empty database"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/stats/dashboard")

    assert response.status_code == 200
    data = response.json()

    assert data["total_duplicates"] == 0
    assert data["pending_duplicates"] == 0
    assert data["approved_duplicates"] == 0
    assert data["processed_duplicates"] == 0
    assert data["space_to_reclaim"] == 0
    assert data["total_deletions"] == 0
    assert data["successful_deletions"] == 0
    assert data["failed_deletions"] == 0


@pytest.mark.asyncio
async def test_get_dashboard_stats_with_data(test_db):
    """Test GET /api/stats/dashboard with data"""
    now = datetime.now(timezone.utc)

    duplicate1 = DuplicateSet(
        item_id="movie1",
        title="Test Movie 1",
        media_type=MediaType.MOVIE,
        found_at=now,
        status=DuplicateStatus.PENDING,
        space_to_reclaim=1024 * 1024 * 1024,  # 1 GB
    )
    duplicate2 = DuplicateSet(
        item_id="movie2",
        title="Test Movie 2",
        media_type=MediaType.MOVIE,
        found_at=now,
        status=DuplicateStatus.APPROVED,
        space_to_reclaim=2 * 1024 * 1024 * 1024,  # 2 GB
    )
    test_db.add_all([duplicate1, duplicate2])
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/stats/dashboard")

    assert response.status_code == 200
    data = response.json()

    assert data["total_duplicates"] == 2
    assert data["pending_duplicates"] == 1
    assert data["approved_duplicates"] == 1
    assert data["space_to_reclaim"] == 3 * 1024 * 1024 * 1024


@pytest.mark.asyncio
async def test_get_recent_activity_empty(test_db):
    """Test GET /api/stats/recent-activity with no data"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/stats/recent-activity")

    assert response.status_code == 200
    data = response.json()

    assert isinstance(data, list)
    assert len(data) == 0


@pytest.mark.asyncio
async def test_get_recent_activity_with_data(test_db):
    """Test GET /api/stats/recent-activity with data"""
    now = datetime.now(timezone.utc)

    for i in range(5):
        duplicate = DuplicateSet(
            item_id=f"item{i}",
            title=f"Test Item {i}",
            media_type=MediaType.MOVIE,
            found_at=now - timedelta(minutes=i),
            status=DuplicateStatus.PENDING,
            space_to_reclaim=1024 * 1024 * (i + 1),
        )
        test_db.add(duplicate)

    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/stats/recent-activity")

    assert response.status_code == 200
    data = response.json()

    assert len(data) == 5
    assert data[0]["title"] == "Test Item 0"
    assert data[0]["media_type"] == "movie"
    assert data[0]["status"] == "pending"
    assert "found_at" in data[0]
    assert "space_to_reclaim" in data[0]


@pytest.mark.asyncio
async def test_get_recent_activity_with_limit(test_db):
    """Test GET /api/stats/recent-activity with custom limit"""
    now = datetime.now(timezone.utc)

    for i in range(15):
        duplicate = DuplicateSet(
            item_id=f"item{i}",
            title=f"Test Item {i}",
            media_type=MediaType.EPISODE,
            found_at=now - timedelta(minutes=i),
            status=DuplicateStatus.APPROVED,
            space_to_reclaim=1024 * 1024 * (i + 1),
        )
        test_db.add(duplicate)

    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/stats/recent-activity?limit=3")

    assert response.status_code == 200
    data = response.json()

    assert len(data) == 3
    assert data[0]["title"] == "Test Item 0"
    assert data[2]["title"] == "Test Item 2"


@pytest.mark.asyncio
async def test_get_recent_deletions_empty(test_db):
    """Test GET /api/stats/recent-deletions with no data"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/stats/recent-deletions")

    assert response.status_code == 200
    data = response.json()

    assert isinstance(data, list)
    assert len(data) == 0


@pytest.mark.asyncio
async def test_get_recent_deletions_with_data(test_db):
    """Test GET /api/stats/recent-deletions with data"""
    now = datetime.now(timezone.utc)

    duplicate = DuplicateSet(
        item_id="movie1",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        found_at=now,
        status=DuplicateStatus.PROCESSED,
    )
    test_db.add(duplicate)
    await test_db.commit()

    for i in range(3):
        file = DuplicateFile(
            set_id=duplicate.id,
            file_path=f"/media/file{i}.mkv",
            file_size=1024 * 1024 * (i + 1),
            score=i * 10,
            keep=False,
        )
        test_db.add(file)
        await test_db.flush()

        history = DeletionHistory(
            duplicate_file_id=file.id,
            deleted_at=now - timedelta(minutes=i),
            deleted_from_qbit=True,
            deleted_from_arr=True,
            deleted_from_disk=True,
            media_server_refreshed=True,
            error=None,
        )
        test_db.add(history)

    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/stats/recent-deletions")

    assert response.status_code == 200
    data = response.json()

    assert len(data) == 3
    assert data[0]["file_path"] == "/media/file0.mkv"
    assert data[0]["is_complete"] is True
    assert data[0]["error"] is None
    assert "deleted_at" in data[0]


@pytest.mark.asyncio
async def test_get_recent_deletions_with_errors(test_db):
    """Test GET /api/stats/recent-deletions with failed deletions"""
    now = datetime.now(timezone.utc)

    duplicate = DuplicateSet(
        item_id="movie1",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        found_at=now,
        status=DuplicateStatus.PROCESSED,
    )
    test_db.add(duplicate)
    await test_db.commit()

    file = DuplicateFile(
        set_id=duplicate.id,
        file_path="/media/failed.mkv",
        file_size=1024 * 1024 * 1024,
        score=50,
        keep=False,
    )
    test_db.add(file)
    await test_db.flush()

    history = DeletionHistory(
        duplicate_file_id=file.id,
        deleted_at=now,
        deleted_from_qbit=True,
        deleted_from_arr=False,
        deleted_from_disk=False,
        media_server_refreshed=False,
        error="Failed to connect to Radarr API",
    )
    test_db.add(history)
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/stats/recent-deletions")

    assert response.status_code == 200
    data = response.json()

    assert len(data) == 1
    assert data[0]["file_path"] == "/media/failed.mkv"
    assert data[0]["is_complete"] is False
    assert data[0]["error"] == "Failed to connect to Radarr API"


@pytest.mark.asyncio
async def test_get_recent_deletions_with_limit(test_db):
    """Test GET /api/stats/recent-deletions with custom limit"""
    now = datetime.now(timezone.utc)

    duplicate = DuplicateSet(
        item_id="movie1",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        found_at=now,
        status=DuplicateStatus.PROCESSED,
    )
    test_db.add(duplicate)
    await test_db.commit()

    for i in range(10):
        file = DuplicateFile(
            set_id=duplicate.id,
            file_path=f"/media/file{i}.mkv",
            file_size=1024 * 1024 * (i + 1),
            score=i * 10,
            keep=False,
        )
        test_db.add(file)
        await test_db.flush()

        history = DeletionHistory(
            duplicate_file_id=file.id,
            deleted_at=now - timedelta(minutes=i),
            deleted_from_qbit=True,
            deleted_from_arr=True,
            deleted_from_disk=True,
            media_server_refreshed=True,
        )
        test_db.add(history)

    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/stats/recent-deletions?limit=5")

    assert response.status_code == 200
    data = response.json()

    assert len(data) == 5
