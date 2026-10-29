"""
Tests for database models
"""

import pytest
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import Config, DuplicateSet, DuplicateFile, ScoringRule
from app.models.duplicate import DuplicateStatus, MediaType
from app.models.scoring_rule import RuleType


@pytest.mark.asyncio
async def test_config_model(test_db: AsyncSession):
    """Test Config model CRUD operations"""
    # Create
    config = Config(key="test_key", value="test_value")
    test_db.add(config)
    await test_db.commit()
    await test_db.refresh(config)

    assert config.id is not None
    assert config.key == "test_key"
    assert config.value == "test_value"
    assert config.updated_at is not None

    # Read
    result = await test_db.execute(select(Config).where(Config.key == "test_key"))
    fetched_config = result.scalar_one_or_none()
    assert fetched_config is not None
    assert fetched_config.value == "test_value"

    # Update
    fetched_config.value = "updated_value"
    await test_db.commit()
    await test_db.refresh(fetched_config)
    assert fetched_config.value == "updated_value"

    # Delete
    await test_db.delete(fetched_config)
    await test_db.commit()
    result = await test_db.execute(select(Config).where(Config.key == "test_key"))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_duplicate_set_model(test_db: AsyncSession, create_duplicate_set):
    """Test DuplicateSet model"""
    dup_set = await create_duplicate_set(
        item_id="12345",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.PENDING,
        space_to_reclaim=5000000000,
    )

    assert dup_set.id is not None
    assert dup_set.title == "Test Movie"
    assert dup_set.media_type == MediaType.MOVIE
    assert dup_set.status == DuplicateStatus.PENDING
    assert dup_set.found_at is not None
    assert dup_set.space_to_reclaim == 5000000000


@pytest.mark.asyncio
async def test_duplicate_file_model(
    test_db: AsyncSession, create_duplicate_set, create_duplicate_file
):
    """Test DuplicateFile model"""
    dup_set = await create_duplicate_set()

    # Create duplicate file
    metadata = json.dumps(
        {
            "resolution": "1080p",
            "video_codec": "H.264",
            "audio_codec": "AAC",
            "bitrate": 5000,
        }
    )

    dup_file = await create_duplicate_file(
        set_id=dup_set.id,
        file_path="/media/movies/Test Movie (2023) 1080p.mkv",
        file_size=2000000000,
        score=100,
        keep=True,
        file_metadata=metadata,
    )

    assert dup_file.id is not None
    assert dup_file.set_id == dup_set.id
    assert dup_file.file_size == 2000000000
    assert dup_file.score == 100
    assert dup_file.keep is True
    assert dup_file.file_metadata == metadata


@pytest.mark.asyncio
async def test_duplicate_relationship(
    test_db: AsyncSession, create_duplicate_set, create_duplicate_file
):
    """Test relationship between DuplicateSet and DuplicateFile"""
    dup_set = await create_duplicate_set()

    # Create multiple files
    await create_duplicate_file(
        set_id=dup_set.id,
        file_path="/media/movies/Test Movie 1080p.mkv",
        file_size=2000000000,
        score=100,
        keep=True,
    )
    await create_duplicate_file(
        set_id=dup_set.id,
        file_path="/media/movies/Test Movie 720p.mkv",
        file_size=1000000000,
        score=50,
        keep=False,
    )

    # Fetch the duplicate set with files using selectinload

    result = await test_db.execute(
        select(DuplicateSet)
        .where(DuplicateSet.id == dup_set.id)
        .options(selectinload(DuplicateSet.files))
    )
    fetched_set = result.scalar_one()

    # Check relationship
    assert len(fetched_set.files) == 2
    assert any(f.file_path.endswith("1080p.mkv") for f in fetched_set.files)
    assert any(f.file_path.endswith("720p.mkv") for f in fetched_set.files)


@pytest.mark.asyncio
async def test_deletion_history_model(
    test_db: AsyncSession,
    create_duplicate_set,
    create_duplicate_file,
    create_deletion_history,
):
    """Test DeletionHistory model"""
    dup_set = await create_duplicate_set()
    dup_file = await create_duplicate_file(set_id=dup_set.id)

    # Create deletion history
    history = await create_deletion_history(
        file_id=dup_file.id,
        deleted_from_qbit=True,
        deleted_from_arr=True,
        deleted_from_disk=True,
        media_server_refreshed=True,
        qbit_torrent_hash="abc123",
        arr_type="radarr",
    )

    assert history.id is not None
    assert history.duplicate_file_id == dup_file.id
    assert history.deleted_at is not None
    assert history.is_complete is True
    assert history.qbit_torrent_hash == "abc123"
    assert history.arr_type == "radarr"


@pytest.mark.asyncio
async def test_deletion_history_incomplete(
    test_db: AsyncSession,
    create_duplicate_set,
    create_duplicate_file,
    create_deletion_history,
):
    """Test DeletionHistory is_complete property when deletion fails"""
    dup_set = await create_duplicate_set()
    dup_file = await create_duplicate_file(set_id=dup_set.id)

    # Create history with error
    history = await create_deletion_history(
        file_id=dup_file.id,
        deleted_from_qbit=True,
        deleted_from_arr=False,
        deleted_from_disk=False,
        media_server_refreshed=False,
        error="Failed to delete from Radarr",
    )

    assert history.is_complete is False


@pytest.mark.asyncio
async def test_scoring_rule_model(test_db):
    """Test ScoringRule model"""
    rule = ScoringRule(
        rule_type=RuleType.FILENAME_PATTERN,
        pattern=r".*REMUX.*",
        score_modifier=50,
        enabled=True,
        description="Bonus points for REMUX releases",
    )
    test_db.add(rule)
    await test_db.commit()
    await test_db.refresh(rule)

    assert rule.id is not None
    assert rule.rule_type == RuleType.FILENAME_PATTERN
    assert rule.pattern == r".*REMUX.*"
    assert rule.score_modifier == 50
    assert rule.enabled is True
    assert rule.created_at is not None


@pytest.mark.asyncio
async def test_cascade_delete(
    test_db: AsyncSession, create_duplicate_set, create_duplicate_file
):
    """Test cascade delete from DuplicateSet to DuplicateFile"""
    dup_set = await create_duplicate_set()
    dup_file = await create_duplicate_file(set_id=dup_set.id)

    # Delete the duplicate set
    await test_db.delete(dup_set)
    await test_db.commit()

    # Check that the file was also deleted
    result = await test_db.execute(
        select(DuplicateFile).where(DuplicateFile.id == dup_file.id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_duplicate_status_enum(test_db: AsyncSession, create_duplicate_set):
    """Test DuplicateStatus enum values"""
    dup_set = await create_duplicate_set(status=DuplicateStatus.APPROVED)

    assert dup_set.status == DuplicateStatus.APPROVED

    # Change status
    dup_set.status = DuplicateStatus.PROCESSED
    await test_db.commit()
    await test_db.refresh(dup_set)

    assert dup_set.status == DuplicateStatus.PROCESSED
