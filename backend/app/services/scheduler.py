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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import Config
from app.services.media_server import get_media_servers
from app.services.scan.runner import run_scan

logger = logging.getLogger(__name__)


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
        result = await db.execute(
            select(Config).where(Config.key == "enable_scheduled_deletion")
        )
        config = result.scalar_one_or_none()
        if not (config and config.value == "true"):
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

    async def start(
        self,
        scan_mode: str = "daily",
        scan_time: str = "02:00",
        scan_interval_hours: int = 24,
    ):
        """
        Start the scheduler

        Args:
            scan_mode: "daily" or "interval"
            scan_time: Starting time for scans (HH:MM, 24-hour format)
            scan_interval_hours: Hours between scans when mode is "interval" (1-168)

        Note:
            Scheduled deletion runs automatically 30 minutes after each scan completes
            if enable_scheduled_deletion config is set to "true"
        """
        if self.is_running:
            logger.warning("Scheduler is already running")
            return

        # Configure scan job based on mode
        if scan_mode == "daily":
            scan_hour, scan_minute = map(int, scan_time.split(":"))
            scan_trigger = CronTrigger(hour=scan_hour, minute=scan_minute)
            logger.info(f"Starting scan scheduler to run daily at {scan_time}")
        else:  # interval mode
            scan_hour, scan_minute = map(int, scan_time.split(":"))
            # Calculate next occurrence from now
            now = datetime.now(timezone.utc)
            next_run = now.replace(
                hour=scan_hour, minute=scan_minute, second=0, microsecond=0
            )

            # If the time has already passed today, start from tomorrow
            if next_run <= now:
                next_run = next_run + timedelta(days=1)

            scan_trigger = IntervalTrigger(
                hours=scan_interval_hours,
                start_date=next_run,
            )
            logger.info(
                f"Starting scan scheduler to run every {scan_interval_hours} hours starting at {scan_time}"
            )

        self.scheduler.add_job(
            self._run_scheduled_scan,
            trigger=scan_trigger,
            id="duplicate_scan",
            name="Scheduled Duplicate Scan",
            replace_existing=True,
        )

        self.scheduler.start()
        self.is_running = True
        logger.info("Scan scheduler started successfully")

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

    async def run_now(self):
        """Trigger an immediate scan (in addition to scheduled ones)"""
        logger.info("Triggering immediate scan")
        await self._run_scheduled_scan()

    def is_deletion_scheduled(self) -> bool:
        """Check if a post-scan deletion is currently scheduled"""
        job = self.scheduler.get_job("scheduled_deletion_after_scan")
        return job is not None

    def get_scheduled_deletion_time(self) -> Optional[datetime]:
        """Get the scheduled deletion time if one is scheduled"""
        job = self.scheduler.get_job("scheduled_deletion_after_scan")
        if job and job.next_run_time:
            return job.next_run_time
        return None


# Global scheduler instance
_scheduler: Optional[ScanScheduler] = None


def get_scheduler() -> ScanScheduler:
    """Get or create the global scheduler instance"""
    global _scheduler
    if _scheduler is None:
        _scheduler = ScanScheduler()
    return _scheduler
