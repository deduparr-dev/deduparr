"""
Tests for the scheduler service
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.scan.runner import ScanTotals
from app.services.scheduler import ScanScheduler, get_scheduler
from app.models import Config


@pytest.mark.asyncio
async def test_get_enabled_libraries_success(test_db):
    """Test retrieving enabled libraries from config"""
    # Setup: Add config with libraries
    config = Config(key="media_libraries", value="Movies,TV Shows,Anime")
    test_db.add(config)
    await test_db.commit()

    # Execute
    scheduler = ScanScheduler()
    libraries = await scheduler._get_enabled_libraries(test_db)

    # Verify
    assert len(libraries) == 3
    assert "Movies" in libraries
    assert "TV Shows" in libraries
    assert "Anime" in libraries


@pytest.mark.asyncio
async def test_get_enabled_libraries_empty(test_db):
    """Test retrieving libraries when none configured"""
    scheduler = ScanScheduler()
    libraries = await scheduler._get_enabled_libraries(test_db)

    # Should return empty list and log warning
    assert libraries == []


@pytest.mark.asyncio
async def test_get_enabled_libraries_strips_whitespace(test_db):
    """Test that library names are properly trimmed"""
    # Setup: Add config with extra whitespace
    config = Config(key="media_libraries", value="  Movies  ,  TV Shows  ,  ")
    test_db.add(config)
    await test_db.commit()

    # Execute
    scheduler = ScanScheduler()
    libraries = await scheduler._get_enabled_libraries(test_db)

    # Verify whitespace is stripped and empty strings removed
    assert len(libraries) == 2
    assert "Movies" in libraries
    assert "TV Shows" in libraries


@pytest.mark.asyncio
@patch("app.services.scheduler.run_scan", new_callable=AsyncMock)
@patch("app.services.scheduler.AsyncSessionLocal")
async def test_run_scheduled_scan_delegates_to_the_runner(
    mock_session_local, mock_run_scan, test_db
):
    """The scheduler hands the configured libraries to the shared scan runner."""
    mock_session_local.return_value.__aenter__.return_value = test_db
    mock_session_local.return_value.__aexit__.return_value = AsyncMock()
    mock_run_scan.return_value = ScanTotals(
        duplicates_found=4, sets_created=2, sets_updated=1
    )

    test_db.add_all(
        [
            Config(key="media_libraries", value="Movies, TV Shows"),
            Config(key="plex_auth_token", value="token"),
        ]
    )
    await test_db.commit()

    await ScanScheduler()._run_scheduled_scan()

    mock_run_scan.assert_awaited_once_with(test_db, ["Movies", "TV Shows"])


@pytest.mark.asyncio
@patch("app.services.scheduler.run_scan", new_callable=AsyncMock)
@patch("app.services.scheduler.AsyncSessionLocal")
async def test_run_scheduled_scan_needs_a_media_server(
    mock_session_local, mock_run_scan, test_db
):
    """With libraries but no server credentials the scan is skipped."""
    mock_session_local.return_value.__aenter__.return_value = test_db
    mock_session_local.return_value.__aexit__.return_value = AsyncMock()

    test_db.add(Config(key="media_libraries", value="Movies"))
    await test_db.commit()

    await ScanScheduler()._run_scheduled_scan()

    mock_run_scan.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_scheduled_scan_no_plex_config(test_db):
    """Test scheduled scan fails gracefully when Plex not configured"""
    # Setup: No Plex config
    test_db.add(Config(key="media_libraries", value="Movies"))
    await test_db.commit()

    # Execute
    scheduler = ScanScheduler()
    await scheduler._run_scheduled_scan()

    # Should complete without error (logs error internally)
    # No assertions needed - just verify no exception raised


@pytest.mark.asyncio
@patch("app.services.deletion.scheduled.ScheduledDeletionService")
@patch("app.services.scheduler.AsyncSessionLocal")
async def test_run_scheduled_deletion(
    mock_session_local, mock_deletion_service, test_db
):
    """Test scheduled deletion execution"""
    # Mock AsyncSessionLocal to return test_db
    mock_session_local.return_value.__aenter__.return_value = test_db
    mock_session_local.return_value.__aexit__.return_value = AsyncMock()

    # Mock deletion service
    mock_service_instance = AsyncMock()
    mock_service_instance.run_scheduled_deletion.return_value = {
        "sets_processed": 3,
        "files_deleted": 7,
        "errors": [],
    }
    mock_deletion_service.return_value = mock_service_instance

    # Execute
    scheduler = ScanScheduler()
    await scheduler._run_scheduled_deletion()

    # Verify
    mock_deletion_service.assert_called_once()
    mock_service_instance.run_scheduled_deletion.assert_called_once_with(
        dry_run=False, send_email=True
    )


@pytest.mark.asyncio
@patch("app.services.scheduler.run_scan", new_callable=AsyncMock)
@patch("app.services.scheduler.AsyncSessionLocal")
async def test_run_scheduled_scan_queues_deletion_when_enabled(
    mock_session_local, mock_run_scan, test_db
):
    """Deletion is queued after a scan only when the setting is on."""
    mock_session_local.return_value.__aenter__.return_value = test_db
    mock_session_local.return_value.__aexit__.return_value = AsyncMock()
    mock_run_scan.return_value = ScanTotals()

    test_db.add_all(
        [
            Config(key="media_libraries", value="Movies"),
            Config(key="plex_auth_token", value="token"),
            Config(key="enable_scheduled_deletion", value="true"),
        ]
    )
    await test_db.commit()

    scheduler = ScanScheduler()
    scheduler.scheduler = MagicMock()
    await scheduler._run_scheduled_scan()

    assert scheduler.scheduler.add_job.called
    assert scheduler.scheduler.add_job.call_args.kwargs["id"] == "scheduled_deletion"


@pytest.mark.asyncio
async def test_start_daily_mode():
    """Test scheduler starts in daily mode"""
    scheduler = ScanScheduler()

    # Execute
    await scheduler.start(
        scan_mode="daily",
        scan_time="02:00",
    )

    # Verify
    assert scheduler.is_running is True
    assert scheduler.scheduler.running is True

    # Verify only scan job exists (deletion runs after scan if enabled)
    jobs = scheduler.scheduler.get_jobs()
    assert len(jobs) == 1
    job_ids = [job.id for job in jobs]
    assert "duplicate_scan" in job_ids

    # Cleanup
    await scheduler.stop()


@pytest.mark.asyncio
async def test_start_interval_mode():
    """Test scheduler starts in interval mode"""
    scheduler = ScanScheduler()

    # Execute
    await scheduler.start(
        scan_mode="interval",
        scan_time="00:00",
        scan_interval_hours=6,
    )

    # Verify
    assert scheduler.is_running is True

    # Verify only scan job exists
    jobs = scheduler.scheduler.get_jobs()
    assert len(jobs) == 1

    # Cleanup
    await scheduler.stop()


@pytest.mark.asyncio
async def test_start_mixed_mode():
    """Test scheduler with daily scan (deletion now runs after scan, not separately)"""
    scheduler = ScanScheduler()

    # Execute
    await scheduler.start(
        scan_mode="daily",
        scan_time="02:00",
    )

    # Verify
    assert scheduler.is_running is True

    # Only one job (scan) - deletion runs after scan completes
    jobs = scheduler.scheduler.get_jobs()
    assert len(jobs) == 1

    # Cleanup
    await scheduler.stop()


@pytest.mark.asyncio
async def test_start_already_running():
    """Test that starting scheduler twice doesn't duplicate jobs"""
    scheduler = ScanScheduler()

    # Start first time
    await scheduler.start(scan_mode="daily", scan_time="02:00")
    jobs_count_first = len(scheduler.scheduler.get_jobs())

    # Try to start again
    await scheduler.start(scan_mode="daily", scan_time="02:00")
    jobs_count_second = len(scheduler.scheduler.get_jobs())

    # Should still have same number of jobs
    assert jobs_count_first == jobs_count_second

    # Cleanup
    await scheduler.stop()


@pytest.mark.asyncio
async def test_stop_scheduler():
    """Test stopping the scheduler"""
    scheduler = ScanScheduler()

    # Start and then stop
    await scheduler.start(scan_mode="daily", scan_time="02:00")
    assert scheduler.is_running is True

    await scheduler.stop()
    assert scheduler.is_running is False
    assert scheduler.scheduler.running is False


@pytest.mark.asyncio
async def test_stop_not_running():
    """Test stopping scheduler that's not running"""
    scheduler = ScanScheduler()

    # Should not raise error
    await scheduler.stop()
    assert scheduler.is_running is False


@pytest.mark.asyncio
@patch("app.services.scheduler.ScanScheduler._run_scheduled_scan")
async def test_run_now(mock_run_scan):
    """Test triggering immediate scan"""
    mock_run_scan.return_value = None

    scheduler = ScanScheduler()
    await scheduler.run_now()

    # Verify scan was triggered
    mock_run_scan.assert_called_once()


def test_get_scheduler_singleton():
    """Test that get_scheduler returns the same instance"""
    scheduler1 = get_scheduler()
    scheduler2 = get_scheduler()

    assert scheduler1 is scheduler2
