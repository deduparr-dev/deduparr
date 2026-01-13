"""
Scan routes for triggering and managing duplicate detection
"""

import json
import logging
import os
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.models import Config, DuplicateSet, ScoringRule
from app.models.duplicate import DuplicateStatus, MediaType
from app.services.deletion_pipeline import DeletionPipeline
from app.services.disk_scan_service import (
    DiskScanConfig,
    DiskScanService,
    DuplicateDetectionStrategy,
    HardlinkHandling,
)
from app.services.plex_service import PlexService
from app.services.scan_helpers import (
    collect_media_metadata,
    validate_duplicate_files,
    create_duplicate_set,
    cleanup_stale_set,
    verify_and_update_existing_set,
)
from app.services.scan_orchestrator import ScanOrchestrator
from app.services.scoring_engine import ScoringEngine

logger = logging.getLogger(__name__)

router = APIRouter()


class ScanRequest(BaseModel):
    """Request to start a duplicate scan"""

    library_names: List[str]
    # media_types removed - auto-detected from library type


class ScanResponse(BaseModel):
    """Response from scan operation"""

    success: bool
    message: str
    duplicates_found: int
    sets_created: int
    sets_updated: int
    sets_removed: int
    total_sets: int


class DuplicateFileResponse(BaseModel):
    """Duplicate file information"""

    id: int
    file_path: str
    file_size: int
    score: int
    keep: bool
    file_metadata: Optional[dict] = None


class DuplicateSetResponse(BaseModel):
    """Duplicate set information"""

    id: int
    plex_item_id: str
    title: str
    media_type: str
    found_at: str
    status: str
    space_to_reclaim: int
    files: List[DuplicateFileResponse]


class DeleteRequest(BaseModel):
    """Request to delete duplicates from a set"""

    dry_run: bool = True


class DeleteResponse(BaseModel):
    """Response from deletion operation"""

    success: bool
    message: str
    dry_run: bool
    files_deleted: int
    space_reclaimed: int
    errors: List[str] = []


async def get_plex_service(db: AsyncSession) -> PlexService:
    """Get configured Plex service"""
    result = await db.execute(select(Config).where(Config.key == "plex_auth_token"))
    token_config = result.scalar_one_or_none()

    result = await db.execute(select(Config).where(Config.key == "plex_server_name"))
    server_config = result.scalar_one_or_none()

    if not token_config:
        raise HTTPException(
            status_code=400, detail="Plex not configured. Complete setup first."
        )

    # Convert to plain string to detach from SQLAlchemy session
    encrypted_token = str(token_config.value) if token_config.value else None
    server_name = (
        str(server_config.value) if server_config and server_config.value else None
    )

    return PlexService(
        encrypted_token=encrypted_token,
        server_name=server_name,
    )


async def get_custom_scoring_rules(db: AsyncSession) -> List[dict]:
    """Get enabled custom scoring rules from database"""
    result = await db.execute(select(ScoringRule).where(ScoringRule.enabled))
    rules = result.scalars().all()

    return [
        {
            "pattern": rule.pattern,
            "score_modifier": rule.score_modifier,
            "enabled": rule.enabled,
        }
        for rule in rules
    ]


