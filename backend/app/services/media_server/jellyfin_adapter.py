"""
Jellyfin adapter.

Built on the official jellyfin-apiclient-python SDK. That SDK is synchronous,
so every call is dispatched to a worker thread and never blocks the event loop.

The API key has to belong to an administrator: reading library paths and
triggering scans are admin-only endpoints, and item queries need a user id,
which only an admin key can look up.
"""

import asyncio
import logging
from typing import Dict, List, Optional

from jellyfin_apiclient_python import JellyfinClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.shared.base_service import BaseExternalService
from app.services.media_server.base import (
    ConnectionInfo,
    DuplicateGroup,
    LibraryInfo,
    MediaServerError,
    MediaServerType,
)
from app.services.media_server.file_probe import (
    SERVER_SAMPLE_PATTERNS,
    is_sample_file,
    probe_file,
)
from app.services.scan.scoring_engine import MediaMetadata

logger = logging.getLogger(__name__)

# Jellyfin's own words for a library's contents, mapped to ours.
COLLECTION_TYPES = {"movies": "movie", "tvshows": "show"}

# Items are fetched in pages; Jellyfin is happy with a few hundred at a time.
PAGE_SIZE = 500


class JellyfinAdapter(BaseExternalService):
    """Reads duplicates out of Jellyfin."""

    type = MediaServerType.JELLYFIN

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self._api = None
        self._libraries: Optional[List[dict]] = None

    async def test_connection(self) -> ConnectionInfo:
        try:
            api = await self._connect()
            info = await asyncio.to_thread(api.get_system_info) or {}
            # Proves the key is an admin one, which everything else relies on.
            await self._raw_libraries()
        except MediaServerError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": f"Jellyfin connection failed: {e}"}

        return {
            "success": True,
            "server_name": str(info.get("ServerName") or "Jellyfin"),
            "version": str(info.get("Version") or ""),
        }

    async def get_libraries(
        self, library_type: Optional[str] = None
    ) -> List[LibraryInfo]:
        libraries = []
        for folder in await self._raw_libraries():
            kind = COLLECTION_TYPES.get(folder.get("CollectionType") or "")
            if kind is None or (library_type and kind != library_type):
                continue

            libraries.append(
                LibraryInfo(
                    key=str(folder.get("ItemId") or ""),
                    title=str(folder.get("Name") or ""),
                    type=kind,
                    count=await self._count_items(str(folder.get("ItemId") or "")),
                )
            )
        return libraries

    async def get_library_paths(self, library_name: str) -> List[str]:
        folder = await self._find_library(library_name)
        return [str(path) for path in folder.get("Locations") or []]

    async def find_duplicate_movies(self, library_name: str) -> List[DuplicateGroup]:
        return await self._find_duplicates(library_name, "Movie")

    async def find_duplicate_episodes(self, library_name: str) -> List[DuplicateGroup]:
        return await self._find_duplicates(library_name, "Episode")

    async def refresh_item(self, item_id: str) -> bool:
        try:
            api = await self._connect()
            await asyncio.to_thread(api.refresh_item, item_id)
            return True
        except Exception as e:
            logger.error(f"Failed to refresh Jellyfin item {item_id}: {e}")
            return False

    async def refresh_library(self, library_name: str) -> bool:
        """Jellyfin only exposes a server-wide scan, so library_name is unused."""
        try:
            api = await self._connect()
            await asyncio.to_thread(api.refresh_library)
            return True
        except Exception as e:
            logger.error(f"Failed to trigger Jellyfin library scan: {e}")
            return False

    async def _connect(self):
        """An authenticated SDK API, built once per adapter."""
        if self._api is not None:
            return self._api

        config = await self._get_encrypted_config(
            service_name="Jellyfin",
            config_keys={"url": "jellyfin_url", "api_key": "jellyfin_api_key"},
        )
        url = str(config["url"]).rstrip("/")
        self._api = await asyncio.to_thread(self._build_client, url, config["api_key"])
        return self._api

    def _build_client(self, url: str, api_key: str):
        """
        Authenticate the SDK with an API key.

        Item queries resolve against Users/{UserId}, so an administrator is
        picked when no user was configured.
        """
        client = JellyfinClient()
        client.config.app("Deduparr", "1.0.0", "Deduparr", "deduparr")
        client.config.data["auth.ssl"] = url.startswith("https")
        client.authenticate(
            {"Servers": [{"AccessToken": api_key, "address": url}]}, discover=False
        )

        users = client.jellyfin.get_users() or []
        admin = next(
            (
                user
                for user in users
                if (user.get("Policy") or {}).get("IsAdministrator")
            ),
            None,
        )
        if admin is None:
            raise MediaServerError(
                "Jellyfin accepted the key but reported no administrator. "
                "Deduparr needs an API key created by an admin account."
            )

        client.config.data["auth.user_id"] = admin["Id"]
        client.jellyfin.config.data["auth.user_id"] = admin["Id"]
        return client.jellyfin

    async def _raw_libraries(self) -> List[dict]:
        """
        Libraries with their filesystem locations.

        The SDK has no wrapper for this endpoint, so it goes through the same
        primitive its own methods use.
        """
        if self._libraries is None:
            api = await self._connect()
            folders = await asyncio.to_thread(api._get, "Library/VirtualFolders")
            if not isinstance(folders, list):
                raise MediaServerError(
                    "Jellyfin refused to list libraries. The API key must belong "
                    "to an administrator."
                )
            self._libraries = folders
        return self._libraries

    async def _find_library(self, library_name: str) -> dict:
        for folder in await self._raw_libraries():
            if folder.get("Name") == library_name:
                return folder
        raise MediaServerError(f"Library '{library_name}' not found")

    async def _count_items(self, parent_id: str) -> int:
        page = await self._page(parent_id, "Movie,Episode", start_index=0, limit=1)
        return int(page.get("TotalRecordCount") or 0)

    async def _page(
        self, parent_id: str, item_types: str, start_index: int, limit: int
    ) -> dict:
        api = await self._connect()
        return (
            await asyncio.to_thread(
                api.get_user_items,
                parent_id=parent_id,
                include_item_types=item_types,
                params={
                    "Recursive": True,
                    "Fields": "MediaSources,Path",
                    "StartIndex": start_index,
                    "Limit": limit,
                },
            )
            or {}
        )

    async def _find_duplicates(
        self, library_name: str, item_type: str
    ) -> List[DuplicateGroup]:
        """
        Items Jellyfin stores more than one file for.

        Jellyfin merges alternate files of a title into one item with several
        MediaSources, which is the duplicate signal.
        """
        folder = await self._find_library(library_name)
        parent_id = str(folder.get("ItemId") or "")

        groups: List[DuplicateGroup] = []
        start_index = 0
        while True:
            page = await self._page(parent_id, item_type, start_index, PAGE_SIZE)
            items = page.get("Items") or []
            if not items:
                break

            for item in items:
                files = self._collect_files(item)
                if len(files) > 1:
                    groups.append(
                        DuplicateGroup(
                            item_id=str(item.get("Id")),
                            title=self._title(item),
                            files=files,
                        )
                    )

            start_index += len(items)
            if start_index >= int(page.get("TotalRecordCount") or 0):
                break

        logger.info(
            f"Jellyfin library '{library_name}': {len(groups)} "
            f"{item_type.lower()}(s) with duplicates"
        )
        return groups

    @staticmethod
    def _title(item: Dict[str, object]) -> str:
        name = str(item.get("Name") or "Unknown")
        if item.get("Type") != "Episode":
            return name

        series = str(item.get("SeriesName") or "Unknown Show")
        season = item.get("ParentIndexNumber")
        number = item.get("IndexNumber")
        if season is None or number is None:
            return f"{series} - {name}"
        return f"{series} - S{int(season):02d}E{int(number):02d} - {name}"

    @staticmethod
    def _collect_files(item: Dict[str, object]) -> List[MediaMetadata]:
        """Describe every real file behind one item."""
        files: List[MediaMetadata] = []

        for source in item.get("MediaSources") or []:
            path = source.get("Path")
            # Protocol distinguishes a file on disk from a stream Jellyfin proxies.
            if not path or source.get("Protocol") != "File":
                continue
            if is_sample_file(str(path), SERVER_SAMPLE_PATTERNS):
                continue

            streams = source.get("MediaStreams") or []
            video = next((s for s in streams if s.get("Type") == "Video"), {})
            audio = next((s for s in streams if s.get("Type") == "Audio"), {})
            probe = probe_file(str(path))

            files.append(
                MediaMetadata(
                    file_path=str(path),
                    file_size=int(source.get("Size") or probe.size),
                    # Jellyfin reports no resolution label; the scoring engine
                    # derives one from the height.
                    resolution=None,
                    video_codec=video.get("Codec"),
                    audio_codec=audio.get("Codec"),
                    bitrate=source.get("Bitrate"),
                    width=video.get("Width"),
                    height=video.get("Height"),
                    inode=probe.inode,
                    is_hardlink=probe.is_hardlink,
                )
            )

        return files
