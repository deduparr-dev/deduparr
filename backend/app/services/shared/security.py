"""
Security utilities for application-wide authentication and token management.
Provides token encryption and secure logging.

Usage Examples:

    Encrypting/Decrypting Tokens (any service):
        from app.services.shared.security import get_token_manager

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

    OAuth PIN Flow (for services that support it):
        from app.services.shared.security import pin_cache

        pin_cache.set("pin-123", {"code": "ABCD", "client_id": "xyz"}, ttl=600)
        data = pin_cache.get("pin-123")
        pin_cache.delete("pin-123")

    Setting up Secure Logging Filter:
        from app.services.shared.security import SensitiveDataFilter

        # In your main.py or logging config:
        logging.basicConfig(...)
        for handler in logging.root.handlers:
            handler.addFilter(SensitiveDataFilter())
"""

import base64
import logging
import re
import secrets
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from itsdangerous import URLSafeSerializer
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import Config

logger = logging.getLogger(__name__)


# How every Fernet token starts: its version byte and the top of its timestamp
FERNET_PREFIX = "gAAAAA"


class InvalidTokenError(Exception):
    """Raised when token encryption/decryption fails."""

    pass


class TokenManager:
    """
    Encrypts and decrypts tokens, API keys and passwords with Fernet.

    Fernet is authenticated encryption: a stored value cannot be read without
    the key, and one altered without it fails to decrypt.

    Can be used for any service: Plex, Radarr, Sonarr, qBittorrent, etc.
    """

    def __init__(self, encryption_key: str):
        # The key file holds a random string, not a Fernet key, so the Fernet
        # key is derived from it rather than kept in a file of its own
        key = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=b"deduparr secrets"
        ).derive(encryption_key.encode())
        self._fernet = Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, token: str) -> str:
        """
        Encrypt a token, API key or password.

        Args:
            token: Plain text token/API key to encrypt

        Returns:
            Encrypted token string, or None if input is empty
        """
        if not token:
            return None

        return self._fernet.encrypt(token.encode()).decode()

    def decrypt(self, encrypted_token: str) -> str:
        """
        Decrypt a token, API key or password.

        Args:
            encrypted_token: Encrypted token to decrypt

        Returns:
            Plain text token string, or None if input is empty

        Raises:
            InvalidTokenError: If it was not encrypted with this key, or was altered
        """
        if not encrypted_token:
            return None
        try:
            return self._fernet.decrypt(encrypted_token).decode()
        except (InvalidToken, ValueError):
            # Fernet raises ValueError for a string that is not ASCII
            raise InvalidTokenError("Failed to decrypt token")


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


# Config keys whose value is a secret and must never be stored in the clear.
# One list, so every write path agrees: the setup wizard, the config API and
# anything else that persists configuration.
SENSITIVE_CONFIG_KEYS = frozenset(
    {
        "plex_auth_token",
        "jellyfin_api_key",
        "radarr_api_key",
        "sonarr_api_key",
        "qbittorrent_password",
        "smtp_password",
    }
)

# What the API shows for a stored secret instead of its value. Sent back, it
# stands for the stored secret, which is then kept as it is.
SECRET_MASK = "********"

# Where connection tests used to put the credentials they were given while
# they ran. A test that failed halfway left them behind, secret included.
LEFTOVER_TEST_KEYS = (
    "temp_radarr_url",
    "temp_radarr_api_key",
    "temp_sonarr_url",
    "temp_sonarr_api_key",
    "temp_qbittorrent_url",
    "temp_qbittorrent_username",
    "temp_qbittorrent_password",
)


def mask_secret(key: str, value: Optional[str]) -> Optional[str]:
    """A config value as the API shows it: a stored secret only as the mask."""
    return SECRET_MASK if value and key in SENSITIVE_CONFIG_KEYS else value


def is_masked(key: str, value: Optional[str]) -> bool:
    """Whether a value sent for a key is the mask, which keeps the stored secret."""
    return key in SENSITIVE_CONFIG_KEYS and value == SECRET_MASK


def _unwrap_signed(value: str) -> str:
    """
    The secret in a value stored before secrets were encrypted.

    Those were signed with itsdangerous: base64 JSON with the secret in the
    clear, readable whatever key signed it, so it is read without one. Any
    other value is a secret stored as typed, and comes back unchanged.
    """
    _, payload = URLSafeSerializer("").loads_unsafe(value)
    if isinstance(payload, dict) and isinstance(payload.get("token"), str):
        return payload["token"]
    return value


def encrypt_if_sensitive(key: str, value: Optional[str]) -> Optional[str]:
    """
    Encrypt a config value when its key names a secret.

    A value already encrypted is left alone, such as the Plex token the setup
    wizard was handed, and one in the old signed form is encrypted for the
    secret it holds.
    """
    if not value or key not in SENSITIVE_CONFIG_KEYS:
        return value

    token_manager = get_token_manager()
    try:
        token_manager.decrypt(value)
        return value
    except InvalidTokenError:
        if value.startswith(FERNET_PREFIX):
            # Encrypting it again would lose it for good if the key comes back
            logger.warning(
                f"{key} was encrypted with another key file: restore that file, "
                "or enter it again in Settings"
            )
            return value
        return token_manager.encrypt(_unwrap_signed(value))


def decrypt_if_encrypted(value: str) -> str:
    """
    A secret as typed, whether it was typed just now or is a stored one.

    A connection test runs with the stored secret, encrypted, when its field
    was left alone.
    """
    try:
        return get_token_manager().decrypt(value) or value
    except InvalidTokenError:
        return value


async def secure_stored_secrets(db: AsyncSession) -> None:
    """
    Encrypt the secrets an earlier version stored, and drop what its failed
    connection tests left behind.

    Those were signed rather than encrypted, or stored as typed, so anyone
    with the database could read them. Runs at every start: a value already
    encrypted is left as it is.
    """
    result = await db.execute(
        select(Config).where(Config.key.in_(SENSITIVE_CONFIG_KEYS))
    )
    encrypted = 0
    for config in result.scalars():
        value = encrypt_if_sensitive(config.key, config.value)
        if value != config.value:
            config.value = value
            encrypted += 1

    await db.execute(delete(Config).where(Config.key.in_(LEFTOVER_TEST_KEYS)))
    await db.commit()
    if encrypted:
        logger.info(f"Encrypted {encrypted} stored secret(s)")


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
            data: PIN state data (code, client_id, etc.)
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


# Global PIN cache instance (shared across OAuth flows)
pin_cache = PinCache()


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
        # Encrypted values (Fernet tokens)
        (re.compile(r"gAAAAA[a-zA-Z0-9_\-]{20,}={0,2}"), "***ENCRYPTED***"),
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