@router.post("/start", response_model=ScanResponse)
async def start_scan(
    scan_request: ScanRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Start scanning for duplicates in specified libraries

    This will:
    1. Connect to Plex and scan libraries
    2. Find duplicate media items (using orchestrator for optional deep scan)
    3. Score each version using the scoring engine
    4. Store results in database with status=PENDING
    5. Verify existing sets and remove stale file references
    """
    logger.info(f"Starting scan for libraries: {scan_request.library_names}")

    # Let HTTPExceptions (like 400 from get_plex_service) bubble up naturally
    # FastAPI will handle them correctly
    plex_service = await get_plex_service(db)
    orchestrator = ScanOrchestrator(plex_service, db)
    scoring_engine = ScoringEngine()
    custom_rules = await get_custom_scoring_rules(db)

    total_duplicates = 0
    total_sets_created = 0
    total_sets_updated = 0
    total_sets_removed = 0

    try:
        for library_name in scan_request.library_names:
            logger.info(f"Scanning library: {library_name}")

            # Get library to detect type
            library = plex_service.get_library(library_name)
            logger.info(f"Detected library type: {library.type} for '{library_name}'")

            # Scan based on library type (orchestrator handles deep scan automatically)
            if library.type == "movie":
                movie_dupes = await orchestrator.scan_movies(library_name)

                # Clean up stale duplicate sets that Plex no longer reports
                await _cleanup_stale_duplicate_sets(db, movie_dupes, MediaType.MOVIE)

                sets_created, sets_updated, sets_removed = (
                    await _process_duplicate_movies(
                        db, movie_dupes, scoring_engine, custom_rules
                    )
                )
                # Count actual media files, not Movie objects
                total_duplicates += sum(
                    len(movie.media)
                    for movies in movie_dupes.values()
                    for movie in movies
                )
                total_sets_created += sets_created
                total_sets_updated += sets_updated
                total_sets_removed += sets_removed

            elif library.type == "show":
                # Scan for duplicate episodes
                try:
                    logger.info(f"Starting episode duplicate scan for '{library_name}'")
                    episode_dupes = await orchestrator.scan_episodes(library_name)
                    logger.info(
                        f"Found {len(episode_dupes)} duplicate episode groups in '{library_name}'"
                    )

                    # Clean up stale duplicate sets that Plex no longer reports
                    await _cleanup_stale_duplicate_sets(
                        db, episode_dupes, MediaType.EPISODE
                    )

                    sets_created, sets_updated, sets_removed = (
                        await _process_duplicate_episodes(
                            db, episode_dupes, scoring_engine, custom_rules
                        )
                    )
                    logger.info(
                        f"Processed episodes: {sets_created} created, "
                        f"{sets_updated} updated, {sets_removed} removed"
                    )

                    # Count actual media files, not Episode objects
                    total_duplicates += sum(
                        len(episode.media)
                        for episodes in episode_dupes.values()
                        for episode in episodes
                    )
                    total_sets_created += sets_created
                    total_sets_updated += sets_updated
                    total_sets_removed += sets_removed
                except Exception as e:
                    logger.error(
                        f"Could not scan episodes in {library_name}: {e}", exc_info=True
                    )
            else:
                logger.warning(
                    f"Unsupported library type '{library.type}' for '{library_name}' - skipping"
                )

        await db.commit()

        # Get current total from database
        total_result = await db.execute(
            select(func.count(DuplicateSet.id)).where(
                DuplicateSet.status == DuplicateStatus.PENDING
            )
        )
        current_total = total_result.scalar() or 0

        return ScanResponse(
            success=True,
            message=f"Scan completed for {len(scan_request.library_names)} libraries",
            duplicates_found=total_duplicates,
            sets_created=total_sets_created,
            sets_updated=total_sets_updated,
            sets_removed=total_sets_removed,
            total_sets=current_total,
        )

    except Exception as e:
        # Only catch unexpected errors during the scan process itself
        logger.error(f"Scan failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Scan failed: {str(e)}")


async def _cleanup_stale_duplicate_sets(
    db: AsyncSession,
    current_duplicates: dict,
    media_type: MediaType,
) -> int:
    """
    Clean up duplicate sets that are in the database but no longer reported by Plex.
    This happens when:
    - Files are deleted outside of Deduparr
    - Plex no longer considers them duplicates (e.g., after manual unmatching/splitting)
    - Files have been deleted through Plex or *arr

    Only cleans up PENDING sets - we preserve APPROVED/REJECTED/PROCESSED sets
    for activity history and user decisions.

    Args:
        db: Database session
        current_duplicates: Dictionary of duplicates currently found by Plex (keyed by plex_item_id)
        media_type: Type of media (MOVIE or EPISODE)

    Returns:
        Number of stale sets cleaned up
    """
    # Get all PENDING duplicate sets of this media type from database
    result = await db.execute(
        select(DuplicateSet)
        .options(selectinload(DuplicateSet.files))
        .where(
            DuplicateSet.media_type == media_type,
            DuplicateSet.status == DuplicateStatus.PENDING,
        )
    )
    db_sets = result.scalars().all()

    # Build set of plex_item_ids currently reported by Plex
    current_plex_ids = set()
    for items in current_duplicates.values():
        if items:  # Skip empty lists
            # For movies/episodes, use the first item's ratingKey
            current_plex_ids.add(str(items[0].ratingKey))

    cleaned = 0
    for db_set in db_sets:
        if db_set.plex_item_id not in current_plex_ids:
            # This duplicate set is no longer reported by Plex
            logger.info(
                f"Cleaning up stale PENDING duplicate set: {db_set.title} (plex_item_id={db_set.plex_item_id}, "
                f"no longer reported as duplicate by Plex)"
            )
            await db.delete(db_set)
            cleaned += 1

    if cleaned > 0:
        await db.flush()
        logger.info(
            f"Cleaned up {cleaned} stale PENDING duplicate sets for {media_type.value}"
        )

    return cleaned


async def _process_duplicate_movies(
    db: AsyncSession,
    duplicates: dict,
    scoring_engine: ScoringEngine,
    custom_rules: List[dict],
) -> Tuple[int, int, int]:
    """Process and store duplicate movie sets

    Returns:
        tuple[int, int, int]: (sets_created, sets_updated, sets_removed)
    """
    sets_created = 0
    sets_updated = 0
    sets_removed = 0

    for title_key, movies in duplicates.items():
        if not movies:
            continue

        first_movie = movies[0]
        plex_item_id = str(first_movie.ratingKey)

        existing = await db.execute(
            select(DuplicateSet)
            .options(selectinload(DuplicateSet.files))
            .where(
                DuplicateSet.plex_item_id == plex_item_id,
                DuplicateSet.media_type == MediaType.MOVIE,
            )
        )
        existing_set = existing.scalar_one_or_none()

        files_metadata = await collect_media_metadata(movies, "movie", logger)

        validation_error = validate_duplicate_files(
            files_metadata, first_movie.title, logger
        )
        if validation_error:
            logger.info(f"Skipping '{first_movie.title}' - {validation_error.lower()}")
            await cleanup_stale_set(db, existing_set, validation_error, logger)
            if existing_set:
                sets_removed += 1
            continue

        if existing_set:
            # Verify and update existing set - detect externally removed files
            set_valid, files_removed = await verify_and_update_existing_set(
                db,
                existing_set,
                files_metadata,
                scoring_engine,
                custom_rules,
                logger,
            )
            if set_valid:
                if files_removed > 0:
                    sets_updated += 1
                    logger.info(
                        f"Updated duplicate set for movie: {first_movie.title} "
                        f"(removed {files_removed} stale file(s))"
                    )
            else:
                sets_removed += 1
            continue

        await create_duplicate_set(
            db,
            plex_item_id,
            first_movie.title,
            MediaType.MOVIE,
            files_metadata,
            scoring_engine,
            custom_rules,
            logger,
        )
        sets_created += 1

    return sets_created, sets_updated, sets_removed


async def _process_duplicate_episodes(
    db: AsyncSession,
    duplicates: dict,
    scoring_engine: ScoringEngine,
    custom_rules: List[dict],
) -> Tuple[int, int, int]:
    """Process and store duplicate episode sets

    Returns:
        tuple[int, int, int]: (sets_created, sets_updated, sets_removed)
    """
    sets_created = 0
    sets_updated = 0
    sets_removed = 0

    for episode_key, episodes in duplicates.items():
        if not episodes:
            continue

        first_episode = episodes[0]
        plex_item_id = str(first_episode.ratingKey)

        existing = await db.execute(
            select(DuplicateSet)
            .options(selectinload(DuplicateSet.files))
            .where(
                DuplicateSet.plex_item_id == plex_item_id,
                DuplicateSet.media_type == MediaType.EPISODE,
            )
        )
        existing_set = existing.scalar_one_or_none()

        files_metadata = await collect_media_metadata(episodes, "episode", logger)

        episode_title = f"{first_episode.grandparentTitle} - {first_episode.title}"
        validation_error = validate_duplicate_files(
            files_metadata, episode_title, logger
        )
        if validation_error:
            logger.info(f"Skipping '{episode_title}' - {validation_error.lower()}")
            await cleanup_stale_set(db, existing_set, validation_error, logger)
            if existing_set:
                sets_removed += 1
            continue

        if existing_set:
            # Verify and update existing set - detect externally removed files
            set_valid, files_removed = await verify_and_update_existing_set(
                db,
                existing_set,
                files_metadata,
                scoring_engine,
                custom_rules,
                logger,
            )
            if set_valid:
                if files_removed > 0:
                    sets_updated += 1
                    logger.info(
                        f"Updated duplicate set for episode: {first_episode.grandparentTitle} "
                        f"S{first_episode.seasonNumber:02d}E{first_episode.episodeNumber:02d} "
                        f"(removed {files_removed} stale file(s))"
                    )
            else:
                sets_removed += 1
            continue

        full_title = f"{first_episode.grandparentTitle} - S{first_episode.seasonNumber:02d}E{first_episode.episodeNumber:02d} - {first_episode.title}"
        await create_duplicate_set(
            db,
            plex_item_id,
            full_title,
            MediaType.EPISODE,
            files_metadata,
            scoring_engine,
            custom_rules,
            logger,
        )
        sets_created += 1

    return sets_created, sets_updated, sets_removed


@router.get("/duplicates", response_model=List[DuplicateSetResponse])
async def get_duplicates(
    status: Optional[str] = Query(None, description="Filter by status"),
    media_type: Optional[str] = Query(None, description="Filter by media type"),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """Get list of duplicate sets with their files"""
    query = select(DuplicateSet).options(selectinload(DuplicateSet.files))

    if status:
        try:
            status_enum = DuplicateStatus(status)
            query = query.where(DuplicateSet.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    if media_type:
        try:
            media_type_enum = MediaType(media_type)
            query = query.where(DuplicateSet.media_type == media_type_enum)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Invalid media_type: {media_type}"
            )

    query = query.order_by(DuplicateSet.found_at.desc()).limit(limit)

    result = await db.execute(query)
    duplicate_sets = result.scalars().all()

    return [
        DuplicateSetResponse(
            id=dup_set.id,
            plex_item_id=dup_set.plex_item_id,
            title=dup_set.title,
            media_type=dup_set.media_type.value,
            found_at=dup_set.found_at.isoformat(),
            status=dup_set.status.value,
            space_to_reclaim=dup_set.space_to_reclaim,
            files=[
                DuplicateFileResponse(
                    id=file.id,
                    file_path=file.file_path,
                    file_size=file.file_size,
                    score=file.score,
                    keep=file.keep,
                    file_metadata=(
                        json.loads(file.file_metadata) if file.file_metadata else None
                    ),
                )
                for file in dup_set.files
            ],
        )
        for dup_set in duplicate_sets
    ]


@router.get("/status")
async def get_scan_status(db: AsyncSession = Depends(get_db)):
    """Get current scan statistics"""
    total_sets = await db.execute(select(func.count(DuplicateSet.id)))
    pending_sets = await db.execute(
        select(func.count(DuplicateSet.id)).where(
            DuplicateSet.status == DuplicateStatus.PENDING
        )
    )
    # Only sum space from PENDING and APPROVED sets (exclude PROCESSED)
    total_space = await db.execute(
        select(func.sum(DuplicateSet.space_to_reclaim)).where(
            DuplicateSet.status.in_([DuplicateStatus.PENDING, DuplicateStatus.APPROVED])
        )
    )

    return {
        "total_duplicate_sets": total_sets.scalar() or 0,
        "pending_sets": pending_sets.scalar() or 0,
        "total_space_reclaimable": total_space.scalar() or 0,
    }


@router.post("/duplicates/{set_id}/delete", response_model=DeleteResponse)
async def delete_duplicate_set(
    set_id: int,
    delete_request: DeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete duplicate files from a set, keeping only the highest-scored file

    Args:
        set_id: ID of the duplicate set
        delete_request: Contains dry_run flag (default True for safety)

    Returns:
        DeleteResponse with deletion results
    """
    result = await db.execute(
        select(DuplicateSet)
        .options(selectinload(DuplicateSet.files))
        .where(DuplicateSet.id == set_id)
    )
    duplicate_set = result.scalar_one_or_none()

    if not duplicate_set:
        raise HTTPException(status_code=404, detail=f"Duplicate set {set_id} not found")

    if duplicate_set.status == DuplicateStatus.PROCESSED:
        raise HTTPException(
            status_code=400, detail="This duplicate set has already been processed"
        )

    files_to_delete = [f for f in duplicate_set.files if not f.keep]
    files_to_keep = [f for f in duplicate_set.files if f.keep]

    if not files_to_delete:
        raise HTTPException(
            status_code=400, detail="No files marked for deletion in this set"
        )

    # Log which files are being kept vs deleted for clarity
    logger.info(f"Processing duplicate set '{duplicate_set.title}' (ID: {set_id})")
    for file in files_to_keep:
        logger.info(f"  KEEPING (score {file.score}): {file.file_path}")
    for file in files_to_delete:
        logger.info(f"  DELETING (score {file.score}): {file.file_path}")

    pipeline = DeletionPipeline(db, dry_run=delete_request.dry_run)

    deleted_count = 0
    total_space = 0
    errors = []
    warnings = []

    # Delete all files WITHOUT triggering individual rescans
    for file in files_to_delete:
        try:
            history = await pipeline.delete_file(
                file.id,
                skip_qbit=False,
                skip_rescan=True,  # Skip rescan during deletion
            )
            deleted_count += 1
            total_space += file.file_size

            # Collect warnings from deletion history
            if history.error and history.is_complete:
                # Deletion succeeded but with warnings about unconfigured services
                warnings.append(history.error)

            logger.info(
                f"{'[DRY-RUN] Would delete' if delete_request.dry_run else 'Deleted'} file: {file.file_path}"
            )
        except Exception as e:
            error_msg = f"Failed to delete {file.file_path}: {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)

    # After ALL deletions complete, trigger ONE rescan using the kept file
    if deleted_count > 0 and files_to_keep:
        kept_file = files_to_keep[0]  # There's only one kept file per set
        try:
            # The deletion pipeline saves arr_media_id in history, pass the set ID
            # so rescan_for_kept_file can query it from deletion history
            await pipeline.rescan_for_kept_file(
                duplicate_set.media_type, kept_file.file_path, duplicate_set.id
            )
            logger.info(
                f"Triggered *arr rescan to import kept file: {kept_file.file_path}"
            )
        except Exception as e:
            # Rescan failure is non-critical
            logger.warning(f"Failed to trigger *arr rescan (non-critical): {e}")

    if not delete_request.dry_run and deleted_count > 0:
        duplicate_set.status = DuplicateStatus.PROCESSED
        await db.commit()

    # Build message with warnings if any
    base_message = (
        f"{'[DRY-RUN] Would delete' if delete_request.dry_run else 'Deleted'} "
        f"{deleted_count} file(s) from duplicate set '{duplicate_set.title}'"
    )

    if warnings and not delete_request.dry_run:
        # Get unique warnings
        unique_warnings = list(set(warnings))
        warning_text = "; ".join(unique_warnings)
        base_message += f". Note: {warning_text}"

    return DeleteResponse(
        success=len(errors) == 0,
        message=base_message,
        dry_run=delete_request.dry_run,
        files_deleted=deleted_count,
        space_reclaimed=total_space,
        errors=errors,
    )


@router.get("/duplicates/{set_id}/preview")
async def preview_deletion(
    set_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Preview what would be deleted for a duplicate set without executing

    Returns detailed information about which files would be kept vs deleted
    """
    result = await db.execute(
        select(DuplicateSet)
        .options(selectinload(DuplicateSet.files))
        .where(DuplicateSet.id == set_id)
    )
    duplicate_set = result.scalar_one_or_none()

    if not duplicate_set:
        raise HTTPException(status_code=404, detail=f"Duplicate set {set_id} not found")

    files_to_keep = []
    files_to_delete = []

    for file in duplicate_set.files:
        file_info = {
            "id": file.id,
            "file_path": file.file_path,
            "file_size": file.file_size,
            "score": file.score,
            "metadata": json.loads(file.file_metadata) if file.file_metadata else None,
        }

        if file.keep:
            files_to_keep.append(file_info)
        else:
            files_to_delete.append(file_info)

    total_space_to_reclaim = sum(f["file_size"] for f in files_to_delete)

    return {
        "set_id": duplicate_set.id,
        "title": duplicate_set.title,
        "media_type": duplicate_set.media_type.value,
        "status": duplicate_set.status.value,
        "files_to_keep": files_to_keep,
        "files_to_delete": files_to_delete,
        "total_files": len(duplicate_set.files),
        "files_to_delete_count": len(files_to_delete),
        "space_to_reclaim": total_space_to_reclaim,
        "space_to_reclaim_mb": round(total_space_to_reclaim / (1024 * 1024), 2),
        "space_to_reclaim_gb": round(total_space_to_reclaim / (1024 * 1024 * 1024), 2),
    }


class UpdateFileKeepRequest(BaseModel):
    """Request to update the keep flag for a file"""

    keep: bool


class UpdateFileKeepResponse(BaseModel):
    """Response from updating file keep flag"""

    success: bool
    message: str
    file_id: int
    keep: bool
    space_to_reclaim: int


@router.patch("/duplicates/{set_id}/files/{file_id}")
async def update_file_keep_flag(
    set_id: int,
    file_id: int,
    request: UpdateFileKeepRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Update the keep flag for a specific file in a duplicate set.

    This allows users to override the automated scoring decision and
    manually select which files to keep or delete.

    Validation:
    - At least one file must remain marked as keep=True
    - Cannot modify files in PROCESSED sets
    """
    # Fetch the duplicate set with files
    result = await db.execute(
        select(DuplicateSet)
        .options(selectinload(DuplicateSet.files))
        .where(DuplicateSet.id == set_id)
    )
    duplicate_set = result.scalar_one_or_none()

    if not duplicate_set:
        raise HTTPException(status_code=404, detail=f"Duplicate set {set_id} not found")

    if duplicate_set.status == DuplicateStatus.PROCESSED:
        raise HTTPException(
            status_code=400,
            detail="Cannot modify files in a processed duplicate set",
        )

    # Find the target file
    target_file = None
    for file in duplicate_set.files:
        if file.id == file_id:
            target_file = file
            break

    if not target_file:
        raise HTTPException(
            status_code=404,
            detail=f"File {file_id} not found in duplicate set {set_id}",
        )

    # Validation: ensure at least one file remains marked as keep
    if not request.keep:
        # Count how many files are currently marked as keep (excluding the target)
        other_keep_count = sum(
            1 for f in duplicate_set.files if f.keep and f.id != file_id
        )
        if other_keep_count == 0:
            raise HTTPException(
                status_code=400,
                detail="At least one file must be marked to keep. "
                "Cannot mark all files for deletion.",
            )

    # Update the file's keep flag
    target_file.keep = request.keep

    # Recalculate space_to_reclaim for the set
    space_to_reclaim = sum(f.file_size for f in duplicate_set.files if not f.keep)
    duplicate_set.space_to_reclaim = space_to_reclaim

    await db.commit()

    logger.info(
        f"Updated file {file_id} in set {set_id}: keep={request.keep}, "
        f"new space_to_reclaim={space_to_reclaim}"
    )

    return UpdateFileKeepResponse(
        success=True,
        message=f"File {'will be kept' if request.keep else 'marked for deletion'}",
        file_id=file_id,
        keep=request.keep,
        space_to_reclaim=space_to_reclaim,
    )


# =============================================================================
# DEV-ONLY ENDPOINTS
# These endpoints are only available in development mode (LOG_LEVEL=DEBUG)
# =============================================================================


def _is_dev_mode() -> bool:
    """Check if running in development mode"""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    return log_level == "DEBUG"


class DevScanRequest(BaseModel):
    """Request for dev disk scan"""

    paths: List[str] = ["/media/movies", "/media/tv"]
    media_type: str = "movie"  # "movie" or "episode"


@router.post("/dev/disk-scan", response_model=ScanResponse)
async def dev_disk_scan(
    request: DevScanRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    DEV ONLY: Scan filesystem for duplicates and create DB records.

    This endpoint bypasses Plex entirely and scans the specified paths
    directly, creating actual DuplicateSet records. Only available when
    LOG_LEVEL=DEBUG.

    Use this to test the full UI flow with mock files in development.
    """
    if not _is_dev_mode():
        raise HTTPException(
            status_code=403,
            detail="This endpoint is only available in development mode (LOG_LEVEL=DEBUG)",
        )

    logger.info(f"[DEV] Starting direct disk scan for paths: {request.paths}")

    # Check which paths exist
    existing_paths = [p for p in request.paths if os.path.exists(p)]
    missing_paths = [p for p in request.paths if not os.path.exists(p)]

    if missing_paths:
        logger.warning(f"[DEV] Missing paths: {missing_paths}")

    if not existing_paths:
        return ScanResponse(
            success=False,
            message=f"No valid paths found. Missing: {missing_paths}",
            duplicates_found=0,
            sets_created=0,
            sets_updated=0,
            sets_removed=0,
            total_sets=0,
        )

    # Initialize disk scan service with NAME_ONLY strategy
    disk_config = DiskScanConfig(
        strategy=DuplicateDetectionStrategy.NAME_ONLY,
        hardlink_handling=HardlinkHandling.EXCLUDE,
        enable_checksum=False,
    )
    disk_service = DiskScanService(config=disk_config)

    # Scan based on media type
    media_type = MediaType.MOVIE if request.media_type == "movie" else MediaType.EPISODE
    if media_type == MediaType.MOVIE:
        duplicates = disk_service.find_duplicate_movies_on_disk(existing_paths)
    else:
        duplicates = disk_service.find_duplicate_episodes_on_disk(existing_paths)

    # Initialize scoring engine
    scoring_engine = ScoringEngine()
    custom_rules = await get_custom_scoring_rules(db)

    sets_created = 0
    total_files = 0

    for key, files in duplicates.items():
        if len(files) < 2:
            continue

        # Extract title from key (format: "title|year" or "show s01e01")
        title = key.split("|")[0].title() if "|" in key else key.title()

        # Check if set already exists
        result = await db.execute(
            select(DuplicateSet).where(
                DuplicateSet.title == title,
                DuplicateSet.media_type == media_type,
            )
        )
        existing_set = result.scalar_one_or_none()

        if existing_set:
            logger.info(f"[DEV] Set already exists for '{title}', skipping")
            continue

        # Create MediaMetadata objects for scoring
        from app.services.scan_helpers import MediaMetadata

        metadata_list = []
        for f in files:
            # Parse quality info from filename
            path = f["path"]
            filename = os.path.basename(path)

            # Simple resolution detection from filename
            resolution = "unknown"
            if "2160p" in filename or "4k" in filename.lower():
                resolution = "2160p"
            elif "1080p" in filename:
                resolution = "1080p"
            elif "720p" in filename:
                resolution = "720p"
            elif "480p" in filename:
                resolution = "480p"

            metadata_list.append(
                MediaMetadata(
                    file_path=path,
                    file_size=f["size"],
                    resolution=resolution,
                    video_codec="unknown",
                    audio_codec="unknown",
                    bitrate=0,
                    width=0,
                    height=0,
                    inode=f.get("inode", 0),
                    is_hardlink=f.get("is_hardlink", False),
                )
            )

        # Score and rank files
        ranked = scoring_engine.rank_duplicates(metadata_list, custom_rules)

        # Create duplicate set
        dup_set = DuplicateSet(
            plex_item_id=f"dev-{key}",
            title=title,
            media_type=media_type,
            status=DuplicateStatus.PENDING,
            space_to_reclaim=0,
        )
        db.add(dup_set)
        await db.flush()

        # Create duplicate files
        space_to_reclaim = 0
        for metadata, score, keep in ranked:
            from app.models.duplicate import DuplicateFile

            dup_file = DuplicateFile(
                set_id=dup_set.id,
                file_path=metadata.file_path,
                file_size=metadata.file_size,
                score=score,
                keep=keep,
                file_metadata=json.dumps(
                    {
                        "resolution": metadata.resolution,
                        "video_codec": metadata.video_codec,
                        "audio_codec": metadata.audio_codec,
                    }
                ),
                inode=metadata.inode,
                is_hardlink=metadata.is_hardlink,
            )
            db.add(dup_file)
            total_files += 1

            if not keep:
                space_to_reclaim += metadata.file_size

        dup_set.space_to_reclaim = space_to_reclaim
        sets_created += 1
        logger.info(f"[DEV] Created set '{title}' with {len(ranked)} files")

    await db.commit()

    # Get total sets count
    result = await db.execute(
        select(func.count(DuplicateSet.id)).where(
            DuplicateSet.status == DuplicateStatus.PENDING
        )
    )
    total_sets = result.scalar() or 0

    logger.info(
        f"[DEV] Scan complete: {sets_created} sets created, {total_files} files"
    )

    return ScanResponse(
        success=True,
        message=f"Dev scan complete: {sets_created} sets created",
        duplicates_found=total_files,
        sets_created=sets_created,
        sets_updated=0,
        sets_removed=0,
        total_sets=total_sets,
    )
