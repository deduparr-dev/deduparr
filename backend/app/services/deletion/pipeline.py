"""
Deletion pipeline for orchestrating multi-stage file deletion
"""

import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import DeletionHistory, DuplicateFile, DuplicateSet
from app.models.duplicate import DuplicateStatus, MediaType
from app.services.arr.client import ArrClientError
from app.services.media_server import (
    MediaServerType,
    get_media_server,
    selected_libraries,
)
from app.services.media_server.file_probe import is_video_file
from app.services.download.qbittorrent_service import QBittorrentService
from app.services.arr.radarr_service import RadarrService
from app.services.arr.sonarr_service import SonarrService

logger = logging.getLogger(__name__)

# Folders a release ships beside its video. They go with it once no other
# video shares the directory.
RELEASE_SUBDIRS = {"sample", "subs", "proof", "extras"}


@dataclass
class SetDeletion:
    """What deleting one duplicate set did."""

    files_deleted: int = 0
    space_reclaimed: int = 0
    errors: list[str] = field(default_factory=list)
    # Deleted, but with something worth knowing, such as an unconfigured *arr
    warnings: list[str] = field(default_factory=list)


class DeletionPipeline:
    """Orchestrates multi-stage deletion process"""

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
        # Library folders per media server, as the server reports them
        self._library_roots: dict[str, list[str]] = {}

    async def _library_root(
        self, duplicate_file: DuplicateFile, located_path: Optional[str]
    ) -> Optional[str]:
        """
        The library folder a file lives in, where this container sees it.

        Cleanup removes emptied folders up to it, never it: Radarr, Sonarr and
        the media server all expect it to be there. It comes from the libraries
        of the server that reported the file, so it is None when that server
        cannot list them, and then no folder is removed.
        """
        if self.dry_run or not located_path:
            return None

        server_name = duplicate_file.duplicate_set.media_server
        if server_name not in self._library_roots:
            self._library_roots[server_name] = []
            try:
                server = await get_media_server(self.db, MediaServerType(server_name))
                self._library_roots[server_name] = [
                    path
                    for library in await server.get_libraries()
                    for path in await server.get_library_paths(library["title"])
                ]
            except Exception as e:
                logger.warning(
                    f"Leaving emptied folders in place: the library folders "
                    f"of '{server_name}' are unknown ({e})"
                )

        # The innermost library holding the file. Below it, the server's path
        # and the located one are the same, whatever each mounts it as.
        server_path = duplicate_file.file_path
        for root in sorted(
            (path.rstrip("/") for path in self._library_roots[server_name]),
            key=len,
            reverse=True,
        ):
            below = server_path[len(root) :]
            if server_path.startswith(root + "/") and located_path.endswith(below):
                return located_path[: -len(below)]
        return None

    def _locate_file(self, server_path: str, size: int) -> Optional[str]:
        """
        Where a media server's file is in this container, or None.

        The media server can mount the library elsewhere, so after the path
        itself the longest tail of it under the media directory is tried, and
        only taken at the size the server reported. A file is never looked up
        by its name alone: other titles have files of the same name.
        """
        if os.path.isfile(server_path):
            return server_path

        parts = [part for part in server_path.split("/") if part]
        for start in range(len(parts)):
            candidate = os.path.join(settings.media_dir, *parts[start:])
            if os.path.isfile(candidate) and os.path.getsize(candidate) == size:
                logger.debug(f"Found {server_path} at {candidate}")
                return candidate

        logger.warning(
            f"File not found (checked its path and {settings.media_dir}): {server_path}"
        )
        return None

    def _remove(self, path: str) -> None:
        """Delete a file or directory tree, or on a dry run say it would."""
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would delete: {path}")
        elif os.path.isdir(path):
            shutil.rmtree(path)
            logger.info(f"Deleted directory: {path}")
        else:
            os.remove(path)
            logger.info(f"Deleted: {path}")

    def _discard(self, path: str) -> None:
        """Remove something a deleted video left behind, if the mount allows it."""
        try:
            self._remove(path)
        except OSError as e:
            logger.debug(f"Could not delete {path}: {e}")

    @staticmethod
    def _owner(entry: str, stems: set[str]) -> Optional[str]:
        """The video a side file is named after: the longest stem it extends."""
        return max(
            (
                stem
                for stem in stems
                if entry.startswith(stem)
                and entry[len(stem) : len(stem) + 1] in (".", "-")
            ),
            key=len,
            default=None,
        )

    def _clean_up_after(self, video_path: str, library_root: Optional[str]) -> None:
        """
        Remove what a deleted video leaves behind.

        That is its own subtitles, .nfo and artwork and, once no other video
        shares the directory, the release's Sample/Subs/Proof/Extras folders
        and the directories left empty, up to its library folder. A side file
        belongs to the video with the longest name it extends, so a kept
        version or an extra named after the deleted file keeps its own files.
        """
        directory, name = os.path.split(video_path)
        if not os.path.isdir(directory):
            return

        entries = os.listdir(directory)
        stem = os.path.splitext(name)[0]
        other_stems = {
            os.path.splitext(entry)[0]
            for entry in entries
            if entry != name and is_video_file(entry)
        }

        for entry in entries:
            path = os.path.join(directory, entry)
            if os.path.isdir(path):
                if not other_stems and entry.lower() in RELEASE_SUBDIRS:
                    self._discard(path)
            elif (
                not is_video_file(entry)
                and stem not in other_stems
                and self._owner(entry, other_stems | {stem}) == stem
            ):
                self._discard(path)

        if other_stems:
            return
        if self.dry_run:
            logger.info(
                f"[DRY-RUN] Would remove {directory} and its parents once empty"
            )
            return
        if library_root is None:
            return

        try:
            while directory.startswith(library_root + "/") and not os.listdir(
                directory
            ):
                os.rmdir(directory)
                logger.info(f"Removed empty directory: {directory}")
                directory = os.path.dirname(directory)
        except OSError as e:
            logger.debug(f"Stopped removing empty directories at {directory}: {e}")

    async def delete_set(self, duplicate_set: DuplicateSet) -> SetDeletion:
        """
        Delete every file of a set not marked keep, then rescan the *arr once.

        A file counts as deleted once it is gone from disk. Anything less is an
        error and leaves the set pending, so it can be retried; a retry skips
        the files an earlier attempt already deleted.
        """
        outcome = SetDeletion()
        kept = [file for file in duplicate_set.files if file.keep]
        unwanted = [file for file in duplicate_set.files if not file.keep]

        logger.info(
            f"Processing duplicate set '{duplicate_set.title}' (ID: {duplicate_set.id})"
        )
        for file in kept:
            logger.info(f"  KEEPING (score {file.score}): {file.file_path}")
        for file in unwanted:
            logger.info(f"  DELETING (score {file.score}): {file.file_path}")

        result = await self.db.execute(
            select(DeletionHistory.duplicate_file_id).where(
                DeletionHistory.duplicate_file_id.in_([file.id for file in unwanted]),
                DeletionHistory.deleted_from_disk.is_(True),
            )
        )
        already_deleted = set(result.scalars().all())

        for file in unwanted:
            if file.id in already_deleted:
                continue
            try:
                history = await self.delete_file(file.id)
            except Exception as e:
                outcome.errors.append(f"Failed to delete {file.file_path}: {e}")
                continue

            if not history.deleted_from_disk:
                outcome.errors.append(
                    f"Failed to delete {file.file_path}: "
                    f"{history.error or 'it is still on disk'}"
                )
                continue

            outcome.files_deleted += 1
            outcome.space_reclaimed += file.file_size
            if history.error:
                outcome.warnings.append(history.error)

        for error in outcome.errors:
            logger.error(error)

        if outcome.files_deleted and kept:
            try:
                await self.rescan_for_kept_file(
                    duplicate_set.media_type, kept[0].file_path, duplicate_set.id
                )
            except Exception as e:
                # The duplicates are gone either way; what is left is for the user
                outcome.warnings.append(str(e))

        if not self.dry_run and not outcome.errors:
            duplicate_set.status = DuplicateStatus.PROCESSED
        return outcome

    async def delete_file(
        self,
        duplicate_file_id: int,
        skip_qbit: bool = False,
    ) -> DeletionHistory:
        """
        Execute full deletion pipeline for a file

        Args:
            duplicate_file_id: ID of the DuplicateFile to delete
            skip_qbit: Whether to skip qBittorrent removal (e.g., if not in library)

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

        existing_history = (
            await self.db.execute(
                select(DeletionHistory).where(
                    DeletionHistory.duplicate_file_id == duplicate_file_id
                )
            )
        ).scalar_one_or_none()
        if existing_history:
            if existing_history.deleted_from_disk:
                raise ValueError(
                    f"Deletion already in progress or completed for file {duplicate_file_id}"
                )
            if not self.dry_run:
                # An earlier attempt left the file in place; this one starts over
                await self.db.delete(existing_history)
                await self.db.flush()

        file_path = duplicate_file.file_path

        if self.dry_run:
            logger.info(f"[DRY-RUN] Would delete file: {file_path}")
            logger.info("[DRY-RUN] Simulating deletion pipeline stages...")
            # Create a temporary history object for simulation (not saved to DB)
            history = DeletionHistory(
                duplicate_file_id=duplicate_file_id,
                deleted_at=datetime.now(timezone.utc),
            )
            await self._execute_deletion_stages(duplicate_file, history, skip_qbit)
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
            await self._execute_deletion_stages(duplicate_file, history, skip_qbit)
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
    ):
        """
        Execute all deletion stages in optimal order

        Deletion flow:
        1. Remove from *arr and DELETE FILES (Radarr/Sonarr deletes via API)
        2. Remove item from qBittorrent and delete any remaining files
        3. *arr rescan - once per set, after all of its files (delete_set)
        4. Delete the file if still on disk, and what it leaves behind
        5. Refresh the item on the media server that reported it
        """
        file_path = duplicate_file.file_path
        arr_type = None
        item_hash = None
        arr_media_id = None
        kept_file = next(
            (
                file
                for file in duplicate_file.duplicate_set.files
                if file.keep and file.id != duplicate_file.id
            ),
            None,
        )
        # Resolved before any stage removes the file, so later stages still
        # know where it lived.
        located_path = self._locate_file(file_path, duplicate_file.file_size)
        library_root = await self._library_root(duplicate_file, located_path)

        try:
            # Stage 1: Remove from *arr and delete files
            arr_type, arr_media_id = await self._stage_arr_removal(
                duplicate_file, history
            )
            await self.db.commit()

            # Stage 2: Remove item from qBittorrent (deletes any remaining files)
            if not skip_qbit:
                item_hash = await self._stage_qbittorrent_removal(
                    duplicate_file, history, located_path, kept_file
                )
                await self.db.commit()

            # Stage 4: Delete the file if it is still there, and its leftovers
            await self._stage_disk_removal(
                file_path, history, located_path, library_root
            )
            await self.db.commit()

            # Stage 5: Refresh the item on the media server that reported it
            await self._stage_media_server_refresh(history, duplicate_file)

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
        self,
        duplicate_file: DuplicateFile,
        history: DeletionHistory,
        located_path: Optional[str],
        kept_file: Optional[DuplicateFile],
    ) -> Optional[str]:
        """
        Stage 2: Remove the file's torrent from qBittorrent, with its data

        CRITICAL: This must complete BEFORE *arr rescan to ensure the deleted file
        is fully removed and won't be re-imported.

        The torrent stays, and the disk stage removes just the file, when
        removing it would take more than this file:
        - the kept file has a torrent, which may be this one and should keep seeding
        - the torrent holds other videos too, as a season pack does
        - there is no kept file and this is the only torrent holding the file

        Returns:
            Hash of the removed torrent
        """
        file_path = duplicate_file.file_path
        try:
            match = await self.qbit_service.find_item_by_file_path(
                located_path or file_path, duplicate_file.file_size
            )

            if not match:
                # Not finding the item is OK - file might have been manually added
                # or acquired outside of qBittorrent. We'll clean it up in disk stage.
                history.deleted_from_qbit = True
                logger.info(
                    "Item not found in qBittorrent (file may have been added manually). "
                    "Will attempt disk cleanup in next stage."
                )
                return None

            if kept_file:
                if await self.qbit_service.find_item_by_file_path(
                    kept_file.file_path, kept_file.file_size
                ):
                    logger.info(
                        "Kept file has a torrent in qBittorrent. Skipping qBittorrent deletion "
                        "to preserve seeding. Will delete unwanted file via disk cleanup only."
                    )
                    history.deleted_from_qbit = True
                    return None
            elif match.count <= 1:
                # No kept file AND only 1 torrent - DANGER!
                logger.warning(
                    f"Skipping qBittorrent deletion - only 1 torrent found and no other file to keep. "
                    f"Cannot delete the last copy! File: {file_path}"
                )
                history.error = (
                    f"{history.error}; Only 1 torrent exists and no kept file - cannot delete last copy"
                    if history.error
                    else "Only 1 torrent exists and no kept file - cannot delete last copy"
                )
                history.deleted_from_qbit = False
                return None

            if match.holds_other_videos:
                logger.info(
                    f"Torrent {match.hash} holds other videos too. Leaving it in "
                    "qBittorrent; the disk stage removes only this file."
                )
                history.deleted_from_qbit = True
                return None

            if self.dry_run:
                logger.info(
                    f"[DRY-RUN] Would remove item {match.hash} from qBittorrent (with files)"
                )
            else:
                await self.qbit_service.remove_item(match.hash, delete_files=True)
                logger.info(
                    f"Removed item {match.hash} from qBittorrent and deleted files"
                )
            history.deleted_from_qbit = True
            history.deleted_from_disk = True
            return match.hash

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
                        f"Found '{episode.get('title')}' in Sonarr (series {series_id}). "
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

    async def _stage_disk_removal(
        self,
        file_path: str,
        history: DeletionHistory,
        located_path: Optional[str],
        library_root: Optional[str] = None,
    ):
        """
        Stage 4: Delete the file if it is still on disk, then what it leaves behind

        An *arr or qBittorrent can report a delete and leave the file, so the
        filesystem decides. This also covers files no service knows about.

        Args:
            file_path: The file's path as the media server reports it
            history: DeletionHistory record
            located_path: Where the file was before any stage ran, None when
                this container cannot see it
            library_root: The library folder the file lives in, which emptied
                folders are removed up to; None removes none
        """
        if not located_path:
            if history.deleted_from_arr or history.deleted_from_qbit:
                history.deleted_from_disk = True
                logger.info(
                    f"Main file already deleted: {os.path.basename(file_path)} "
                    f"({'by qBittorrent' if history.deleted_from_qbit else 'by *arr or manually'})"
                )
            else:
                error_msg = (
                    f"File not found for deletion (checked its path and "
                    f"{settings.media_dir}): {file_path}"
                )
                logger.error(error_msg)
                history.error = (
                    f"{history.error}; {error_msg}" if history.error else error_msg
                )
                history.deleted_from_disk = False
            return

        if os.path.isfile(located_path):
            # An *arr or qBittorrent delete can report success and leave the
            # file behind; the filesystem decides.
            if history.deleted_from_disk:
                logger.warning(
                    f"An earlier stage reported this file deleted but it is "
                    f"still on disk, removing it here: {located_path}"
                )
            try:
                self._remove(located_path)
            except OSError as e:
                error_msg = f"Could not delete {located_path}: {e.strerror or e}"
                logger.error(error_msg)
                history.error = (
                    f"{history.error}; {error_msg}" if history.error else error_msg
                )
                history.deleted_from_disk = False
                return

        try:
            self._clean_up_after(located_path, library_root)
        except OSError as e:
            logger.warning(f"Could not clean up after {located_path}: {e}")
        history.deleted_from_disk = True

    async def rescan_for_kept_file(
        self,
        media_type: MediaType,
        kept_file_path: str,
        duplicate_set_id: int | None = None,
    ):
        """
        Have Radarr/Sonarr re-read the set's movie or series from disk.

        The rescan imports the kept file and drops the deleted ones. The item
        comes from the deletion history, or from the kept file when the *arr
        tracks it already. When the *arr tracks neither file it can still hold
        a deleted one under a path of its own mount, so its whole library is
        rescanned.

        Args:
            media_type: MediaType.MOVIE or MediaType.EPISODE
            kept_file_path: Path to the file we kept
            duplicate_set_id: ID of the duplicate set (to query deletion history for arr_media_id)
        """
        arr_name = "Radarr" if media_type == MediaType.MOVIE else "Sonarr"
        arr_type = arr_name.lower()
        media_id = None
        if duplicate_set_id:
            media_id = await self._get_arr_media_id_from_history(
                duplicate_set_id, arr_type
            )
        if not media_id:
            media_id = await self._get_arr_media_id(
                arr_type, kept_file_path, media_type
            )

        if self.dry_run:
            target = f"item {media_id}" if media_id else "whole library"
            logger.info(f"[DRY-RUN] Would have {arr_name} rescan its {target}")
            return

        try:
            if media_type == MediaType.MOVIE:
                await self.radarr_service.rescan_movie(media_id, kept_file_path)
            else:
                await self.sonarr_service.rescan_series(media_id, kept_file_path)
        except ValueError as e:
            if "configuration not found" not in str(e):
                raise
            logger.info(f"{arr_name} not configured, skipping rescan")
            return
        except ArrClientError as e:
            raise ArrClientError(f"{arr_name} was not asked to rescan: {e}") from e

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

    async def _stage_media_server_refresh(
        self, history: DeletionHistory, duplicate_file: DuplicateFile
    ):
        """
        Stage 5: ask the media server that reported this set to re-read the item.

        It runs after *arr has imported the file being kept, so the server
        notices the deleted file is gone and picks the better version up. Only
        the owning server is refreshed; another server configured over the same
        media sees the change on its own next scan.
        """
        duplicate_set = duplicate_file.duplicate_set

        if self.dry_run:
            logger.info(
                f"[DRY-RUN] Would refresh {duplicate_set.media_server} item "
                f"for: {duplicate_file.file_path}"
            )
            history.media_server_refreshed = True
            return

        try:
            server_type = MediaServerType(duplicate_set.media_server)
        except ValueError:
            # Sets created by the dev disk scan belong to no server.
            logger.debug(
                f"No media server owns set {duplicate_set.id} "
                f"('{duplicate_set.media_server}') - nothing to refresh"
            )
            history.media_server_refreshed = True
            return

        try:
            server = await get_media_server(self.db, server_type)

            if await server.refresh_item(duplicate_set.item_id):
                history.media_server_refreshed = True
                logger.info(
                    f"Refreshed {server_type.value} item {duplicate_set.item_id}"
                )
                return

            # A targeted refresh can fail if the item is already gone, so fall
            # back to re-scanning the libraries the user selected.
            logger.warning("Targeted refresh failed - falling back to library scan")
            for library_name in await selected_libraries(self.db, server_type):
                await server.refresh_library(library_name)
            history.media_server_refreshed = True

        except Exception as e:
            # The file is already gone; the server catches up on its next scan.
            error_msg = f"{server_type.value.title()} refresh failed: {e}"
            logger.error(error_msg)
            history.error = (
                f"{history.error}; {error_msg}" if history.error else error_msg
            )

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
