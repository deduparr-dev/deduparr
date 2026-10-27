"""
Statistics service for dashboard
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.duplicate import DuplicateFile, DuplicateSet, DuplicateStatus
from app.models.history import DeletionHistory


class DashboardStats(BaseModel):
    """Dashboard statistics structure"""

    model_config = ConfigDict(from_attributes=True)

    total_duplicates: int  # Number of unique items (movies/episodes) with duplicates
    total_duplicate_files: int  # Total number of duplicate files across all sets
    pending_duplicates: int
    approved_duplicates: int
    processed_duplicates: int
    space_to_reclaim: int
    total_deletions: int
    successful_deletions: int
    failed_deletions: int


class RecentActivity(BaseModel):
    """Recent activity entry structure"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    media_type: str
    status: str
    found_at: datetime
    space_to_reclaim: int

    @field_serializer("found_at")
    def serialize_found_at(self, dt: datetime) -> str:
        """Serialize datetime to ISO format with Z suffix for UTC"""
        if dt.tzinfo is None:
            # If naive, assume UTC
            from datetime import timezone

            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")


class DeletionActivity(BaseModel):
    """Recent deletion activity structure"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    file_path: str
    deleted_at: datetime
    is_complete: bool
    error: str | None

    @field_serializer("deleted_at")
    def serialize_deleted_at(self, dt: datetime) -> str:
        """Serialize datetime to ISO format with Z suffix for UTC"""
        if dt.tzinfo is None:
            # If naive, assume UTC
            from datetime import timezone

            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")


class StatsService:
    """Service for retrieving dashboard statistics"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_dashboard_stats(self) -> DashboardStats:
        """Get comprehensive dashboard statistics"""
        total_duplicates = await self._count_duplicates()
        total_files = await self._count_duplicate_files()
        status_counts = await self._count_by_status()

        total_space = await self._sum_space_to_reclaim()
        deletion_counts = await self._count_deletions()

        return DashboardStats(
            total_duplicates=total_duplicates,
            total_duplicate_files=total_files,
            pending_duplicates=status_counts.get(DuplicateStatus.PENDING, 0),
            approved_duplicates=status_counts.get(DuplicateStatus.APPROVED, 0),
            processed_duplicates=status_counts.get(DuplicateStatus.PROCESSED, 0),
            space_to_reclaim=total_space,
            total_deletions=deletion_counts["total"],
            successful_deletions=deletion_counts["successful"],
            failed_deletions=deletion_counts["failed"],
        )

    async def get_recent_activity(self, limit: int = 10) -> list[RecentActivity]:
        """Get recent duplicate sets activity"""
        stmt = select(DuplicateSet).order_by(DuplicateSet.found_at.desc()).limit(limit)

        result = await self.db.execute(stmt)
        duplicate_sets = result.scalars().all()

        return [
            RecentActivity(
                id=ds.id,
                title=ds.title,
                media_type=ds.media_type.value,
                status=ds.status.value,
                found_at=ds.found_at,
                space_to_reclaim=ds.space_to_reclaim or 0,
            )
            for ds in duplicate_sets
        ]

    async def get_recent_deletions(self, limit: int = 10) -> list[DeletionActivity]:
        """Get recent deletion activity"""
        stmt = (
            select(DeletionHistory, DuplicateFile.file_path)
            .join(DuplicateFile, DeletionHistory.duplicate_file_id == DuplicateFile.id)
            .order_by(DeletionHistory.deleted_at.desc())
            .limit(limit)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            DeletionActivity(
                id=history.id,
                file_path=file_path,
                deleted_at=history.deleted_at,
                is_complete=history.is_complete,
                error=history.error,
            )
            for history, file_path in rows
        ]

    async def _count_duplicates(self) -> int:
        """Count total duplicate sets"""
        stmt = select(func.count()).select_from(DuplicateSet)
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def _count_duplicate_files(self) -> int:
        """Count total duplicate files across all sets"""
        stmt = select(func.count()).select_from(DuplicateFile)
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def _count_by_status(self) -> dict[DuplicateStatus, int]:
        """Count duplicate sets by status"""
        stmt = select(DuplicateSet.status, func.count(DuplicateSet.id)).group_by(
            DuplicateSet.status
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        return {status: count for status, count in rows}

    async def _sum_space_to_reclaim(self) -> int:
        """Sum total space that can be reclaimed from pending/approved duplicates"""
        stmt = select(func.sum(DuplicateSet.space_to_reclaim)).where(
            DuplicateSet.status.in_([DuplicateStatus.PENDING, DuplicateStatus.APPROVED])
        )

        result = await self.db.execute(stmt)
        total = result.scalar()
        return total or 0

    async def _count_deletions(self) -> dict[str, int]:
        """Count total, successful, and failed deletions"""
        total_stmt = select(func.count()).select_from(DeletionHistory)
        total_result = await self.db.execute(total_stmt)
        total = total_result.scalar() or 0

        successful_stmt = (
            select(func.count())
            .select_from(DeletionHistory)
            .where(
                DeletionHistory.deleted_from_qbit.is_(True),
                DeletionHistory.deleted_from_arr.is_(True),
                DeletionHistory.deleted_from_disk.is_(True),
                DeletionHistory.media_server_refreshed.is_(True),
                DeletionHistory.error.is_(None),
            )
        )
        successful_result = await self.db.execute(successful_stmt)
        successful = successful_result.scalar() or 0

        failed = total - successful

        return {"total": total, "successful": successful, "failed": failed}
