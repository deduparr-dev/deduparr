"""
Plex service for interacting with Plex Media Server
Uses OAuth PIN authentication via plex.tv with token encryption
"""

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Union

import plexapi
import requests
from plexapi.exceptions import NotFound, Unauthorized
from plexapi.library import LibrarySection
from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer
from typing_extensions import TypedDict

from app.core.config import settings
from app.services.media_server.plex_exceptions import (
    PlexConnectionError,
    PlexPinExpiredError,
)
from app.services.shared.security import (
    InvalidTokenError,
    get_token_manager,
    pin_cache,
)

# Configure PlexAPI to identify as Deduparr
plexapi.X_PLEX_PRODUCT = "Deduparr"

logger = logging.getLogger(__name__)


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


class PlexAuthService:
    """Handles Plex OAuth authentication via PIN login, with the token encrypted"""

    @staticmethod
    async def initiate_auth() -> PlexAuthData:
        """
        Initiate OAuth PIN authentication

        Returns:
            Dict with auth URL and PIN info
        """
        try:
            # Generate unique client identifier
            client_id = str(uuid.uuid4())

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

            # Cache PIN state
            pin_cache.set(
                str(pin_data["id"]),
                {
                    "code": pin_data["code"],
                    "client_id": client_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )

            # Construct OAuth URL
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
    async def check_auth(pin_id: str) -> Optional[str]:
        """
        Check if user has completed OAuth authentication

        Args:
            pin_id: PIN ID from initiate_auth

        Returns:
            Encrypted auth token if completed, None if pending

        Raises:
            PlexPinExpiredError: If PIN not found or expired
        """
        try:
            # Get cached PIN data
            cached_pin = pin_cache.get(pin_id)
            if not cached_pin:
                raise PlexPinExpiredError("PIN not found or expired")

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
                token_to_use = token_manager.decrypt(auth_token)
            except Exception as e:
                # Decryption failed - assume it's already a plaintext OAuth token
                logger.info(f"Using token as-is, decryption failed: {type(e).__name__}")
                token_to_use = auth_token

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
                logger.info("Authenticated to plex.tv")
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
                        "key": str(section.key),
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
        Make Plex notice a file of a specific item (movie or episode) is gone.

        A metadata refresh leaves a deleted file listed as a version of the item, and
        only a scan removes it. Scanning just the item's folders is much faster than
        scanning the entire library.

        Args:
            item_id: Plex ratingKey of the item to refresh

        Returns:
            True if successful, False otherwise
        """
        try:
            server = self._get_server()
            # Fetch the item by its ratingKey
            item = server.fetchItem(int(item_id))
            section = item.section()
            for folder in {os.path.dirname(path) for path in item.locations}:
                section.update(path=folder)
            logger.info(f"Triggered a scan of Plex item {item_id} ('{item.title}')")
            return True
        except Exception as e:
            logger.error(f"Failed to refresh Plex item {item_id}: {str(e)}")
            return False
