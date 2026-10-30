"""
Tests for stats service
"""

import pytest
from datetime import datetime, timezone, timedelta

from app.services.stats_service import StatsService
from app.models.duplicate import DuplicateSet, DuplicateFile, DuplicateStatus, MediaType
from app.models.history import DeletionHistory


@pytest.mark.asyncio
async def test_get_dashboard_stats_empty_database(test_db):
    """Test dashboard stats with empty database"""
    service = StatsService(test_db)
    stats = await service.get_dashboard_stats()

    assert stats.total_duplicates == 0
    assert stats.pending_duplicates == 0
    assert stats.approved_duplicates == 0
    assert stats.processed_duplicates == 0
    assert stats.space_to_reclaim == 0
    assert stats.total_deletions == 0
    assert stats.successful_deletions == 0
    assert stats.failed_deletions == 0


@pytest.mark.asyncio
async def test_get_dashboard_stats_with_duplicates(test_db):
    """Test dashboard stats with duplicate sets"""
    now = datetime.now(timezone.utc)

    duplicate1 = DuplicateSet(
        item_id="movie1",
        title="Test Movie 1",
        media_type=MediaType.MOVIE,
        found_at=now,
        status=DuplicateStatus.PENDING,
        space_to_reclaim=1024 * 1024 * 500,  # 500 MB
    )
    test_db.add(duplicate1)

    duplicate2 = DuplicateSet(
        item_id="movie2",
        title="Test Movie 2",
        media_type=MediaType.MOVIE,
        found_at=now,
        status=DuplicateStatus.APPROVED,
        space_to_reclaim=1024 * 1024 * 1024,  # 1 GB
    )
    test_db.add(duplicate2)

    duplicate3 = DuplicateSet(
        item_id="show1-e1",
        title="Test Show S01E01",
        media_type=MediaType.EPISODE,
        found_at=now,
        status=DuplicateStatus.PROCESSED,
        space_to_reclaim=1024 * 1024 * 200,  # 200 MB
    )
    test_db.add(duplicate3)
    await test_db.flush()
    test_db.add_all(
        [
            DuplicateFile(
                set_id=duplicate1.id, file_path="/m/a.mkv", file_size=1024 * 1024 * 500
            ),
            DuplicateFile(
                set_id=duplicate3.id, file_path="/m/b.mkv", file_size=1024 * 1024 * 200
            ),
        ]
    )

    await test_db.commit()

    service = StatsService(test_db)
    stats = await service.get_dashboard_stats()

    assert stats.total_duplicates == 3
    assert stats.pending_duplicates == 1
    assert stats.approved_duplicates == 1
    assert stats.processed_duplicates == 1
    assert stats.space_to_reclaim == 1024 * 1024 * 500  # Only what pending sets delete


@pytest.mark.asyncio
async def test_get_dashboard_stats_with_deletions(test_db):
    """Test dashboard stats with deletion history"""
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

    file1 = DuplicateFile(
        set_id=duplicate.id,
        file_path="/media/movie1.mkv",
        file_size=1024 * 1024 * 1024,
        score=100,
        keep=True,
    )
    file2 = DuplicateFile(
        set_id=duplicate.id,
        file_path="/media/movie1_low.mkv",
        file_size=500 * 1024 * 1024,
        score=50,
        keep=False,
    )
    test_db.add_all([file1, file2])
    await test_db.commit()

    history1 = DeletionHistory(
        duplicate_file_id=file2.id,
        deleted_at=now,
        deleted_from_qbit=True,
        deleted_from_arr=True,
        deleted_from_disk=True,
        media_server_refreshed=True,
        error=None,
    )
    test_db.add(history1)

    history2 = DeletionHistory(
        duplicate_file_id=file1.id,
        deleted_at=now,
        deleted_from_qbit=True,
        deleted_from_arr=False,
        deleted_from_disk=False,
        media_server_refreshed=False,
        error="Failed to delete from Radarr",
    )
    test_db.add(history2)

    await test_db.commit()

    service = StatsService(test_db)
    stats = await service.get_dashboard_stats()

    assert stats.total_deletions == 2
    assert stats.successful_deletions == 1
    assert stats.failed_deletions == 1


