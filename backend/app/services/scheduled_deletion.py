"""
Scheduled deletion service - automatically deletes approved duplicates
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import DuplicateSet, DuplicateStatus
from app.services.deletion_pipeline import DeletionPipeline

logger = logging.getLogger(__name__)


class ScheduledDeletionService:
    """Service to handle scheduled deletion of approved duplicates"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.deletion_pipeline = DeletionPipeline(db)

    async def run_scheduled_deletion(
        self,
        dry_run: bool = False,
        send_email: bool = True,
    ) -> dict:
        """
        Execute scheduled deletion of all pending duplicate sets

        When scheduled deletion is enabled, it automatically deletes ALL duplicates
        found by scheduled scans. No manual approval needed - that's the point of automation!

        Args:
            dry_run: If True, simulate deletion without actually deleting
            send_email: If True, send email summary after deletion

        Returns:
            dict with summary statistics
        """
        logger.info(f"Starting scheduled deletion (dry_run={dry_run})")

        # Get all PENDING duplicate sets (found by scheduled scans, not yet processed)
        result = await self.db.execute(
            select(DuplicateSet)
            .options(selectinload(DuplicateSet.files))
            .where(DuplicateSet.status == DuplicateStatus.PENDING)
        )
        pending_sets = result.scalars().all()

        if not pending_sets:
            logger.info("No pending duplicates to delete")
            return {
                "sets_processed": 0,
                "files_deleted": 0,
                "errors": [],
                "dry_run": dry_run,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        logger.info(f"Found {len(pending_sets)} pending sets to delete")

        sets_processed = 0
        files_deleted = 0
        errors = []

        for duplicate_set in pending_sets:
            try:
                set_errors: list[str] = []
                # Get files marked for deletion (keep=False means delete)
                files_to_delete = [f for f in duplicate_set.files if not f.keep]

                if not files_to_delete:
                    logger.warning(
                        f"Set {duplicate_set.id} ({duplicate_set.title}) "
                        "has no files marked for deletion - skipping"
                    )
                    continue

                logger.info(
                    f"Deleting {len(files_to_delete)} files from set {duplicate_set.id} "
                    f"({duplicate_set.title})"
                )

                if dry_run:
                    # Simulate deletion
                    logger.info(
                        f"[DRY RUN] Would delete: {[f.file_path for f in files_to_delete]}"
                    )
                    files_deleted += len(files_to_delete)
                    sets_processed += 1
                else:
                    # Actually delete files
                    for file in files_to_delete:
                        try:
                            await self.deletion_pipeline.delete_file(file.id)
                            files_deleted += 1
                        except Exception as e:
                            error_msg = f"Failed to delete {file.file_path}: {str(e)}"
                            logger.error(error_msg)
                            set_errors.append(error_msg)

                    # Mark set as processed if all deletions completed
                    if not set_errors:
                        duplicate_set.status = DuplicateStatus.PROCESSED
                        sets_processed += 1
                    else:
                        errors.extend(set_errors)

            except Exception as e:
                error_msg = f"Error processing set {duplicate_set.id}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)

        # Commit changes
        if not dry_run:
            await self.db.commit()

        summary = {
            "sets_processed": sets_processed,
            "files_deleted": files_deleted,
            "errors": errors,
            "dry_run": dry_run,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            f"Scheduled deletion complete: {sets_processed} sets, "
            f"{files_deleted} files, {len(errors)} errors"
        )

        # Send email notification
        if send_email and not dry_run:
            try:
                await self._send_deletion_email(summary)
            except Exception as e:
                logger.warning(f"Failed to send deletion email: {e}")

        return summary

    async def _send_deletion_email(self, summary: dict) -> None:
        """Send email summary of scheduled deletion"""
        from app.services.email_helpers import get_email_service_from_config

        # Get configured email service
        email_service, to_email, error = await get_email_service_from_config(self.db)

        if error:
            logger.error(f"Email configuration error: {error}")
            return

        if not email_service or not to_email:
            # Email not configured - skip silently
            return

        # Build email content
        status_icon = "✅" if not summary["errors"] else "⚠️"

        content = f"""
        <p>Your scheduled deletion has completed.</p>
        
        <div style="background-color: #2a2a2a; padding: 15px; border-radius: 8px; margin: 15px 0;">
            <p style="margin: 5px 0;"><strong>Status:</strong> {status_icon} {"Success" if not summary["errors"] else "Completed with errors"}</p>
            <p style="margin: 5px 0;"><strong>Sets Processed:</strong> {summary["sets_processed"]}</p>
            <p style="margin: 5px 0;"><strong>Files Deleted:</strong> {summary["files_deleted"]}</p>
            <p style="margin: 5px 0;"><strong>Errors:</strong> {len(summary["errors"])}</p>
        </div>
        """

        if summary["errors"]:
            content += """
            <p><strong>Error Details:</strong></p>
            <div style="background-color: #3a1a1a; padding: 10px; border-radius: 8px; margin: 10px 0;">
            """
            for error in summary["errors"][:5]:  # Show first 5 errors
                content += f"<p style='margin: 5px 0; font-size: 14px;'>• {error}</p>"

            if len(summary["errors"]) > 5:
                content += f"<p style='margin: 5px 0; font-size: 14px;'>... and {len(summary['errors']) - 5} more errors</p>"

            content += "</div>"

        # Send email
        html_content = email_service.build_email_template(
            title="Scheduled Deletion Complete",
            content=content,
            action_url="http://localhost:3000/scan",
            action_text="View Results",
        )

        email_service.send_email(
            to_email=to_email,
            subject="Deduparr - Scheduled Deletion Complete",
            html_content=html_content,
        )
