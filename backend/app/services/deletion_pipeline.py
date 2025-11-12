"""
Deletion pipeline for orchestrating multi-stage file deletion
"""

import logging
import os
import shutil
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import DeletionHistory, DuplicateFile, DuplicateSet
from app.models.duplicate import MediaType
from app.services.arr_helpers import refresh_media_item
from app.services.plex_service import PlexService
from app.services.qbittorrent_service import QBittorrentService
from app.services.radarr_service import RadarrService
from app.services.sonarr_service import SonarrService

logger = logging.getLogger(__name__)


class DeletionPipeline:
    """Orchestrates multi-stage deletion process"""

    # Class-level cache for file locations (shared across instances)
    _file_location_cache: dict[str, str] = {}

    def __init__(self, db: AsyncSession, dry_run: bool = True):
        """
        Initialize deletion pipeline

        Args:
            db: Database session
            dry_run: If True, simulate deletions without actually executing them
        """
        self.db = db
        self.dry_run = dry_run
        self.qbit_service = QBittorrentService(db)
        self.radarr_service = RadarrService(db)
        self.sonarr_service = SonarrService(db)

    def _get_media_root_from_path(self, file_path: str) -> str:
        """
        Extract media root from a file path

        For paths like /data/movies/Movie/file.mkv, returns /plexdownloads
        For paths like /media/movies/Movie/file.mkv, returns /media

        Args:
            file_path: Full file path

        Returns:
            Media root directory (first path component after /)
        """
        # Split path and get first non-empty component after root /
        parts = [p for p in file_path.split("/") if p]
        if parts:
            return f"/{parts[0]}"
        # Fallback to settings default
        return settings.media_dir

    def _cleanup_associated_files(
        self, directory: str, base_name: str, exclude_filename: str = None
    ) -> int:
        """
        Clean up associated files (subtitles, NFO, images) in a directory.

        Args:
            directory: Directory to clean up
            base_name: Base filename to match (without extension)
            exclude_filename: Optional filename to exclude from deletion

        Returns:
            Number of files deleted
        """
        if not os.path.exists(directory):
            return 0

        deleted_count = 0
        for file in os.listdir(directory):
            # Skip the main video file if specified
            if exclude_filename and file == exclude_filename:
                continue

            file_path = os.path.join(directory, file)
            # Match files with same base name
            if file.startswith(base_name) and os.path.isfile(file_path):
                try:
                    if self.dry_run:
                        logger.debug(f"[DRY-RUN] Would delete: {file}")
                    else:
                        os.remove(file_path)
                        deleted_count += 1
                        logger.debug(f"Deleted associated file: {file}")
                except (PermissionError, OSError) as e:
                    logger.debug(f"No write permission for {file}: {e}")
                except Exception as e:
                    logger.warning(f"Failed to delete {file}: {e}")

        if deleted_count > 0:
            logger.info(
                f"Deleted {deleted_count} associated files in {os.path.basename(directory)}"
            )

        return deleted_count

    def _find_file_in_media_root(self, plex_path: str) -> Optional[str]:
        """
        Find actual file location by searching media root for the file
        Uses caching for performance on large media libraries.
        Matches on last 2 path segments (parent_dir/filename) for accuracy.

        Args:
            plex_path: Path as reported by Plex (e.g., /long-path/movies/Movie (2025)/Movie.mkv)

        Returns:
            Actual path in container if found, None otherwise
        """
        # Extract last 2 path segments for better matching specificity
        # e.g., /long-path/movies/Movie (2025)/Movie.mkv -> Movie (2025)/Movie.mkv
        path_parts = plex_path.split("/")
        match_key = (
            "/".join(path_parts[-2:]) if len(path_parts) >= 2 else path_parts[-1]
        )

        # Check cache first
        if match_key in self._file_location_cache:
            cached_path = self._file_location_cache[match_key]
            if os.path.exists(cached_path):
                logger.debug(f"Cache hit: {match_key} -> {cached_path}")
                return cached_path
            else:
                # File was moved or deleted, remove from cache
                logger.debug(f"Cache invalidated (file not found): {match_key}")
                del self._file_location_cache[match_key]

        # Cache miss - search filesystem
        logger.debug(f"Cache miss, searching for: {match_key}")
        # Auto-detect media root from the plex_path
        media_root = self._get_media_root_from_path(plex_path)

        for root, dirs, files in os.walk(media_root):
            for file in files:
                full_path = os.path.join(root, file)
                # Match on last 2 path segments for accuracy
                if full_path.endswith(match_key):
                    self._file_location_cache[match_key] = full_path
                    logger.debug(f"Found and cached: {match_key} -> {full_path}")
                    return full_path

        logger.debug(f"File not found under {media_root}: {match_key}")
        return None

    async def _get_plex_service(self) -> PlexService:
        """Get Plex service instance with stored credentials"""
        from app.models.config import Config

        result = await self.db.execute(
            select(Config).where(Config.key == "plex_auth_token")
        )
        token_config = result.scalar_one_or_none()

        result = await self.db.execute(
            select(Config).where(Config.key == "plex_server_name")
        )
        server_config = result.scalar_one_or_none()

        if not token_config:
            raise ValueError("Plex authentication token not found in database")

        return PlexService(
            encrypted_token=token_config.value,
            server_name=server_config.value if server_config else None,
        )

    async def delete_file(
        self,
        duplicate_file_id: int,
        skip_qbit: bool = False,
        skip_rescan: bool = False,
    ) -> DeletionHistory:
        """
        Execute full deletion pipeline for a file

        Args:
            duplicate_file_id: ID of the DuplicateFile to delete
            skip_qbit: Whether to skip qBittorrent removal (e.g., if not in library)
            skip_rescan: Whether to skip *arr rescan (will be done once for all files later)

        Returns:
            DeletionHistory record

        Raises:
            ValueError: If file not found or already has deletion history
        """
        result = await self.db.execute(
            select(DuplicateFile)
            .options(
                selectinload(DuplicateFile.duplicate_set).selectinload(
                    DuplicateSet.files
                )
            )
            .where(DuplicateFile.id == duplicate_file_id)
        )
        duplicate_file = result.scalar_one_or_none()

        if not duplicate_file:
            raise ValueError(f"DuplicateFile {duplicate_file_id} not found")

        existing_history = await self.db.execute(
            select(DeletionHistory).where(
                DeletionHistory.duplicate_file_id == duplicate_file_id
            )
        )
        if existing_history.scalar_one_or_none():
            raise ValueError(
                f"Deletion already in progress or completed for file {duplicate_file_id}"
            )

        file_path = duplicate_file.file_path

        if self.dry_run:
            logger.info(f"[DRY-RUN] Would delete file: {file_path}")
            logger.info("[DRY-RUN] Simulating deletion pipeline stages...")
            # Create a temporary history object for simulation (not saved to DB)
            history = DeletionHistory(
                duplicate_file_id=duplicate_file_id,
                deleted_at=datetime.now(timezone.utc),
            )
            await self._execute_deletion_stages(
                duplicate_file, history, skip_qbit, skip_rescan
            )
            # Don't commit in dry-run mode
            logger.info(
                f"[DRY-RUN] Deletion simulation completed for file: {file_path}"
            )
            return history
        else:
            logger.info(f"Starting deletion pipeline for file: {file_path}")
            history = DeletionHistory(
                duplicate_file_id=duplicate_file_id,
                deleted_at=datetime.now(timezone.utc),
            )
            self.db.add(history)
            await self.db.flush()

        try:
            await self._execute_deletion_stages(
                duplicate_file, history, skip_qbit, skip_rescan
            )
            await self.db.commit()
            logger.info(f"Deletion pipeline completed for file: {file_path}")
            return history

        except Exception as e:
            logger.error(f"Deletion pipeline failed for {file_path}: {e}")

            history.error = str(e)
            await self.db.commit()
            raise

    async def _execute_deletion_stages(
        self,
        duplicate_file: DuplicateFile,
        history: DeletionHistory,
        skip_qbit: bool = False,
        skip_rescan: bool = False,
    ):
        """
        Execute all deletion stages in optimal order

        Deletion flow:
        1. Remove from *arr and DELETE FILES (Radarr/Sonarr deletes via API)
        2. Remove item from qBittorrent and delete any remaining files
        3. Rescan *arr AFTER deletion complete (SKIPPED if skip_rescan=True)
        4. Fallback disk cleanup (for any stragglers or manual files)
        5. Refresh only the specific media in Plex (targeted refresh)

        Args:
            skip_rescan: Skip the *arr rescan stage (will be done once for entire set later)
        """
        file_path = duplicate_file.file_path
        arr_type = None
        item_hash = None
        arr_media_id = None

        try:
            # Stage 1: Remove from *arr and delete files
            arr_type, arr_media_id = await self._stage_arr_removal(
                duplicate_file, history
            )
            await self.db.commit()

            # Stage 2: Remove item from qBittorrent (deletes any remaining files)
            if not skip_qbit:
                item_hash = await self._stage_qbittorrent_removal(file_path, history)
                await self.db.commit()

            # Stage 3: Rescan *arr AFTER deletion (SKIPPED - will be done once for entire set)
            if not skip_rescan:
                # This is for individual file deletions outside of batch processing
                # duplicate_file.duplicate_set is already loaded via selectinload
                kept_file = None
                if duplicate_file.duplicate_set:
                    for file in duplicate_file.duplicate_set.files:
                        if file.keep and file.id != duplicate_file.id:
                            kept_file = file
                            break

                if arr_type and arr_media_id and kept_file:
                    kept_file_path = kept_file.file_path
                    await self._stage_arr_rescan(
                        arr_type, arr_media_id, history, kept_file_path
                    )
                    await self.db.commit()

            # Stage 4: Fallback disk cleanup (for any stragglers)
            await self._stage_disk_removal(file_path, history)
            await self.db.commit()

            # Stage 5: Refresh only the specific media in Plex (targeted refresh)
            await self._stage_plex_refresh(history, duplicate_file)

            # Store metadata in history
            history.arr_type = arr_type
            history.arr_media_id = arr_media_id
            history.qbit_torrent_hash = item_hash
            await self.db.commit()

        except Exception as e:
            logger.error(f"Deletion stage failed, attempting rollback: {e}")
            await self._rollback_deletion(history, item_hash, arr_type, file_path)
            raise

    async def _stage_qbittorrent_removal(
        self, file_path: str, history: DeletionHistory
    ) -> Optional[str]:
        """
        Stage 2: Remove item from qBittorrent AND delete files

        Searches qBittorrent's library by filename (path-agnostic) and removes
        the item. Deletes files via qBittorrent's API since qBit knows the exact
        file locations better than path matching.

        CRITICAL: This must complete BEFORE *arr rescan to ensure the deleted file
        is fully removed and won't be re-imported.

        Returns:
            Item hash if found and removed
        """
        try:
            item_hash = await self.qbit_service.find_item_by_file_path(file_path)

            if item_hash:
                if self.dry_run:
                    logger.info(
                        f"[DRY-RUN] Would remove item {item_hash} from qBittorrent (with files)"
                    )
                    history.deleted_from_qbit = True
                    history.deleted_from_disk = True
                else:
                    # Delete item AND files - qBit knows exact paths
                    await self.qbit_service.remove_item(item_hash, delete_files=True)
                    history.deleted_from_qbit = True
                    history.deleted_from_disk = True
                    logger.info(
                        f"Removed item {item_hash} from qBittorrent and deleted files"
                    )
                return item_hash
            else:
                # Not finding the item is OK - file might have been manually added
                # or acquired outside of qBittorrent. We'll clean it up in disk stage.
                history.deleted_from_qbit = True
                logger.info(
                    "Item not found in qBittorrent (file may have been added manually). "
                    "Will attempt disk cleanup in next stage."
                )
                return None

        except ValueError as e:
            # qBittorrent not configured - don't mark as success, record why it failed
            if "configuration not found" in str(e):
                error_msg = "qBittorrent not configured"
                logger.info(f"{error_msg}, skipping item removal for {file_path}")
                history.error = (
                    f"{history.error}; {error_msg}" if history.error else error_msg
                )
                history.deleted_from_qbit = False
                return None
            logger.error(f"qBittorrent removal failed: {e}")
            raise
        except Exception as e:
            logger.error(f"qBittorrent removal failed: {e}")
            raise

    async def _stage_arr_removal(
        self, duplicate_file: DuplicateFile, history: DeletionHistory
    ) -> tuple[Optional[str], Optional[int]]:
        """
        Stage 1: Remove file from Radarr/Sonarr (deletes file from disk via API)

        Radarr/Sonarr's delete API removes the file from disk AND their database.
        Since this file is part of a duplicate set, we know there's at least one
        other version (marked keep=True), so the rescan will find and import it.

        Returns:
            Tuple of (arr_type, media_id) where:
            - arr_type: 'radarr', 'sonarr', or None
            - media_id: movie_id or series_id for rescanning
        """
        file_path = duplicate_file.file_path

        # duplicate_file.duplicate_set is already loaded via selectinload
        media_type = duplicate_file.duplicate_set.media_type

        try:
            if media_type == MediaType.MOVIE:
                movie = await self.radarr_service.find_movie_by_file_path(file_path)
                if movie and "movieFile" in movie:
                    movie_id = movie["id"]

                    logger.info(
                        f"Found movie '{movie.get('title')}' (ID: {movie_id}) in Radarr. "
                        f"Deleting this version via Radarr API (includes disk deletion)."
                    )

                    if self.dry_run:
                        logger.info(
                            f"[DRY-RUN] Would remove movie file from Radarr (and disk): {file_path}"
                        )
                        history.deleted_from_arr = True
                        history.deleted_from_disk = True
                    else:
                        # Radarr's delete API removes from database AND disk
                        await self.radarr_service.delete_movie_file(
                            movie_id, movie["movieFile"]["id"]
                        )
                        history.deleted_from_arr = True
                        history.deleted_from_disk = True
                        logger.info(
                            "Removed movie file from Radarr (file deleted from disk by Radarr API)"
                        )
                    return "radarr", movie_id
                else:
                    # Movie not tracked in Radarr (orphaned file)
                    history.deleted_from_arr = False
                    logger.info(
                        f"Movie not tracked in Radarr (orphaned/old file): {file_path}. "
                        "Will delete via qBittorrent and disk cleanup stages."
                    )
                    return "radarr", None

            elif media_type == MediaType.EPISODE:
                episode = await self.sonarr_service.find_episode_by_file_path(file_path)
                if episode and "episodeFile" in episode:
                    series_id = episode["seriesId"]

                    logger.info(
                        f"Found episode S{episode.get('seasonNumber'):02d}E{episode.get('episodeNumber'):02d} in Sonarr. "
                        f"Deleting this version via Sonarr API (includes disk deletion)."
                    )

                    if self.dry_run:
                        logger.info(
                            f"[DRY-RUN] Would remove episode file from Sonarr (and disk): {file_path}"
                        )
                        history.deleted_from_arr = True
                        history.deleted_from_disk = True
                    else:
                        # Sonarr's delete API removes from database AND disk
                        await self.sonarr_service.delete_episode_file(
                            series_id, episode["episodeFile"]["id"]
                        )
                        history.deleted_from_arr = True
                        history.deleted_from_disk = True
                        logger.info(
                            "Removed episode file from Sonarr (file deleted from disk by Sonarr API)"
                        )
                    return "sonarr", series_id
                else:
                    # Episode not tracked in Sonarr (orphaned file)
                    history.deleted_from_arr = False
                    logger.info(
                        f"Episode not tracked in Sonarr (orphaned/old file): {file_path}. "
                        "Will delete via qBittorrent and disk cleanup stages."
                    )
                    return "sonarr", None

            else:
                raise ValueError(f"Unknown media type: {media_type}")

        except ValueError as e:
            # *arr service not configured
            if "configuration not found" in str(e):
                service_name = "Radarr" if media_type == MediaType.MOVIE else "Sonarr"
                error_msg = f"{service_name} not configured"
                logger.info(
                    f"{error_msg}, will delete via qBittorrent and disk cleanup: {file_path}"
                )
                history.error = (
                    f"{history.error}; {error_msg}" if history.error else error_msg
                )
                history.deleted_from_arr = False
                return None, None
            logger.error(f"*arr removal failed: {e}")
            raise
        except Exception as e:
            logger.error(f"*arr removal failed: {e}")
            raise

    async def _stage_disk_removal(self, file_path: str, history: DeletionHistory):
        """
        Stage 4: Fallback disk cleanup and associated files removal

        This is now a FALLBACK stage that runs after qBittorrent deletion.
        It handles:
        - Files that weren't in qBittorrent (manually added)
        - Associated files qBittorrent might have missed (.nfo, .srt, fanart, etc.)
        - Common subdirectories (Sample, Subs, Proof, Extras)
        - Empty parent directories cleanup

        If qBittorrent already deleted the file (deleted_from_disk=True), this stage
        focuses on cleaning up associated files and directories only.
        """
        try:
            # If qBittorrent already deleted the file, we just clean up remnants
            if history.deleted_from_disk:
                logger.info(
                    "Main file already deleted by qBittorrent. Checking for associated files cleanup..."
                )

            # Find the actual file location by searching media root
            actual_path = self._find_file_in_media_root(file_path)

            if actual_path and os.path.exists(actual_path):
                # Main file still exists - delete it and associated files
                parent_dir = os.path.dirname(actual_path)
                base_name = os.path.splitext(os.path.basename(actual_path))[0]

                if self.dry_run:
                    logger.info(f"[DRY-RUN] Would delete file from disk: {actual_path}")

                    # Find associated files
                    associated_files = []
                    if os.path.exists(parent_dir):
                        for file in os.listdir(parent_dir):
                            file_path_full = os.path.join(parent_dir, file)
                            # Match files with same base name (different extensions)
                            if (
                                file.startswith(base_name)
                                and file_path_full != actual_path
                            ):
                                associated_files.append(file_path_full)

                    if associated_files:
                        logger.info(
                            f"[DRY-RUN] Would also delete {len(associated_files)} associated files"
                        )
                        for assoc_file in associated_files:
                            logger.debug(f"[DRY-RUN]   - {assoc_file}")

                    # Check for subdirectories to clean up
                    cleanup_subdirs = ["sample", "subs", "proof", "extras"]
                    subdirs_to_remove = []

                    if os.path.exists(parent_dir):
                        for item in os.listdir(parent_dir):
                            item_path = os.path.join(parent_dir, item)
                            if (
                                os.path.isdir(item_path)
                                and item.lower() in cleanup_subdirs
                            ):
                                subdirs_to_remove.append(item)

                    if subdirs_to_remove:
                        logger.info(
                            f"[DRY-RUN] Would also delete {len(subdirs_to_remove)} subdirectories: {', '.join(subdirs_to_remove)}"
                        )

                    # Check for empty directories that would be removed (recursive)
                    logger.info(
                        f"[DRY-RUN] Would recursively remove empty parent directories starting from: {parent_dir}"
                    )

                    history.deleted_from_disk = True
                else:
                    try:
                        # Delete the main file (if not already deleted by qBittorrent)
                        if not history.deleted_from_disk:
                            os.remove(actual_path)
                            logger.info(f"Deleted file from disk: {actual_path}")
                        else:
                            logger.info(
                                "Main file already deleted by qBittorrent, cleaning up associated files only"
                            )

                        # Delete associated files using helper method
                        # Always exclude the main file to prevent double deletion
                        filename = os.path.basename(actual_path)
                        self._cleanup_associated_files(
                            parent_dir, base_name, exclude_filename=filename
                        )

                        # Clean up common subdirectories (Sample, Subs, etc.)
                        # These are typically found in scene releases and should be removed
                        cleanup_subdirs = ["sample", "subs", "proof", "extras"]
                        deleted_subdirs = []

                        if os.path.exists(parent_dir):
                            for item in os.listdir(parent_dir):
                                item_path = os.path.join(parent_dir, item)
                                # Check if it's a directory and matches common subdir names (case insensitive)
                                if (
                                    os.path.isdir(item_path)
                                    and item.lower() in cleanup_subdirs
                                ):
                                    try:
                                        # Remove directory and all its contents
                                        shutil.rmtree(item_path)
                                        deleted_subdirs.append(item)
                                        logger.info(
                                            f"Removed subdirectory: {item_path}"
                                        )
                                    except (PermissionError, OSError) as e:
                                        logger.debug(
                                            f"No write permission for subdirectory {item} (readonly mount): {e}"
                                        )
                                    except Exception as e:
                                        logger.warning(
                                            f"Failed to remove subdirectory {item}: {e}"
                                        )

                        if deleted_subdirs:
                            logger.info(
                                f"Deleted {len(deleted_subdirs)} subdirectories: {', '.join(deleted_subdirs)}"
                            )

                        current_dir = parent_dir
                        media_root = self._get_media_root_from_path(file_path)
                        removed_dirs = []

                        while current_dir != media_root and current_dir.startswith(
                            media_root
                        ):
                            if os.path.exists(current_dir) and os.path.isdir(
                                current_dir
                            ):
                                if not os.listdir(current_dir):
                                    try:
                                        os.rmdir(current_dir)
                                        removed_dirs.append(current_dir)
                                        logger.info(
                                            f"Removed empty directory: {current_dir}"
                                        )
                                        current_dir = os.path.dirname(current_dir)
                                    except (PermissionError, OSError) as e:
                                        logger.debug(
                                            f"No write permission for directory {current_dir} (readonly mount): {e}"
                                        )
                                        break
                                    except Exception as e:
                                        logger.warning(
                                            f"Failed to remove directory {current_dir}: {e}"
                                        )
                                        break
                                else:
                                    # Directory not empty, stop cleanup
                                    break
                            else:
                                break

                        if removed_dirs:
                            logger.info(
                                f"Cleaned up {len(removed_dirs)} empty directories"
                            )

                        history.deleted_from_disk = True

                    except (PermissionError, OSError) as e:
                        # Readonly filesystem or permission denied
                        # Check if it's errno 30 (EROFS - Read-only file system)
                        if isinstance(e, OSError) and e.errno == 30:
                            logger.info(
                                f"Read-only file system for {actual_path}. "
                                f"File deletion handled by Radarr/Sonarr API."
                            )
                        else:
                            logger.info(
                                f"No write permission for {actual_path} (readonly mount). "
                                f"File deletion handled by Radarr/Sonarr API."
                            )
                        history.deleted_from_disk = True
            else:
                # File not found - was already deleted by *arr services or qBittorrent
                # But we still need to clean up orphaned files (subtitles, NFO, etc.)
                if not history.deleted_from_disk:
                    history.deleted_from_disk = True

                filename = os.path.basename(file_path)
                logger.info(
                    f"Main file already deleted: {filename} "
                    f"({'by qBittorrent' if history.deleted_from_qbit else 'by *arr or manually'})"
                )

                # First, check if the original parent directory still exists with orphaned files
                parent_dir = os.path.dirname(file_path)
                base_name = os.path.splitext(filename)[0]

                if os.path.exists(parent_dir) and os.path.isdir(parent_dir):
                    # Clean up any orphaned files in the original directory
                    self._cleanup_associated_files(
                        parent_dir, base_name, exclude_filename=filename
                    )

                    # Try to remove the directory if it's now empty
                    try:
                        if not os.listdir(parent_dir):
                            if self.dry_run:
                                logger.info(
                                    f"[DRY-RUN] Would remove empty directory: {parent_dir}"
                                )
                            else:
                                os.rmdir(parent_dir)
                                logger.info(f"Removed empty directory: {parent_dir}")
                    except Exception as e:
                        logger.debug(f"Could not remove directory {parent_dir}: {e}")

                # Try to find and clean up other copies in the library with orphaned files
                # Search for instances of this file but be careful about hardlinks
                path_parts = file_path.split("/")
                if len(path_parts) >= 2:
                    base_name = os.path.splitext(os.path.basename(file_path))[0]
                    filename = os.path.basename(file_path)

                    # Extract library path (e.g., /plexdownloads/Filmer) to limit search scope
                    library_path = (
                        "/".join(path_parts[:3])
                        if len(path_parts) >= 3
                        else self._get_media_root_from_path(file_path)
                    )

                    logger.info(
                        f"Searching for remaining copies of '{filename}' in library: {library_path}"
                    )

                    # Track which inodes we've seen to avoid deleting all hardlinks
                    processed_inodes = set()
                    folders_cleaned = 0

                    for root, dirs, files in os.walk(library_path):
                        if filename in files:
                            file_full_path = os.path.join(root, filename)

                            # Check if this is a hardlink we've already processed
                            try:
                                stat_info = os.stat(file_full_path)
                                file_inode = stat_info.st_ino

                                # If this inode was already processed, skip (avoid deleting all hardlinks)
                                if file_inode in processed_inodes:
                                    logger.info(
                                        f"Skipping {file_full_path} - hardlink already processed (inode: {file_inode})"
                                    )
                                    continue

                                # Track this inode
                                processed_inodes.add(file_inode)

                            except OSError as e:
                                logger.debug(f"Could not stat {file_full_path}: {e}")
                                # If we can't stat it, skip it to be safe
                                continue

                            logger.info(f"Found remaining copy at: {file_full_path}")

                            # Delete the remaining file
                            try:
                                if self.dry_run:
                                    logger.info(
                                        f"[DRY-RUN] Would delete: {file_full_path}"
                                    )
                                else:
                                    os.remove(file_full_path)
                                    logger.info(
                                        f"Deleted remaining file: {file_full_path}"
                                    )
                            except (PermissionError, OSError) as e:
                                logger.debug(
                                    f"No write permission for {file_full_path}: {e}"
                                )
                            except Exception as e:
                                logger.warning(
                                    f"Failed to delete {file_full_path}: {e}"
                                )

                            # Clean up associated files using helper method
                            self._cleanup_associated_files(
                                root, base_name, exclude_filename=filename
                            )

                            # Remove the directory if it's now empty
                            try:
                                if not os.listdir(root):
                                    if self.dry_run:
                                        logger.info(
                                            f"[DRY-RUN] Would remove empty directory: {root}"
                                        )
                                    else:
                                        os.rmdir(root)
                                        logger.info(f"Removed empty directory: {root}")
                            except Exception as e:
                                logger.debug(f"Could not remove directory {root}: {e}")

                            folders_cleaned += 1

                    if folders_cleaned > 0:
                        logger.info(
                            f"Cleaned up {folders_cleaned} location(s) for file: {filename}"
                        )

        except PermissionError:
            # Readonly filesystem at search level - mark as success since *arr handles deletion
            logger.info(
                f"Readonly filesystem for {file_path}. File deletion handled by Radarr/Sonarr API."
            )
            history.deleted_from_disk = True
        except Exception as e:
            logger.error(f"Disk deletion failed: {e}")
            raise

    async def rescan_for_kept_file(
        self,
        media_type: MediaType,
        kept_file_path: str,
        duplicate_set_id: int | None = None,
    ):
        """
        Trigger *arr rescan to import the kept file after all duplicates are deleted.

        When files are deleted, the deletion pipeline saves arr_media_id in deletion history.
        We query that history to find the movie/series ID, then use it for a targeted rescan.

        Args:
            media_type: MediaType.MOVIE or MediaType.EPISODE
            kept_file_path: Path to the file we kept
            duplicate_set_id: ID of the duplicate set (to query deletion history for arr_media_id)
        """
        try:
            arr_type = "radarr" if media_type == MediaType.MOVIE else "sonarr"
            arr_media_id = None

            # Try to get arr_media_id from deletion history first (most reliable)
            if duplicate_set_id:
                arr_media_id = await self._get_arr_media_id_from_history(
                    duplicate_set_id, arr_type
                )
                if arr_media_id:
                    logger.info(
                        f"Found {arr_type} ID {arr_media_id} from deletion history for set {duplicate_set_id}"
                    )

            # Fallback: Try to find by kept file path
            if not arr_media_id:
                arr_media_id = await self._get_arr_media_id(
                    arr_type, kept_file_path, media_type
                )

            if arr_media_id:
                # File is already in *arr - just trigger a rescan for that specific item
                if media_type == MediaType.MOVIE:
                    if not self.dry_run:
                        # First, scan for new files
                        await self.radarr_service.rescan_movie(
                            arr_media_id, kept_file_path
                        )
                        logger.info(
                            f"Triggered Radarr rescan for movie {arr_media_id} to import: {kept_file_path}"
                        )

                        # Then refresh to clean up orphaned DB entries
                        radarr_client = await self.radarr_service._get_client()
                        await refresh_media_item(
                            client=radarr_client,
                            media_id=arr_media_id,
                            media_type="movie",
                            logger_instance=logger,
                        )
                        logger.info(
                            f"Triggered Radarr refresh for movie {arr_media_id} (cleans orphaned DB entries)"
                        )
                    else:
                        logger.info(
                            f"[DRY-RUN] Would trigger Radarr rescan and refresh for movie {arr_media_id}"
                        )
                else:
                    if not self.dry_run:
                        # First, scan for new files
                        await self.sonarr_service.rescan_series(
                            arr_media_id, kept_file_path
                        )
                        logger.info(
                            f"Triggered Sonarr rescan for series {arr_media_id} to import: {kept_file_path}"
                        )

                        # Then refresh to clean up orphaned DB entries
                        sonarr_client = await self.sonarr_service._get_client()
                        await refresh_media_item(
                            client=sonarr_client,
                            media_id=arr_media_id,
                            media_type="series",
                            logger_instance=logger,
                        )
                        logger.info(
                            f"Triggered Sonarr refresh for series {arr_media_id} (cleans orphaned DB entries)"
                        )
                    else:
                        logger.info(
                            f"[DRY-RUN] Would trigger Sonarr rescan and refresh for series {arr_media_id}"
                        )
            else:
                # File not tracked in *arr - try manual import, then fall back to full library scan
                logger.info(
                    f"Kept file not yet in {arr_type}. Attempting manual import: {kept_file_path}"
                )

                manual_import_success = False

                if media_type == MediaType.MOVIE:
                    # Try to find the movie by title/metadata to get movie_id for manual import
                    movie = await self.radarr_service.find_movie_by_file_path(
                        kept_file_path
                    )
                    if movie:
                        movie_id = movie["id"]
                        if not self.dry_run:
                            result = await self.radarr_service.manual_import_file(
                                kept_file_path, movie_id
                            )
                            if result is True:
                                logger.info(
                                    f"✅ Successfully triggered manual import for movie {movie_id}: {kept_file_path}"
                                )
                                manual_import_success = True
                            elif result is False:
                                logger.warning(
                                    f"Manual import failed for movie {movie_id}, will try full scan"
                                )
                            else:  # result is None
                                logger.warning(
                                    "File not found in manual import scan, will try full library scan"
                                )
                        else:
                            logger.info(
                                f"[DRY-RUN] Would trigger manual import for movie {movie_id}"
                            )
                            manual_import_success = True

                    # Fall back to full library scan if manual import didn't work
                    if not manual_import_success and not self.dry_run:
                        logger.info(
                            "Manual import not available, triggering full Radarr library scan"
                        )
                        await self.radarr_service.trigger_rescan_all()
                        logger.info("Triggered full Radarr library scan")
                    elif not manual_import_success and self.dry_run:
                        logger.info("[DRY-RUN] Would trigger full Radarr library scan")

                else:  # Series
                    # Try to find the series by episode file path to get series_id for manual import
                    episode = await self.sonarr_service.find_episode_by_file_path(
                        kept_file_path
                    )
                    if episode:
                        series_id = episode["seriesId"]
                        if not self.dry_run:
                            result = await self.sonarr_service.manual_import_file(
                                kept_file_path, series_id
                            )
                            if result is True:
                                logger.info(
                                    f"✅ Successfully triggered manual import for series {series_id}: {kept_file_path}"
                                )
                                manual_import_success = True
                            elif result is False:
                                logger.warning(
                                    f"Manual import failed for series {series_id}, will try full scan"
                                )
                            else:  # result is None
                                logger.warning(
                                    "File not found in manual import scan, will try full library scan"
                                )
                        else:
                            logger.info(
                                f"[DRY-RUN] Would trigger manual import for series {series_id}"
                            )
                            manual_import_success = True

                    # Fall back to full library scan if manual import didn't work
                    if not manual_import_success and not self.dry_run:
                        logger.info(
                            "Manual import not available, triggering full Sonarr library scan"
                        )
                        await self.sonarr_service.trigger_rescan_all()
                        logger.info("Triggered full Sonarr library scan")
                    else:
                        logger.info("[DRY-RUN] Would trigger full Sonarr library scan")

        except ValueError as e:
            if "configuration not found" in str(e):
                logger.info("*arr not configured, skipping rescan")
            else:
                raise
        except Exception as e:
            logger.warning(f"Failed to trigger *arr rescan: {e}")

    async def _get_arr_media_id(
        self, arr_type: str, file_path: str, media_type: MediaType
    ) -> Optional[int]:
        """
        Get movie/series ID from *arr for a given file path.
        Reuses existing find_movie_by_file_path/find_episode_by_file_path methods.

        Args:
            arr_type: 'radarr' or 'sonarr'
            file_path: Path to the media file
            media_type: MediaType.MOVIE or MediaType.EPISODE

        Returns:
            movie_id or series_id if found, None otherwise
        """
        try:
            if arr_type == "radarr" and media_type == MediaType.MOVIE:
                movie = await self.radarr_service.find_movie_by_file_path(file_path)
                if movie:
                    logger.info(
                        f"Found movie '{movie.get('title')}' (ID: {movie['id']}) for file: {file_path}"
                    )
                    return movie["id"]

            elif arr_type == "sonarr" and media_type == MediaType.EPISODE:
                episode = await self.sonarr_service.find_episode_by_file_path(file_path)
                if episode:
                    logger.info(
                        f"Found series (ID: {episode['seriesId']}) for file: {file_path}"
                    )
                    return episode["seriesId"]

            logger.warning(f"Could not find media in {arr_type} for file: {file_path}")
            return None

        except ValueError as e:
            if "configuration not found" in str(e):
                logger.debug(f"{arr_type} not configured")
            else:
                logger.warning(f"Error querying {arr_type}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Error querying {arr_type}: {e}")
            return None

    async def _get_arr_media_id_from_history(
        self, duplicate_set_id: int, arr_type: str
    ) -> Optional[int]:
        """
        Get arr_media_id from deletion history of deleted files in the duplicate set.

        When delete_file() runs, it saves arr_media_id in DeletionHistory.
        We query that to find the movie/series ID for targeted rescanning.

        Args:
            duplicate_set_id: ID of the duplicate set
            arr_type: 'radarr' or 'sonarr'

        Returns:
            arr_media_id if found in any deletion history, None otherwise
        """
        from sqlalchemy import select
        from app.models.duplicate import DuplicateFile
        from app.models.history import DeletionHistory

        try:
            # Find any deletion history from this duplicate set that has arr_media_id
            stmt = (
                select(DeletionHistory.arr_media_id)
                .join(
                    DuplicateFile, DeletionHistory.duplicate_file_id == DuplicateFile.id
                )
                .where(DuplicateFile.set_id == duplicate_set_id)
                .where(DeletionHistory.arr_type == arr_type)
                .where(DeletionHistory.arr_media_id.is_not(None))
                .limit(1)
            )

            result = await self.db.execute(stmt)
            arr_media_id = result.scalar_one_or_none()

            if arr_media_id:
                logger.info(
                    f"Found {arr_type} media ID {arr_media_id} from deletion history for duplicate set {duplicate_set_id}"
                )
            else:
                logger.warning(
                    f"No {arr_type} media ID found in deletion history for duplicate set {duplicate_set_id}"
                )

            return arr_media_id

        except Exception as e:
            logger.warning(f"Error querying deletion history for arr_media_id: {e}")
            return None

    async def _stage_arr_rescan(
        self,
        arr_type: Optional[str],
        media_id: int,
        history: DeletionHistory,
        kept_file_path: Optional[str] = None,
    ):
        """
        Stage 3: Trigger *arr rescan AFTER deletion is complete

        This runs AFTER both Radarr/Sonarr AND qBittorrent have deleted the file.
        This ensures:
        1. The deleted file is completely gone from disk
        2. *arr won't accidentally re-import the file we just deleted
        3. *arr can scan the directory and find the better file we kept
        4. The better file gets automatically imported
        5. Orphaned database entries are cleaned up via RefreshMovie/RefreshSeries

        This ensures the movie/series stays tracked with the higher quality version.

        Args:
            arr_type: 'radarr' or 'sonarr'
            media_id: movie_id or series_id to rescan
            history: Deletion history to update
            kept_file_path: Path to the file we kept (for targeted scanning)
        """
        try:
            if arr_type == "radarr":
                if self.dry_run:
                    logger.info(
                        f"[DRY-RUN] Would trigger Radarr rescan for movie {media_id}"
                    )
                else:
                    # First, rescan for the better file
                    await self.radarr_service.rescan_movie(media_id, kept_file_path)
                    logger.info(
                        f"Triggered Radarr rescan for movie {media_id} "
                        f"(will find and import the better file we kept)"
                    )

                    # Then refresh metadata to clean up orphaned DB entries
                    radarr_client = await self.radarr_service._get_client()
                    await refresh_media_item(
                        client=radarr_client,
                        media_id=media_id,
                        media_type="movie",
                        logger_instance=logger,
                    )
                    logger.info(
                        f"Triggered Radarr refresh for movie {media_id} "
                        f"(will clean up orphaned database entries)"
                    )
            elif arr_type == "sonarr":
                if self.dry_run:
                    logger.info(
                        f"[DRY-RUN] Would trigger Sonarr rescan for series {media_id}"
                    )
                else:
                    # First, rescan for the better file
                    await self.sonarr_service.rescan_series(media_id, kept_file_path)
                    logger.info(
                        f"Triggered Sonarr rescan for series {media_id} "
                        f"(will find and import the better file we kept)"
                    )

                    # Then refresh metadata to clean up orphaned DB entries
                    sonarr_client = await self.sonarr_service._get_client()
                    await refresh_media_item(
                        client=sonarr_client,
                        media_id=media_id,
                        media_type="series",
                        logger_instance=logger,
                    )
                    logger.info(
                        f"Triggered Sonarr refresh for series {media_id} "
                        f"(will clean up orphaned database entries)"
                    )
            else:
                logger.warning(f"Unknown arr_type for rescan: {arr_type}")

        except Exception as e:
            # Don't fail the entire deletion if rescan fails
            # The file is already deleted, rescan is important but not critical
            logger.warning(f"*arr rescan failed (non-critical): {e}")

    async def _stage_plex_refresh(
        self, history: DeletionHistory, duplicate_file: DuplicateFile
    ):
        """
        Stage 5: Trigger targeted Plex refresh for the specific item only

        Refreshes only the specific movie/episode item, not the entire library.
        This runs AFTER the better file has been imported by *arr, so Plex will:
        1. Notice the deleted file is gone
        2. Find the newly imported better-quality file
        3. Update metadata to reflect the better version

        This is much faster and more efficient than a full library scan.
        Uses the item's refresh() method to only refresh metadata for that specific item.

        Args:
            history: DeletionHistory record
            duplicate_file: DuplicateFile with duplicate_set relationship loaded
        """
        try:
            plex_service = await self._get_plex_service()

            if self.dry_run:
                logger.info(
                    f"[DRY-RUN] Would trigger targeted Plex refresh for: {duplicate_file.file_path}"
                )
                history.plex_refreshed = True
            else:
                # Use already-loaded relationship
                plex_item_id = duplicate_file.duplicate_set.plex_item_id

                # Use item-specific refresh instead of path-based library scan
                success = plex_service.refresh_item(plex_item_id)

                if success:
                    history.plex_refreshed = True
                    logger.info(
                        f"Triggered targeted Plex refresh for item: {plex_item_id}"
                    )
                else:
                    # Fallback to full library refresh if targeted refresh fails
                    logger.warning(
                        "Targeted item refresh failed, falling back to library scan"
                    )

                    from app.models.config import Config

                    result = await self.db.execute(
                        select(Config).where(Config.key == "plex_libraries")
                    )
                    library_config = result.scalar_one_or_none()

                    if library_config and library_config.value:
                        library_names = library_config.value.split(",")
                        for library_name in library_names:
                            library_name = library_name.strip()
                            if library_name:
                                # Use refresh_library with library name (not ID)
                                plex_service.refresh_library(library_name)

                    history.plex_refreshed = True
                    logger.info("Completed fallback library refresh")

        except Exception as e:
            logger.error(f"Plex refresh failed: {e}")
            raise

    async def _rollback_deletion(
        self,
        history: DeletionHistory,
        item_hash: Optional[str],
        arr_type: Optional[str],
        file_path: str,
    ):
        """
        Attempt to rollback deletion stages

        Note: This is best-effort. Some operations (like file deletion)
        cannot be fully reversed.
        """
        logger.warning(f"Attempting rollback for {file_path}")

        rollback_needed = False

        # Check if file was actually deleted from disk (and still exists, indicating failed delete)
        if history.deleted_from_disk:
            # If file still exists, the "deletion" was actually just marking read-only filesystem as OK
            # If file doesn't exist, it was actually deleted
            if not os.path.exists(file_path):
                logger.error(
                    "Cannot restore deleted file - backup/recycle bin feature not implemented"
                )
                rollback_needed = True
            else:
                logger.debug(
                    "File still exists on disk (read-only filesystem, no actual deletion)"
                )

        # Only warn if *arr removal actually happened (item_hash or arr_type indicates actual removal)
        # If file wasn't found in *arr, deleted_from_arr=True but nothing was actually removed
        if history.deleted_from_arr and arr_type:
            logger.warning(
                f"File may have been removed from {arr_type} - check {arr_type} UI and re-import if needed"
            )
            rollback_needed = True

        if history.deleted_from_qbit and item_hash:
            logger.warning(
                f"Item {item_hash} removed from qBittorrent - manual re-add needed"
            )
            rollback_needed = True

        if rollback_needed:
            logger.error(
                "Rollback incomplete - some stages cannot be automatically reversed"
            )
        else:
            # No actual deletion occurred yet - safe to delete the history record
            # This allows the user to retry the deletion after fixing the issue
            logger.info(
                "Deletion failed before any destructive operations - removing failed history record to allow retry"
            )
            await self.db.delete(history)
            await self.db.commit()