@pytest.mark.asyncio
async def test_a_deletion_succeeded_once_the_file_is_gone(test_db):
    """
    Whatever else a stage reported is a note, as in the deletion's own result.

    Counting only deletions that also went through qBittorrent made every
    deletion without it a failure, and a failed refresh marked a deleted file
    Failed on the dashboard.
    """
    duplicate = DuplicateSet(
        item_id="movie1",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.PROCESSED,
    )
    test_db.add(duplicate)
    await test_db.flush()

    outcomes = [
        (True, True, "qBittorrent not configured"),
        (True, False, "Jellyfin refresh failed: timed out"),
        (False, False, "Could not delete /media/movie.mkv: Read-only file system"),
    ]
    for index, (deleted, refreshed, error) in enumerate(outcomes):
        file = DuplicateFile(
            set_id=duplicate.id, file_path=f"/media/{index}.mkv", file_size=1
        )
        test_db.add(file)
        await test_db.flush()
        test_db.add(
            DeletionHistory(
                duplicate_file_id=file.id,
                deleted_at=datetime.now(timezone.utc) - timedelta(minutes=index),
                deleted_from_disk=deleted,
                media_server_refreshed=refreshed,
                error=error,
            )
        )
    await test_db.commit()

    service = StatsService(test_db)
    stats = await service.get_dashboard_stats()
    deletions = await service.get_recent_deletions()

    assert (stats.successful_deletions, stats.failed_deletions) == (2, 1)
    assert [deletion.is_complete for deletion in deletions] == [True, True, False]


@pytest.mark.asyncio
async def test_get_recent_activity(test_db):
    """Test getting recent duplicate activity"""
    now = datetime.now(timezone.utc)

    for i in range(15):
        duplicate = DuplicateSet(
            item_id=f"item{i}",
            title=f"Test Item {i}",
            media_type=MediaType.MOVIE if i % 2 == 0 else MediaType.EPISODE,
            found_at=now - timedelta(minutes=i),
            status=DuplicateStatus.PENDING,
            space_to_reclaim=1024 * 1024 * (i + 1),
        )
        test_db.add(duplicate)

    await test_db.commit()

    service = StatsService(test_db)
    activities = await service.get_recent_activity(limit=10)

    assert len(activities) == 10
    assert activities[0].title == "Test Item 0"
    assert activities[0].media_type == "movie"
    assert activities[0].status == "pending"
    assert activities[9].title == "Test Item 9"


@pytest.mark.asyncio
async def test_get_recent_activity_empty(test_db):
    """Test getting recent activity with no data"""
    service = StatsService(test_db)
    activities = await service.get_recent_activity()

    assert len(activities) == 0


@pytest.mark.asyncio
async def test_get_recent_deletions(test_db):
    """Test getting recent deletion activity"""
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

    for i in range(12):
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
            deleted_from_disk=i % 2 == 0,
            media_server_refreshed=i % 2 == 0,
            error="Test error" if i % 3 == 0 else None,
        )
        test_db.add(history)

    await test_db.commit()

    service = StatsService(test_db)
    deletions = await service.get_recent_deletions(limit=10)

    assert len(deletions) == 10
    assert deletions[0].file_path == "/media/file0.mkv"
    assert deletions[0].is_complete is True  # deleted, its error a note
    assert deletions[1].is_complete is False  # still on disk
    assert deletions[1].error is None


@pytest.mark.asyncio
async def test_get_recent_deletions_empty(test_db):
    """Test getting recent deletions with no data"""
    service = StatsService(test_db)
    deletions = await service.get_recent_deletions()

    assert len(deletions) == 0


@pytest.mark.asyncio
async def test_count_by_status(test_db):
    """Test counting duplicates by status"""
    now = datetime.now(timezone.utc)

    for status in DuplicateStatus:
        for i in range(2 if status == DuplicateStatus.PENDING else 1):
            duplicate = DuplicateSet(
                item_id=f"{status.value}_{i}",
                title=f"Test {status.value} {i}",
                media_type=MediaType.MOVIE,
                found_at=now,
                status=status,
            )
            test_db.add(duplicate)

    await test_db.commit()

    service = StatsService(test_db)
    counts = await service._count_by_status()

    assert counts[DuplicateStatus.PENDING] == 2
    assert counts[DuplicateStatus.APPROVED] == 1
    assert counts[DuplicateStatus.REJECTED] == 1
    assert counts[DuplicateStatus.PROCESSED] == 1


