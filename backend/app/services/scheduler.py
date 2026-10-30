"""
Background scheduler for automated duplicate scanning
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import ScanIntervalHours, ScanScheduleMode, ScanTime, settings
from app.core.database import AsyncSessionLocal
from app.models import Config
from app.services.media_server import get_media_servers
from app.services.scan.runner import run_scan

logger = logging.getLogger(__name__)


# The System page reads the schedule every few seconds: a bad value warns once
_reported_invalid: set[str] = set()


class Schedule(BaseModel):
    """When scheduled scans run, and whether a deletion follows each one"""

    enable_scheduled_scans: bool
    scan_schedule_mode: ScanScheduleMode
    scheduled_scan_time: ScanTime
    scan_interval_hours: ScanIntervalHours
    enable_scheduled_deletion: bool


async def load_schedule(db: AsyncSession) -> Schedule:
    """The schedule in effect: each value saved in Settings, or else the
    environment variable of the same name, which also stands in for a saved
    value that is not valid"""
    keys = list(Schedule.model_fields)
    result = await db.execute(select(Config).where(Config.key.in_(keys)))
    values = {key: getattr(settings, key) for key in keys}
    values.update({item.key: item.value for item in result.scalars()})
    try:
        return Schedule.model_validate(values)
    except ValidationError as e:
        for error in e.errors():
            key = str(error["loc"][0])
            if f"{key}={values[key]}" not in _reported_invalid:
                _reported_invalid.add(f"{key}={values[key]}")
                logger.warning(
                    f"Saved {key} {values[key]!r} is not valid ({error['msg']}), "
                    f"using {getattr(settings, key)!r} until the schedule is saved again"
                )
            values[key] = getattr(settings, key)
    return Schedule.model_validate(values)


class ScanScheduler:
    """Manages scheduled duplicate scans"""

    def __init__(self):
        """Initialize the scheduler"""
        self.scheduler = AsyncIOScheduler()
        self.is_running = False

    async def _run_scheduled_scan(self):
        """Execute a scheduled duplicate scan across every configured server."""
        logger.info("Starting scheduled duplicate scan")

        async with AsyncSessionLocal() as db:
            try:
                servers = await get_media_servers(db)
                if not servers:
                    logger.error("No media server configured - skipping scheduled scan")
                    return

                totals = await run_scan(db)
                if not totals.libraries_scanned:
                    logger.warning("No libraries selected - skipping scheduled scan")
                    return

                logger.info(
                    f"Scheduled scan complete: {totals.sets_created} new sets, "
                    f"{totals.sets_updated} updated, {totals.sets_removed} removed"
                )

                try:
                    from app.services.notifications.email import (
                        send_scan_complete_email,
                    )

                    await send_scan_complete_email(
                        db=db,
                        duplicates_found=totals.duplicates_found,
                        sets_created=totals.sets_created,
                        sets_existing=totals.sets_updated,
                        libraries_scanned=totals.libraries_scanned,
                    )
                except Exception as e:
                    logger.warning(f"Failed to send scheduled scan email: {e}")

                await self._schedule_deletion_if_enabled(db)

            except Exception as e:
                logger.error(f"Scheduled scan failed: {e}", exc_info=True)

    async def _schedule_deletion_if_enabled(self, db: AsyncSession) -> None:
        """Queue the deletion pass that follows a scan, when it is switched on."""
        if not (await load_schedule(db)).enable_scheduled_deletion:
            return

        deletion_time = datetime.now(timezone.utc) + timedelta(minutes=30)
        logger.info("Scheduled deletion enabled - running it in 30 minutes")
        self.scheduler.add_job(
            self._run_scheduled_deletion,
            trigger="date",
            run_date=deletion_time,
            id="scheduled_deletion",
            name="Scheduled Deletion",
            replace_existing=True,
        )

    async def _run_scheduled_deletion(self):
        """Execute scheduled deletion of approved duplicates"""
        logger.info("Starting scheduled deletion")

        async with AsyncSessionLocal() as db:
            try:
                from app.services.deletion.scheduled import ScheduledDeletionService

                deletion_service = ScheduledDeletionService(db)
                summary = await deletion_service.run_scheduled_deletion(
                    dry_run=False,
                    send_email=True,
                )

                logger.info(
                    f"Scheduled deletion complete: {summary['sets_processed']} sets, "
                    f"{summary['files_deleted']} files, {len(summary['errors'])} errors"
                )

            except Exception as e:
                logger.error(f"Scheduled deletion failed: {e}", exc_info=True)

    async def apply(self, schedule: Schedule) -> None:
        """
        Run scans on this schedule, or none when it has them off.

        Every save in Settings lands here, so the deletion the last scan queued
        stays, unless this schedule turns scans or the deletion off.
        """
        if not schedule.enable_scheduled_scans:
            await self.stop()
            logger.info("Scheduled scans disabled")
            return
        if not schedule.enable_scheduled_deletion and self.scheduler.get_job(
            "scheduled_deletion"
        ):
            self.scheduler.remove_job("scheduled_deletion")

        # Both modes read the start time in the scheduler's time zone, the TZ
        # the app runs with
        zone = self.scheduler.timezone
        hour, minute = map(int, schedule.scheduled_scan_time.split(":"))
        if schedule.scan_schedule_mode == "daily":
            trigger = CronTrigger(hour=hour, minute=minute, timezone=zone)
            when = f"daily at {schedule.scheduled_scan_time}"
        else:
            interval = timedelta(hours=schedule.scan_interval_hours)
            now = datetime.now(zone)
            start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            # Scans keep to the grid through today's start time, so a start or
            # save skips none: from 03:15 every 6 hours, 17:20 runs next at 21:15
            while start > now:
                start -= interval
            trigger = IntervalTrigger(
                hours=schedule.scan_interval_hours, start_date=start
            )
            when = (
                f"every {schedule.scan_interval_hours}h "
                f"from {schedule.scheduled_scan_time}"
            )

        job = self.scheduler.add_job(
            self._run_scheduled_scan,
            trigger=trigger,
            id="duplicate_scan",
            name="Scheduled Duplicate Scan",
            replace_existing=True,
        )
        if not self.is_running:
            self.scheduler.start()
            self.is_running = True

        deletion = (
            ", each followed by a deletion 30 minutes after it completes"
            if schedule.enable_scheduled_deletion
            else ""
        )
        logger.info(
            f"Scheduled scans {when} ({zone}), next at {job.next_run_time}{deletion}"
        )

    async def stop(self):
        """Stop the scheduler"""
        if not self.is_running:
            return

        logger.info("Stopping scan scheduler")
        self.scheduler.shutdown(wait=False)

        # Give the scheduler a moment to fully shut down
        for _ in range(10):
            if not self.scheduler.running:
                break
            await asyncio.sleep(0.01)

        self.is_running = False
        logger.info("Scan scheduler stopped")


# Global scheduler instance
_scheduler: Optional[ScanScheduler] = None


def get_scheduler() -> ScanScheduler:
    """Get or create the global scheduler instance"""
    global _scheduler
    if _scheduler is None:
        _scheduler = ScanScheduler()
    return _scheduler
