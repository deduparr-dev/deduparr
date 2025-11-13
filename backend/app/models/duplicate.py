"""
Duplicate set and file models
"""

import enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base, utc_now


class DuplicateStatus(str, enum.Enum):
    """Status of a duplicate set"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSED = "processed"


class MediaType(str, enum.Enum):
    """Type of media"""

    MOVIE = "movie"
    EPISODE = "episode"


class DuplicateSet(Base):
    """Represents a set of duplicate media items"""

    __tablename__ = "duplicate_sets"

    id = Column(Integer, primary_key=True, index=True)
    # plex_item_id can be absent in some test fixtures and import flows; allow nullable
    plex_item_id = Column(String(255), nullable=True, index=True)
    title = Column(String(500), nullable=False)
    media_type = Column(SQLEnum(MediaType), nullable=False)
    found_at = Column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    status = Column(
        SQLEnum(DuplicateStatus),
        default=DuplicateStatus.PENDING,
        nullable=False,
        index=True,
    )
    space_to_reclaim = Column(BigInteger, default=0)

    # Relationships
    files = relationship(
        "DuplicateFile", back_populates="duplicate_set", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_status_found_at", "status", "found_at"),)

    def __repr__(self):
        return f"<DuplicateSet(id={self.id}, title={self.title}, status={self.status})>"


class DuplicateFile(Base):
    """Represents an individual file in a duplicate set"""

    __tablename__ = "duplicate_files"

    id = Column(Integer, primary_key=True, index=True)
    set_id = Column(
        Integer,
        ForeignKey("duplicate_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path = Column(Text, nullable=False, index=True)
    file_size = Column(BigInteger, nullable=False)
    score = Column(Integer, default=0, nullable=False)
    keep = Column(Boolean, default=False, nullable=False)

    # Hardlink detection fields
    inode = Column(BigInteger, nullable=True, index=True)
    is_hardlink = Column(Boolean, default=False, nullable=False)

    # File metadata stored as JSON/JSONB (resolution, codecs, etc.)
    # Using Text for SQLite, PostgreSQL will use JSONB
    file_metadata = Column(Text, nullable=True)

    # Relationships
    duplicate_set = relationship("DuplicateSet", back_populates="files")
    deletion_history = relationship(
        "DeletionHistory", back_populates="duplicate_file", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_set_file", "set_id", "file_path"),)

    def __repr__(self):
        return f"<DuplicateFile(id={self.id}, path={self.file_path[:50]}, score={self.score}, keep={self.keep})>"
