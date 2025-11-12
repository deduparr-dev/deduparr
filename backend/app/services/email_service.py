"""
Email notification service for Deduparr.
Handles SMTP configuration, email sending, and templating.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending email notifications via SMTP."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        from_email: Optional[str] = None,
    ):
        """
        Initialize email service with SMTP configuration.

        Args:
            smtp_host: SMTP server hostname
            smtp_port: SMTP server port
            smtp_user: SMTP username
            smtp_password: SMTP password
            from_email: From email address (defaults to smtp_user)
        """
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_email = from_email or smtp_user

    def _get_email_template(
        self,
        title: str,
        content: str,
        action_url: Optional[str] = None,
        action_text: Optional[str] = None,
    ) -> str:
        """
        Generate branded HTML email template.

        Args:
            title: Email title
            content: Main email content (HTML allowed)
            action_url: Optional action button URL
            action_text: Optional action button text

        Returns:
            Formatted HTML email
        """
        action_button = ""
        if action_url and action_text:
            action_button = f"""
            <tr>
                <td style="padding: 20px 0;">
                    <a href="{action_url}" 
                       style="background-color: #276f6d; color: #ffffff; padding: 12px 30px; 
                              text-decoration: none; border-radius: 6px; display: inline-block; 
                              font-weight: 600;">
                        {action_text}
                    </a>
                </td>
            </tr>
            """

        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 
             'Helvetica Neue', Arial, sans-serif; background-color: #1a1a1a; color: #fafafa;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" 
           style="background-color: #1a1a1a;">
        <tr>
            <td align="center" style="padding: 40px 20px;">
                <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" 
                       style="background-color: #212121; border-radius: 12px; overflow: hidden;">
                    <!-- Header with Logo -->
                    <tr>
                        <td style="padding: 20px; text-align: center; background-color: #1a1a1a; 
                                   border-bottom: 2px solid #276f6d;">
                            <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center">
                                <tr>
                                    <td style="width: 60px; height: 60px; background-color: #276f6d; border-radius: 10px; text-align: center; vertical-align: middle;">
                                        <svg width="30" height="30" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style="display: block; margin: 0 auto; vertical-align: middle;">
                                            <rect x="3" y="6" width="18" height="12" rx="2" stroke="#ffffff" stroke-width="2" fill="none"/>
                                            <path d="M3 8L12 13L21 8" stroke="#ffffff" stroke-width="2" stroke-linecap="round"/>
                                        </svg>
                                    </td>
                                </tr>
                            </table>
                            <h1 style="margin: 12px 0 0 0; color: #fafafa; font-size: 22px; font-weight: 600;">
                                deduparr
                            </h1>
                        </td>
                    </tr>
                    
                    <!-- Content -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <h2 style="margin: 0 0 15px 0; color: #fafafa; font-size: 18px; font-weight: 600;">
                                {title}
                            </h2>
                            <div style="color: #999999; font-size: 15px; line-height: 1.6;">
                                {content}
                            </div>
                        </td>
                    </tr>
                    
                    <!-- Action Button -->
                    {action_button}
                    
                    <!-- Footer -->
                    <tr>
                        <td style="padding: 20px 30px; text-align: center; background-color: #1a1a1a; 
                                   border-top: 1px solid #2d2d2d;">
                            <p style="margin: 0; color: #666666; font-size: 12px;">
                                This is an automated notification from Deduparr
                            </p>
                            <p style="margin: 8px 0 0 0; color: #666666; font-size: 12px;">
                                Duplicate media management for the *arr ecosystem
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    def build_email_template(
        self,
        *,
        title: str,
        content: str,
        action_url: Optional[str] = None,
        action_text: Optional[str] = None,
    ) -> str:
        """Expose the branded template builder for other services."""

        return self._get_email_template(
            title=title,
            content=content,
            action_url=action_url,
            action_text=action_text,
        )

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        plain_content: Optional[str] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Send email via SMTP.

        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML email content
            plain_content: Plain text fallback (auto-generated if not provided)

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_email
            msg["To"] = to_email

            # Add plain text version (fallback)
            if not plain_content:
                # Simple HTML stripping for plain text
                plain_content = html_content.replace("<br>", "\n").replace(
                    "</p>", "\n\n"
                )
                import re

                plain_content = re.sub("<[^<]+?>", "", plain_content)

            part1 = MIMEText(plain_content, "plain")
            part2 = MIMEText(html_content, "html")

            msg.attach(part1)
            msg.attach(part2)

            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            logger.info(f"Email sent successfully to {to_email}")
            return True, None

        except smtplib.SMTPAuthenticationError as e:
            error_msg = f"Authentication failed: {e.smtp_error.decode() if hasattr(e, 'smtp_error') else str(e)}"
            logger.error(f"Failed to send email to {to_email}: {error_msg}")
            return False, error_msg
        except smtplib.SMTPException as e:
            error_msg = f"SMTP error: {str(e)}"
            logger.error(f"Failed to send email to {to_email}: {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = f"Failed to send email: {str(e)}"
            logger.error(f"Failed to send email to {to_email}: {error_msg}")
            return False, error_msg

    def send_test_email(self, to_email: str) -> tuple[bool, Optional[str]]:
        """
        Send a test email to verify SMTP configuration.

        Args:
            to_email: Test recipient email address

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        content = """
        <p>This is a test email from your Deduparr instance.</p>
        <p>If you received this email, your SMTP configuration is working correctly!</p>
        <p style="margin-top: 20px; padding-top: 20px; border-top: 1px solid #2d2d2d;">
            <strong>SMTP Configuration:</strong><br>
            Server: {host}:{port}<br>
            Username: {user}
        </p>
        """.format(
            host=self.smtp_host, port=self.smtp_port, user=self.smtp_user
        )

        html_content = self._get_email_template(
            title="Test Email - SMTP Configuration Success",
            content=content,
        )

        return self.send_email(
            to_email=to_email,
            subject="Deduparr - Test Email",
            html_content=html_content,
        )

    def send_scan_complete_notification(
        self,
        to_email: str,
        duplicates_found: int,
        files_deleted: int,
        space_freed: str,
        dashboard_url: Optional[str] = None,
    ) -> bool:
        """
        Send scan completion notification.

        Args:
            to_email: Recipient email address
            duplicates_found: Number of duplicate sets found
            files_deleted: Number of files deleted
            space_freed: Human-readable space freed (e.g., "15.2 GB")
            dashboard_url: Optional URL to dashboard

        Returns:
            True if email sent successfully
        """
        content = f"""
        <p>Your duplicate scan has completed successfully.</p>
        <p style="margin-top: 20px;">
            <strong>Scan Results:</strong><br>
            Duplicate sets found: <strong>{duplicates_found}</strong><br>
            Files deleted: <strong>{files_deleted}</strong><br>
            Space freed: <strong>{space_freed}</strong>
        </p>
        """

        html_content = self._get_email_template(
            title="Scan Complete",
            content=content,
            action_url=dashboard_url,
            action_text="View Dashboard" if dashboard_url else None,
        )

        success, _ = self.send_email(
            to_email=to_email,
            subject="Deduparr - Scan Complete",
            html_content=html_content,
        )
        return success

    def send_error_notification(
        self, to_email: str, error_message: str, error_details: Optional[str] = None
    ) -> bool:
        """
        Send error notification.

        Args:
            to_email: Recipient email address
            error_message: Brief error message
            error_details: Optional detailed error information

        Returns:
            True if email sent successfully
        """
        details_section = ""
        if error_details:
            details_section = f"""
            <p style="margin-top: 20px; padding: 15px; background-color: #2d2d2d; 
                      border-radius: 6px; font-family: monospace; font-size: 13px;">
                {error_details}
            </p>
            """

        content = f"""
        <p style="color: #ff6b6b;">An error occurred during operation:</p>
        <p><strong>{error_message}</strong></p>
        {details_section}
        <p style="margin-top: 20px; color: #999999;">
            Check the Deduparr logs for more information.
        </p>
        """

        html_content = self._get_email_template(
            title="Error Notification", content=content
        )

        success, _ = self.send_email(
            to_email=to_email,
            subject="Deduparr - Error Notification",
            html_content=html_content,
        )
        return success
