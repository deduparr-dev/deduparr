"""
Plex adapter.

Owns everything plexapi-shaped: finding items the server stores more than once
and turning their media parts into MediaMetadata. Connection handling,
including the relay fallback, stays in PlexService.
"""

import logging
from typing import List, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services.media_server.plex_service import PlexService
from app.services.scan.scoring_engine import MediaMetadata

logger = logging.getLogger(__name__)


class PlexAdapter:
    """Reads duplicates out of Plex Media Server."""

    type = MediaServerType.PLEX

    def __init__(self, db: AsyncSession):
        self._service = PlexService(db)

    async def test_connection(self) -> ConnectionInfo:
        result = self._service.test_connection()
        if not result.get("success"):
            return {"success": False, "error": str(result.get("error", "unknown"))}
        return {
            "success": True,
            "server_name": str(result.get("server_name", "")),
            "version": str(result.get("version", "")),
        }

    async def get_libraries(
        self, library_type: Optional[str] = None
    ) -> List[LibraryInfo]:
        return self._service.get_libraries(library_type)

    async def find_duplicate_movies(self, library_name: str) -> List[DuplicateGroup]:
        """
        Movies stored as more than one file.

        Plex expresses this two ways: one movie carrying several media versions,
        and separate entries it flags as duplicates of each other. Both land in
        the same group, keyed on title and year.
        """
        library = self._library(library_name)
        grouped: dict[str, list] = {}

        for movie in library.all():
            if len(self._playable_media(movie)) > 1:
                grouped.setdefault(self._movie_key(movie), []).append(movie)

        for movie in library.search(duplicate=True):
            # A single entry holding nothing but a sample is not a duplicate.
            if len(self._playable_media(movie)) < 2:
                continue
            group = grouped.setdefault(self._movie_key(movie), [])
            if movie not in group:
                group.append(movie)

        groups = []
        for movies in grouped.values():
            files = self._collect_files(movies, movies[0].title)
            if files:
                groups.append(
                    DuplicateGroup(
                        item_id=str(movies[0].ratingKey),
                        title=movies[0].title,
                        files=files,
                    )
                )

        logger.info(
            f"Plex library '{library_name}': {len(groups)} movie(s) with duplicates"
        )
        return groups

    async def find_duplicate_episodes(self, library_name: str) -> List[DuplicateGroup]:
        """Episodes stored as more than one file."""
        library = self._library(library_name)
        groups = []

        for episode in library.search(libtype="episode"):
            if len(self._playable_media(episode)) < 2:
                continue

            title = self._episode_title(episode)
            files = self._collect_files([episode], title)
            if files:
                groups.append(
                    DuplicateGroup(
                        item_id=str(episode.ratingKey), title=title, files=files
                    )
                )

        logger.info(
            f"Plex library '{library_name}': {len(groups)} episode(s) with duplicates"
        )
        return groups

    async def get_library_paths(self, library_name: str) -> List[str]:
        return list(getattr(self._library(library_name), "locations", []))

    async def refresh_item(self, item_id: str) -> bool:
        return self._service.refresh_item(item_id)

    async def refresh_library(self, library_name: str) -> bool:
        return self._service.refresh_library(library_name)

    def _library(self, library_name: str):
        try:
            return self._service.get_library(library_name)
        except ValueError as e:
            raise MediaServerError(str(e))

    @staticmethod
    def _movie_key(movie) -> str:
        return f"{movie.title}|{movie.year}" if movie.year else movie.title

    @staticmethod
    def _episode_title(episode) -> str:
        show = getattr(episode, "grandparentTitle", None) or "Unknown Show"
        return (
            f"{show} - S{episode.seasonNumber:02d}E{episode.episodeNumber:02d}"
            f" - {episode.title}"
        )

    @staticmethod
    def _playable_media(item) -> list:
        """Media versions that are an actual release rather than a sample."""
        return [
            media
            for media in item.media
            if media.parts
            and media.parts[0].file
            and not is_sample_file(media.parts[0].file, SERVER_SAMPLE_PATTERNS)
        ]

    def _collect_files(self, items: Sequence, title: str) -> List[MediaMetadata]:
        """Describe every playable file of these items."""
        files: List[MediaMetadata] = []

        for item in items:
            try:
                # checkFiles makes Plex re-verify the paths it reports, which is
                # how a file moved behind its back gets noticed.
                item.reload(checkFiles=True)
            except Exception as e:
                logger.warning(f"Could not reload '{title}' from Plex: {e}")

            for media in self._playable_media(item):
                part = media.parts[0]
                probe = probe_file(part.file)
                if not probe.exists:
                    logger.warning(f"Plex reports a missing file: {part.file}")

                files.append(
                    MediaMetadata(
                        file_path=part.file,
                        file_size=part.size or probe.size,
                        resolution=media.videoResolution,
                        video_codec=media.videoCodec,
                        audio_codec=getattr(media, "audioCodec", None),
                        bitrate=media.bitrate,
                        width=media.width,
                        height=media.height,
                        inode=probe.inode,
                        is_hardlink=probe.is_hardlink,
                    )
                )

        return files
