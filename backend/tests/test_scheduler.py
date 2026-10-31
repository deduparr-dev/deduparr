"""
Tests for the scheduler service
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.main import app, lifespan
from app.services.scan.runner import ScanTotals
from app.services.scheduler import (
    ScanScheduler,
    Schedule,
    get_scheduler,
    load_schedule,
)
from app.models import Config


def scans(**values) -> Schedule:
    """A schedule with scans on, daily at 02:00 unless the values say otherwise"""
    return Schedule(
        **{
            "enable_scheduled_scans": True,
            "scan_schedule_mode": "daily",
            "scheduled_scan_time": "02:00",
            "scan_interval_hours": 24,
            "enable_scheduled_deletion": False,
            **values,
        }
    )


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
        duplicates_found=4, sets_created=2, sets_updated=1, libraries_scanned=["Movies"]
    )

    test_db.add_all(
        [
            Config(key="plex_libraries", value="Movies, TV Shows"),
            Config(key="plex_auth_token", value="token"),
        ]
    )
    await test_db.commit()

    await ScanScheduler()._run_scheduled_scan()

    # Each server's own selection is read inside the runner
    mock_run_scan.assert_awaited_once_with(test_db)


@pytest.mark.asyncio
@patch("app.services.scheduler.run_scan", new_callable=AsyncMock)
@patch("app.services.scheduler.AsyncSessionLocal")
async def test_run_scheduled_scan_needs_a_media_server(
    mock_session_local, mock_run_scan, test_db
):
    """With libraries but no server credentials the scan is skipped."""
    mock_session_local.return_value.__aenter__.return_value = test_db
    mock_session_local.return_value.__aexit__.return_value = AsyncMock()

    test_db.add(Config(key="plex_libraries", value="Movies"))
    await test_db.commit()

    await ScanScheduler()._run_scheduled_scan()

    mock_run_scan.assert_not_awaited()


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
    mock_run_scan.return_value = ScanTotals(libraries_scanned=["Movies"])

    test_db.add_all(
        [
            Config(key="plex_libraries", value="Movies"),
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
@patch("app.services.scheduler.run_scan", new_callable=AsyncMock)
@patch("app.services.scheduler.AsyncSessionLocal")
async def test_run_scheduled_scan_queues_no_deletion_after_skipping_something(
    mock_session_local, mock_run_scan, test_db
):
    """Deletion does not act on pending sets this scan could not check."""
    mock_session_local.return_value.__aenter__.return_value = test_db
    mock_session_local.return_value.__aexit__.return_value = AsyncMock()
    mock_run_scan.return_value = ScanTotals(
        libraries_scanned=["Movies"], skipped=["Plex: rejected"]
    )

    test_db.add_all(
        [
            Config(key="plex_auth_token", value="token"),
            Config(key="enable_scheduled_deletion", value="true"),
        ]
    )
    await test_db.commit()

    scheduler = ScanScheduler()
    scheduler.scheduler = MagicMock()
    await scheduler._run_scheduled_scan()

    scheduler.scheduler.add_job.assert_not_called()


@pytest.mark.asyncio
async def test_start_daily_mode():
    """Test scheduler starts in daily mode"""
    scheduler = ScanScheduler()

    # Execute
    await scheduler.apply(scans())

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
    await scheduler.apply(
        scans(
            scan_schedule_mode="interval",
            scheduled_scan_time="00:00",
            scan_interval_hours=6,
        )
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
    await scheduler.apply(scans(enable_scheduled_deletion=True))

    # Verify
    assert scheduler.is_running is True

    # Only one job (scan) - deletion runs after scan completes
    jobs = scheduler.scheduler.get_jobs()
    assert len(jobs) == 1

    # Cleanup
    await scheduler.stop()


@pytest.mark.asyncio
@patch("app.main.get_scheduler")
@patch("app.main.AsyncSessionLocal")
@patch("app.main.init_db", new_callable=AsyncMock)
async def test_startup_runs_the_stored_schedule(
    mock_init_db, mock_session_local, mock_get_scheduler, test_db
):
    """The schedule saved in Settings is the one running after a restart."""
    mock_session_local.return_value.__aenter__.return_value = test_db
    scheduler = mock_get_scheduler.return_value = ScanScheduler()

    test_db.add_all(
        [
            Config(key="enable_scheduled_scans", value="true"),
            Config(key="scan_schedule_mode", value="interval"),
            Config(key="scan_interval_hours", value="6"),
        ]
    )
    await test_db.commit()

    async with lifespan(app):
        trigger = scheduler.scheduler.get_job("duplicate_scan").trigger

    assert trigger.interval == timedelta(hours=6)


@pytest.mark.asyncio
async def test_load_schedule_skips_a_saved_value_that_is_not_valid(test_db, caplog):
    """A saved value that is not valid gives way to the environment's, with a warning."""
    test_db.add_all(
        [
            Config(key="scan_schedule_mode", value="interval"),
            Config(key="scheduled_scan_time", value="25:00"),
            Config(key="scan_interval_hours", value="every day"),
        ]
    )
    await test_db.commit()

    schedule = await load_schedule(test_db)

    assert schedule.scan_schedule_mode == "interval"
    assert schedule.scheduled_scan_time == settings.scheduled_scan_time
    assert schedule.scan_interval_hours == settings.scan_interval_hours
    assert "scheduled_scan_time '25:00' is not valid" in caplog.text
    assert "scan_interval_hours 'every day' is not valid" in caplog.text

    # The System page reads it every few seconds
    caplog.clear()
    await load_schedule(test_db)
    assert "is not valid" not in caplog.text