@pytest.mark.asyncio
async def test_sum_space_to_reclaim(test_db):
    """What deleting every pending set frees, a file both servers list only once"""
    now = datetime.now(timezone.utc)
    plex, jellyfin, processed = (
        DuplicateSet(
            item_id=item_id,
            title="Movie",
            media_type=MediaType.MOVIE,
            found_at=now,
            status=status,
        )
        for item_id, status in (
            ("1", DuplicateStatus.PENDING),
            ("a", DuplicateStatus.PENDING),
            ("2", DuplicateStatus.PROCESSED),
        )
    )
    test_db.add_all([plex, jellyfin, processed])
    await test_db.flush()
    test_db.add_all(
        [
            DuplicateFile(set_id=plex.id, file_path="/m/720p.mkv", file_size=500),
            DuplicateFile(set_id=jellyfin.id, file_path="/m/720p.mkv", file_size=500),
            DuplicateFile(set_id=plex.id, file_path="/m/k.mkv", file_size=9, keep=True),
            DuplicateFile(set_id=processed.id, file_path="/m/old.mkv", file_size=2000),
        ]
    )
    await test_db.commit()

    assert await StatsService(test_db)._sum_space_to_reclaim() == 500


@pytest.mark.asyncio
async def test_timezone_aware_timestamp_serialization(test_db):
    """Test that timestamps are serialized with UTC timezone indicator (Z suffix)"""
    now = datetime.now(timezone.utc)

    # Create a duplicate set with timezone-aware timestamp
    duplicate = DuplicateSet(
        item_id="movie1",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        found_at=now,
        status=DuplicateStatus.PENDING,
        space_to_reclaim=1024 * 1024 * 500,
    )
    test_db.add(duplicate)
    await test_db.commit()

    # Get recent activity
    service = StatsService(test_db)
    activities = await service.get_recent_activity(limit=10)

    assert len(activities) == 1
    activity = activities[0]

    # Activity is already a RecentActivity Pydantic model
    # Serialize to JSON format to check the timestamp format
    serialized = activity.model_dump(mode="json")

    # Verify the timestamp is a string with Z suffix
    assert isinstance(serialized["found_at"], str)
    assert serialized["found_at"].endswith(
        "Z"
    ), f"Timestamp should end with 'Z' for UTC timezone, got: {serialized['found_at']}"

    # Verify it can be parsed back to a timezone-aware datetime
    parsed_dt = datetime.fromisoformat(serialized["found_at"].replace("Z", "+00:00"))
    assert parsed_dt.tzinfo is not None, "Parsed datetime should be timezone-aware"
    assert parsed_dt.tzinfo == timezone.utc, "Parsed datetime should be in UTC timezone"


@pytest.mark.asyncio
async def test_deletion_timezone_aware_timestamp_serialization(test_db):
    """Test that deletion timestamps are serialized with UTC timezone indicator (Z suffix)"""
    now = datetime.now(timezone.utc)

    # Create a duplicate set and file with deletion history
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
        file_path="/media/movie.mkv",
        file_size=1024 * 1024 * 1024,
        score=50,
        keep=False,
    )
    test_db.add(file)
    await test_db.commit()

    deletion = DeletionHistory(
        duplicate_file_id=file.id,
        deleted_at=now,
        deleted_from_qbit=True,
        deleted_from_arr=True,
        deleted_from_disk=True,
        media_server_refreshed=True,
    )
    test_db.add(deletion)
    await test_db.commit()

    # Get recent deletions
    service = StatsService(test_db)
    deletions = await service.get_recent_deletions(limit=10)

    assert len(deletions) == 1
    deletion_activity = deletions[0]

    # Deletion is already a DeletionActivity Pydantic model
    # Serialize to JSON format to check the timestamp format
    serialized = deletion_activity.model_dump(mode="json")

    # Verify the timestamp is a string with Z suffix
    assert isinstance(serialized["deleted_at"], str)
    assert serialized["deleted_at"].endswith(
        "Z"
    ), f"Timestamp should end with 'Z' for UTC timezone, got: {serialized['deleted_at']}"

    # Verify it can be parsed back to a timezone-aware datetime
    parsed_dt = datetime.fromisoformat(serialized["deleted_at"].replace("Z", "+00:00"))
    assert parsed_dt.tzinfo is not None, "Parsed datetime should be timezone-aware"
    assert parsed_dt.tzinfo == timezone.utc, "Parsed datetime should be in UTC timezone"
