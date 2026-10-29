"""
Radarr service for movie file management
"""

import logging
from typing import Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.arr.client import (
    ArrAuthError,
    ArrClientError,
    ArrConnectionError,
    MediaItem,
    RadarrClient,
)
from app.services.arr.helpers import find_movie_by_file_path, rescan_media_item
from app.services.shared.base_service import BaseExternalService
from app.services.arr.path_mapping import PathMapper

logger = logging.getLogger(__name__)


class RadarrService(BaseExternalService):
    """Service for interacting with Radarr"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self._client: Optional[RadarrClient] = None

    async def find_movie_by_file_path(self, file_path: str) -> Optional[MediaItem]:
        """
        Find movie by file path using filename matching (path-agnostic)

        Args:
            file_path: Full path to the movie file from Plex

        Returns:
            Movie data if found, None otherwise
        """
        client = await self._get_client()
        return await find_movie_by_file_path(client, file_path, logger)

    async def _get_client(self) -> RadarrClient:
        """Get Radarr client instance"""
        if self._client is not None:
            return self._client

        config = await self._get_encrypted_config(
            service_name="Radarr",
            config_keys={"url": "radarr_url", "api_key": "radarr_api_key"},
        )

        try:
            path_mapper = PathMapper.from_text(
                await self._get_optional_config("radarr_path_mappings")
            )
            self._client = RadarrClient(
                base_url=config["url"],
                api_key=config["api_key"],
                path_mapper=path_mapper,
            )
            return self._client
        except (ArrConnectionError, ArrAuthError) as e:
            raise ValueError(f"Radarr connection failed: {e}")

    async def delete_movie_file(self, movie_id: int, movie_file_id: int) -> bool:
        """
        Delete movie file from Radarr

        Args:
            movie_id: ID of the movie
            movie_file_id: ID of the movie file to delete

        Returns:
            True if successful, False otherwise
        """
        client = await self._get_client()

        try:
            await client.delete_movie_file(movie_file_id)
            logger.info(
                f"Deleted movie file {movie_file_id} for movie {movie_id} from Radarr"
            )
            return True
        except ArrClientError as e:
            logger.error(
                f"Error deleting movie file {movie_file_id} for movie {movie_id}: {e}"
            )
            raise

    async def rescan_movie(self, movie_id: Optional[int], kept_file_path: str) -> None:
        """
        Have Radarr rescan a movie from disk, or every movie without an id.

        Used after deleting duplicates, so Radarr imports the file kept and
        drops the ones deleted.
        """
        client = await self._get_client()
        await rescan_media_item(client, movie_id, kept_file_path, logger)

    async def test_connection(self) -> Dict[str, str | bool]:
        """
        Test connection to Radarr

        Returns:
            Dictionary with system status if successful, error info if failed
            Keys: success (bool), version (str) if success, error (str) if failed
        """
        try:
            client = await self._get_client()
            status = await client.get_system_status()
            return {"success": True, "version": status.get("version", "unknown")}
        except ArrClientError as e:
            logger.error(f"Radarr connection test failed: {e}")
            return {"success": False, "error": str(e)}
