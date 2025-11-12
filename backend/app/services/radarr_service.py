"""
Radarr service for movie file management
"""

import logging
from typing import Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.arr_client import (
    ArrAuthError,
    ArrClientError,
    ArrConnectionError,
    RadarrClient,
)
from app.services.arr_helpers import (
    find_media_by_file_path,
    manual_import_file,
    rescan_media_item,
    trigger_full_library_scan,
)
from app.services.base_service import BaseExternalService

logger = logging.getLogger(__name__)


class RadarrService(BaseExternalService):
    """Service for interacting with Radarr"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self._client: Optional[RadarrClient] = None

    async def find_movie_by_file_path(self, file_path: str) -> Optional[dict]:
        """
        Find movie by file path using filename matching (path-agnostic)

        Args:
            file_path: Full path to the movie file from Plex

        Returns:
            Movie data if found, None otherwise
        """
        client = await self._get_client()
        return await find_media_by_file_path(client, file_path, "movie", logger)

    async def _get_client(self) -> RadarrClient:
        """Get Radarr client instance"""
        if self._client is not None:
            return self._client

        config = await self._get_encrypted_config(
            service_name="Radarr",
            config_keys={"url": "radarr_url", "api_key": "radarr_api_key"},
        )

        try:
            self._client = RadarrClient(
                base_url=config["url"], api_key=config["api_key"]
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
            await client.del_movie_file(movie_file_id)
            logger.info(
                f"Deleted movie file {movie_file_id} for movie {movie_id} from Radarr"
            )
            return True
        except ArrClientError as e:
            logger.error(
                f"Error deleting movie file {movie_file_id} for movie {movie_id}: {e}"
            )
            raise

    async def manual_import_file(
        self, file_path: str, movie_id: int, search_for_file: bool = True
    ) -> Optional[bool]:
        """
        Manually import a specific file for a movie using Radarr's manual import API

        Args:
            file_path: Full path to the file to import (may be outdated if file was moved)
            movie_id: ID of the movie this file belongs to
            search_for_file: If True, search for actual file location if original path not found

        Returns:
            True if import succeeded, False if failed, None if file not found
        """
        client = await self._get_client()
        return await manual_import_file(
            client=client,
            file_path=file_path,
            media_id=movie_id,
            media_type="movie",
            logger_instance=logger,
            search_for_file=search_for_file,
        )

    async def rescan_movie(
        self, movie_id: int, kept_file_path: Optional[str] = None
    ) -> bool:
        """
        Trigger a scan to find and import files for a specific movie

        This is used after deleting a duplicate file to make Radarr find and import
        the better quality file we kept. We use DownloadedMoviesScan with the folder
        containing the kept file to ensure Radarr finds it.

        Args:
            movie_id: ID of the movie to scan for
            kept_file_path: Path to the file we kept (if known). If provided, we'll
                           scan the parent directory of this file. If not provided,
                           we'll scan the movie's configured path.

        Returns:
            True if command was successfully queued, False otherwise
        """
        client = await self._get_client()
        return await rescan_media_item(
            client=client,
            media_id=movie_id,
            media_type="movie",
            kept_file_path=kept_file_path,
            logger_instance=logger,
        )

    async def trigger_rescan_all(self) -> bool:
        """
        Trigger a full library scan for all movies

        This is used when we have a file that isn't tracked in Radarr yet
        and we want Radarr to find and import it.

        Returns:
            True if command was successfully queued
        """
        client = await self._get_client()
        return await trigger_full_library_scan(
            client=client, media_type="movie", logger_instance=logger
        )

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
