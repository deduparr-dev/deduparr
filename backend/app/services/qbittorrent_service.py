"""
qBittorrent service for media library management
"""

import logging
from typing import Dict, Optional

from qbittorrentapi import APIConnectionError, Client, LoginFailed
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.base_service import BaseExternalService

logger = logging.getLogger(__name__)


class QBittorrentService(BaseExternalService):
    """Service for interacting with qBittorrent"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def _get_client(self) -> Client:
        """Get qBittorrent client instance (no caching - always fresh connection)"""

        config = await self._get_encrypted_config(
            service_name="qBittorrent",
            config_keys={
                "url": "qbittorrent_url",
                "username": "qbittorrent_username",
                "password": "qbittorrent_password",
            },
        )

        try:
            client = Client(
                host=config["url"],
                username=config["username"],
                password=config["password"],
            )
            client.auth_log_in()
            return client
        except LoginFailed as e:
            raise ValueError(f"qBittorrent login failed: {e}")
        except APIConnectionError as e:
            raise ValueError(f"qBittorrent connection failed: {e}")

    async def find_item_by_file_path(self, file_path: str) -> Optional[tuple[str, int]]:
        """
        Find torrent hash by file path and count total torrents for this file.

        Matching strategy (in order):
        1. Exact match: full_path == file_path
        2. Filename match: Extract filename from file_path and match against torrent file basenames
        3. Normalized match: Handle path differences (spaces, casing, etc.)

        Args:
            file_path: Full path to the file (may be Plex path or actual filesystem path)

        Returns:
            Tuple of (torrent_hash, count) if found, None otherwise
            - torrent_hash: Hash of the first matching torrent
            - count: Total number of torrents containing this file
        """
        import os

        client = await self._get_client()

        try:
            torrents = client.torrents_info()
            found_hash = None
            count = 0

            # Extract just the filename from the path for flexible matching
            search_filename = os.path.basename(file_path)

            # Normalize for comparison (lowercase, no extra spaces)
            normalized_search = search_filename.lower().replace(" ", ".")

            for torrent in torrents:
                torrent_files = client.torrents_files(torrent_hash=torrent.hash)
                for torrent_file in torrent_files:
                    # Construct full qBittorrent path
                    full_path = f"{torrent.save_path}/{torrent_file.name}"
                    torrent_filename = os.path.basename(torrent_file.name)
                    normalized_torrent = torrent_filename.lower().replace(" ", ".")

                    # Match strategies:
                    # 1. Exact full path match
                    if full_path == file_path:
                        if not found_hash:
                            found_hash = torrent.hash
                            logger.debug(
                                f"Matched torrent {torrent.hash} via exact path: {full_path}"
                            )
                        count += 1
                        break

                    # 2. Exact filename match
                    if torrent_filename == search_filename:
                        if not found_hash:
                            found_hash = torrent.hash
                            logger.debug(
                                f"Matched torrent {torrent.hash} via filename: {torrent_filename}"
                            )
                        count += 1
                        break

                    # 3. Normalized filename match (handles spaces vs dots, casing)
                    if normalized_torrent == normalized_search:
                        if not found_hash:
                            found_hash = torrent.hash
                            logger.debug(
                                f"Matched torrent {torrent.hash} via normalized filename: {torrent_filename}"
                            )
                        count += 1
                        break

            if found_hash:
                logger.info(
                    f"Found torrent {found_hash} for file {file_path} ({count} total torrents)"
                )
                return (found_hash, count)

            logger.info(
                f"No torrent found for file: {file_path} (searched for '{search_filename}')"
            )
            return None
        except Exception as e:
            logger.error(f"Error finding torrent for {file_path}: {e}")
            raise

    async def remove_item(self, item_hash: str, delete_files: bool = True) -> bool:
        """
        Remove item from qBittorrent library

        Args:
            item_hash: Hash of the item to remove
            delete_files: Whether to delete files from disk

        Returns:
            True if successful, False otherwise
        """
        client = await self._get_client()

        try:
            client.torrents_delete(delete_files=delete_files, torrent_hashes=item_hash)
            logger.info(f"Removed item {item_hash} (delete_files={delete_files})")
            return True
        except Exception as e:
            logger.error(f"Error removing item {item_hash}: {e}")
            raise

    async def test_connection(self) -> Dict[str, str | bool]:
        """
        Test connection to qBittorrent

        Returns:
            Dictionary with connection test results
            Keys: success (bool), version (str) if success, error (str) if failed
        """
        try:
            client = await self._get_client()
            version = client.app_version()
            return {"success": True, "version": version}
        except Exception as e:
            logger.error(f"qBittorrent connection test failed: {e}")
            return {"success": False, "error": str(e)}
