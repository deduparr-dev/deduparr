"""
Setup wizard service for first-run configuration and validation
"""

import asyncio
import logging
from typing import Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.config import Config
from app.services.media_server import (
    MediaServerType,
    configured_types,
    get_media_servers,
)
from app.services.scan.runner import drop_pending_sets
from app.services.media_server.jellyfin_adapter import JellyfinAdapter
from app.services.media_server.plex_service import PlexAuthService, PlexService
from app.services.download.qbittorrent_service import QBittorrentService
from app.services.arr.radarr_service import RadarrService
from app.services.arr.sonarr_service import SonarrService
from app.services.shared.security import (
    decrypt_if_encrypted,
    encrypt_if_sensitive,
    is_masked,
)

logger = logging.getLogger(__name__)


class SetupService:
    """Service for managing setup wizard and configuration validation"""

    # A media server is the one thing Deduparr cannot work without; which one,
    # and whether both, is decided by the credentials that are present.
    # qBittorrent, Radarr and Sonarr are optional and enable automated deletion.

    # Optional *arr services - at least one enables automated *arr integration
    # Both can be configured if user has both movies and TV shows
    ARR_SERVICE_KEYS = {
        "radarr": ["radarr_url", "radarr_api_key"],
        "sonarr": ["sonarr_url", "sonarr_api_key"],
    }

    SETUP_COMPLETE_KEY = "setup_completed"

    def __init__(self, db: AsyncSession):
        self.db = db

    async def is_setup_complete(self) -> bool:
        """
        Check if initial setup has been completed

        Returns:
            True if setup is complete, False otherwise
        """
        # Check if setup is marked complete
        result = await self.db.execute(
            select(Config).where(Config.key == self.SETUP_COMPLETE_KEY)
        )
        setup_config = result.scalar_one_or_none()

        if not setup_config or setup_config.value != "true":
            return False

        # At least one media server has to be usable
        if not await configured_types(self.db):
            return False

        # All required keys present - setup is complete
        # Optional services (qBittorrent, *arr services) can be configured later
        return True

    async def get_setup_status(
        self,
    ) -> Dict[str, str | bool | List[str] | Dict[str, bool]]:
        """
        Get detailed setup status

        Returns:
            Dictionary with setup completion status and missing configurations
            Keys: is_complete (bool), missing_required (List[str]),
                  configured_services (Dict[str, bool]), database_type (str)
        """
        is_complete = await self.is_setup_complete()
        missing_required = []
        servers = await configured_types(self.db)
        configured_services = {
            "radarr": False,
            "sonarr": False,
            **{server.value: True for server in MediaServerType},
        }
        for server in MediaServerType:
            configured_services[server.value] = server in servers

        if not servers:
            missing_required.append("media_server")

        # Check which *arr services are configured
        for service_name, service_keys in self.ARR_SERVICE_KEYS.items():
            service_configured = True
            for key in service_keys:
                result = await self.db.execute(select(Config).where(Config.key == key))
                config = result.scalar_one_or_none()
                if not config or not config.value:
                    service_configured = False
                    break
            configured_services[service_name] = service_configured

        # Check qBittorrent configuration (also optional)
        result = await self.db.execute(
            select(Config).where(Config.key == "qbittorrent_url")
        )
        qbit_url = result.scalar_one_or_none()
        result = await self.db.execute(
            select(Config).where(Config.key == "qbittorrent_username")
        )
        qbit_user = result.scalar_one_or_none()
        result = await self.db.execute(
            select(Config).where(Config.key == "qbittorrent_password")
        )
        qbit_pass = result.scalar_one_or_none()
        configured_services["qbittorrent"] = bool(
            qbit_url
            and qbit_url.value
            and qbit_user
            and qbit_user.value
            and qbit_pass
            and qbit_pass.value
        )

        return {
            "is_complete": is_complete,
            "missing_required": missing_required,
            "configured_services": configured_services,
            "database_type": settings.database_type,
        }

    async def test_plex_connection(
        self, auth_token: str, server_name: str
    ) -> Dict[str, str | bool | List[str]]:
        """
        Test Plex server connection

        Args:
            auth_token: Encrypted Plex authentication token, blank for the stored one
            server_name: Name of the Plex server

        Returns:
            Dictionary with connection test results
            Keys: success (bool), error (str) if failed,
                  available_servers (List[str]) if server not found,
                  version (str), server_name (str), platform (str) if success
        """
        try:
            auth_token = await self.secret_or_stored("plex_auth_token", auth_token)

            # Verify server exists in available servers
            servers = await PlexAuthService.get_servers(auth_token)
            server_found = any(s["name"] == server_name for s in servers)

            if not server_found:
                return {
                    "success": False,
                    "error": f"Server '{server_name}' not found",
                    "available_servers": [s["name"] for s in servers],
                }

            # Test connection using PlexService
            plex_service = PlexService(
                encrypted_token=auth_token, server_name=server_name
            )
            result = plex_service.test_connection()

            return result
        except Exception as e:
            logger.error(f"Plex connection test failed: {str(e)}")
            return {"success": False, "error": str(e)}

    async def test_radarr_connection(
        self, url: str, api_key: str
    ) -> Dict[str, str | bool]:
        """
        Test Radarr API connection

        Args:
            url: Radarr URL
            api_key: Radarr API key, blank for the stored one

        Returns:
            Dictionary with connection test results
            Keys: success (bool), version (str) if success, error (str) if failed
        """
        return await self._test_service(
            RadarrService(self.db),
            {
                "radarr_url": url,
                "radarr_api_key": await self.secret_or_stored(
                    "radarr_api_key", api_key, "radarr_url", url
                ),
            },
        )

    async def test_sonarr_connection(
        self, url: str, api_key: str
    ) -> Dict[str, str | bool]:
        """
        Test Sonarr API connection

        Args:
            url: Sonarr URL
            api_key: Sonarr API key, blank for the stored one

        Returns:
            Dictionary with connection test results
            Keys: success (bool), version (str) if success, error (str) if failed
        """
        return await self._test_service(
            SonarrService(self.db),
            {
                "sonarr_url": url,
                "sonarr_api_key": await self.secret_or_stored(
                    "sonarr_api_key", api_key, "sonarr_url", url
                ),
            },
        )

    async def test_qbittorrent_connection(
        self, url: str, username: str, password: str
    ) -> Dict[str, str | bool]:
        """
        Test qBittorrent connection

        Args:
            url: qBittorrent URL
            username: qBittorrent username
            password: qBittorrent password, blank for the stored one

        Returns:
            Dictionary with connection test results
            Keys: success (bool), version (str) if success, error (str) if failed
        """
        return await self._test_service(
            QBittorrentService(self.db),
            {
                "qbittorrent_url": url,
                "qbittorrent_username": username,
                "qbittorrent_password": await self.secret_or_stored(
                    "qbittorrent_password", password, "qbittorrent_url", url
                ),
            },
        )

    async def _test_service(
        self,
        service: RadarrService | SonarrService | QBittorrentService,
        config: Dict[str, str],
    ) -> Dict[str, str | bool]:
        """Test a service with the credentials given rather than the stored ones."""
        service._get_encrypted_config = _fixed_config(config)
        try:
            return await service.test_connection()
        except Exception as e:
            logger.error(f"{type(service).__name__} connection test failed: {e}")
            return {"success": False, "error": str(e)}

    async def secret_or_stored(
        self,
        key: str,
        value: str,
        target_key: Optional[str] = None,
        target: Optional[str] = None,
    ) -> str:
        """
        A secret sent for a connection test, or the stored one in its place.

        The API never hands a stored secret out, so Settings sends its field
        blank, and the mask a secret is shown as stands for it too. It goes
        only to the server stored with it (target_key): with no login, anyone
        could otherwise have it sent to a server of their own.
        """
        if value and not is_masked(key, value):
            return value
        result = await self.db.execute(
            select(Config).where(Config.key.in_([key, target_key]))
        )
        stored = {config.key: config.value for config in result.scalars()}
        if target_key and stored.get(target_key) != target:
            return ""
        return stored.get(key) or ""

    async def get_plex_libraries(
        self, auth_token: str, server_name: Optional[str] = None
    ) -> List[Dict]:
        """
        Get list of available Plex libraries

        Args:
            auth_token: Encrypted Plex authentication token
            server_name: Name of the Plex server

        Returns:
            List of available libraries, each dict contains:
            key (str), title (str), type (str), agent (str)
        """
        try:
            plex_service = PlexService(
                encrypted_token=auth_token, server_name=server_name
            )
            server = plex_service._get_server()
            libraries = []

            for library in server.library.sections():
                libraries.append(
                    {
                        "key": str(library.key),
                        "title": library.title,
                        "type": library.type,
                        "agent": library.agent,
                    }
                )

            return libraries
        except Exception as e:
            logger.error(f"Failed to get Plex libraries: {str(e)}")
            raise ValueError(f"Failed to get Plex libraries: {str(e)}")

    async def save_configuration(self, config_data: Dict[str, str]) -> None:
        """
        Save configuration settings

        Args:
            config_data: Dictionary of config key-value pairs
        """
        for key, value in config_data.items():
            # Skip empty values - don't save them
            if not value:
                logger.warning(f"Skipping empty value for key: {key}")
                continue
            # The mask a secret was shown as keeps the stored one
            if is_masked(key, value):
                continue

            # Secrets are encrypted by the one helper every write path uses
            value = encrypt_if_sensitive(key, value)

            result = await self.db.execute(select(Config).where(Config.key == key))
            config = result.scalar_one_or_none()

            if config:
                config.value = value
            else:
                config = Config(key=key, value=value)
                self.db.add(config)

        await self.db.commit()

    async def mark_setup_complete(self) -> None:
        """Mark setup as complete"""
        result = await self.db.execute(
            select(Config).where(Config.key == self.SETUP_COMPLETE_KEY)
        )
        config = result.scalar_one_or_none()

        if config:
            config.value = "true"
        else:
            config = Config(key=self.SETUP_COMPLETE_KEY, value="true")
            self.db.add(config)

        await self.db.commit()

    async def reset_setup(self) -> None:
        """
        Reset setup wizard status to allow reconfiguration

        This marks setup as incomplete so users can re-run the wizard
        from settings to update their configuration.
        """
        result = await self.db.execute(
            select(Config).where(Config.key == self.SETUP_COMPLETE_KEY)
        )
        config = result.scalar_one_or_none()

        if config:
            config.value = "false"
            await self.db.commit()

    async def clear_plex_credentials(self) -> None:
        """
        Log out of Plex: plex.tv revokes the token, and this instance forgets it and
        the pending sets only Plex could report on.

        Logging out does not depend on plex.tv, which refuses a token already
        revoked and can be out of reach.
        """
        result = await self.db.execute(
            select(Config.value).where(Config.key == "plex_auth_token")
        )
        token = result.scalar_one_or_none()
        if token:
            try:
                await asyncio.to_thread(PlexService(encrypted_token=token).sign_out)
            except Exception as e:
                logger.warning(f"plex.tv did not revoke the Plex token: {e}")

        await self.db.execute(
            delete(Config).where(
                Config.key.in_(("plex_auth_token", "plex_server_name"))
            )
        )
        await drop_pending_sets(self.db, MediaServerType.PLEX)
        await self.db.commit()

    async def test_jellyfin_connection(
        self, url: str, api_key: str
    ) -> Dict[str, object]:
        """
        Check a Jellyfin server before its credentials are saved.

        The key has to be an administrator one, so this reports that
        explicitly rather than leaving the user with a bare 403 later.
        """
        config_data = {
            "jellyfin_url": url,
            "jellyfin_api_key": await self.secret_or_stored(
                "jellyfin_api_key", api_key, "jellyfin_url", url
            ),
        }
        adapter = JellyfinAdapter(self.db)
        adapter._get_encrypted_config = _fixed_config(config_data)

        result = await adapter.test_connection()
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "unknown error")}

        return {
            "success": True,
            "server_name": result.get("server_name", ""),
            "version": result.get("version", ""),
        }

    async def get_jellyfin_libraries(self, url: str, api_key: str) -> List[Dict]:
        """
        Libraries of a Jellyfin server whose credentials are not stored yet.

        The setup wizard needs this before it saves anything, the same way the
        Plex step lists libraries straight from an unsaved token.
        """
        adapter = JellyfinAdapter(self.db)
        adapter._get_encrypted_config = _fixed_config(
            {"jellyfin_url": url, "jellyfin_api_key": api_key}
        )
        return [
            {**library, "server": MediaServerType.JELLYFIN.value}
            for library in await adapter.get_libraries()
        ]

    async def get_media_libraries(self) -> List[Dict]:
        """
        Libraries from every configured media server.

        The server is included so the UI can show where a library came from
        when both are set up and both have, say, a "Movies" library.
        """
        libraries: List[Dict] = []
        for server in await get_media_servers(self.db):
            try:
                for library in await server.get_libraries():
                    libraries.append({**library, "server": server.type.value})
            except Exception as e:
                logger.error(f"Could not list {server.type.value} libraries: {e}")
        return libraries


def _fixed_config(values: Dict[str, str]):
    """
    Feed an adapter credentials that are not in the database yet.

    As with stored ones, the secret may be encrypted: a test with its field
    left blank runs with the stored secret.
    """

    async def _get(service_name: str, config_keys: Dict[str, str]) -> Dict[str, str]:
        return {
            internal: (
                decrypt_if_encrypted(values[db_key])
                if internal in ("api_key", "password")
                else values[db_key]
            )
            for internal, db_key in config_keys.items()
        }

    return _get
