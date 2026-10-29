"""
Shared helper functions for duplicate scanning operations
Extracts common logic from scan routes for processing duplicate media
"""

import json
import logging
import os
from typing import Dict, List, Literal, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import DuplicateFile, DuplicateSet
from app.models.duplicate import DuplicateStatus, MediaType, decode_inode, encode_inode
from app.services.arr.quality import (
    ArrQuality,
    ArrQualityRanker,
    ArrQualityUnavailable,
    RankedFile,
    rank_by_arr_quality,
)
from app.services.scan.scoring_engine import MediaMetadata, ScoringEngine

logger = logging.getLogger(__name__)

MediaItem = Literal["movie", "episode"]


def build_file_metadata(
    metadata: MediaMetadata, arr_quality: Optional[ArrQuality] = None
) -> str:
    """Serialize file metadata for storage on a DuplicateFile"""
    file_metadata: Dict[str, str | int | None] = {
        "resolution": metadata.resolution,
        "video_codec": metadata.video_codec,
        "audio_codec": metadata.audio_codec,
        "bitrate": metadata.bitrate,
        "width": metadata.width,
        "height": metadata.height,
    }
    if arr_quality:
        file_metadata["arr_quality"] = arr_quality.quality_name
        file_metadata["arr_custom_format_score"] = arr_quality.custom_format_score
        file_metadata["arr_tracked"] = arr_quality.tracked
    return json.dumps(file_metadata)


async def rank_files(
    files_metadata: List[MediaMetadata],
    media_type: MediaType,
    title: str,
    scoring_engine: ScoringEngine,
    custom_rules: List[dict],
    logger_inst: logging.Logger,
    arr_ranker: Optional[ArrQualityRanker] = None,
) -> Tuple[List[RankedFile], Dict[str, ArrQuality]]:
    """
    Rank the files of a duplicate set and mark the one to keep

    Uses Deduparr's score, or the Radarr/Sonarr quality profile when an
    ArrQualityRanker is given and every file can be evaluated by the *arr.

    Returns:
        Tuple of (ranked files, ArrQuality per file path - empty if not used)
    """
    ranked = scoring_engine.rank_duplicates(files_metadata, custom_rules)
    if arr_ranker is None:
        return ranked, {}

    try:
        arr_qualities = await arr_ranker.evaluate(
            media_type, [m.file_path for m in files_metadata]
        )
    except ArrQualityUnavailable as e:
        logger_inst.warning(
            f"'{title}': *arr quality profile unavailable ({e}), "
            f"using Deduparr score to choose the file to keep"
        )
        return ranked, {}

    ranked = rank_by_arr_quality(ranked, arr_qualities)
    for metadata, score, keep in ranked:
        quality = arr_qualities[metadata.file_path]
        logger_inst.info(
            f"'{title}': {'keep' if keep else 'delete'} {metadata.file_path} - "
            f"{quality.quality_name} (profile rank {quality.quality_rank}, "
            f"revision {quality.revision[0]}.{quality.revision[1]}, "
            f"custom format score {quality.custom_format_score}, "
            f"{'tracked' if quality.tracked else 'untracked'} by the *arr, score {score})"
        )
    return ranked, arr_qualities


