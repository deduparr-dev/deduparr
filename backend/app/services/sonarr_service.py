"""
Sonarr service for TV show episode file management
"""

import logging
from typing import Dict, Optional

from pyarr import SonarrAPI
from pyarr.exceptions import PyarrAccessRestricted, PyarrConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.arr_helpers import (
    find_media_by_file_path,
    manual_import_file,
    rescan_media_item,
    trigger_full_library_scan,
)
from app.services.base_service import BaseExternalService

logger = logging.getLogger(__name__)


class SonarrService(BaseExternalService):
    """Service for interacting with Sonarr"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self._client: Optional[SonarrAPI] = None

    async def find_episode_by_file_path(self, file_path: str) -> Optional[dict]:
        """
        Find episode by file path using the episodefile API endpoint

        This is MUCH more efficient than iterating through all series and episodes.
        Old approach: O(n) API calls where n = number of series (could be 100+)
        New approach: O(1) API call to get all episode files directly

        Uses filename matching (path-agnostic) to handle different mount points.

        Args:
            file_path: Full path to the episode file from Plex

        Returns:
            Episode data with episodeFile if found, None otherwise
        """
        client = await self._get_client()
        return find_media_by_file_path(client, file_path, "series", logger)

    async def _get_client(self) -> SonarrAPI:
        """Get Sonarr client instance"""
        if self._client is not None:
            return self._client

        config = await self._get_encrypted_config(
            service_name="Sonarr",
            config_keys={"url": "sonarr_url", "api_key": "sonarr_api_key"},
        )

        try:
            self._client = SonarrAPI(config["url"], config["api_key"])
            return self._client
        except (PyarrConnectionError, PyarrAccessRestricted) as e:
            raise ValueError(f"Sonarr connection failed: {e}")

    async def delete_episode_file(self, series_id: int, episode_file_id: int) -> bool:
        """
        Delete episode file from Sonarr

        Args:
            series_id: ID of the series
            episode_file_id: ID of the episode file to delete

        Returns:
            True if successful, False otherwise
        """
        client = await self._get_client()

        try:
            client.del_episode_file(episode_file_id)
            logger.info(
                f"Deleted episode file {episode_file_id} for series {series_id} from Sonarr"
            )
            return True
        except Exception as e:
            logger.error(
                f"Error deleting episode file {episode_file_id} for series {series_id}: {e}"
            )
            raise

    async def manual_import_file(
        self, file_path: str, series_id: int, search_for_file: bool = True
    ) -> Optional[bool]:
        """
        Manually import a specific file for a series using Sonarr's manual import API

        Args:
            file_path: Full path to the file to import (may be outdated if file was moved)
            series_id: ID of the series this file belongs to
            search_for_file: If True, search for actual file location if original path not found

        Returns:
            True if import succeeded, False if failed, None if file not found
        """
        client = await self._get_client()
        return await manual_import_file(
            client=client,
            file_path=file_path,
            media_id=series_id,
            media_type="series",
            logger_instance=logger,
            search_for_file=search_for_file,
        )

    async def rescan_series(
        self, series_id: int, kept_file_path: Optional[str] = None
    ) -> bool:
        """
        Trigger a scan to find and import files for a specific series

        This is used after deleting a duplicate file to make Sonarr find and import
        the better quality file we kept. We use DownloadedEpisodesScan with the folder
        containing the kept file to ensure Sonarr finds it.

        Args:
            series_id: ID of the series to scan for
            kept_file_path: Path to the file we kept (if known). If provided, we'll
                           scan the parent directory of this file. If not provided,
                           we'll scan the series' configured path.

        Returns:
            True if command was successfully queued, False otherwise
        """
        client = await self._get_client()
        return await rescan_media_item(
            client=client,
            media_id=series_id,
            media_type="series",
            kept_file_path=kept_file_path,
            logger_instance=logger,
        )

    async def trigger_rescan_all(self) -> bool:
        """
        Trigger a full library scan for all series

        This is used when we have a file that isn't tracked in Sonarr yet
        and we want Sonarr to find and import it.

        Returns:
            True if command was successfully queued
        """
        client = await self._get_client()
        return await trigger_full_library_scan(
            client=client, media_type="series", logger_instance=logger
        )

    async def test_connection(self) -> Dict[str, str | bool]:
        """
        Test connection to Sonarr

        Returns:
            Dictionary with system status if successful, error info if failed
            Keys: success (bool), version (str) if success, error (str) if failed
        """
        try:
            client = await self._get_client()
            status = client.get_system_status()
            return {"success": True, "version": status.get("version", "unknown")}
        except Exception as e:
            logger.error(f"Sonarr connection test failed: {e}")
            return {"success": False, "error": str(e)}
