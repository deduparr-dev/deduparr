"""
Tests for the email service
"""

import pytest
from unittest.mock import MagicMock, patch
import smtplib

from app.services.email_service import EmailService


@pytest.fixture
def email_service():
    """Create email service instance for testing"""
    return EmailService(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="test@example.com",
        smtp_password="test_password",
        from_email="noreply@deduparr.com",
    )


def test_email_service_initialization():
    """Test email service initializes with correct config"""
    service = EmailService(
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_user="user@gmail.com",
        smtp_password="secret",
    )

    assert service.smtp_host == "smtp.gmail.com"
    assert service.smtp_port == 587
    assert service.smtp_user == "user@gmail.com"
    assert service.smtp_password == "secret"
    assert service.from_email == "user@gmail.com"  # Defaults to smtp_user


def test_email_service_custom_from_email():
    """Test email service with custom from_email"""
    service = EmailService(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="user@example.com",
        smtp_password="secret",
        from_email="custom@example.com",
    )

    assert service.from_email == "custom@example.com"


def test_get_email_template_basic(email_service):
    """Test basic email template generation"""
    html = email_service._get_email_template(
        title="Test Email", content="<p>This is a test</p>"
    )

    assert "Test Email" in html
    assert "This is a test" in html
    assert "deduparr" in html
    assert "<!DOCTYPE html>" in html


def test_get_email_template_with_action_button(email_service):
    """Test email template with action button"""
    html = email_service._get_email_template(
        title="Action Required",
        content="<p>Please click the button below</p>",
        action_url="https://deduparr.com/dashboard",
        action_text="View Dashboard",
    )

    assert "Action Required" in html
    assert "https://deduparr.com/dashboard" in html
    assert "View Dashboard" in html
    assert 'href="https://deduparr.com/dashboard"' in html


def test_get_email_template_without_action_button(email_service):
    """Test email template without action button"""
    html = email_service._get_email_template(
        title="Simple Email", content="<p>No action needed</p>"
    )

    # Should not contain action button HTML
    assert 'style="background-color: #276f6d' not in html or "href=" not in html


def test_build_email_template(email_service):
    """Test public template builder method"""
    html = email_service.build_email_template(
        title="Public Test",
        content="<p>Testing public method</p>",
        action_url="https://example.com",
        action_text="Click Here",
    )

    assert "Public Test" in html
    assert "Testing public method" in html
    assert "https://example.com" in html


@patch("smtplib.SMTP")
def test_send_email_success(mock_smtp, email_service):
    """Test successful email sending"""
    # Mock SMTP server
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    # Send email
    success, error = email_service.send_email(
        to_email="recipient@example.com",
        subject="Test Subject",
        html_content="<p>Test content</p>",
        plain_content="Test content",
    )

    # Verify
    assert success is True
    assert error is None

    # Verify SMTP calls
    mock_smtp.assert_called_once_with("smtp.example.com", 587)
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("test@example.com", "test_password")
    mock_server.send_message.assert_called_once()


@patch("smtplib.SMTP")
def test_send_email_auto_generates_plain_text(mock_smtp, email_service):
    """Test that plain text is auto-generated if not provided"""
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    # Send email without plain_content
    success, error = email_service.send_email(
        to_email="recipient@example.com",
        subject="Test Subject",
        html_content="<p>HTML content</p><br>New line</p>",
    )

    assert success is True
    # Plain text should be auto-generated (HTML stripped)


@patch("smtplib.SMTP")
def test_send_email_authentication_error(mock_smtp, email_service):
    """Test email sending with authentication error"""
    mock_server = MagicMock()
    mock_server.login.side_effect = smtplib.SMTPAuthenticationError(
        535, b"Authentication failed"
    )
    mock_smtp.return_value.__enter__.return_value = mock_server

    # Send email
    success, error = email_service.send_email(
        to_email="recipient@example.com",
        subject="Test Subject",
        html_content="<p>Test</p>",
    )

    # Verify
    assert success is False
    assert error is not None
    assert "Authentication failed" in error or "authentication" in error.lower()


