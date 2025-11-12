"""
Security utilities for application-wide authentication and token management.
Provides token encryption, CSRF protection, and secure logging.

Usage Examples:

    Encrypting/Decrypting Tokens (any service):
        from app.services.security import get_token_manager

        # Plex token
        tm = get_token_manager()
        encrypted_plex = tm.encrypt("plex-auth-token-123")
        decrypted_plex = tm.decrypt(encrypted_plex)

        # Radarr API key
        encrypted_radarr = tm.encrypt("radarr-api-key-456")
        decrypted_radarr = tm.decrypt(encrypted_radarr)

        # Sonarr API key
        encrypted_sonarr = tm.encrypt("sonarr-api-key-789")
        decrypted_sonarr = tm.decrypt(encrypted_sonarr)

    Sanitizing Sensitive Data for Logs:
        from app.services.security import sanitize_log_data

        logger.info(f"Authenticated with token: {sanitize_log_data(api_key)}")
        # Output: "Authenticated with token: abcd...xyz"

    OAuth PIN Flow (for services that support it):
        from app.services.security import pin_cache

        pin_cache.set("pin-123", {"code": "ABCD", "state": "xyz"}, ttl=600)
        data = pin_cache.get("pin-123")
        pin_cache.delete("pin-123")

    Setting up Secure Logging Filter:
        from app.services.security import SensitiveDataFilter

        # In your main.py or logging config:
        logging.basicConfig(...)
        for handler in logging.root.handlers:
            handler.addFilter(SensitiveDataFilter())
"""

import logging
import re
import secrets
import time
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime, timedelta, timezone

from itsdangerous import URLSafeSerializer, BadSignature
from itsdangerous.exc import BadPayload


class InvalidTokenError(Exception):
    """Raised when token encryption/decryption fails."""

    pass


class TokenManager:
    """
    Handles encryption/decryption of tokens and API keys using itsdangerous.

    Can be used for any service: Plex, Radarr, Sonarr, qBittorrent, etc.
    """

    def __init__(self, encryption_key: str):
        self.serializer = URLSafeSerializer(encryption_key)

    def encrypt(self, token: str) -> str:
        """
        Encrypt a token or API key with salt and timestamp.

        Args:
            token: Plain text token/API key to encrypt

        Returns:
            Encrypted token string, or None if input is empty
        """
        if not token:
            return None

        salt = secrets.token_hex(16)
        payload = {"token": token, "salt": salt, "timestamp": int(time.time())}
        return self.serializer.dumps(payload)

    def decrypt(self, encrypted_token: str) -> str:
        """
        Decrypt a token or API key, validating the payload structure.

        Args:
            encrypted_token: Encrypted token to decrypt

        Returns:
            Plain text token string, or None if input is empty

        Raises:
            InvalidTokenError: If decryption fails or payload is malformed
        """
        if not encrypted_token:
            return None
        try:
            payload = self.serializer.loads(encrypted_token)
            if not isinstance(payload, dict) or "token" not in payload:
                raise InvalidTokenError("Invalid token format")
            return payload["token"]
        except (BadSignature, BadPayload, ValueError, KeyError):
            raise InvalidTokenError("Failed to decrypt token")

    def generate_state_token(self) -> str:
        """Generate a random state token for CSRF protection."""
        return secrets.token_urlsafe(32)

    def validate_state_token(self, state: str, stored_state: str) -> bool:
        """Validate state token using constant-time comparison."""
        if not state or not stored_state:
            return False
        return secrets.compare_digest(state, stored_state)


def generate_secure_key() -> str:
    """Generate a cryptographically secure random key."""
    return secrets.token_urlsafe(32)


