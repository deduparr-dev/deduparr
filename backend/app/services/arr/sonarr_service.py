"""
Sonarr service for TV show episode file management
"""

import logging
from typing import Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.arr.client import (
    ArrAuthError,
    ArrClientError,
    ArrConnectionError,
    SonarrClient,
)
from app.services.arr.helpers import (
    find_media_by_file_path,
    rescan_media_item,
)
from app.services.shared.base_service import BaseExternalService

logger = logging.getLogger(__name__)


class SonarrService(BaseExternalService):
    """Service for interacting with Sonarr"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self._client: Optional[SonarrClient] = None

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
        return await find_media_by_file_path(client, file_path, "series", logger)

    async def _get_client(self) -> SonarrClient:
        """Get Sonarr client instance"""
        if self._client is not None:
            return self._client

        config = await self._get_encrypted_config(
            service_name="Sonarr",
            config_keys={"url": "sonarr_url", "api_key": "sonarr_api_key"},
        )

        try:
            self._client = SonarrClient(
                base_url=config["url"], api_key=config["api_key"]
            )
            return self._client
        except (ArrConnectionError, ArrAuthError) as e:
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
            await client.del_episode_file(episode_file_id)
            logger.info(
                f"Deleted episode file {episode_file_id} for series {series_id} from Sonarr"
            )
            return True
        except ArrClientError as e:
            logger.error(
                f"Error deleting episode file {episode_file_id} for series {series_id}: {e}"
            )
            raise

    async def rescan_series(
        self, series_id: Optional[int], kept_file_path: str
    ) -> None:
        """
        Have Sonarr rescan a series from disk, or every series without an id.

        Used after deleting duplicates, so Sonarr imports the file kept and
        drops the ones deleted.
        """
        client = await self._get_client()
        await rescan_media_item(client, series_id, kept_file_path, logger)

    async def test_connection(self) -> Dict[str, str | bool]:
        """
        Test connection to Sonarr

        Returns:
            Dictionary with system status if successful, error info if failed
            Keys: success (bool), version (str) if success, error (str) if failed
        """
        try:
            client = await self._get_client()
            status = await client.get_system_status()
            return {"success": True, "version": status.get("version", "unknown")}
        except ArrClientError as e:
            logger.error(f"Sonarr connection test failed: {e}")
            return {"success": False, "error": str(e)}