@pytest.mark.asyncio
async def test_interval_scans_keep_to_the_grid_through_the_start_time():
    """Every 6 hours from two hours ago runs next in four hours, not tomorrow."""
    scheduler = ScanScheduler()
    now = datetime.now(scheduler.scheduler.timezone)
    start = now.replace(second=0, microsecond=0) - timedelta(hours=2)

    await scheduler.apply(
        scans(
            scan_schedule_mode="interval",
            scheduled_scan_time=f"{start:%H:%M}",
            scan_interval_hours=6,
        )
    )

    next_run = scheduler.scheduler.get_job("duplicate_scan").next_run_time
    assert next_run == start + timedelta(hours=6)

    await scheduler.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["daily", "interval"])
async def test_scans_start_at_the_time_in_the_app_time_zone(mode):
    """02:00 is 02:00 in the time zone the app runs in, in either mode."""
    scheduler = ScanScheduler()
    scheduler.scheduler.configure(timezone="Asia/Kolkata")  # UTC+05:30

    await scheduler.apply(scans(scan_schedule_mode=mode, scan_interval_hours=6))

    next_run = scheduler.scheduler.get_job("duplicate_scan").next_run_time
    local = next_run.astimezone(ZoneInfo("Asia/Kolkata"))
    assert (local.hour % 6, local.minute) == (2, 0)

    await scheduler.stop()


@pytest.mark.asyncio
async def test_start_already_running():
    """Test that starting scheduler twice doesn't duplicate jobs"""
    scheduler = ScanScheduler()

    # Start first time
    await scheduler.apply(scans())
    jobs_count_first = len(scheduler.scheduler.get_jobs())

    # Try to start again
    await scheduler.apply(scans())
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
    await scheduler.apply(scans())
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
@pytest.mark.parametrize("hours", [48, 168])
async def test_a_restart_does_not_push_back_a_long_interval(hours):
    """Through today's start time, every restart moved the next scan a full interval."""
    schedule = Schedule(
        enable_scheduled_scans=True,
        scan_schedule_mode="interval",
        scheduled_scan_time="02:00",
        scan_interval_hours=hours,
        enable_scheduled_deletion=False,
    )
    next_runs = []
    with patch("app.services.scheduler.datetime", wraps=datetime) as clock:
        for day in (1, 2):
            clock.now.return_value = datetime(2026, 11, day, 3, 0, tzinfo=timezone.utc)
            scheduler = ScanScheduler()
            scheduler.scheduler.configure(timezone=timezone.utc)
            await scheduler.apply(schedule)
            next_runs.append(
                scheduler.scheduler.get_job("duplicate_scan").trigger.start_date
            )
            await scheduler.stop()

    assert (next_runs[1] - next_runs[0]) % timedelta(hours=hours) == timedelta(0)


@pytest.mark.asyncio
async def test_saving_the_schedule_keeps_a_queued_deletion():
    """Any save in Settings re-applies the schedule, which used to drop it."""
    schedule = Schedule(
        enable_scheduled_scans=True,
        scan_schedule_mode="daily",
        scheduled_scan_time="02:00",
        scan_interval_hours=24,
        enable_scheduled_deletion=True,
    )
    scheduler = ScanScheduler()
    await scheduler.apply(schedule)
    scheduler.scheduler.add_job(
        lambda: None,
        trigger="date",
        run_date=datetime.now(timezone.utc) + timedelta(minutes=30),
        id="scheduled_deletion",
    )

    await scheduler.apply(schedule)
    assert scheduler.scheduler.get_job("scheduled_deletion")

    await scheduler.apply(
        schedule.model_copy(update={"enable_scheduled_deletion": False})
    )
    assert scheduler.scheduler.get_job("scheduled_deletion") is None
    await scheduler.stop()


def test_get_scheduler_singleton():
    """Test that get_scheduler returns the same instance"""
    scheduler1 = get_scheduler()
    scheduler2 = get_scheduler()

    assert scheduler1 is scheduler2


@pytest.mark.asyncio
@patch("app.services.scheduler.run_scan", new_callable=AsyncMock)
@patch("app.services.scheduler.AsyncSessionLocal")
async def test_run_scheduled_scan_stops_when_nothing_was_scanned(
    mock_session_local, mock_run_scan, test_db
):
    """No libraries selected means no scan happened, so no deletion follows."""
    mock_session_local.return_value.__aenter__.return_value = test_db
    mock_session_local.return_value.__aexit__.return_value = AsyncMock()
    mock_run_scan.return_value = ScanTotals()

    test_db.add_all(
        [
            Config(key="plex_auth_token", value="token"),
            Config(key="enable_scheduled_deletion", value="true"),
        ]
    )
    await test_db.commit()

    scheduler = ScanScheduler()
    scheduler.scheduler = MagicMock()
    await scheduler._run_scheduled_scan()

    assert not scheduler.scheduler.add_job.called
