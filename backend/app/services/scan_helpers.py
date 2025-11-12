"""
Shared helper functions for duplicate scanning operations
Extracts common logic from scan routes for processing duplicate media
"""

import json
import logging
import os
from typing import List, Literal, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DuplicateFile, DuplicateSet
from app.models.duplicate import DuplicateStatus, MediaType
from app.services.plex_service import is_sample_file
from app.services.scoring_engine import MediaMetadata, ScoringEngine

logger = logging.getLogger(__name__)

MediaItem = Literal["movie", "episode"]


async def collect_media_metadata(
    media_items: List, media_type: MediaItem, logger_inst: logging.Logger
) -> List[MediaMetadata]:
    """
    Collect metadata from Plex media items (movies or episodes)

    Args:
        media_items: List of Plex Movie or Episode objects
        media_type: Type of media ("movie" or "episode")
        logger_inst: Logger instance to use

    Returns:
        List of MediaMetadata objects
    """
    files_metadata = []

    for item in media_items:
        try:
            old_paths = [
                media.parts[0].file
                for media in item.media
                if media.parts and media.parts[0].file
            ]

            item.reload(checkFiles=True)

            new_paths = [
                media.parts[0].file
                for media in item.media
                if media.parts and media.parts[0].file
            ]

            if old_paths != new_paths:
                title = (
                    item.title
                    if media_type == "movie"
                    else f"{item.grandparentTitle} - {item.title}"
                )
                logger_inst.info(
                    f"Plex metadata refreshed for '{title}' - paths updated:"
                )
                for old, new in zip(old_paths, new_paths):
                    if old != new:
                        logger_inst.info(f"  OLD: {old}")
                        logger_inst.info(f"  NEW: {new}")
        except Exception as e:
            title = (
                item.title
                if media_type == "movie"
                else f"{item.grandparentTitle} - {item.title}"
            )
            logger_inst.warning(f"Failed to reload metadata for '{title}': {e}")

        for media in item.media:
            try:
                media_part = media.parts[0]
                file_path = media_part.file
                file_size = media_part.size or 0

                title = (
                    item.title
                    if media_type == "movie"
                    else f"{item.grandparentTitle} - {item.title}"
                )
                logger_inst.info(f"Plex reported file path for '{title}': {file_path}")
                logger_inst.info(f"File exists check: {os.path.exists(file_path)}")

                if is_sample_file(file_path):
                    logger_inst.info(f"Skipping sample file: {file_path}")
                    continue

                inode = None
                is_hardlink = False
                if file_path and os.path.exists(file_path):
                    try:
                        stat_info = os.stat(file_path)
                        inode = stat_info.st_ino
                        is_hardlink = stat_info.st_nlink > 1
                        logger_inst.info(
                            f"File found - inode: {inode}, hardlink: {is_hardlink}"
                        )
                    except OSError as e:
                        logger_inst.warning(f"Failed to stat file {file_path}: {e}")
                else:
                    logger_inst.warning(f"File not found on disk: {file_path}")

                metadata = MediaMetadata(
                    file_path=file_path,
                    file_size=file_size,
                    resolution=media.videoResolution,
                    video_codec=media.videoCodec,
                    audio_codec=(
                        media.audioCodec if hasattr(media, "audioCodec") else None
                    ),
                    bitrate=media.bitrate,
                    width=media.width,
                    height=media.height,
                    inode=inode,
                    is_hardlink=is_hardlink,
                )
                files_metadata.append(metadata)
            except (AttributeError, IndexError) as e:
                logger_inst.warning(f"Could not extract metadata from media file: {e}")
                continue

    return files_metadata


