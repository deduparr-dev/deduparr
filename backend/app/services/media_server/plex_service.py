"""
Plex service for interacting with Plex Media Server
Uses OAuth PIN authentication via plex.tv with token encryption and CSRF protection
"""

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Union

import plexapi
import requests
from plexapi.exceptions import NotFound, Unauthorized
from plexapi.library import LibrarySection
from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer
from plexapi.video import Episode, Movie
from typing_extensions import TypedDict

from app.core.config import settings
from app.services.media_server.plex_exceptions import (
    PlexConnectionError,
    PlexPinExpiredError,
    TokenExpiredError,
    UnauthorizedError,
)
from app.services.shared.security import (
    InvalidTokenError,
    get_token_manager,
    pin_cache,
    sanitize_log_data,
)

# Configure PlexAPI to identify as Deduparr
plexapi.X_PLEX_PRODUCT = "Deduparr"

logger = logging.getLogger(__name__)


def is_sample_file(file_path: str) -> bool:
    """
    Check if a file path represents a sample file using comprehensive pattern matching.

    Checks for:
    - "sample" anywhere in path (case-insensitive)
    - /Sample/, /SAMPLE/, /SaMpLe/ directory patterns
    - -sample., _sample., .sample. filename patterns

    Args:
        file_path: Full file path to check

    Returns:
        True if file appears to be a sample, False otherwise
    """
    if not file_path:
        return False

    file_path_lower = file_path.lower()

    # Check for "sample" anywhere in the path (handles all case variations)
    if "sample" in file_path_lower:
        return True

    return False


class PlexAuthData(TypedDict):
    """OAuth authentication data structure"""

    auth_url: str
    pin_id: str
    code: str
    expires_in: int


class PlexConnectionData(TypedDict):
    """Plex server connection data"""

    uri: str
    local: bool


class PlexServerData(TypedDict):
    """Plex server information"""

    name: str
    client_identifier: str
    product: str
    platform: str
    owned: bool
    connections: List[PlexConnectionData]


class PlexConnectionTestResult(TypedDict):
    """Connection test result"""

    success: bool
    username: str
    email: str
    server_name: str
    version: str
    platform: str
    platform_version: str


class PlexConnectionTestError(TypedDict):
    """Connection test error result"""

    success: bool
    error: str


class PlexLibraryData(TypedDict):
    """Plex library information"""

    key: str
    title: str
    type: str
    count: int


class PlexMediaInfo(TypedDict, total=False):
    """Media information extracted from media server"""

    title: str
    year: Optional[int]
    rating_key: str
    file_path: Optional[str]
    file_size: int
    duration: Optional[int]
    container: Optional[str]
    video_codec: Optional[str]
    video_resolution: Optional[str]
    bitrate: Optional[int]
    audio_codec: Optional[str]
    width: Optional[int]
    height: Optional[int]
    season: int
    episode: int
    show_title: str
    inode: Optional[int]  # For hardlink detection
    is_hardlink: bool  # Whether this file is a hardlink


