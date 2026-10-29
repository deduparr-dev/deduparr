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
        Whether the deletion succeeded: the file is gone.

        Anything else a stage reported, such as an unconfigured service or a
        failed media server refresh, is a note in error, as the deletion's own
        result treats it.
        """
        return bool(self.deleted_from_disk)
