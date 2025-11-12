"""
Scan Orchestrator Service

Coordinates Plex API-based duplicate detection with optional filesystem-based
deep scanning for comprehensive duplicate detection.
"""

import logging
from typing import Dict, List

from plexapi.video import Movie, Episode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Config
from app.services.disk_scan_service import (
    DiskScanConfig,
    DiskScanService,
    DuplicateDetectionStrategy,
    HardlinkHandling,
)
from app.services.plex_service import PlexService

logger = logging.getLogger(__name__)


class ScanOrchestrator:
    """
    Orchestrates duplicate detection across Plex API and filesystem scans

    This service provides a unified interface for finding duplicates, automatically
    enabling deep filesystem scans when configured. Deep scans complement Plex API
    detection by finding duplicates Plex might miss (case sensitivity, cross-library).
    """

    def __init__(self, plex_service: PlexService, db: AsyncSession):
        """
        Initialize scan orchestrator

        Args:
            plex_service: Configured PlexService instance
            db: Database session for config access
        """
        self.plex_service = plex_service
        self.db = db

        # Initialize disk scan service with default config
        # TODO: Load config from database settings in future
        disk_config = DiskScanConfig(
            strategy=DuplicateDetectionStrategy.NAME_AND_SIMILAR_SIZE,
            size_threshold_percent=5.0,
            hardlink_handling=HardlinkHandling.EXCLUDE,
            enable_checksum=False,  # Too slow for default use
        )
        self.disk_scan_service = DiskScanService(config=disk_config)

    async def scan_movies(self, library_name: str) -> Dict[str, List[Movie]]:
        """
        Scan for duplicate movies using Plex API and optionally disk scan

        Workflow:
        1. Always run Plex API scan (fast, primary method with metadata)
        2. If deep scan enabled, run filesystem scan on library paths
        3. Merge results, preferring Plex entries (they have full metadata)

        Args:
            library_name: Name of the Plex movie library to scan

        Returns:
            Dict mapping movie key to list of duplicate Movie objects
            Key format: "Title|Year" or "Title" if no year
        """
        logger.info(f"Starting orchestrated movie scan for '{library_name}'")

        # Always run Plex API scan first (fast, has full metadata)
        plex_duplicates = self.plex_service.find_duplicate_movies(library_name)
        logger.info(
            f"Plex API found {len(plex_duplicates)} duplicate groups in '{library_name}'"
        )

        # Check if deep scan is enabled
        deep_scan_enabled = await self._get_deep_scan_setting()

        if not deep_scan_enabled:
            logger.info("Deep scan disabled - returning Plex results only")
            return plex_duplicates

        # Deep scan: get library paths and scan filesystem
        logger.info("Deep scan enabled - performing filesystem analysis")
        try:
            library = self.plex_service.get_library(library_name)
            library_paths = self._get_library_paths(library)

            if not library_paths:
                logger.warning(
                    f"No filesystem paths found for library '{library_name}' - skipping deep scan"
                )
                return plex_duplicates

            logger.info(
                f"Scanning {len(library_paths)} filesystem path(s) for duplicates"
            )
            disk_duplicates = self.disk_scan_service.find_duplicate_movies_on_disk(
                library_paths
            )
            logger.info(
                f"Filesystem scan found {len(disk_duplicates)} duplicate groups"
            )

            # Merge results
            merged = self._merge_movie_results(plex_duplicates, disk_duplicates)
            logger.info(
                f"After merge: {len(merged)} total duplicate groups "
                f"(Plex: {len(plex_duplicates)}, Disk: {len(disk_duplicates)})"
            )

            return merged

        except Exception as e:
            logger.error(f"Deep scan failed: {e}", exc_info=True)
            logger.warning("Falling back to Plex results only")
            return plex_duplicates

    async def scan_episodes(self, library_name: str) -> Dict[str, List[Episode]]:
        """
        Scan for duplicate episodes using Plex API and optionally disk scan

        Workflow:
        1. Always run Plex API scan (fast, primary method with metadata)
        2. If deep scan enabled, run filesystem scan on library paths
        3. Merge results, preferring Plex entries (they have full metadata)

        Args:
            library_name: Name of the Plex TV library to scan

        Returns:
            Dict mapping episode key to list of duplicate Episode objects
            Key format: "Show|S01E01" for proper grouping
        """
        logger.info(f"Starting orchestrated episode scan for '{library_name}'")

        # Always run Plex API scan first (fast, has full metadata)
        plex_duplicates = self.plex_service.find_duplicate_episodes(library_name)
        logger.info(
            f"Plex API found {len(plex_duplicates)} duplicate episode groups in '{library_name}'"
        )

        # Check if deep scan is enabled
        deep_scan_enabled = await self._get_deep_scan_setting()

        if not deep_scan_enabled:
            logger.info("Deep scan disabled - returning Plex results only")
            return plex_duplicates

        # Deep scan: get library paths and scan filesystem
        logger.info("Deep scan enabled - performing filesystem analysis")
        try:
            library = self.plex_service.get_library(library_name)
            library_paths = self._get_library_paths(library)

            if not library_paths:
                logger.warning(
                    f"No filesystem paths found for library '{library_name}' - skipping deep scan"
                )
                return plex_duplicates

            logger.info(
                f"Scanning {len(library_paths)} filesystem path(s) for duplicates"
            )
            disk_duplicates = self.disk_scan_service.find_duplicate_episodes_on_disk(
                library_paths
            )
            logger.info(
                f"Filesystem scan found {len(disk_duplicates)} duplicate episode groups"
            )

            # Merge results
            merged = self._merge_episode_results(plex_duplicates, disk_duplicates)
            logger.info(
                f"After merge: {len(merged)} total duplicate episode groups "
                f"(Plex: {len(plex_duplicates)}, Disk: {len(disk_duplicates)})"
            )

            return merged

        except Exception as e:
            logger.error(f"Deep scan failed: {e}", exc_info=True)
            logger.warning("Falling back to Plex results only")
            return plex_duplicates

    async def _get_deep_scan_setting(self) -> bool:
        """
        Get the current deep scan configuration setting

        Returns:
            True if deep scan is enabled, False otherwise (default)
        """
        result = await self.db.execute(
            select(Config).where(Config.key == "enable_deep_scan")
        )
        config = result.scalar_one_or_none()

        enabled = config.value == "true" if config else False
        logger.debug(f"Deep scan setting: {enabled}")
        return enabled

    def _get_library_paths(self, library) -> List[str]:
        """
        Extract filesystem paths from Plex library

        Args:
            library: Plex library object

        Returns:
            List of absolute filesystem paths configured for this library
        """
        paths = []
        try:
            # Plex libraries have location objects with paths
            for location in library.locations:
                paths.append(location)
                logger.debug(f"Found library path: {location}")
        except AttributeError:
            logger.warning("Library object has no 'locations' attribute")

        return paths

    def _merge_movie_results(
        self,
        plex_results: Dict[str, List[Movie]],
        disk_results: Dict[str, List],
    ) -> Dict[str, List[Movie]]:
        """
        Merge Plex and disk scan results for movies

        Strategy:
        1. Start with Plex results (they have full metadata)
        2. Add disk-only findings that aren't in Plex results
        3. Match by file path to avoid double-counting

        Note: Disk results contain DiskFileInfo dicts, not Movie objects.
        We only use them if Plex hasn't already found those files.

        Args:
            plex_results: Duplicates found by Plex API
            disk_results: Duplicates found by filesystem scan

        Returns:
            Merged duplicate dictionary with Plex Movie objects
        """
        # Start with Plex results (they're already properly formatted)
        merged = dict(plex_results)

        # Extract all file paths that Plex already knows about
        plex_file_paths = set()
        for movie_list in plex_results.values():
            for movie in movie_list:
                for media in movie.media:
                    for part in media.parts:
                        if part.file:
                            plex_file_paths.add(part.file)

        # Check disk results for files Plex doesn't know about
        disk_only_files = []
        for file_list in disk_results.values():
            for file_info in file_list:
                if file_info["path"] not in plex_file_paths:
                    disk_only_files.append(file_info)

        if disk_only_files:
            logger.info(
                f"Found {len(disk_only_files)} disk-only duplicate files not in Plex"
            )
            logger.debug(
                f"Disk-only files: {[f['path'] for f in disk_only_files[:5]]}..."
            )
            # Note: These would need to be converted to proper Movie objects
            # For now, we log them but don't add them (Plex objects are required downstream)
            # Future enhancement: Create minimal Movie objects for disk-only findings
        else:
            logger.debug("All disk scan results are already in Plex")

        return merged

    def _merge_episode_results(
        self,
        plex_results: Dict[str, List[Episode]],
        disk_results: Dict[str, List],
    ) -> Dict[str, List[Episode]]:
        """
        Merge Plex and disk scan results for episodes

        Strategy:
        1. Start with Plex results (they have full metadata)
        2. Add disk-only findings that aren't in Plex results
        3. Match by file path to avoid double-counting

        Note: Disk results contain DiskFileInfo dicts, not Episode objects.
        We only use them if Plex hasn't already found those files.

        Args:
            plex_results: Duplicates found by Plex API
            disk_results: Duplicates found by filesystem scan

        Returns:
            Merged duplicate dictionary with Plex Episode objects
        """
        # Start with Plex results (they're already properly formatted)
        merged = dict(plex_results)

        # Extract all file paths that Plex already knows about
        plex_file_paths = set()
        for episode_list in plex_results.values():
            for episode in episode_list:
                for media in episode.media:
                    for part in media.parts:
                        if part.file:
                            plex_file_paths.add(part.file)

        # Check disk results for files Plex doesn't know about
        disk_only_files = []
        for file_list in disk_results.values():
            for file_info in file_list:
                if file_info["path"] not in plex_file_paths:
                    disk_only_files.append(file_info)

        if disk_only_files:
            logger.info(
                f"Found {len(disk_only_files)} disk-only duplicate episode files not in Plex"
            )
            logger.debug(
                f"Disk-only files: {[f['path'] for f in disk_only_files[:5]]}..."
            )
            # Note: These would need to be converted to proper Episode objects
            # For now, we log them but don't add them (Plex objects are required downstream)
            # Future enhancement: Create minimal Episode objects for disk-only findings
        else:
            logger.debug("All disk scan results are already in Plex")

        return merged
