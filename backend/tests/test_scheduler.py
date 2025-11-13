"""
Tests for the scheduler service
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.scheduler import ScanScheduler, get_scheduler
from app.models import Config


@pytest.mark.asyncio
async def test_get_enabled_libraries_success(test_db):
    """Test retrieving enabled libraries from config"""
    # Setup: Add config with libraries
    config = Config(key="plex_libraries", value="Movies,TV Shows,Anime")
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
    config = Config(key="plex_libraries", value="  Movies  ,  TV Shows  ,  ")
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
@patch("app.api.routes.scan._cleanup_stale_duplicate_sets")
@patch("app.api.routes.scan._process_duplicate_movies")
@patch("app.services.scheduler.PlexService")
@patch("app.services.scheduler.AsyncSessionLocal")
async def test_run_scheduled_scan_movies(
    mock_session_local, mock_plex_service, mock_process_movies, mock_cleanup, test_db
):
    """Test scheduled scan for movie libraries"""
    # Mock AsyncSessionLocal to return test_db
    mock_session_local.return_value.__aenter__.return_value = test_db
    mock_session_local.return_value.__aexit__.return_value = AsyncMock()

    # Setup configs
    test_db.add(Config(key="plex_libraries", value="Movies"))
    test_db.add(Config(key="plex_auth_token", value="encrypted_token_123"))
    test_db.add(Config(key="plex_server_name", value="MyPlexServer"))
    await test_db.commit()

    # Mock Plex service
    mock_library = MagicMock()
    mock_library.type = "movie"
    mock_plex_instance = MagicMock()
    mock_plex_instance.get_library.return_value = mock_library
    mock_plex_instance.find_duplicate_movies.return_value = []
    mock_plex_service.return_value = mock_plex_instance

    # Mock processing functions
    mock_cleanup.return_value = AsyncMock()
    mock_process_movies.return_value = AsyncMock(return_value=(5, 3))

    # Execute
    scheduler = ScanScheduler()
    await scheduler._run_scheduled_scan()

    # Verify
    mock_plex_service.assert_called_once()
    mock_plex_instance.get_library.assert_called_once_with("Movies")
    mock_plex_instance.find_duplicate_movies.assert_called_once_with("Movies")


@pytest.mark.asyncio
@patch("app.api.routes.scan._cleanup_stale_duplicate_sets")
@patch("app.api.routes.scan._process_duplicate_episodes")
@patch("app.services.scheduler.PlexService")
@patch("app.services.scheduler.AsyncSessionLocal")
async def test_run_scheduled_scan_shows(
    mock_session_local, mock_plex_service, mock_process_episodes, mock_cleanup, test_db
):
    """Test scheduled scan for TV show libraries"""
    # Mock AsyncSessionLocal to return test_db
    mock_session_local.return_value.__aenter__.return_value = test_db
    mock_session_local.return_value.__aexit__.return_value = AsyncMock()

    # Setup configs
    test_db.add(Config(key="plex_libraries", value="TV Shows"))
    test_db.add(Config(key="plex_auth_token", value="encrypted_token_123"))
    await test_db.commit()

    # Mock Plex service
    mock_library = MagicMock()
    mock_library.type = "show"
    mock_plex_instance = MagicMock()
    mock_plex_instance.get_library.return_value = mock_library
    mock_plex_instance.find_duplicate_episodes.return_value = []
    mock_plex_service.return_value = mock_plex_instance

    # Mock processing functions
    mock_cleanup.return_value = AsyncMock()
    mock_process_episodes.return_value = AsyncMock(return_value=(2, 1))

    # Execute
    scheduler = ScanScheduler()
    await scheduler._run_scheduled_scan()

    # Verify
    mock_plex_instance.find_duplicate_episodes.assert_called_once_with("TV Shows")
    mock_process_episodes.assert_called_once()


@pytest.mark.asyncio
async def test_run_scheduled_scan_no_plex_config(test_db):
    """Test scheduled scan fails gracefully when Plex not configured"""
    # Setup: No Plex config
    test_db.add(Config(key="plex_libraries", value="Movies"))
    await test_db.commit()

    # Execute
    scheduler = ScanScheduler()
    await scheduler._run_scheduled_scan()

    # Should complete without error (logs error internally)
    # No assertions needed - just verify no exception raised


@pytest.mark.asyncio
@patch("app.services.scheduler.PlexService")
@patch("app.services.scheduler.AsyncSessionLocal")
async def test_run_scheduled_scan_library_error_continues(
    mock_session_local, mock_plex_service, test_db
):
    """Test that scan continues if one library fails"""
    # Mock AsyncSessionLocal to return test_db
    mock_session_local.return_value.__aenter__.return_value = test_db
    mock_session_local.return_value.__aexit__.return_value = AsyncMock()

    # Setup configs with multiple libraries
    test_db.add(Config(key="plex_libraries", value="Movies,TV Shows"))
    test_db.add(Config(key="plex_auth_token", value="encrypted_token_123"))
    await test_db.commit()

    # Mock Plex service to fail on first library
    mock_plex_instance = MagicMock()
    mock_plex_instance.get_library.side_effect = [
        Exception("Library not found"),  # First call fails
        MagicMock(type="show"),  # Second call succeeds
    ]
    mock_plex_service.return_value = mock_plex_instance

    # Execute
    scheduler = ScanScheduler()
    await scheduler._run_scheduled_scan()

    # Verify both libraries were attempted
    assert mock_plex_instance.get_library.call_count == 2


@pytest.mark.asyncio
@patch("app.services.scheduled_deletion.ScheduledDeletionService")
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
async def test_start_daily_mode():
    """Test scheduler starts in daily mode"""
    scheduler = ScanScheduler()

    # Execute
    await scheduler.start(
        scan_mode="daily",
        scan_time="02:00",
        deletion_mode="daily",
        deletion_time="03:00",
    )

    # Verify
    assert scheduler.is_running is True
    assert scheduler.scheduler.running is True

    # Verify jobs exist
    jobs = scheduler.scheduler.get_jobs()
    assert len(jobs) == 2
    job_ids = [job.id for job in jobs]
    assert "duplicate_scan" in job_ids
    assert "scheduled_deletion" in job_ids

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
        deletion_mode="interval",
        deletion_time="00:30",
        deletion_interval_hours=12,
    )

    # Verify
    assert scheduler.is_running is True

    # Verify jobs exist with interval triggers
    jobs = scheduler.scheduler.get_jobs()
    assert len(jobs) == 2

    # Cleanup
    await scheduler.stop()


@pytest.mark.asyncio
async def test_start_mixed_mode():
    """Test scheduler with daily scan and interval deletion"""
    scheduler = ScanScheduler()

    # Execute
    await scheduler.start(
        scan_mode="daily",
        scan_time="02:00",
        deletion_mode="interval",
        deletion_time="00:00",
        deletion_interval_hours=4,
    )

    # Verify
    assert scheduler.is_running is True

    jobs = scheduler.scheduler.get_jobs()
    assert len(jobs) == 2

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