def validate_duplicate_files(
    files_metadata: List[MediaMetadata], title: str, logger_inst: logging.Logger
) -> Optional[str]:
    """
    Validate that files are true duplicates (not hardlinks, all files exist, etc.)

    Args:
        files_metadata: List of file metadata
        title: Title of the media (for logging)
        logger_inst: Logger instance to use

    Returns:
        Error message if validation fails, None if valid
    """
    if len(files_metadata) < 2:
        return (
            f"Only {len(files_metadata)} non-sample file(s) remaining, need at least 2"
        )

    missing_files = [m for m in files_metadata if m.inode is None]
    if missing_files:
        logger_inst.warning(
            f"'{title}' has {len(missing_files)} missing file(s) out of {len(files_metadata)} total. "
            f"Plex may have stale references."
        )
        return "Has missing files"

    inodes = [m.inode for m in files_metadata if m.inode is not None]
    if inodes and len(set(inodes)) == 1:
        sizes = [m.file_size for m in files_metadata]
        if len(set(sizes)) == 1:
            logger_inst.info(
                f"Skipping '{title}' - all {len(files_metadata)} files are hardlinks "
                f"(same inode: {inodes[0]}, size: {sizes[0]:,} bytes), not real duplicates"
            )
            return "All files are hardlinks, not true duplicates"
        else:
            logger_inst.warning(
                f"'{title}' has files with same inode but different sizes - possible filesystem corruption"
            )

    # Check for identical files (same size and same filename - likely copies)
    import os

    sizes = [m.file_size for m in files_metadata]
    filenames = [os.path.basename(m.file_path).lower() for m in files_metadata]
    full_paths = [m.file_path for m in files_metadata]

    # Only skip if files have same size, same filename, AND same parent directory
    # (which would mean Plex has duplicate entries for the same physical file)
    if len(set(sizes)) == 1 and len(set(filenames)) == 1:
        # Check if all files are in the same directory
        parent_dirs = [os.path.dirname(path) for path in full_paths]
        if len(set(parent_dirs)) == 1:
            # All files are in same directory with same name and size - Plex duplicate entry bug
            logger_inst.info(
                f"Skipping '{title}' - all {len(files_metadata)} Plex entries point to same file "
                f"(same directory: {parent_dirs[0]}, filename: {filenames[0]}), not real duplicates"
            )
            return "All Plex entries point to same file, not true duplicates"
        else:
            # Same filename and size but different directories - these ARE real duplicates!
            logger_inst.debug(
                f"'{title}' has {len(files_metadata)} files with same name and size in different directories - "
                f"these are real duplicates to process"
            )

    return None


async def create_duplicate_set(
    db: AsyncSession,
    plex_item_id: str,
    title: str,
    media_type: MediaType,
    files_metadata: List[MediaMetadata],
    scoring_engine: ScoringEngine,
    custom_rules: List[dict],
    logger_inst: logging.Logger,
) -> bool:
    """
    Create a duplicate set with ranked files

    Args:
        db: Database session
        plex_item_id: Plex item ID
        title: Title of the media
        media_type: Type of media (MOVIE or EPISODE)
        files_metadata: List of file metadata
        scoring_engine: Scoring engine instance
        custom_rules: Custom scoring rules
        logger_inst: Logger instance to use

    Returns:
        True if set was created
    """
    ranked_files = scoring_engine.rank_duplicates(files_metadata, custom_rules)

    space_to_reclaim = sum(
        metadata.file_size for metadata, score, keep in ranked_files if not keep
    )

    dup_set = DuplicateSet(
        plex_item_id=plex_item_id,
        title=title,
        media_type=media_type,
        status=DuplicateStatus.PENDING,
        space_to_reclaim=space_to_reclaim,
    )
    db.add(dup_set)
    await db.flush()

    for metadata, score, keep in ranked_files:
        file_metadata_dict = {
            "resolution": metadata.resolution,
            "video_codec": metadata.video_codec,
            "audio_codec": metadata.audio_codec,
            "bitrate": metadata.bitrate,
            "width": metadata.width,
            "height": metadata.height,
        }

        dup_file = DuplicateFile(
            set_id=dup_set.id,
            file_path=metadata.file_path,
            file_size=metadata.file_size,
            score=score,
            keep=keep,
            file_metadata=json.dumps(file_metadata_dict),
            inode=metadata.inode,
            is_hardlink=metadata.is_hardlink,
        )
        db.add(dup_file)

    logger_inst.info(f"Created duplicate set for {media_type.value}: {title}")
    return True


async def cleanup_stale_set(
    db: AsyncSession, existing_set, reason: str, logger_inst: logging.Logger
) -> None:
    """
    Clean up a stale duplicate set

    Args:
        db: Database session
        existing_set: Existing duplicate set to clean up
        reason: Reason for cleanup (for logging)
        logger_inst: Logger instance to use
    """
    if existing_set:
        logger_inst.info(
            f"Cleaning up stale duplicate set for {existing_set.media_type.value}: {existing_set.title} ({reason})"
        )
        await db.delete(existing_set)
        await db.flush()
