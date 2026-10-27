"""
Scan Orchestrator Service

Finds duplicates through the configured media server, optionally widened by a
filesystem scan for files the server has not catalogued.
"""

import logging
from typing import Awaitable, Callable, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Config
from app.services.scan.disk_scan import (
    DiskScanConfig,
    DiskScanService,
    DuplicateDetectionStrategy,
    HardlinkHandling,
)
from app.services.media_server import DuplicateGroup, MediaServer

logger = logging.getLogger(__name__)


class ScanOrchestrator:
    """
    Unified duplicate detection.

    The media server is the primary source because it carries the metadata the
    scoring engine needs. A deep scan adds a filesystem pass that can see files
    the server missed, such as ones differing only by case.
    """

    def __init__(self, media_server: MediaServer, db: AsyncSession):
        self.media_server = media_server
        self.db = db
        self.disk_scan_service = DiskScanService(
            config=DiskScanConfig(
                strategy=DuplicateDetectionStrategy.NAME_AND_SIMILAR_SIZE,
                size_threshold_percent=5.0,
                hardlink_handling=HardlinkHandling.EXCLUDE,
                enable_checksum=False,  # too slow to run by default
            )
        )

    async def scan_movies(self, library_name: str) -> List[DuplicateGroup]:
        """Duplicate movies in a library."""
        return await self._scan(
            library_name,
            self.media_server.find_duplicate_movies,
            self.disk_scan_service.find_duplicate_movies_on_disk,
        )

    async def scan_episodes(self, library_name: str) -> List[DuplicateGroup]:
        """Duplicate episodes in a library."""
        return await self._scan(
            library_name,
            self.media_server.find_duplicate_episodes,
            self.disk_scan_service.find_duplicate_episodes_on_disk,
        )

    async def _scan(
        self,
        library_name: str,
        find_on_server: Callable[[str], Awaitable[List[DuplicateGroup]]],
        find_on_disk: Callable[[List[str]], Dict[str, List[dict]]],
    ) -> List[DuplicateGroup]:
        groups = await find_on_server(library_name)
        logger.info(f"Media server found {len(groups)} duplicate group(s)")

        if not await self._deep_scan_enabled():
            return groups

        try:
            paths = await self.media_server.get_library_paths(library_name)
            if not paths:
                logger.warning(
                    f"Library '{library_name}' reports no filesystem paths - "
                    "skipping deep scan"
                )
                return groups

            self._report_disk_only(find_on_disk(paths), groups)
        except Exception as e:
            logger.error(f"Deep scan failed: {e}", exc_info=True)

        return groups

    async def _deep_scan_enabled(self) -> bool:
        result = await self.db.execute(
            select(Config).where(Config.key == "enable_deep_scan")
        )
        config = result.scalar_one_or_none()
        return config.value == "true" if config else False

    @staticmethod
    def _report_disk_only(
        disk_results: Dict[str, List[dict]], groups: List[DuplicateGroup]
    ) -> None:
        """
        Log duplicate files the filesystem has but the media server does not.

        They are not turned into duplicate sets: acting on files the server has
        never catalogued would delete media Deduparr cannot verify, so this
        stays a report until that is a deliberate feature.
        """
        known = {file.file_path for group in groups for file in group.files}
        disk_only = [
            info["path"]
            for files in disk_results.values()
            for info in files
            if info["path"] not in known
        ]

        if disk_only:
            logger.info(
                f"Deep scan found {len(disk_only)} duplicate file(s) the media "
                f"server does not list, for example: {disk_only[:3]}"
            )