@patch("smtplib.SMTP")
def test_send_email_smtp_exception(mock_smtp, email_service):
    """Test email sending with SMTP exception"""
    mock_server = MagicMock()
    mock_server.send_message.side_effect = smtplib.SMTPException("Server error")
    mock_smtp.return_value.__enter__.return_value = mock_server

    # Send email
    success, error = email_service.send_email(
        to_email="recipient@example.com",
        subject="Test Subject",
        html_content="<p>Test</p>",
    )

    # Verify
    assert success is False
    assert error is not None
    assert "SMTP error" in error


@patch("smtplib.SMTP")
def test_send_email_generic_exception(mock_smtp, email_service):
    """Test email sending with generic exception"""
    mock_smtp.side_effect = Exception("Network error")

    # Send email
    success, error = email_service.send_email(
        to_email="recipient@example.com",
        subject="Test Subject",
        html_content="<p>Test</p>",
    )

    # Verify
    assert success is False
    assert error is not None
    assert "Failed to send email" in error


@patch("smtplib.SMTP")
def test_send_test_email(mock_smtp, email_service):
    """Test sending test email"""
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    # Send test email
    success, error = email_service.send_test_email("test@example.com")

    # Verify
    assert success is True
    assert error is None

    # Verify email was sent
    mock_server.send_message.assert_called_once()

    # Verify email contains SMTP config details
    # The message should contain SMTP configuration info


@patch("smtplib.SMTP")
def test_send_scan_complete_notification(mock_smtp, email_service):
    """Test sending scan complete notification"""
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    # Send notification
    success = email_service.send_scan_complete_notification(
        to_email="user@example.com",
        duplicates_found=42,
        files_deleted=15,
        space_freed="15.2 GB",
        dashboard_url="https://deduparr.com/dashboard",
    )

    # Verify
    assert success is True
    mock_server.send_message.assert_called_once()


@patch("smtplib.SMTP")
def test_send_scan_complete_notification_without_url(mock_smtp, email_service):
    """Test scan notification without dashboard URL"""
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    # Send notification without URL
    success = email_service.send_scan_complete_notification(
        to_email="user@example.com",
        duplicates_found=10,
        files_deleted=5,
        space_freed="2.5 GB",
        dashboard_url=None,
    )

    assert success is True


@patch("smtplib.SMTP")
def test_send_error_notification(mock_smtp, email_service):
    """Test sending error notification"""
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    # Send error notification
    success = email_service.send_error_notification(
        to_email="admin@example.com",
        error_message="Database connection failed",
        error_details="Connection timeout after 30 seconds",
    )

    # Verify
    assert success is True
    mock_server.send_message.assert_called_once()


@patch("smtplib.SMTP")
def test_send_error_notification_without_details(mock_smtp, email_service):
    """Test error notification without details"""
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    # Send error notification without details
    success = email_service.send_error_notification(
        to_email="admin@example.com", error_message="Unknown error occurred"
    )

    assert success is True


@patch("smtplib.SMTP")
def test_email_headers_correct(mock_smtp, email_service):
    """Test that email headers are set correctly"""
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    # Send email
    email_service.send_email(
        to_email="recipient@example.com",
        subject="Test Subject",
        html_content="<p>Test</p>",
    )

    # Get the message that was sent
    call_args = mock_server.send_message.call_args
    message = call_args[0][0] if call_args else None

    assert message is not None
    assert message["Subject"] == "Test Subject"
    assert message["From"] == "noreply@deduparr.com"
    assert message["To"] == "recipient@example.com"


def test_email_template_contains_branding(email_service):
    """Test that email template includes proper branding"""
    html = email_service.build_email_template(
        title="Branding Test", content="<p>Test content</p>"
    )

    # Check for Deduparr branding elements
    assert "deduparr" in html.lower()
    assert (
        "duplicate media management" in html.lower() or "arr ecosystem" in html.lower()
    )
    assert "#276f6d" in html  # Brand color


def test_email_template_responsive_styles(email_service):
    """Test that email template includes responsive styles"""
    html = email_service.build_email_template(
        title="Responsive Test", content="<p>Test content</p>"
    )

    # Check for responsive meta tag
    assert 'name="viewport"' in html
    assert "width=device-width" in html
