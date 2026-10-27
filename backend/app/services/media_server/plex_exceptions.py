"""
Plex-specific exception classes for authentication and API errors.

Note: InvalidTokenError has been moved to security.py since it's used
across multiple services (Plex, Radarr, Sonarr, etc.).
"""


class PlexAuthError(Exception):
    """Base exception for Plex authentication errors"""

    def __init__(self, message: str, error_code: str = "PLEX_AUTH_ERROR"):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


class TokenExpiredError(PlexAuthError):
    """Raised when a Plex token has expired"""

    def __init__(self, message: str):
        super().__init__(message, "TOKEN_EXPIRED")


class UnauthorizedError(PlexAuthError):
    """Raised when access is forbidden"""

    def __init__(self, message: str):
        super().__init__(message, "UNAUTHORIZED")


class PlexConnectionError(PlexAuthError):
    """Raised when connection to Plex.tv fails"""

    def __init__(self, message: str):
        super().__init__(message, "PLEX_CONNECTION_ERROR")


class PlexPinExpiredError(PlexAuthError):
    """Raised when a PIN has expired"""

    def __init__(self, message: str):
        super().__init__(message, "PIN_EXPIRED")


class CSRFValidationError(PlexAuthError):
    """Raised when CSRF state validation fails"""

    def __init__(self, message: str):
        super().__init__(message, "CSRF_VALIDATION_ERROR")
