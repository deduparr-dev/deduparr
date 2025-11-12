"""
Setup wizard service for first-run configuration and validation
"""

import logging
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import Config
from app.services.plex_service import PlexAuthService, PlexService
from app.services.qbittorrent_service import QBittorrentService
from app.services.radarr_service import RadarrService
from app.services.sonarr_service import SonarrService
from app.services.security import InvalidTokenError, get_token_manager

logger = logging.getLogger(__name__)


class SetupService:
    """Service for managing setup wizard and configuration validation"""

    # Core required services - Only Plex is required as the data source
    # Other services (qBittorrent, Radarr, Sonarr) are optional and enable automated deletion
    REQUIRED_KEYS = [
        "plex_auth_token",
        "plex_server_name",
    ]

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

        # Check all required keys
        for key in self.REQUIRED_KEYS:
            result = await self.db.execute(select(Config).where(Config.key == key))
            config = result.scalar_one_or_none()
            if not config or not config.value:
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
        configured_services = {
            "radarr": False,
            "sonarr": False,
        }

        # Check core required keys
        for key in self.REQUIRED_KEYS:
            result = await self.db.execute(select(Config).where(Config.key == key))
            config = result.scalar_one_or_none()
            if not config or not config.value:
                missing_required.append(key)

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
            "database_type": "sqlite",
        }

    async def test_plex_connection(
        self, auth_token: str, server_name: str
    ) -> Dict[str, str | bool | List[str]]:
        """
        Test Plex server connection

        Args:
            auth_token: Encrypted Plex authentication token
            server_name: Name of the Plex server

        Returns:
            Dictionary with connection test results
            Keys: success (bool), error (str) if failed,
                  available_servers (List[str]) if server not found,
                  version (str), server_name (str), platform (str) if success
        """
        try:
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
            api_key: Radarr API key

        Returns:
            Dictionary with connection test results
            Keys: success (bool), version (str) if success, error (str) if failed
        """
        try:
            # Check if temp config entries already exist and delete them first
            result = await self.db.execute(
                select(Config).where(Config.key == "temp_radarr_url")
            )
            existing_temp_url = result.scalar_one_or_none()
            if existing_temp_url:
                await self.db.delete(existing_temp_url)

            result = await self.db.execute(
                select(Config).where(Config.key == "temp_radarr_api_key")
            )
            existing_temp_key = result.scalar_one_or_none()
            if existing_temp_key:
                await self.db.delete(existing_temp_key)

            await self.db.commit()

            # Now create new temp config entries
            temp_config_url = Config(key="temp_radarr_url", value=url)
            temp_config_key = Config(key="temp_radarr_api_key", value=api_key)
            self.db.add(temp_config_url)
            self.db.add(temp_config_key)
            await self.db.commit()

            result = await self.db.execute(
                select(Config).where(Config.key == "radarr_url")
            )
            existing_url = result.scalar_one_or_none()
            result = await self.db.execute(
                select(Config).where(Config.key == "radarr_api_key")
            )
            existing_key = result.scalar_one_or_none()

            if existing_url:
                old_url = existing_url.value
                existing_url.value = url
            else:
                old_url = None
                new_config = Config(key="radarr_url", value=url)
                self.db.add(new_config)

            if existing_key:
                old_key = existing_key.value
                existing_key.value = api_key
            else:
                old_key = None
                new_config = Config(key="radarr_api_key", value=api_key)
                self.db.add(new_config)

            await self.db.commit()

            radarr_service = RadarrService(self.db)
            result = await radarr_service.test_connection()

            await self.db.execute(select(Config).where(Config.key == "temp_radarr_url"))
            await self.db.delete(temp_config_url)
            await self.db.execute(
                select(Config).where(Config.key == "temp_radarr_api_key")
            )
            await self.db.delete(temp_config_key)
            await self.db.commit()

            if existing_url:
                existing_url.value = old_url
            elif old_url is None:
                result_config = await self.db.execute(
                    select(Config).where(Config.key == "radarr_url")
                )
                to_delete = result_config.scalar_one_or_none()
                if to_delete:
                    await self.db.delete(to_delete)

            if existing_key:
                existing_key.value = old_key
            elif old_key is None:
                result_config = await self.db.execute(
                    select(Config).where(Config.key == "radarr_api_key")
                )
                to_delete = result_config.scalar_one_or_none()
                if to_delete:
                    await self.db.delete(to_delete)

            await self.db.commit()

            return result
        except Exception as e:
            logger.error(f"Radarr connection test failed: {str(e)}")
            return {"success": False, "error": str(e)}

    async def test_sonarr_connection(
        self, url: str, api_key: str
    ) -> Dict[str, str | bool]:
        """
        Test Sonarr API connection

        Args:
            url: Sonarr URL
            api_key: Sonarr API key

        Returns:
            Dictionary with connection test results
            Keys: success (bool), version (str) if success, error (str) if failed
        """
        try:
            # Check if temp config entries already exist and delete them first
            result = await self.db.execute(
                select(Config).where(Config.key == "temp_sonarr_url")
            )
            existing_temp_url = result.scalar_one_or_none()
            if existing_temp_url:
                await self.db.delete(existing_temp_url)

            result = await self.db.execute(
                select(Config).where(Config.key == "temp_sonarr_api_key")
            )
            existing_temp_key = result.scalar_one_or_none()
            if existing_temp_key:
                await self.db.delete(existing_temp_key)

            await self.db.commit()

            # Now create new temp config entries
            temp_config_url = Config(key="temp_sonarr_url", value=url)
            temp_config_key = Config(key="temp_sonarr_api_key", value=api_key)
            self.db.add(temp_config_url)
            self.db.add(temp_config_key)
            await self.db.commit()

            result = await self.db.execute(
                select(Config).where(Config.key == "sonarr_url")
            )
            existing_url = result.scalar_one_or_none()
            result = await self.db.execute(
                select(Config).where(Config.key == "sonarr_api_key")
            )
            existing_key = result.scalar_one_or_none()

            if existing_url:
                old_url = existing_url.value
                existing_url.value = url
            else:
                old_url = None
                new_config = Config(key="sonarr_url", value=url)
                self.db.add(new_config)

            if existing_key:
                old_key = existing_key.value
                existing_key.value = api_key
            else:
                old_key = None
                new_config = Config(key="sonarr_api_key", value=api_key)
                self.db.add(new_config)

            await self.db.commit()

            sonarr_service = SonarrService(self.db)
            result = await sonarr_service.test_connection()

            await self.db.execute(select(Config).where(Config.key == "temp_sonarr_url"))
            await self.db.delete(temp_config_url)
            await self.db.execute(
                select(Config).where(Config.key == "temp_sonarr_api_key")
            )
            await self.db.delete(temp_config_key)
            await self.db.commit()

            if existing_url:
                existing_url.value = old_url
            elif old_url is None:
                result_config = await self.db.execute(
                    select(Config).where(Config.key == "sonarr_url")
                )
                to_delete = result_config.scalar_one_or_none()
                if to_delete:
                    await self.db.delete(to_delete)

            if existing_key:
                existing_key.value = old_key
            elif old_key is None:
                result_config = await self.db.execute(
                    select(Config).where(Config.key == "sonarr_api_key")
                )
                to_delete = result_config.scalar_one_or_none()
                if to_delete:
                    await self.db.delete(to_delete)

            await self.db.commit()

            return result
        except Exception as e:
            logger.error(f"Sonarr connection test failed: {str(e)}")
            return {"success": False, "error": str(e)}

    async def test_qbittorrent_connection(
        self, url: str, username: str, password: str
    ) -> Dict[str, str | bool]:
        """
        Test qBittorrent connection

        Args:
            url: qBittorrent URL
            username: qBittorrent username
            password: qBittorrent password

        Returns:
            Dictionary with connection test results
            Keys: success (bool), version (str) if success, error (str) if failed
        """
        # Encrypt password before testing
        token_manager = get_token_manager()
        encrypted_password = token_manager.encrypt(password)

        try:
            temp_config_url = Config(key="temp_qbittorrent_url", value=url)
            temp_config_user = Config(key="temp_qbittorrent_username", value=username)
            temp_config_pass = Config(
                key="temp_qbittorrent_password", value=encrypted_password
            )
            self.db.add(temp_config_url)
            self.db.add(temp_config_user)
            self.db.add(temp_config_pass)
            await self.db.commit()

            result = await self.db.execute(
                select(Config).where(Config.key == "qbittorrent_url")
            )
            existing_url = result.scalar_one_or_none()
            result = await self.db.execute(
                select(Config).where(Config.key == "qbittorrent_username")
            )
            existing_user = result.scalar_one_or_none()
            result = await self.db.execute(
                select(Config).where(Config.key == "qbittorrent_password")
            )
            existing_pass = result.scalar_one_or_none()

            if existing_url:
                old_url = existing_url.value
                existing_url.value = url
            else:
                old_url = None
                new_config = Config(key="qbittorrent_url", value=url)
                self.db.add(new_config)

            if existing_user:
                old_user = existing_user.value
                existing_user.value = username
            else:
                old_user = None
                new_config = Config(key="qbittorrent_username", value=username)
                self.db.add(new_config)

            if existing_pass:
                old_pass = existing_pass.value
                existing_pass.value = encrypted_password
            else:
                old_pass = None
                new_config = Config(
                    key="qbittorrent_password", value=encrypted_password
                )
                self.db.add(new_config)

            await self.db.commit()

            qbit_service = QBittorrentService(self.db)
            result = await qbit_service.test_connection()

            await self.db.execute(
                select(Config).where(Config.key == "temp_qbittorrent_url")
            )
            await self.db.delete(temp_config_url)
            await self.db.execute(
                select(Config).where(Config.key == "temp_qbittorrent_username")
            )
            await self.db.delete(temp_config_user)
            await self.db.execute(
                select(Config).where(Config.key == "temp_qbittorrent_password")
            )
            await self.db.delete(temp_config_pass)
            await self.db.commit()

            if existing_url:
                existing_url.value = old_url
            elif old_url is None:
                result_config = await self.db.execute(
                    select(Config).where(Config.key == "qbittorrent_url")
                )
                to_delete = result_config.scalar_one_or_none()
                if to_delete:
                    await self.db.delete(to_delete)

            if existing_user:
                existing_user.value = old_user
            elif old_user is None:
                result_config = await self.db.execute(
                    select(Config).where(Config.key == "qbittorrent_username")
                )
                to_delete = result_config.scalar_one_or_none()
                if to_delete:
                    await self.db.delete(to_delete)

            if existing_pass:
                existing_pass.value = old_pass
            elif old_pass is None:
                result_config = await self.db.execute(
                    select(Config).where(Config.key == "qbittorrent_password")
                )
                to_delete = result_config.scalar_one_or_none()
                if to_delete:
                    await self.db.delete(to_delete)

            await self.db.commit()

            return result
        except Exception as e:
            logger.error(f"qBittorrent connection test failed: {str(e)}")
            return {"success": False, "error": str(e)}

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
        token_manager = get_token_manager()

        # Keys that should be encrypted before storage
        encrypted_keys = {
            "qbittorrent_password",
            "plex_auth_token",
            "radarr_api_key",
            "sonarr_api_key",
            "smtp_password",
        }

        for key, value in config_data.items():
            # Skip empty values - don't save them
            if not value:
                logger.warning(f"Skipping empty value for key: {key}")
                continue

            # Encrypt sensitive values before saving
            if key in encrypted_keys:
                # Check if value is already encrypted to prevent double-encryption
                try:
                    token_manager.decrypt(value)
                    # Successfully decrypted - it's already encrypted, use as-is
                    logger.info(
                        f"Value for {key} is already encrypted, skipping re-encryption"
                    )
                except (InvalidTokenError, Exception):
                    # Not encrypted or invalid - encrypt it now
                    encrypted_value = token_manager.encrypt(value)
                    # Ensure encryption succeeded (should never return None for non-empty input)
                    if not encrypted_value:
                        raise ValueError(f"Failed to encrypt value for key: {key}")
                    value = encrypted_value

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
