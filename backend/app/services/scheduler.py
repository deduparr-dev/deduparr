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
from app.models import Config, ScoringRule
from app.services.plex_service import PlexService
from app.services.scoring_engine import ScoringEngine

logger = logging.getLogger(__name__)


class ScanScheduler:
    """Manages scheduled duplicate scans"""

    def __init__(self):
        """Initialize the scheduler"""
        self.scheduler = AsyncIOScheduler()
        self.is_running = False

    async def _get_enabled_libraries(self, db: AsyncSession) -> list[str]:
        """Get list of enabled Plex libraries from config"""
        result = await db.execute(select(Config).where(Config.key == "plex_libraries"))
        config = result.scalar_one_or_none()

        if not config or not config.value:
            logger.warning("No Plex libraries configured for scheduled scans")
            return []

        # Value is stored as comma-separated string
        libraries = [lib.strip() for lib in config.value.split(",") if lib.strip()]
        logger.info(f"Found {len(libraries)} configured libraries for scanning")
        return libraries

    async def _run_scheduled_scan(self):
        """Execute a scheduled duplicate scan"""
        logger.info("Starting scheduled duplicate scan")

        async with AsyncSessionLocal() as db:
            try:
                # Get enabled libraries
                libraries = await self._get_enabled_libraries(db)

                if not libraries:
                    logger.warning("No libraries configured - skipping scheduled scan")
                    return

                # Get Plex credentials from config
                result = await db.execute(
                    select(Config).where(Config.key == "plex_auth_token")
                )
                token_config = result.scalar_one_or_none()

                result = await db.execute(
                    select(Config).where(Config.key == "plex_server_name")
                )
                server_config = result.scalar_one_or_none()

                if not token_config:
                    logger.error("Plex not configured - cannot run scheduled scan")
                    return

                # Convert to plain string to detach from SQLAlchemy session
                encrypted_token = (
                    str(token_config.value) if token_config.value else None
                )
                server_name = (
                    str(server_config.value)
                    if server_config and server_config.value
                    else None
                )

                # Initialize services
                plex_service = PlexService(
                    encrypted_token=encrypted_token, server_name=server_name
                )
                scoring_engine = ScoringEngine()

                # Get custom scoring rules
                rules_result = await db.execute(
                    select(ScoringRule).where(ScoringRule.enabled)
                )
                scoring_rules = rules_result.scalars().all()
                custom_rules = [
                    {
                        "pattern": rule.pattern,
                        "score_modifier": rule.score_modifier,
                        "rule_type": rule.rule_type.value,
                    }
                    for rule in scoring_rules
                ]

                # Import here to avoid circular dependency
                from app.api.routes.scan import (
                    _cleanup_stale_duplicate_sets,
                    _process_duplicate_movies,
                    _process_duplicate_episodes,
                )
                from app.models.duplicate import MediaType

                total_sets_created = 0
                total_sets_existing = 0

                # Scan each library
                for library_name in libraries:
                    try:
                        logger.info(f"Scanning library: {library_name}")
                        library = plex_service.get_library(library_name)

                        if library.type == "movie":
                            movie_dupes = plex_service.find_duplicate_movies(
                                library_name
                            )
                            await _cleanup_stale_duplicate_sets(
                                db, movie_dupes, MediaType.MOVIE
                            )
                            sets_created, sets_updated, _ = (
                                await _process_duplicate_movies(
                                    db, movie_dupes, scoring_engine, custom_rules
                                )
                            )
                            total_sets_created += sets_created
                            total_sets_existing += sets_updated

                        elif library.type == "show":
                            episode_dupes = plex_service.find_duplicate_episodes(
                                library_name
                            )
                            await _cleanup_stale_duplicate_sets(
                                db, episode_dupes, MediaType.EPISODE
                            )
                            sets_created, sets_updated, _ = (
                                await _process_duplicate_episodes(
                                    db, episode_dupes, scoring_engine, custom_rules
                                )
                            )
                            total_sets_created += sets_created
                            total_sets_existing += sets_updated

                        else:
                            logger.warning(f"Unsupported library type: {library.type}")

                    except Exception as e:
                        logger.error(
                            f"Error scanning library '{library_name}': {e}",
                            exc_info=True,
                        )
                        continue

                await db.commit()
                logger.info(
                    f"Scheduled scan complete: {total_sets_created} new sets, "
                    f"{total_sets_existing} existing sets"
                )

                # Send email notification
                try:
                    from app.services.email_notifications import (
                        send_scan_complete_email,
                    )

                    await send_scan_complete_email(
                        db=db,
                        duplicates_found=0,  # We don't track this in scheduled scans currently
                        sets_created=total_sets_created,
                        sets_existing=total_sets_existing,
                        libraries_scanned=libraries,
                    )
                except Exception as e:
                    logger.warning(f"Failed to send scheduled scan email: {e}")

                # Trigger scheduled deletion 30 minutes after scan completes
                # (only if enabled)
                result = await db.execute(
                    select(Config).where(Config.key == "enable_scheduled_deletion")
                )
                deletion_config = result.scalar_one_or_none()
                deletion_enabled = deletion_config and deletion_config.value == "true"

                if deletion_enabled:
                    logger.info(
                        "Scheduled deletion enabled - scheduling deletion to run in 30 minutes"
                    )
                    # Schedule a one-time deletion job to run in 30 minutes
                    deletion_time = datetime.now(timezone.utc) + timedelta(minutes=30)
                    self.scheduler.add_job(
                        self._run_scheduled_deletion,
                        trigger="date",
                        run_date=deletion_time,
                        id="scheduled_deletion_after_scan",
                        name="Scheduled Deletion (Post-Scan)",
                        replace_existing=True,
                    )
                    logger.info(
                        f"Deletion scheduled for {deletion_time.strftime('%H:%M:%S UTC')}"
                    )
                else:
                    logger.info("Scheduled deletion disabled - skipping deletion")

            except Exception as e:
                logger.error(f"Scheduled scan failed: {e}", exc_info=True)
                await db.rollback()

    async def _run_scheduled_deletion(self):
        """Execute scheduled deletion of approved duplicates"""
        logger.info("Starting scheduled deletion")

        async with AsyncSessionLocal() as db:
            try:
                from app.services.scheduled_deletion import ScheduledDeletionService

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
