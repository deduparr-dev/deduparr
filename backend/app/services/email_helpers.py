"""
Email helper utilities for retrieving and configuring email service from database.
Shared across email_notifications and scheduled_deletion services.
"""

import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Config
from app.services.email_service import EmailService
from app.services.security import get_token_manager

logger = logging.getLogger(__name__)


async def get_email_service_from_config(
    db: AsyncSession,
) -> tuple[Optional[EmailService], Optional[str], Optional[str]]:
    """
    Get configured EmailService instance from database settings.

    Retrieves SMTP configuration from database, decrypts password if needed,
    and returns ready-to-use EmailService instance along with recipient email.

    Args:
        db: Database session

    Returns:
        Tuple of (EmailService instance, to_email, error_message)
        - If email not configured: (None, None, None)
        - If configuration invalid: (None, None, error_message)
        - If successful: (EmailService, to_email, None)
    """
    try:
        # Get email configuration from database
        result = await db.execute(
            select(Config).where(
                Config.key.in_(
                    [
                        "smtp_host",
                        "smtp_port",
                        "smtp_user",
                        "smtp_password",
                        "smtp_from_email",
                        "notification_email",
                    ]
                )
            )
        )
        config_items = {item.key: item.value for item in result.scalars().all()}

        # Check if email is configured
        required_keys = ["smtp_host", "smtp_port", "smtp_user", "smtp_password"]
        if not all(config_items.get(k) for k in required_keys):
            logger.info("Email not configured - skipping notification")
            return (None, None, None)

        # Get notification email (defaults to smtp_user if not set)
        to_email = config_items.get("notification_email") or config_items.get(
            "smtp_user"
        )
        if not to_email:
            error_msg = "No notification email configured"
            logger.warning(error_msg)
            return (None, None, error_msg)

        # Decrypt password
        encrypted_password = config_items["smtp_password"]
        token_manager = get_token_manager()

        # Check if password is already decrypted (plain text) or encrypted
        # Encrypted passwords have format: base64.signature (contains dot, length > 50)
        if "." in encrypted_password and len(encrypted_password) > 50:
            try:
                smtp_password = token_manager.decrypt(encrypted_password)
            except Exception as e:
                logger.error(f"Failed to decrypt SMTP password: {e}")
                smtp_password = encrypted_password  # Fallback to using as-is
        else:
            smtp_password = encrypted_password

        # Initialize and return email service
        email_service = EmailService(
            smtp_host=config_items["smtp_host"],
            smtp_port=int(config_items["smtp_port"]),
            smtp_user=config_items["smtp_user"],
            smtp_password=smtp_password,
            from_email=config_items.get("smtp_from_email"),
        )

        return (email_service, to_email, None)

    except Exception as e:
        error_msg = f"Failed to initialize email service: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return (None, None, error_msg)
