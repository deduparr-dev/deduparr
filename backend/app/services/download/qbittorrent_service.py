"""
qBittorrent service for media library management
"""

import logging
import os
from typing import Dict, NamedTuple, Optional

from qbittorrentapi import APIConnectionError, Client, LoginFailed
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.media_server.file_probe import is_sample_file, is_video_file
from app.services.shared.base_service import BaseExternalService

logger = logging.getLogger(__name__)


class TorrentMatch(NamedTuple):
    """The first torrent holding a file, and how many torrents hold it."""

    hash: str
    count: int
    # Another feature-length video is in the same torrent, as in a season pack
    holds_other_videos: bool


def _normalized_name(path: str) -> str:
    return os.path.basename(path).lower().replace(" ", ".")


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
        except LoginFailed:
            # qbittorrent-api raises it without a message
            raise ValueError("qBittorrent rejected the username or password")
        except APIConnectionError as e:
            raise ValueError(f"qBittorrent connection failed: {e}")

    async def find_item_by_file_path(
        self, file_path: str, file_size: int
    ) -> Optional[TorrentMatch]:
        """
        Find the torrent holding a file.

        qBittorrent often sees the file under another mount, so a torrent file
        matches on its full path, or on its name together with its size. The
        name alone is not enough: unrelated releases share names like
        S01E01.mkv.

        Args:
            file_path: Path to the file, as the media server or this container sees it
            file_size: Its size in bytes
        """
        client = await self._get_client()
        wanted_name = _normalized_name(file_path)

        try:
            holders = []
            for torrent in client.torrents_info():
                files = client.torrents_files(torrent_hash=torrent.hash)
                found = next(
                    (
                        f
                        for f in files
                        if os.path.join(torrent.save_path, f.name) == file_path
                        or (
                            f.size == file_size
                            and _normalized_name(f.name) == wanted_name
                        )
                    ),
                    None,
                )
                if found is not None:
                    holders.append((torrent.hash, files, found))

            if not holders:
                logger.info(f"No torrent holds {file_path}")
                return None

            torrent_hash, files, found = holders[0]
            logger.info(
                f"Torrent {torrent_hash} holds {file_path} "
                f"({len(holders)} torrent(s) in total)"
            )
            return TorrentMatch(
                hash=torrent_hash,
                count=len(holders),
                holds_other_videos=any(
                    f is not found
                    and is_video_file(f.name)
                    and not is_sample_file(f.name)
                    for f in files
                ),
            )
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
