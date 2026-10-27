"""
Deletion history model for audit trail
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import relationship

from app.core.database import Base, utc_now


class DeletionHistory(Base):
    """Tracks the deletion process for each file"""

    __tablename__ = "deletion_history"

    id = Column(Integer, primary_key=True, index=True)
    duplicate_file_id = Column(
        Integer,
        ForeignKey("duplicate_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    deleted_at = Column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    # Deletion stages
    deleted_from_qbit = Column(Boolean, default=False, nullable=False)
    deleted_from_arr = Column(Boolean, default=False, nullable=False)
    deleted_from_disk = Column(Boolean, default=False, nullable=False)
    media_server_refreshed = Column(Boolean, default=False, nullable=False)

    # Error tracking
    error = Column(Text, nullable=True)

    # Additional metadata
    qbit_torrent_hash = Column(Text, nullable=True)
    arr_type = Column(Text, nullable=True)  # 'radarr' or 'sonarr'
    arr_media_id = Column(Integer, nullable=True)  # movie_id or series_id for rescan

    # Relationships
    duplicate_file = relationship("DuplicateFile", back_populates="deletion_history")

    __table_args__ = (Index("idx_deleted_at_desc", "deleted_at"),)

    def __repr__(self):
        return f"<DeletionHistory(id={self.id}, file_id={self.duplicate_file_id}, deleted_at={self.deleted_at})>"

    @property
    def is_complete(self) -> bool:
        """
        Check if deletion was successful

        A deletion is considered successful if the critical stages completed:
        1. File deleted from disk (deleted_from_disk=True)
        2. Media server metadata refreshed (media_server_refreshed=True)
        3. No unacceptable errors occurred

        The arr/qBit stages are optional - orphaned files won't be tracked in
        those services, so we only check that critical stages succeeded.
        """
        # Critical stages must always succeed
        if not (self.deleted_from_disk and self.media_server_refreshed):
            return False

        # If there's an error, check if it's only about unconfigured services
        if self.error:
            # Errors about unconfigured services are acceptable
            acceptable_errors = [
                "qBittorrent not configured",
                "Radarr not configured",
                "Sonarr not configured",
            ]

            # Check if all errors are acceptable
            error_parts = [e.strip() for e in self.error.split(";")]
            has_unacceptable_error = any(
                not any(acceptable in error_part for acceptable in acceptable_errors)
                for error_part in error_parts
            )

            if has_unacceptable_error:
                # Has a real error, not just missing config
                return False

        # Critical stages succeeded and no unacceptable errors
        return True
