"""
Email notification service for scan events
"""

import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.email_helpers import get_email_service_from_config

logger = logging.getLogger(__name__)


async def send_scan_complete_email(
    db: AsyncSession,
    duplicates_found: int,
    sets_created: int,
    sets_existing: int,
    libraries_scanned: list[str],
) -> tuple[bool, Optional[str]]:
    """
    Send email notification when a scan completes

    Returns:
        tuple[bool, Optional[str]]: (success, error_message)
    """
    try:
        # Get configured email service
        email_service, to_email, error = await get_email_service_from_config(db)

        if error:
            return (False, error)

        if not email_service or not to_email:
            # Email not configured - not an error, just skip
            return (True, None)

        # Build email content
        libraries_text = ", ".join(f'"{lib}"' for lib in libraries_scanned)

        content = f"""
        <p>Your scheduled duplicate scan has completed successfully.</p>
        
        <div style="background-color: #2a2a2a; padding: 15px; border-radius: 8px; margin: 15px 0;">
            <p style="margin: 5px 0;"><strong>Libraries Scanned:</strong> {libraries_text}</p>
            <p style="margin: 5px 0;"><strong>Duplicate Files Found:</strong> {duplicates_found}</p>
            <p style="margin: 5px 0;"><strong>New Duplicate Sets:</strong> {sets_created}</p>
            <p style="margin: 5px 0;"><strong>Existing Sets:</strong> {sets_existing}</p>
            <p style="margin: 5px 0;"><strong>Total Sets:</strong> {sets_created + sets_existing}</p>
        </div>
        
        <p>You can review and manage these duplicates in your Deduparr dashboard.</p>
        """

        html_content = email_service.build_email_template(
            title="Duplicate Scan Complete",
            content=content,
            action_url="http://localhost:3000/scan",  # TODO: Make this configurable
            action_text="View Duplicates",
        )

        # Send email
        success, error = email_service.send_email(
            to_email=to_email,
            subject="Deduparr - Scan Complete",
            html_content=html_content,
        )

        if success:
            logger.info(f"Scan complete email sent to {to_email}")
        else:
            logger.error(f"Failed to send scan complete email: {error}")

        return (success, error)

    except Exception as e:
        logger.error(f"Error sending scan complete email: {e}", exc_info=True)
        return (False, str(e))