def get_or_create_key_file() -> str:
    """
    Get encryption key from file, create if doesn't exist.

    The key file is stored at /app/data/.encryption_key (Docker volume mount).
    For tests, uses a temp directory if /app/data is not writable.

    Returns:
        The encryption key as a string
    """
    import os
    import tempfile

    key_file_path = os.environ.get("ENCRYPTION_KEY_FILE", "/app/data/.encryption_key")
    key_file = Path(key_file_path)

    if key_file.exists():
        return key_file.read_text().strip()

    # Generate new key
    new_key = generate_secure_key()

    try:
        # Create directory if needed
        key_file.parent.mkdir(parents=True, exist_ok=True)

        # Write key to file
        key_file.write_text(new_key)

        # Set restrictive permissions (owner read/write only)
        key_file.chmod(0o600)
    except PermissionError:
        # For tests: use temp directory if /app/data is not writable
        temp_dir = Path(tempfile.gettempdir()) / "deduparr_test"
        temp_dir.mkdir(parents=True, exist_ok=True)
        key_file = temp_dir / ".encryption_key"
        key_file.write_text(new_key)
        key_file.chmod(0o600)

    return new_key


def get_token_manager() -> TokenManager:
    """
    Get a TokenManager instance with the application encryption key.

    The encryption key is loaded from a file and shared across all services
    (Plex, Radarr, Sonarr, qBittorrent, etc.).

    Returns:
        TokenManager instance ready to encrypt/decrypt tokens
    """
    encryption_key = get_or_create_key_file()
    return TokenManager(encryption_key)


class PinCache:
    """
    In-memory cache for OAuth PIN data with TTL.

    Used for OAuth flows (Plex, potentially others in the future).
    Stores PIN state temporarily during the authentication handshake.
    """

    def __init__(self):
        self._cache: Dict[str, Dict] = {}

    def set(self, pin_id: str, data: Dict, ttl: int = 600):
        """
        Store PIN data with expiration time.

        Args:
            pin_id: Unique PIN identifier
            data: PIN state data (code, client_id, state_token, etc.)
            ttl: Time to live in seconds (default 10 minutes)
        """
        self._cache[pin_id] = {
            "data": data,
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl),
        }

    def get(self, pin_id: str) -> Optional[Dict]:
        """
        Retrieve PIN data if not expired.

        Args:
            pin_id: Unique PIN identifier

        Returns:
            PIN data dict if found and not expired, None otherwise
        """
        if pin_id not in self._cache:
            return None

        entry = self._cache[pin_id]
        if datetime.now(timezone.utc) > entry["expires_at"]:
            del self._cache[pin_id]
            return None

        return entry["data"].copy()

    def delete(self, pin_id: str):
        """
        Remove PIN data from cache.

        Args:
            pin_id: Unique PIN identifier
        """
        self._cache.pop(pin_id, None)

    def cleanup_expired(self):
        """Remove all expired entries from cache (housekeeping)."""
        current_time = datetime.now(timezone.utc)
        expired_keys = [
            key
            for key, entry in self._cache.items()
            if current_time > entry["expires_at"]
        ]
        for key in expired_keys:
            self._cache.pop(key, None)


# Global PIN cache instance (shared across OAuth flows)
pin_cache = PinCache()


def sanitize_server_url(url: str) -> str:
    """
    Normalize server URL to include protocol and remove trailing slashes.

    Works for any service URL (Plex, Radarr, Sonarr, qBittorrent, etc.).

    Args:
        url: Server URL (may or may not include protocol)

    Returns:
        Normalized URL with https:// protocol and no trailing slash

    Example:
        "192.168.1.100:32400" -> "https://192.168.1.100:32400"
        "http://localhost:8989/" -> "http://localhost:8989"
    """
    if not url:
        return ""

    url = url.strip().rstrip("/")

    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    return url


