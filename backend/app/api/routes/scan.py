"""
Scan routes for triggering and managing duplicate detection
"""

import json
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.models import DuplicateSet, ScoringRule
from app.models.duplicate import DuplicateStatus, MediaType, encode_inode
from app.services.deletion.pipeline import DeletionPipeline
from app.services.deletion.scheduled import ScheduledDeletionService
from app.services.scan.disk_scan import (
    DiskScanConfig,
    DiskScanService,
    DuplicateDetectionStrategy,
    HardlinkHandling,
)
from app.services.media_server import (
    MediaServer,
    get_media_servers,
)
from app.services.scan.runner import run_scan
from app.services.scan.scoring_engine import ScoringEngine

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
    # Which server reported this set, so the UI can tell two servers apart
    media_server: str
    item_id: str
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


class DeleteAllResponse(BaseModel):
    """Response from deleting every pending duplicate set"""

    success: bool
    message: str
    dry_run: bool
    sets_processed: int
    files_deleted: int
    errors: List[str] = []


async def get_configured_media_servers(db: AsyncSession) -> List[MediaServer]:
    """Every media server this instance is set up against, or a 400."""
    servers = await get_media_servers(db)
    if not servers:
        raise HTTPException(
            status_code=400,
            detail="No media server configured. Complete setup first.",
        )
    return servers


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
    Scan the named libraries for duplicates.

    Every configured media server is scanned, so an instance running both Plex
    and Jellyfin over the same media covers both.
    """
    await get_configured_media_servers(db)
    totals = await run_scan(db, scan_request.library_names)

    total_result = await db.execute(
        select(func.count(DuplicateSet.id)).where(
            DuplicateSet.status == DuplicateStatus.PENDING
        )
    )

    return ScanResponse(
        success=True,
        message=f"Scan completed for {len(scan_request.library_names)} libraries",
        duplicates_found=totals.duplicates_found,
        sets_created=totals.sets_created,
        sets_updated=totals.sets_updated,
        sets_removed=totals.sets_removed,
        total_sets=total_result.scalar() or 0,
    )


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
            media_server=dup_set.media_server,
            item_id=dup_set.item_id,
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


@router.post("/duplicates/delete-all", response_model=DeleteAllResponse)
async def delete_all_duplicate_sets(
    delete_request: DeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete the non-kept files of every PENDING duplicate set in one pass.

    Which file survives is whatever the scan already marked as keep, so the
    criteria are the scoring rules and the optional *arr quality profile
    preference. Runs the same pipeline as the scheduled deletion.

    Args:
        delete_request: Contains dry_run flag (default True for safety)
    """
    summary = await ScheduledDeletionService(db).run_scheduled_deletion(
        dry_run=delete_request.dry_run,
        send_email=False,
    )

    verb = "Would delete" if summary["dry_run"] else "Deleted"
    message = (
        f"{'[DRY-RUN] ' if summary['dry_run'] else ''}{verb} "
        f"{summary['files_deleted']} file(s) across {summary['sets_processed']} duplicate set(s)"
    )

    return DeleteAllResponse(
        success=not summary["errors"],
        message=message,
        dry_run=summary["dry_run"],
        sets_processed=summary["sets_processed"],
        files_deleted=summary["files_deleted"],
        errors=summary["errors"],
    )


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
        from app.services.scan.helpers import MediaMetadata

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
            media_server="disk",
            item_id=f"dev-{key}",
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
                inode=encode_inode(metadata.inode),
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
