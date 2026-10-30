"""
Tests for the scheduled deletion service
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.services.deletion.pipeline import SetDeletion
from app.services.deletion.scheduled import ScheduledDeletionService
from app.models import (
    DuplicateSet,
    DuplicateFile,
    DuplicateStatus,
    MediaType,
)


def _pipeline(*outcomes):
    """A DeletionPipeline stand-in whose delete_set gives these outcomes in turn."""
    pipeline = AsyncMock()
    pipeline.delete_set.side_effect = list(outcomes)
    return pipeline


@pytest.mark.asyncio
async def test_run_scheduled_deletion_no_pending_sets(test_db):
    """Test scheduled deletion with no pending sets"""
    service = ScheduledDeletionService(test_db)

    summary = await service.run_scheduled_deletion(dry_run=False, send_email=False)

    assert summary["sets_processed"] == 0
    assert summary["files_deleted"] == 0
    assert summary["errors"] == []
    assert summary["dry_run"] is False


@pytest.mark.asyncio
@patch("app.services.deletion.scheduled.DeletionPipeline")
async def test_run_scheduled_deletion_success(mock_pipeline_class, test_db):
    """Test successful scheduled deletion"""
    # Create pending duplicate set
    duplicate_set = DuplicateSet(
        item_id="12345",
        media_type=MediaType.MOVIE,
        title="Test Movie (2020)",
        status=DuplicateStatus.PENDING,
    )
    test_db.add(duplicate_set)
    await test_db.flush()

    file1 = DuplicateFile(
        set_id=duplicate_set.id,
        file_path="/media/movie1.mkv",
        file_size=1000000,
        score=75,
        keep=False,
    )
    file2 = DuplicateFile(
        set_id=duplicate_set.id,
        file_path="/media/movie2.mkv",
        file_size=2000000,
        score=90,
        keep=True,  # Keep this one
    )
    test_db.add_all([file1, file2])
    await test_db.commit()

    mock_pipeline_class.return_value = _pipeline(SetDeletion(files_deleted=1))

    service = ScheduledDeletionService(test_db)
    summary = await service.run_scheduled_deletion(dry_run=False, send_email=False)

    assert summary["sets_processed"] == 1
    assert summary["files_deleted"] == 1
    assert summary["errors"] == []
    # A real run must not inherit the pipeline's dry_run=True default
    mock_pipeline_class.assert_called_once_with(test_db, dry_run=False)
    mock_pipeline_class.return_value.delete_set.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_scheduled_deletion_skip_no_files_to_delete(test_db):
    """Test that sets with no files marked for deletion are skipped"""
    # Create pending set with no files to delete
    duplicate_set = DuplicateSet(
        item_id="12345",
        media_type=MediaType.MOVIE,
        title="Test Movie (2020)",
        status=DuplicateStatus.PENDING,
    )
    test_db.add(duplicate_set)
    await test_db.flush()

    file1 = DuplicateFile(
        set_id=duplicate_set.id,
        file_path="/media/movie1.mkv",
        file_size=1000000,
        score=75,
        keep=True,  # Nothing to delete
    )
    test_db.add(file1)
    await test_db.commit()

    # Run deletion
    service = ScheduledDeletionService(test_db)
    summary = await service.run_scheduled_deletion(dry_run=False, send_email=False)

    # Verify nothing was processed
    assert summary["sets_processed"] == 0
    assert summary["files_deleted"] == 0


@pytest.mark.asyncio
@patch("app.services.deletion.scheduled.DeletionPipeline")
async def test_run_scheduled_deletion_file_error(mock_pipeline_class, test_db):
    """Test handling of file deletion errors"""
    # Create pending duplicate set
    duplicate_set = DuplicateSet(
        item_id="12345",
        media_type=MediaType.MOVIE,
        title="Test Movie (2020)",
        status=DuplicateStatus.PENDING,
    )
    test_db.add(duplicate_set)
    await test_db.flush()

    file1 = DuplicateFile(
        set_id=duplicate_set.id,
        file_path="/media/movie1.mkv",
        file_size=1000000,
        score=75,
        keep=False,
    )
    test_db.add(file1)
    await test_db.commit()

    mock_pipeline_class.return_value = _pipeline(
        SetDeletion(errors=["Failed to delete /media/movie1.mkv: Deletion failed"])
    )

    service = ScheduledDeletionService(test_db)
    summary = await service.run_scheduled_deletion(dry_run=False, send_email=False)

    assert summary["sets_processed"] == 0
    assert summary["files_deleted"] == 0
    assert summary["errors"] == ["Failed to delete /media/movie1.mkv: Deletion failed"]


@pytest.mark.asyncio
@patch("app.services.deletion.scheduled.DeletionPipeline")
async def test_run_scheduled_deletion_multiple_sets(mock_pipeline_class, test_db):
    """Test deletion of multiple duplicate sets"""
    # Create multiple pending sets
    set1 = DuplicateSet(
        item_id="12345",
        media_type=MediaType.MOVIE,
        title="Movie 1 (2020)",
        status=DuplicateStatus.PENDING,
    )
    set2 = DuplicateSet(
        item_id="67890",
        media_type=MediaType.EPISODE,
        title="Show 1 S01E01",
        status=DuplicateStatus.PENDING,
    )
    test_db.add_all([set1, set2])
    await test_db.flush()

    # Add files to delete
    file1 = DuplicateFile(
        set_id=set1.id,
        file_path="/media/movie1.mkv",
        file_size=1000000,
        score=75,
        keep=False,
    )
    file2 = DuplicateFile(
        set_id=set2.id,
        file_path="/media/show1.mkv",
        file_size=500000,
        score=60,
        keep=False,
    )
    test_db.add_all([file1, file2])
    await test_db.commit()

    mock_pipeline_class.return_value = _pipeline(
        SetDeletion(files_deleted=1), SetDeletion(files_deleted=1)
    )

    service = ScheduledDeletionService(test_db)
    summary = await service.run_scheduled_deletion(dry_run=False, send_email=False)

    assert summary["sets_processed"] == 2
    assert summary["files_deleted"] == 2
    assert summary["errors"] == []


@pytest.mark.asyncio
@patch("app.services.deletion.scheduled.DeletionPipeline")
async def test_run_scheduled_deletion_set_exception(mock_pipeline_class, test_db):
    """Test that exception in one set doesn't stop processing others"""
    # Create multiple pending sets
    set1 = DuplicateSet(
        item_id="12345",
        media_type=MediaType.MOVIE,
        title="Movie 1 (2020)",
        status=DuplicateStatus.PENDING,
    )
    set2 = DuplicateSet(
        item_id="67890",
        media_type=MediaType.MOVIE,
        title="Movie 2 (2021)",
        status=DuplicateStatus.PENDING,
    )
    test_db.add_all([set1, set2])
    await test_db.flush()

    # Add files
    file1 = DuplicateFile(
        set_id=set1.id,
        file_path="/media/movie1.mkv",
        file_size=1000000,
        score=75,
        keep=False,
    )
    file2 = DuplicateFile(
        set_id=set2.id,
        file_path="/media/movie2.mkv",
        file_size=500000,
        score=60,
        keep=False,
    )
    test_db.add_all([file1, file2])
    await test_db.commit()

    mock_pipeline_class.return_value = _pipeline(
        Exception("First deletion failed"), SetDeletion(files_deleted=1)
    )

    service = ScheduledDeletionService(test_db)
    summary = await service.run_scheduled_deletion(dry_run=False, send_email=False)

    assert summary["sets_processed"] == 1
    assert summary["files_deleted"] == 1
    assert len(summary["errors"]) == 1
    assert "First deletion failed" in summary["errors"][0]