def sanitize_log_data(data: str) -> str:
    """
    Sanitize sensitive data for logging by showing only first/last few characters.

    Use this for tokens, API keys, passwords, or any sensitive strings in logs.

    Args:
        data: Sensitive string to sanitize

    Returns:
        Sanitized string showing only first and last few characters

    Example:
        "abcdefghijklmnop" -> "abcd...mnop"
        "short" -> "***"
    """
    if not data or len(data) <= 8:
        return "***"

    visible_chars = min(4, len(data) // 3)
    if len(data) <= visible_chars * 2:
        return "***"

    return f"{data[:visible_chars]}...{data[-visible_chars:]}"


class SensitiveDataFilter(logging.Filter):
    """
    Logging filter that automatically sanitizes sensitive data patterns.

    Detects and redacts:
    - API keys (patterns like api_key=, apikey=, X-Api-Key:)
    - Tokens (patterns like token=, auth_token=, X-Plex-Token:)
    - Passwords (patterns like password=, passwd=)
    - Encrypted values (long base64-like strings with dots)
    - Bearer tokens in Authorization headers

    Usage:
        for handler in logging.root.handlers:
            handler.addFilter(SensitiveDataFilter())
    """

    # Patterns to detect sensitive data
    SENSITIVE_PATTERNS = [
        # API Keys
        (
            re.compile(
                r'(["\']?(?:api[-_]?key|apikey)["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9_\-\.]{8,})(["\']?)',
                re.IGNORECASE,
            ),
            r"\1***REDACTED***\3",
        ),
        # Tokens
        (
            re.compile(
                r'(["\']?(?:auth[-_]?token|token|access[-_]?token)["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9_\-\.]{8,})(["\']?)',
                re.IGNORECASE,
            ),
            r"\1***REDACTED***\3",
        ),
        # Passwords
        (
            re.compile(
                r'(["\']?(?:password|passwd|pwd)["\']?\s*[:=]\s*["\']?)([^"\'\s,)]{3,})(["\']?)',
                re.IGNORECASE,
            ),
            r"\1***REDACTED***\3",
        ),
        # Encrypted values (itsdangerous format: base64.signature)
        (
            re.compile(
                r'(\()(["\'])(eyJ[a-zA-Z0-9_\-\.]{20,})\.[a-zA-Z0-9_\-]{10,}(["\'])([,)])',
                re.IGNORECASE,
            ),
            r"\1\2***ENCRYPTED***\4\5",
        ),
        # HTTP Headers with tokens
        (
            re.compile(
                r"(X-(?:Api-Key|Plex-Token|Auth-Token):\s*)([a-zA-Z0-9_\-\.]{8,})",
                re.IGNORECASE,
            ),
            r"\1***REDACTED***",
        ),
        # Bearer tokens
        (
            re.compile(r"(Bearer\s+)([a-zA-Z0-9_\-\.]{8,})", re.IGNORECASE),
            r"\1***REDACTED***",
        ),
        # Email passwords in SMTP context
        (
            re.compile(
                r'(smtp_password["\']?\s*[:=]\s*["\']?)([^"\'\s,)]{3,})(["\']?)',
                re.IGNORECASE,
            ),
            r"\1***REDACTED***\3",
        ),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter log record by sanitizing sensitive data.

        Args:
            record: Log record to filter

        Returns:
            Always True (record is not blocked, just modified)
        """
        # Sanitize the message
        if record.msg:
            msg = str(record.msg)
            for pattern, replacement in self.SENSITIVE_PATTERNS:
                msg = pattern.sub(replacement, msg)
            record.msg = msg

        # Sanitize args if present
        if record.args:
            sanitized_args = []
            for arg in (
                record.args if isinstance(record.args, (list, tuple)) else [record.args]
            ):
                if isinstance(arg, str):
                    sanitized_arg = arg
                    for pattern, replacement in self.SENSITIVE_PATTERNS:
                        sanitized_arg = pattern.sub(replacement, sanitized_arg)
                    sanitized_args.append(sanitized_arg)
                else:
                    sanitized_args.append(arg)

            if isinstance(record.args, tuple):
                record.args = tuple(sanitized_args)
            elif isinstance(record.args, list):
                record.args = sanitized_args

        return True