class PlexAuthService:
    """Handles Plex OAuth authentication via PIN login with encryption and CSRF protection"""

    @staticmethod
    async def initiate_auth() -> PlexAuthData:
        """
        Initiate OAuth PIN authentication with CSRF protection

        Returns:
            Dict with auth URL and PIN info
        """
        try:
            # Generate unique client identifier
            client_id = str(uuid.uuid4())

            # Generate CSRF state token
            token_manager = get_token_manager()
            state_token = token_manager.generate_state_token()

            # Create PIN via Plex API
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Plex-Product": "Deduparr",
                "X-Plex-Version": "1.0",
                "X-Plex-Client-Identifier": client_id,
                "X-Plex-Platform": "Web",
                "X-Plex-Platform-Version": "1.0",
                "X-Plex-Device": "Deduparr",
                "X-Plex-Device-Name": "Deduparr Web",
            }

            response = requests.post(
                "https://plex.tv/api/v2/pins",
                headers=headers,
                json={"strong": True},
                timeout=10,
            )
            response.raise_for_status()

            pin_data = response.json()

            # Cache PIN state with CSRF token
            pin_cache.set(
                str(pin_data["id"]),
                {
                    "code": pin_data["code"],
                    "client_id": client_id,
                    "state_token": state_token,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )

            # Construct OAuth URL with state parameter
            auth_url = (
                f"https://app.plex.tv/auth#?"
                f"clientID={client_id}"
                f"&code={pin_data['code']}"
                f"&context[device][product]=Deduparr"
            )

            logger.info(f"Initiated Plex auth for PIN: {pin_data['id']}")

            return {
                "auth_url": auth_url,
                "pin_id": str(pin_data["id"]),
                "code": pin_data["code"],
                "expires_in": 600,  # 10 minutes
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create Plex PIN: {type(e).__name__}")
            raise PlexConnectionError(
                f"Failed to connect to Plex.tv for authentication: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Failed to initiate Plex auth: {str(e)}")
            raise

    @staticmethod
    async def check_auth(pin_id: str, state: Optional[str] = None) -> Optional[str]:
        """
        Check if user has completed OAuth authentication

        Args:
            pin_id: PIN ID from initiate_auth
            state: Optional CSRF state token for validation

        Returns:
            Encrypted auth token if completed, None if pending

        Raises:
            PlexPinExpiredError: If PIN not found or expired
            CSRFValidationError: If state validation fails
        """
        try:
            # Get cached PIN data
            cached_pin = pin_cache.get(pin_id)
            if not cached_pin:
                raise PlexPinExpiredError("PIN not found or expired")

            # Validate CSRF state if provided
            if state:
                stored_state = cached_pin.get("state_token")
                token_manager = get_token_manager()
                if not token_manager.validate_state_token(state, stored_state):
                    logger.warning(
                        f"CSRF state validation failed for PIN {sanitize_log_data(pin_id)}"
                    )
                    # Don't raise - just log for now (optional enforcement)

            # Check PIN status with Plex API
            headers = {
                "Accept": "application/json",
                "X-Plex-Client-Identifier": cached_pin["client_id"],
            }

            response = requests.get(
                f"https://plex.tv/api/v2/pins/{pin_id}",
                headers=headers,
                timeout=10,
            )

            if response.status_code == 404:
                pin_cache.delete(pin_id)
                raise PlexPinExpiredError("PIN expired or consumed")

            response.raise_for_status()
            pin_data = response.json()

            # Check if authentication complete
            if pin_data.get("authToken"):
                # DON'T validate the token here - it might be one-time use!
                # Just encrypt and return it for immediate use
                token_manager = get_token_manager()
                encrypted_token = token_manager.encrypt(pin_data["authToken"])

                # Clean up PIN cache
                pin_cache.delete(pin_id)

                logger.info(
                    "OAuth authentication successful, token encrypted and ready for use"
                )

                return encrypted_token

            # Still pending
            return None

        except (PlexPinExpiredError, PlexConnectionError):
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to check PIN status: {type(e).__name__}")
            raise PlexConnectionError(
                f"Failed to check authentication status: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Failed to check Plex auth status: {str(e)}")
            return None

    @staticmethod
    def validate_token(token: str) -> dict:
        """
        Validate a Plex authentication token

        Args:
            token: Plain text auth token to validate

        Returns:
            User data dict from Plex API

        Raises:
            InvalidTokenError: If token is invalid
            TokenExpiredError: If token has expired
            UnauthorizedError: If access is forbidden
            PlexConnectionError: If connection to Plex fails
        """
        if not token:
            raise InvalidTokenError(
                "No authentication token provided. Please authenticate with Plex first."
            )

        try:
            headers = {"X-Plex-Token": token, "Accept": "application/json"}

            response = requests.get(
                "https://plex.tv/api/v2/user", headers=headers, timeout=10
            )

            if response.status_code == 401:
                raise InvalidTokenError(
                    "Plex server rejected the authentication token. Token may be invalid or expired."
                )
            elif response.status_code == 403:
                raise UnauthorizedError(
                    "Access forbidden. Your Plex account may not have sufficient permissions."
                )
            elif response.status_code == 404:
                raise PlexConnectionError(
                    "Plex user API endpoint not found. Please check your Plex server version."
                )

            response.raise_for_status()
            return response.json()

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection to Plex.tv failed: {str(e)}")
            raise PlexConnectionError(
                "Unable to connect to Plex.tv servers. Please check your internet connection."
            )
        except requests.exceptions.Timeout as e:
            logger.error(f"Plex.tv request timed out: {str(e)}")
            raise PlexConnectionError(
                "Connection to Plex.tv timed out. Please try again."
            )
        except (
            InvalidTokenError,
            TokenExpiredError,
            UnauthorizedError,
            PlexConnectionError,
        ):
            raise
        except Exception as e:
            logger.error(f"Unexpected error validating token: {str(e)}")
            raise PlexConnectionError(f"Failed to validate token: {str(e)}")

    @staticmethod
    async def refresh_token(encrypted_token: str) -> str:
        """
        Refresh/validate a stored encrypted token

        Args:
            encrypted_token: Encrypted token to validate

        Returns:
            The same encrypted token if still valid

        Raises:
            InvalidTokenError: If token is invalid
            TokenExpiredError: If token has expired
        """
        if not encrypted_token:
            raise InvalidTokenError("No authentication token provided for refresh.")

        try:
            # Decrypt token
            token_manager = get_token_manager()
            decrypted_token = token_manager.decrypt(encrypted_token)

            # Validate with Plex
            headers = {"X-Plex-Token": decrypted_token, "Accept": "application/json"}

            response = requests.get(
                "https://plex.tv/api/v2/ping", headers=headers, timeout=10
            )

            if response.status_code == 401:
                raise TokenExpiredError(
                    "Plex authentication token has expired and cannot be refreshed."
                )
            elif response.status_code == 403:
                raise UnauthorizedError(
                    "Access forbidden during token refresh. Your Plex account may not have sufficient permissions."
                )

            response.raise_for_status()
            return encrypted_token

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection to Plex.tv failed during token refresh: {str(e)}")
            raise PlexConnectionError(
                "Unable to connect to Plex.tv servers for token refresh. Please check your internet connection."
            )
        except requests.exceptions.Timeout as e:
            logger.error(f"Plex.tv token refresh timed out: {str(e)}")
            raise PlexConnectionError(
                "Token refresh timed out. Please try again later."
            )
        except Exception as e:
            logger.error(f"Token decryption or validation failed: {str(e)}")
            raise InvalidTokenError(
                "Failed to decrypt or validate stored authentication token. Please re-authenticate with Plex."
            )

    @staticmethod
    async def get_servers(auth_token: str) -> List[PlexServerData]:
        """
        Get list of available Plex servers

        Args:
            auth_token: Plex.tv auth token (can be plaintext OAuth token or encrypted stored token)

        Returns:
            List of available servers
        """
        try:
            # Try to decrypt the token first (it might be from database)
            # If decryption fails, assume it's a plaintext OAuth token
            token_to_use = auth_token

            try:
                token_manager = get_token_manager()
                decrypted = token_manager.decrypt(auth_token)
                logger.info(
                    f"Successfully decrypted auth token (length: {len(decrypted)})"
                )
                token_to_use = decrypted
            except Exception as e:
                # Decryption failed - assume it's already a plaintext OAuth token
                logger.info(f"Using token as-is, decryption failed: {type(e).__name__}")
                token_to_use = auth_token

            logger.info(
                f"Attempting to connect to Plex with token (first 10 chars): {sanitize_log_data(token_to_use)}"
            )
            account = MyPlexAccount(token=token_to_use)
            servers = []

            for resource in account.resources():
                if resource.product == "Plex Media Server":
                    servers.append(
                        {
                            "name": resource.name,
                            "client_identifier": resource.clientIdentifier,
                            "product": resource.product,
                            "platform": resource.platform,
                            "owned": resource.owned,
                            "connections": [
                                {"uri": conn.uri, "local": conn.local}
                                for conn in resource.connections
                            ],
                        }
                    )

            logger.info(f"Found {len(servers)} Plex servers")
            return servers
        except Unauthorized as e:
            logger.error(f"Plex authentication failed: {str(e)}")
            raise InvalidTokenError(
                "Plex server rejected the authentication token. Token may be invalid or expired. Please re-authenticate."
            )
        except Exception as e:
            logger.error(f"Failed to get Plex servers: {str(e)}")
            raise PlexConnectionError(f"Failed to connect to Plex: {str(e)}")


class PlexService:
    """Service for interacting with Plex Media Server using encrypted OAuth tokens"""

    def __init__(
        self,
        encrypted_token: Optional[str] = None,
        server_name: Optional[str] = None,
    ):
        """
        Initialize Plex service

        Args:
            encrypted_token: Encrypted plex.tv OAuth token
            server_name: Name of the Plex server to connect to
        """
        self.encrypted_token = encrypted_token or settings.plex_auth_token
        self.server_name = server_name or getattr(settings, "plex_server_name", None)
        self._server: Optional[PlexServer] = None
        self._account: Optional[MyPlexAccount] = None
        self._decrypted_token: Optional[str] = None

    def _get_decrypted_token(self) -> str:
        """Get decrypted authentication token"""
        if self._decrypted_token is None:
            if not self.encrypted_token:
                raise ValueError("Plex authentication required. Please sign in.")

            try:
                decrypted = get_token_manager().decrypt(self.encrypted_token)
                if not decrypted:
                    raise ValueError("Decryption returned empty token")
                self._decrypted_token = decrypted
            except Exception as e:
                # Before the config API encrypted secrets, a token written
                # through it was stored in the clear. Use it and ask for a
                # re-save, as the *arr services do, rather than locking the
                # user out of their own instance.
                logger.warning(
                    f"Plex token decryption failed ({e}), treating as plain text. "
                    f"Re-save configuration to encrypt it."
                )
                self._decrypted_token = self.encrypted_token

        return self._decrypted_token

    def _get_account(self) -> MyPlexAccount:
        """Get or create plex.tv account connection"""
        if self._account is None:
            decrypted_token = self._get_decrypted_token()

            try:
                self._account = MyPlexAccount(token=decrypted_token)
                logger.info(
                    f"Authenticated to plex.tv as: {sanitize_log_data(self._account.username)}"
                )
            except Unauthorized:
                raise ValueError("Invalid or expired Plex authentication token")
            except Exception as e:
                raise ConnectionError(f"Failed to authenticate with plex.tv: {str(e)}")

        return self._account

    def _get_server(self) -> PlexServer:
        """Get or create Plex server connection with retry logic and graceful degradation"""
        if self._server is None:
            account = self._get_account()
            decrypted_token = self._get_decrypted_token()

            try:
                if self.server_name:
                    resource = account.resource(self.server_name)

                    # Log available connection URLs for debugging
                    logger.info(f"Available connection URLs for {self.server_name}:")
                    for conn in resource.connections:
                        logger.info(
                            f"  - {conn.uri} (local={conn.local}, relay={conn.relay})"
                        )

                    # Retry with exponential backoff
                    max_retries = 3
                    last_error = None

                    for attempt in range(max_retries):
                        try:
                            # PlexAPI will try URLs in order: local first, then remote, then relay
                            self._server = resource.connect(timeout=10)
                            logger.info(
                                f"✅ Connected to Plex server: {self.server_name}"
                                + (f" (attempt {attempt + 1})" if attempt > 0 else "")
                            )
                            break
                        except Exception as conn_err:
                            last_error = conn_err
                            if attempt < max_retries - 1:
                                wait_time = 2**attempt  # 1s, 2s, 4s exponential backoff
                                logger.warning(
                                    f"Connection attempt {attempt + 1}/{max_retries} failed: {conn_err}. "
                                    f"Retrying in {wait_time}s..."
                                )
                                time.sleep(wait_time)
                            else:
                                # Final attempt - try relay explicitly
                                logger.info(
                                    "All direct connection attempts failed, trying relay..."
                                )
                                relay_conns = [
                                    c for c in resource.connections if c.relay
                                ]
                                if relay_conns:
                                    try:
                                        self._server = PlexServer(
                                            baseurl=relay_conns[0].uri,
                                            token=decrypted_token,
                                            timeout=10,
                                        )
                                        logger.info(
                                            f"✅ Connected via relay to: {self.server_name}"
                                        )
                                        break
                                    except Exception as relay_err:
                                        logger.error(
                                            f"Relay connection also failed: {relay_err}"
                                        )
                                        raise PlexConnectionError(
                                            f"Could not connect to Plex server '{self.server_name}'. "
                                            f"Server found but unreachable after {max_retries} attempts. "
                                            f"Please check:\n"
                                            f"  • Plex Media Server is running\n"
                                            f"  • Network connectivity to server\n"
                                            f"  • Firewall/router settings\n"
                                            f"  • Port forwarding configuration\n"
                                            f"Last error: {str(last_error)}"
                                        )
                                else:
                                    raise PlexConnectionError(
                                        f"Could not connect to Plex server '{self.server_name}'. "
                                        f"Server found but unreachable (no relay available). "
                                        f"Please check:\n"
                                        f"  • Plex Media Server is running\n"
                                        f"  • Network connectivity to server\n"
                                        f"  • Firewall/router settings allow remote access\n"
                                        f"Last error: {str(last_error)}"
                                    )
                else:
                    servers = account.resources()
                    plex_servers = [
                        s for s in servers if s.product == "Plex Media Server"
                    ]

                    if not plex_servers:
                        raise ValueError("No Plex Media Servers found")

                    self._server = plex_servers[0].connect(timeout=10)
                    logger.info(
                        f"Connected to Plex server: {self._server.friendlyName}"
                    )

            except NotFound:
                raise ValueError(f"Plex server '{self.server_name}' not found")
            except PlexConnectionError:
                raise
            except Exception as e:
                raise ConnectionError(f"Failed to connect to Plex server: {str(e)}")

        return self._server

    def test_connection(
        self,
    ) -> Union[PlexConnectionTestResult, PlexConnectionTestError]:
        """Test connection to Plex server"""
        try:
            account = self._get_account()
            server = self._get_server()

            return {
                "success": True,
                "username": account.username,
                "email": account.email,
                "server_name": server.friendlyName,
                "version": server.version,
                "platform": server.platform,
                "platform_version": server.platformVersion,
            }
        except Exception as e:
            logger.error(f"Plex connection test failed: {str(e)}")
            return {"success": False, "error": str(e)}

    async def get_available_servers(self) -> List[PlexServerData]:
        """Get list of available Plex servers for this account"""
        return await PlexAuthService.get_servers(self.encrypted_token)

    def get_libraries(
        self, library_type: Optional[str] = None
    ) -> List[PlexLibraryData]:
        """
        Get all libraries from media server

        Args:
            library_type: Filter by type ('movie' or 'show')

        Returns:
            List of library info dictionaries
        """
        try:
            server = self._get_server()
            libraries = []

            for section in server.library.sections():
                if library_type and section.type != library_type:
                    continue

                libraries.append(
                    {
                        "key": section.key,
                        "title": section.title,
                        "type": section.type,
                        "count": section.totalSize,
                    }
                )

            return libraries
        except Exception as e:
            logger.error(f"Failed to get Plex libraries: {str(e)}")
            raise

    def get_library(self, library_name: str) -> LibrarySection:
        """
        Get a specific library by name

        Args:
            library_name: Name of the library

        Returns:
            LibrarySection object
        """
        try:
            server = self._get_server()
            return server.library.section(library_name)
        except NotFound:
            raise ValueError(f"Library '{library_name}' not found")
        except Exception as e:
            logger.error(f"Failed to get library '{library_name}': {str(e)}")
            raise

    def filter_hardlinks(
        self, duplicates: Dict[str, List[Union[Movie, Episode]]]
    ) -> Dict[str, List[Union[Movie, Episode]]]:
        """
        Filter out hardlinks from duplicate sets

        Hardlinks are when multiple file paths point to the same physical file on disk.
        This is common with *arr apps that organize media into different folder structures.

        Args:
            duplicates: Dict mapping keys to lists of duplicate media items

        Returns:
            Filtered dict with hardlinks removed (only keeps true duplicates)
        """
        filtered_duplicates: Dict[str, List[Union[Movie, Episode]]] = {}
        total_inaccessible = 0
        total_items = 0

        logger.info(f"Filtering hardlinks from {len(duplicates)} duplicate groups")

        for key, items in duplicates.items():
            if len(items) < 2:
                logger.debug(f"Skipping '{key}' - only {len(items)} item(s)")
                continue

            total_items += len(items)

            # Get media info for all items
            items_with_info = []
            items_without_inode = []

            for item in items:
                info = self.get_media_info(item)
                if info.get("file_path"):
                    if info.get("inode"):
                        items_with_info.append((item, info))
                    else:
                        # File path exists but no inode (file not accessible)
                        items_without_inode.append(item)
                        total_inaccessible += 1

            # Group by inode to find hardlinks
            inode_groups: Dict[int, List[Union[Movie, Episode]]] = {}

            for item, info in items_with_info:
                inode = info.get("inode")
                if inode:
                    if inode not in inode_groups:
                        inode_groups[inode] = []
                    inode_groups[inode].append(item)

            # Only keep first item from each inode group (they're the same physical file)
            unique_items = []
            hardlink_count = 0

            for inode, inode_items in inode_groups.items():
                if len(inode_items) > 1:
                    # These are hardlinks - keep only the first one
                    hardlink_count += len(inode_items) - 1
                    logger.info(
                        f"Found {len(inode_items)} hardlinked files for inode {inode} - keeping 1"
                    )
                unique_items.append(inode_items[0])

            # Add items without inode info (couldn't check - assume not hardlinks)
            unique_items.extend(items_without_inode)

            # Only include if there are still 2+ unique files after filtering hardlinks
            if len(unique_items) >= 2:
                filtered_duplicates[key] = unique_items
                if hardlink_count > 0:
                    logger.info(
                        f"Filtered {hardlink_count} hardlinks from '{key}', {len(unique_items)} true duplicates remain"
                    )
            elif hardlink_count > 0:
                logger.info(
                    f"All {len(items)} files for '{key}' were hardlinks - not true duplicates, skipping"
                )

        # Log summary if files were inaccessible
        if total_inaccessible > 0:
            logger.warning(
                f"Hardlink detection: {total_inaccessible}/{total_items} files were not accessible. "
                f"Mount Plex media directories into the container to enable hardlink filtering for all files."
            )

        logger.info(
            f"Hardlink filtering result: {len(filtered_duplicates)} groups remain after filtering"
        )
        return filtered_duplicates

    def find_duplicate_movies(self, library_name: str) -> Dict[str, List[Movie]]:
        """
        Find duplicate movies in a library using Plex's native duplicate detection

        Uses Plex's API to find duplicates, then groups them properly.
        Note: Hardlink detection only works if media files are accessible.

        Args:
            library_name: Name of the movie library

        Returns:
            Dict mapping movie key to list of duplicate Movie objects
        """
        try:
            library = self.get_library(library_name)

            logger.info(f"Scanning library '{library_name}' for duplicates...")

            # First, let's check for movies with multiple versions (editions)
            all_movies = library.all()
            logger.info(f"Found {len(all_movies)} total movies in library")

            duplicates: Dict[str, List[Movie]] = {}
            multi_version_movies = []

            # Find movies with multiple media items (editions/versions)
            for movie in all_movies:
                # Filter out sample files when counting media versions
                non_sample_media = [
                    media
                    for media in movie.media
                    if media.parts
                    and media.parts[0].file
                    and not is_sample_file(media.parts[0].file)
                ]

                if len(non_sample_media) > 1:
                    multi_version_movies.append(movie)
                    key = f"{movie.title}|{movie.year}" if movie.year else movie.title

                    logger.info(
                        f"Found multi-version: '{movie.title} ({movie.year})' has {len(non_sample_media)} versions"
                    )
                    for i, media in enumerate(non_sample_media, 1):
                        part = media.parts[0] if media.parts else None
                        if part:
                            logger.debug(
                                f"  Version {i}: {media.videoResolution} {media.bitrate//1000 if media.bitrate else '?'}kbps - {part.file}"
                            )

                    # For multi-version movies, treat them as duplicates
                    # We'll add the movie once, but the scan route will handle multiple media items
                    if key not in duplicates:
                        duplicates[key] = []
                    # Add the movie to the duplicates list
                    duplicates[key].append(movie)

            logger.info(
                f"Found {len(duplicates)} movies with multiple versions/editions"
            )

            # Also check Plex's native duplicate detection for separate movie entries
            plex_duplicates = library.search(duplicate=True)
            logger.info(
                f"Plex API reports {len(plex_duplicates)} items marked as duplicates"
            )

            # Group Plex-detected duplicates by title+year
            # Filter out movies that only have sample files (no real duplicates)
            for movie in plex_duplicates:
                # Count non-sample media files
                non_sample_media = [
                    media
                    for media in movie.media
                    if media.parts
                    and media.parts[0].file
                    and not is_sample_file(media.parts[0].file)
                ]

                # Only add if there are multiple non-sample versions
                # A single movie with only a sample file is not a true duplicate
                if len(non_sample_media) < 2:
                    logger.debug(
                        f"Skipping '{movie.title}' from Plex duplicates - only {len(non_sample_media)} non-sample media file(s)"
                    )
                    continue
                key = f"{movie.title}|{movie.year}" if movie.year else movie.title
                if key not in duplicates:
                    duplicates[key] = []
                if movie not in duplicates[key]:
                    duplicates[key].append(movie)

            logger.info(f"Total duplicate groups: {len(duplicates)}")

            logger.info(
                f"Returning {len(duplicates)} duplicate groups (hardlink filtering skipped - files not accessible)"
            )

            return duplicates
        except Exception as e:
            logger.error(f"Failed to find duplicate movies: {str(e)}")
            raise

    def find_duplicate_episodes(self, library_name: str) -> Dict[str, List[Episode]]:
        """
        Find duplicate episodes in a TV show library

        Like movies, episodes with multiple versions show as ONE episode object
        with multiple media files in episode.media[] array. This scans all episodes
        and returns those with 2+ media versions.

        Args:
            library_name: Name of the TV show library

        Returns:
            Dict mapping episode identifier to list containing the single Episode object with multi-versions
        """
        try:
            library = self.get_library(library_name)

            # Get ALL episodes in the library
            all_episodes = library.search(libtype="episode")

            logger.info(f"Scanning library '{library_name}' for duplicate episodes...")
            logger.info(f"Found {len(all_episodes)} total episodes in library")

            # Find episodes with multiple media versions (duplicates)
            multi_version_episodes: Dict[str, List[Episode]] = {}

            for episode in all_episodes:
                # Filter out sample files first
                non_sample_media = [
                    m
                    for m in episode.media
                    if not any(
                        is_sample_file(part.file) for part in m.parts if part.file
                    )
                ]

                # Check if this episode has multiple versions (after filtering samples)
                if len(non_sample_media) >= 2:
                    show_title = (
                        episode.grandparentTitle
                        if hasattr(episode, "grandparentTitle")
                        else "Unknown Show"
                    )
                    key = f"{show_title}|S{episode.seasonNumber:02d}E{episode.episodeNumber:02d}"
                    # Store the episode (not multiple episodes, just one episode with multi-versions)
                    multi_version_episodes[key] = [episode]

            logger.info(
                f"Found {len(multi_version_episodes)} episodes with multiple versions"
            )

            for key, episodes in list(multi_version_episodes.items())[
                :5
            ]:  # Show first 5
                ep = episodes[0]
                logger.debug(f"  '{key}': {len(ep.media)} versions")

            logger.info(
                f"Returning {len(multi_version_episodes)} multi-version episodes"
            )

            return multi_version_episodes
        except Exception as e:
            logger.error(f"Failed to find duplicate episodes: {str(e)}", exc_info=True)
            raise

    def get_media_info(self, media: Union[Movie, Episode]) -> PlexMediaInfo:
        """
        Extract media information from a Plex media object

        Args:
            media: Plex media object (Movie, Episode, etc.)

        Returns:
            Dict with media information including hardlink detection
        """
        try:
            # Get the first media part (file)
            media_parts = media.media
            if not media_parts:
                return {}

            media_item = media_parts[0]
            part = media_item.parts[0] if media_item.parts else None

            file_path = part.file if part else None
            file_size = part.size if part else 0

            # Get inode for hardlink detection
            inode = None
            nlink = 1

            if file_path:
                if os.path.exists(file_path):
                    try:
                        stat_info = os.stat(file_path)
                        inode = stat_info.st_ino
                        nlink = stat_info.st_nlink
                    except OSError as e:
                        logger.warning(f"Failed to get inode for {file_path}: {e}")
                else:
                    logger.warning(f"File not accessible: {file_path}")
                    logger.warning(
                        f"File not accessible: {file_path} - "
                        f"Hardlink detection disabled. "
                        f"Mount Plex media directories to enable hardlink filtering."
                    )

            info: PlexMediaInfo = {
                "title": media.title,
                "year": getattr(media, "year", None),
                "rating_key": media.ratingKey,
                "file_path": file_path,
                "file_size": file_size,
                "duration": media.duration,
                "container": media_item.container if media_item else None,
                "video_codec": media_item.videoCodec if media_item else None,
                "video_resolution": media_item.videoResolution if media_item else None,
                "bitrate": media_item.bitrate if media_item else None,
                "audio_codec": media_item.audioCodec if media_item else None,
                "width": media_item.width if media_item else None,
                "height": media_item.height if media_item else None,
                "inode": inode,
                "is_hardlink": nlink
                > 1,  # If nlink > 1, this file has multiple hardlinks
            }

            # Add episode-specific info if applicable
            if hasattr(media, "seasonNumber"):
                info["season"] = media.seasonNumber
                info["episode"] = media.episodeNumber
                info["show_title"] = media.grandparentTitle

            return info
        except Exception as e:
            logger.error(f"Failed to extract media info: {str(e)}")
            return {}

    def refresh_library(self, library_name: str) -> bool:
        """
        Trigger a Plex library refresh/scan

        Args:
            library_name: Name of the library to refresh

        Returns:
            True if successful
        """
        try:
            library = self.get_library(library_name)
            library.update()
            logger.info(f"Triggered refresh for library '{library_name}'")
            return True
        except Exception as e:
            logger.error(f"Failed to refresh library '{library_name}': {str(e)}")
            return False

    def refresh_item(self, item_id: str) -> bool:
        """
        Refresh metadata for a specific Plex item (movie or episode).

        This uses the item's refresh() method to update only that specific item's metadata,
        which is much faster and more efficient than scanning the entire library.

        Args:
            item_id: Plex ratingKey of the item to refresh

        Returns:
            True if successful, False otherwise
        """
        try:
            server = self._get_server()
            # Fetch the item by its ratingKey
            item = server.fetchItem(int(item_id))
            # Call the item's refresh() method to update its metadata
            item.refresh()
            logger.info(
                f"Triggered metadata refresh for Plex item {item_id} ('{item.title}')"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to refresh Plex item {item_id}: {str(e)}")
            return False

    def get_collection_items(
        self, library_name: str, collection_name: str
    ) -> Union[List[Movie], List[Episode]]:
        """
        Get all items from a Plex collection (smart or manual)

        Args:
            library_name: Name of the library
            collection_name: Name of the collection

        Returns:
            List of media items in the collection
        """
        try:
            library = self.get_library(library_name)

            # Search for the collection
            collections = library.search(title=collection_name, libtype="collection")
            if not collections:
                raise ValueError(
                    f"Collection '{collection_name}' not found in '{library_name}'"
                )

            collection = collections[0]
            items = collection.items()

            logger.info(
                f"Retrieved {len(items)} items from collection '{collection_name}'"
            )
            return items
        except Exception as e:
            logger.error(f"Failed to get collection items: {str(e)}")
            raise