@pytest.mark.asyncio
async def test_run_scheduled_deletion_includes_timestamp(test_db):
    """Test that summary includes timestamp"""
    service = ScheduledDeletionService(test_db)
    summary = await service.run_scheduled_deletion(dry_run=False, send_email=False)

    assert "timestamp" in summary
    # Verify timestamp is valid ISO format
    timestamp = datetime.fromisoformat(summary["timestamp"])
    assert timestamp.tzinfo is not None  # Should be timezone-aware


@pytest.mark.asyncio
@patch("app.services.notifications.helpers.get_email_service_from_config")
async def test_send_deletion_email_success(mock_get_email, test_db):
    """Test sending deletion summary email"""
    # Mock email service
    mock_email_service = MagicMock()
    mock_email_service.build_email_template.return_value = "<html>Email</html>"
    mock_email_service.send_email.return_value = (True, None)
    mock_get_email.return_value = (mock_email_service, "admin@example.com", None)

    # Create summary
    summary = {
        "sets_processed": 5,
        "files_deleted": 12,
        "errors": [],
        "warnings": ["Radarr cannot import the kept file"],
        "dry_run": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Send email
    service = ScheduledDeletionService(test_db)
    await service._send_deletion_email(summary)

    # Verify email was sent
    mock_email_service.build_email_template.assert_called_once()
    mock_email_service.send_email.assert_called_once()

    # Verify email content includes summary stats
    template_call = mock_email_service.build_email_template.call_args
    assert "5" in template_call.kwargs["content"]  # sets_processed
    assert "12" in template_call.kwargs["content"]  # files_deleted
    assert "Radarr cannot import the kept file" in template_call.kwargs["content"]


@pytest.mark.asyncio
@patch("app.services.notifications.helpers.get_email_service_from_config")
async def test_send_deletion_email_with_errors(mock_get_email, test_db):
    """Test email includes error details when present"""
    # Mock email service
    mock_email_service = MagicMock()
    mock_email_service.build_email_template.return_value = "<html>Email</html>"
    mock_email_service.send_email.return_value = (True, None)
    mock_get_email.return_value = (mock_email_service, "admin@example.com", None)

    # Create summary with errors
    summary = {
        "sets_processed": 3,
        "files_deleted": 7,
        "errors": ["Error 1", "Error 2", "Error 3"],
        "warnings": [],
        "dry_run": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Send email
    service = ScheduledDeletionService(test_db)
    await service._send_deletion_email(summary)

    # Verify email content includes error count
    template_call = mock_email_service.build_email_template.call_args
    content = template_call.kwargs["content"]
    assert "3" in content  # error count


@pytest.mark.asyncio
@patch("app.services.notifications.helpers.get_email_service_from_config")
async def test_send_deletion_email_not_configured(mock_get_email, test_db):
    """Test email is skipped when not configured"""
    # Mock email service not configured
    mock_get_email.return_value = (None, None, "Not configured")

    summary = {
        "sets_processed": 1,
        "files_deleted": 2,
        "errors": [],
        "warnings": [],
        "dry_run": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Send email (should skip silently)
    service = ScheduledDeletionService(test_db)
    await service._send_deletion_email(summary)

    # Should not raise error


@pytest.mark.asyncio
@patch("app.services.deletion.scheduled.DeletionPipeline")
@patch("app.services.notifications.helpers.get_email_service_from_config")
async def test_run_scheduled_deletion_sends_email_when_enabled(
    mock_get_email, mock_pipeline_class, test_db
):
    """Test that email is sent when send_email=True"""
    # Create pending set
    duplicate_set = DuplicateSet(
        item_id="12345",
        media_type=MediaType.MOVIE,
        title="Test Movie (2020)",
        status=DuplicateStatus.PENDING,
    )
    test_db.add(duplicate_set)
    await test_db.flush()

    file1 = DuplicateFile(
        set_id=duplicate_set.id,
        file_path="/media/movie1.mkv",
        file_size=1000000,
        score=75,
        keep=False,
    )
    test_db.add(file1)
    await test_db.commit()

    mock_pipeline_class.return_value = _pipeline(SetDeletion(files_deleted=1))

    # Mock email service
    mock_email_service = MagicMock()
    mock_email_service.build_email_template.return_value = "<html>Email</html>"
    mock_email_service.send_email.return_value = (True, None)
    mock_get_email.return_value = (mock_email_service, "admin@example.com", None)

    # Run deletion with email enabled
    service = ScheduledDeletionService(test_db)
    await service.run_scheduled_deletion(dry_run=False, send_email=True)

    # Verify email was sent
    mock_email_service.send_email.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.deletion.scheduled.DeletionPipeline")
@patch("app.services.notifications.helpers.get_email_service_from_config")
async def test_run_scheduled_deletion_no_email_in_dry_run(
    mock_get_email,
    mock_pipeline_class,
    test_db,
    create_duplicate_set,
    create_duplicate_file,
):
    """A dry run never emails, even when asked to"""
    dup_set = await create_duplicate_set()
    await create_duplicate_file(dup_set.id, keep=False)
    mock_pipeline_class.return_value = _pipeline(SetDeletion(files_deleted=1))

    await ScheduledDeletionService(test_db).run_scheduled_deletion(
        dry_run=True, send_email=True
    )

    mock_get_email.assert_not_called()


@pytest.mark.asyncio
async def test_real_run_deletes_from_disk(
    test_db, create_duplicate_set, create_duplicate_file, tmp_path, monkeypatch
):
    """A dry_run=False run drives the real pipeline, so the file leaves the disk."""
    from app.models import DeletionHistory

    # The media server is reachable, so the refresh stage does not raise
    server = AsyncMock()
    server.refresh_item.return_value = True
    monkeypatch.setattr(
        "app.services.deletion.pipeline.get_media_server",
        AsyncMock(return_value=server),
    )
    keep = tmp_path / "keep.mkv"
    drop = tmp_path / "drop.mkv"
    keep.write_bytes(b"k" * 2048)
    drop.write_bytes(b"d" * 1024)

    dup_set = await create_duplicate_set(title="Bulk Movie")
    await create_duplicate_file(dup_set.id, file_path=str(keep), keep=True, score=90)
    await create_duplicate_file(dup_set.id, file_path=str(drop), keep=False, score=10)

    summary = await ScheduledDeletionService(test_db).run_scheduled_deletion(
        dry_run=False, send_email=False
    )

    assert summary["files_deleted"] == 1
    assert summary["errors"] == []
    assert not drop.exists()
    assert keep.exists()
    assert (await test_db.execute(select(func.count(DeletionHistory.id)))).scalar() == 1
    await test_db.refresh(dup_set)
    assert dup_set.status == DuplicateStatus.PROCESSED


@pytest.mark.asyncio
async def test_dry_run_leaves_files_in_place(
    test_db, create_duplicate_set, create_duplicate_file, tmp_path
):
    """A dry run reports what it would do without deleting or recording anything."""
    from app.models import DeletionHistory

    drop = tmp_path / "drop.mkv"
    drop.write_bytes(b"d" * 1024)
    (tmp_path / "keep.mkv").write_bytes(b"k" * 1024)

    dup_set = await create_duplicate_set(title="Bulk Movie")
    await create_duplicate_file(
        dup_set.id, file_path=str(tmp_path / "keep.mkv"), keep=True, score=90
    )
    await create_duplicate_file(dup_set.id, file_path=str(drop), keep=False, score=10)

    summary = await ScheduledDeletionService(test_db).run_scheduled_deletion(
        dry_run=True, send_email=False
    )

    assert summary["files_deleted"] == 1
    assert drop.exists()
    assert (await test_db.execute(select(func.count(DeletionHistory.id)))).scalar() == 0
    await test_db.refresh(dup_set)
    assert dup_set.status == DuplicateStatus.PENDING