async def verify_and_update_existing_set(
    db: AsyncSession,
    existing_set: DuplicateSet,
    current_files_metadata: List[MediaMetadata],
    scoring_engine: ScoringEngine,
    custom_rules: List[dict],
    logger_inst: logging.Logger,
    arr_ranker: Optional[ArrQualityRanker] = None,
) -> Tuple[bool, int]:
    """
    Verify an existing duplicate set against current file state.
    Removes files that no longer exist on disk and updates the set.

    This handles cases where:
    - Files were deleted externally (outside Deduparr)
    - Files were deleted through Plex, Radarr/Sonarr, or manually
    - File paths changed due to library reorganization

    Args:
        db: Database session
        existing_set: The existing duplicate set to verify
        current_files_metadata: Fresh metadata from Plex scan
        scoring_engine: Scoring engine instance
        custom_rules: Custom scoring rules
        logger_inst: Logger instance to use
        arr_ranker: Rank files by *arr quality profile when set

    Returns:
        Tuple of (set_still_valid, files_removed_count)
        set_still_valid is False if the set should be deleted (< 2 files remaining)
    """
    current_paths = {m.file_path for m in current_files_metadata}
    db_file_paths = {f.file_path for f in existing_set.files}

    # Find files in DB that are no longer in Plex
    removed_paths = db_file_paths - current_paths
    # Find new files in Plex that aren't in DB
    new_paths = current_paths - db_file_paths

    files_removed = 0

    if removed_paths:
        logger_inst.info(
            f"Detected {len(removed_paths)} externally removed file(s) for '{existing_set.title}'"
        )
        for file in list(existing_set.files):
            if file.file_path in removed_paths:
                logger_inst.info(f"  Removing stale file record: {file.file_path}")
                await db.delete(file)
                files_removed += 1

        await db.flush()

    # Add any new files that appeared in Plex
    if new_paths:
        logger_inst.info(
            f"Detected {len(new_paths)} new file(s) for '{existing_set.title}'"
        )
        for metadata in current_files_metadata:
            if metadata.file_path in new_paths:
                # Score the new file
                ranked = scoring_engine.rank_duplicates([metadata], custom_rules)
                if ranked:
                    _, score, keep = ranked[0]
                    new_file = DuplicateFile(
                        set_id=existing_set.id,
                        file_path=metadata.file_path,
                        file_size=metadata.file_size,
                        score=score,
                        keep=keep,
                        file_metadata=build_file_metadata(metadata),
                        inode=encode_inode(metadata.inode),
                        is_hardlink=metadata.is_hardlink,
                    )
                    db.add(new_file)
                    logger_inst.info(f"  Added new file: {metadata.file_path}")

        await db.flush()

    # Calculate expected file count after changes
    expected_file_count = len(db_file_paths) - len(removed_paths) + len(new_paths)

    if expected_file_count < 2:
        # Not enough files remaining - delete the set
        logger_inst.info(
            f"Removing duplicate set '{existing_set.title}' - only {expected_file_count} file(s) remaining"
        )
        # Refresh the set from DB to sync cascade state after individual file deletions
        await db.refresh(existing_set)
        await db.delete(existing_set)
        await db.flush()
        return False, files_removed

    # Re-rank files if any changes were made
    if removed_paths or new_paths:
        # Re-query to get updated file list for re-ranking
        result = await db.execute(
            select(DuplicateSet)
            .options(selectinload(DuplicateSet.files))
            .where(DuplicateSet.id == existing_set.id)
            .execution_options(populate_existing=True)
        )
        updated_set = result.scalar_one_or_none()

        if not updated_set:
            return False, files_removed

        # Recalculate keep flags and space to reclaim
        all_metadata = []
        for file in updated_set.files:
            metadata = MediaMetadata(
                file_path=file.file_path,
                file_size=file.file_size,
                resolution=(
                    json.loads(file.file_metadata).get("resolution")
                    if file.file_metadata
                    else None
                ),
                video_codec=(
                    json.loads(file.file_metadata).get("video_codec")
                    if file.file_metadata
                    else None
                ),
                audio_codec=(
                    json.loads(file.file_metadata).get("audio_codec")
                    if file.file_metadata
                    else None
                ),
                bitrate=(
                    json.loads(file.file_metadata).get("bitrate")
                    if file.file_metadata
                    else None
                ),
                width=(
                    json.loads(file.file_metadata).get("width")
                    if file.file_metadata
                    else None
                ),
                height=(
                    json.loads(file.file_metadata).get("height")
                    if file.file_metadata
                    else None
                ),
                inode=decode_inode(file.inode),
                is_hardlink=file.is_hardlink,
            )
            all_metadata.append((file, metadata))

        ranked, arr_qualities = await rank_files(
            [m for _, m in all_metadata],
            updated_set.media_type,
            updated_set.title,
            scoring_engine,
            custom_rules,
            logger_inst,
            arr_ranker,
        )

        # Update files with new scores and keep flags
        path_to_ranking = {m.file_path: (s, k) for m, s, k in ranked}
        space_to_reclaim = 0
        for file, metadata in all_metadata:
            if file.file_path in path_to_ranking:
                score, keep = path_to_ranking[file.file_path]
                file.score = score
                file.keep = keep
                file.file_metadata = build_file_metadata(
                    metadata, arr_qualities.get(file.file_path)
                )
                if not keep:
                    space_to_reclaim += file.file_size

        updated_set.space_to_reclaim = space_to_reclaim
        await db.flush()

        logger_inst.info(
            f"Updated duplicate set '{existing_set.title}': "
            f"{len(updated_set.files)} files, {space_to_reclaim:,} bytes to reclaim"
        )

    return True, files_removed


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
    media_server: str,
    item_id: str,
    title: str,
    media_type: MediaType,
    files_metadata: List[MediaMetadata],
    scoring_engine: ScoringEngine,
    custom_rules: List[dict],
    logger_inst: logging.Logger,
    arr_ranker: Optional[ArrQualityRanker] = None,
) -> bool:
    """
    Create a duplicate set with ranked files

    Args:
        db: Database session
        item_id: Plex item ID
        title: Title of the media
        media_type: Type of media (MOVIE or EPISODE)
        files_metadata: List of file metadata
        scoring_engine: Scoring engine instance
        custom_rules: Custom scoring rules
        logger_inst: Logger instance to use
        arr_ranker: Rank files by *arr quality profile when set

    Returns:
        True if set was created
    """
    ranked_files, arr_qualities = await rank_files(
        files_metadata,
        media_type,
        title,
        scoring_engine,
        custom_rules,
        logger_inst,
        arr_ranker,
    )

    space_to_reclaim = sum(
        metadata.file_size for metadata, score, keep in ranked_files if not keep
    )

    dup_set = DuplicateSet(
        media_server=media_server,
        item_id=item_id,
        title=title,
        media_type=media_type,
        status=DuplicateStatus.PENDING,
        space_to_reclaim=space_to_reclaim,
    )
    db.add(dup_set)
    await db.flush()

    for metadata, score, keep in ranked_files:
        dup_file = DuplicateFile(
            set_id=dup_set.id,
            file_path=metadata.file_path,
            file_size=metadata.file_size,
            score=score,
            keep=keep,
            file_metadata=build_file_metadata(
                metadata, arr_qualities.get(metadata.file_path)
            ),
            inode=encode_inode(metadata.inode),
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
