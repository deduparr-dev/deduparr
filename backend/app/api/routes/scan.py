"""
Scan routes for triggering and managing duplicate detection
"""

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.models import Config, DuplicateSet, ScoringRule
from app.models.duplicate import DuplicateStatus, MediaType
from app.services.deletion_pipeline import DeletionPipeline
from app.services.plex_service import PlexService
from app.services.scan_helpers import (
    collect_media_metadata,
    validate_duplicate_files,
    create_duplicate_set,
    cleanup_stale_set,
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
    sets_already_exist: int
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
    total_sets_existing = 0

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

                sets_created, sets_existing = await _process_duplicate_movies(
                    db, movie_dupes, scoring_engine, custom_rules
                )
                # Count actual media files, not Movie objects
                total_duplicates += sum(
                    len(movie.media)
                    for movies in movie_dupes.values()
                    for movie in movies
                )
                total_sets_created += sets_created
                total_sets_existing += sets_existing

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

                    sets_created, sets_existing = await _process_duplicate_episodes(
                        db, episode_dupes, scoring_engine, custom_rules
                    )
                    logger.info(
                        f"Processed episodes: {sets_created} created, {sets_existing} existing"
                    )

                    # Count actual media files, not Episode objects
                    total_duplicates += sum(
                        len(episode.media)
                        for episodes in episode_dupes.values()
                        for episode in episodes
                    )
                    total_sets_created += sets_created
                    total_sets_existing += sets_existing
                except Exception as e:
                    logger.error(
                        f"Could not scan episodes in {library_name}: {e}", exc_info=True
                    )
            else:
                logger.warning(
                    f"Unsupported library type '{library.type}' for '{library_name}' - skipping"
                )

        await db.commit()

        return ScanResponse(
            success=True,
            message=f"Scan completed for {len(scan_request.library_names)} libraries",
            duplicates_found=total_duplicates,
            sets_created=total_sets_created,
            sets_already_exist=total_sets_existing,
            total_sets=total_sets_created + total_sets_existing,
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
) -> tuple[int, int]:
    """Process and store duplicate movie sets

    Returns:
        tuple[int, int]: (sets_created, sets_already_existing)
    """
    sets_created = 0
    sets_existing = 0

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
            continue

        if existing_set:
            logger.info(f"Duplicate set already exists for movie: {first_movie.title}")
            sets_existing += 1
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

    return sets_created, sets_existing


async def _process_duplicate_episodes(
    db: AsyncSession,
    duplicates: dict,
    scoring_engine: ScoringEngine,
    custom_rules: List[dict],
) -> tuple[int, int]:
    """Process and store duplicate episode sets

    Returns:
        tuple[int, int]: (sets_created, sets_already_existing)
    """
    sets_created = 0
    sets_existing = 0

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
            continue

        if existing_set:
            logger.info(
                f"Duplicate set already exists for episode: {first_episode.grandparentTitle} "
                f"S{first_episode.seasonNumber:02d}E{first_episode.episodeNumber:02d}"
            )
            sets_existing += 1
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

    return sets_created, sets_existing

    return sets_created, sets_existing


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
