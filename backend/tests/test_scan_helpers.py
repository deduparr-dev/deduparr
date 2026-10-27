"""Tests for scan helper functions"""

import json
import logging
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import DuplicateFile, DuplicateSet, MediaType
from app.models.duplicate import decode_inode
from app.services.scan.helpers import (
    cleanup_stale_set,
    create_duplicate_set,
    validate_duplicate_files,
    verify_and_update_existing_set,
)
from app.services.scan.scoring_engine import MediaMetadata, ScoringEngine


@pytest.mark.asyncio
async def test_validate_duplicate_files_less_than_two():
    """Test validation rejects sets with fewer than 2 files"""
    files = [
        MediaMetadata(
            file_path="/media/movie.mkv",
            file_size=1000000000,
            resolution="1080p",
            video_codec="h264",
            audio_codec="aac",
            bitrate=5000,
            width=1920,
            height=1080,
            inode=12345,
            is_hardlink=False,
        )
    ]
    mock_logger = Mock()

    result = validate_duplicate_files(files, "Test Movie", mock_logger)

    assert result == "Only 1 non-sample file(s) remaining, need at least 2"


@pytest.mark.asyncio
async def test_validate_duplicate_files_with_missing():
    """Test validation rejects sets with missing files"""
    files = [
        MediaMetadata(
            file_path="/media/movie1.mkv",
            file_size=1000000000,
            resolution="1080p",
            video_codec="h264",
            audio_codec="aac",
            bitrate=5000,
            width=1920,
            height=1080,
            inode=12345,
            is_hardlink=False,
        ),
        MediaMetadata(
            file_path="/media/movie2.mkv",
            file_size=2000000000,
            resolution="2160p",
            video_codec="hevc",
            audio_codec="aac",
            bitrate=15000,
            width=3840,
            height=2160,
            inode=None,  # Missing file
            is_hardlink=False,
        ),
    ]
    mock_logger = Mock()

    result = validate_duplicate_files(files, "Test Movie", mock_logger)

    assert result == "Has missing files"


@pytest.mark.asyncio
async def test_validate_duplicate_files_all_hardlinks():
    """Test validation rejects sets where all files are hardlinks of same file"""
    files = [
        MediaMetadata(
            file_path="/media/movie1.mkv",
            file_size=1000000000,
            resolution="1080p",
            video_codec="h264",
            audio_codec="aac",
            bitrate=5000,
            width=1920,
            height=1080,
            inode=12345,
            is_hardlink=True,
        ),
        MediaMetadata(
            file_path="/media/movie2.mkv",
            file_size=1000000000,
            resolution="1080p",
            video_codec="h264",
            audio_codec="aac",
            bitrate=5000,
            width=1920,
            height=1080,
            inode=12345,  # Same inode
            is_hardlink=True,
        ),
    ]
    mock_logger = Mock()

    result = validate_duplicate_files(files, "Test Movie", mock_logger)

    assert result == "All files are hardlinks, not true duplicates"


@pytest.mark.asyncio
async def test_validate_duplicate_files_valid():
    """Test validation passes for valid duplicate set"""
    files = [
        MediaMetadata(
            file_path="/media/movie1.mkv",
            file_size=1000000000,
            resolution="1080p",
            video_codec="h264",
            audio_codec="aac",
            bitrate=5000,
            width=1920,
            height=1080,
            inode=12345,
            is_hardlink=False,
        ),
        MediaMetadata(
            file_path="/media/movie2.mkv",
            file_size=2000000000,
            resolution="2160p",
            video_codec="hevc",
            audio_codec="aac",
            bitrate=15000,
            width=3840,
            height=2160,
            inode=67890,
            is_hardlink=False,
        ),
    ]
    mock_logger = Mock()

    result = validate_duplicate_files(files, "Test Movie", mock_logger)

    assert result is None


@pytest.mark.asyncio
async def test_create_duplicate_set(test_db: AsyncSession):
    """Test creating a duplicate set"""
    files = [
        MediaMetadata(
            file_path="/media/movie1.mkv",
            file_size=1000000000,
            resolution="1080p",
            video_codec="h264",
            audio_codec="aac",
            bitrate=5000,
            width=1920,
            height=1080,
            inode=12345,
            is_hardlink=False,
        ),
        MediaMetadata(
            file_path="/media/movie2.mkv",
            file_size=2000000000,
            resolution="2160p",
            video_codec="hevc",
            audio_codec="aac",
            bitrate=15000,
            width=3840,
            height=2160,
            inode=67890,
            is_hardlink=False,
        ),
    ]
    mock_logger = Mock()
    scoring_engine = ScoringEngine()

    await create_duplicate_set(
        test_db,
        media_server="plex",
        item_id="12345",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        files_metadata=files,
        scoring_engine=scoring_engine,
        custom_rules=[],
        logger_inst=mock_logger,
    )

    # Verify duplicate set was created
    result = await test_db.execute(
        select(DuplicateSet)
        .options(selectinload(DuplicateSet.files))
        .where(DuplicateSet.item_id == "12345")
    )
    dup_set = result.scalar_one()

    assert dup_set is not None
    assert dup_set.title == "Test Movie"
    assert dup_set.media_type == MediaType.MOVIE
    assert len(dup_set.files) == 2
    assert dup_set.space_to_reclaim > 0

    # Verify files were created with proper metadata
    file1 = next(f for f in dup_set.files if f.file_path == "/media/movie1.mkv")
    assert file1.file_size == 1000000000
    assert file1.inode == "12345"
    assert file1.is_hardlink is False

    file_metadata = json.loads(file1.file_metadata)
    assert file_metadata["resolution"] == "1080p"
    assert file_metadata["video_codec"] == "h264"


@pytest.mark.asyncio
async def test_create_duplicate_set_with_large_inodes(test_db: AsyncSession):
    """
    Inodes above SQLite's signed 64-bit INTEGER range must persist.

    Filesystems such as mergerfs report inode numbers larger than 2**63-1.
    Binding those as integers raises "Python int too large to convert to
    SQLite INTEGER", which aborted the whole scan.
    """
    large_inode_a = 14141372941677636890
    large_inode_b = 11140823705740417837
    assert large_inode_a > 2**63 - 1

    files = [
        MediaMetadata(
            file_path="/movies/9 Songs (2004) a/9 Songs (2004).mp4",
            file_size=1000000000,
            resolution="1080p",
            video_codec="h264",
            audio_codec="aac",
            bitrate=5000,
            width=1920,
            height=1080,
            inode=large_inode_a,
            is_hardlink=False,
        ),
        MediaMetadata(
            file_path="/movies/9 Songs (2004)/9 Songs (2004).mp4",
            file_size=2000000000,
            resolution="2160p",
            video_codec="hevc",
            audio_codec="aac",
            bitrate=15000,
            width=3840,
            height=2160,
            inode=large_inode_b,
            is_hardlink=False,
        ),
    ]

    await create_duplicate_set(
        test_db,
        media_server="plex",
        item_id="9songs",
        title="9 Songs",
        media_type=MediaType.MOVIE,
        files_metadata=files,
        scoring_engine=ScoringEngine(),
        custom_rules=[],
        logger_inst=Mock(),
    )

    result = await test_db.execute(
        select(DuplicateSet)
        .options(selectinload(DuplicateSet.files))
        .where(DuplicateSet.item_id == "9songs")
    )
    dup_set = result.scalar_one()

    stored = {f.file_path: f.inode for f in dup_set.files}
    assert stored["/movies/9 Songs (2004) a/9 Songs (2004).mp4"] == str(large_inode_a)
    assert stored["/movies/9 Songs (2004)/9 Songs (2004).mp4"] == str(large_inode_b)

    # Values round-trip back to the original ints without loss of precision
    assert (
        decode_inode(stored["/movies/9 Songs (2004) a/9 Songs (2004).mp4"])
        == large_inode_a
    )


@pytest.mark.asyncio
async def test_cleanup_stale_set(test_db: AsyncSession):
    """Test cleanup of stale duplicate set"""
    # Create a duplicate set
    dup_set = DuplicateSet(
        item_id="12345",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        status="pending",
        space_to_reclaim=1000000000,
    )
    test_db.add(dup_set)
    await test_db.flush()

    # Add files
    dup_file = DuplicateFile(
        set_id=dup_set.id,
        file_path="/media/movie.mkv",
        file_size=1000000000,
        score=100,
        keep=True,
        file_metadata="{}",
    )
    test_db.add(dup_file)
    await test_db.commit()

    # Cleanup the set
    mock_logger = Mock()
    await cleanup_stale_set(test_db, dup_set, "has missing files", mock_logger)

    # Verify set was deleted
    result = await test_db.execute(
        select(DuplicateSet).where(DuplicateSet.id == dup_set.id)
    )
    assert result.scalar_one_or_none() is None

    # Verify log message
    mock_logger.info.assert_any_call(
        "Cleaning up stale duplicate set for movie: Test Movie (has missing files)"
    )


@pytest.mark.asyncio
async def test_cleanup_stale_set_no_set():
    """Test cleanup when no set exists (should be no-op)"""
    mock_db = Mock()
    mock_logger = Mock()

    await cleanup_stale_set(mock_db, None, "some reason", mock_logger)

    # Should not call delete or log anything
    mock_db.delete.assert_not_called()
    mock_logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_verify_and_update_existing_set_removes_stale_files(
    test_db: AsyncSession,
):
    """Test that externally removed files are detected and removed from DB"""
    from app.services.scan.helpers import verify_and_update_existing_set

    # Create a duplicate set with 3 files
    dup_set = DuplicateSet(
        item_id="12345",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        status="pending",
        space_to_reclaim=3000000000,
    )
    test_db.add(dup_set)
    await test_db.flush()

    # Add 3 files to the set
    for i, (path, size, score, keep) in enumerate(
        [
            ("/media/movie_4k.mkv", 2000000000, 100, True),
            ("/media/movie_1080p.mkv", 1000000000, 50, False),
            ("/media/movie_720p.mkv", 500000000, 25, False),
        ]
    ):
        dup_file = DuplicateFile(
            set_id=dup_set.id,
            file_path=path,
            file_size=size,
            score=score,
            keep=keep,
            file_metadata='{"resolution": "1080p", "video_codec": "h264"}',
            inode=10000 + i,
            is_hardlink=False,
        )
        test_db.add(dup_file)
    await test_db.commit()

    # Simulate Plex now only reporting 2 files (720p was deleted externally)
    current_metadata = [
        MediaMetadata(
            file_path="/media/movie_4k.mkv",
            file_size=2000000000,
            resolution="2160p",
            video_codec="hevc",
            audio_codec="aac",
            bitrate=15000,
            width=3840,
            height=2160,
            inode=10000,
            is_hardlink=False,
        ),
        MediaMetadata(
            file_path="/media/movie_1080p.mkv",
            file_size=1000000000,
            resolution="1080p",
            video_codec="h264",
            audio_codec="aac",
            bitrate=5000,
            width=1920,
            height=1080,
            inode=10001,
            is_hardlink=False,
        ),
    ]

    scoring_engine = ScoringEngine()
    mock_logger = Mock()

    # Reload the set with files relationship
    from sqlalchemy.orm import selectinload

    result = await test_db.execute(
        select(DuplicateSet)
        .options(selectinload(DuplicateSet.files))
        .where(DuplicateSet.id == dup_set.id)
    )
    loaded_set = result.scalar_one()

    set_valid, files_removed = await verify_and_update_existing_set(
        test_db,
        loaded_set,
        current_metadata,
        scoring_engine,
        [],
        mock_logger,
    )

    assert set_valid is True
    assert files_removed == 1

    # Verify only 2 files remain
    result = await test_db.execute(
        select(DuplicateFile).where(DuplicateFile.set_id == dup_set.id)
    )
    remaining_files = result.scalars().all()
    assert len(remaining_files) == 2

    # Verify the 720p file was removed
    remaining_paths = {f.file_path for f in remaining_files}
    assert "/media/movie_720p.mkv" not in remaining_paths
    assert "/media/movie_4k.mkv" in remaining_paths
    assert "/media/movie_1080p.mkv" in remaining_paths


@pytest.mark.asyncio
async def test_verify_and_update_existing_set_removes_set_when_insufficient_files(
    test_db: AsyncSession,
):
    """Test that set is removed when fewer than 2 files remain"""
    from app.services.scan.helpers import verify_and_update_existing_set

    # Create a duplicate set with 2 files
    dup_set = DuplicateSet(
        item_id="12345",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        status="pending",
        space_to_reclaim=1000000000,
    )
    test_db.add(dup_set)
    await test_db.flush()

    # Add 2 files
    for i, path in enumerate(["/media/movie_4k.mkv", "/media/movie_1080p.mkv"]):
        dup_file = DuplicateFile(
            set_id=dup_set.id,
            file_path=path,
            file_size=1000000000,
            score=100 - i * 50,
            keep=(i == 0),
            file_metadata='{"resolution": "1080p"}',
            inode=10000 + i,
            is_hardlink=False,
        )
        test_db.add(dup_file)
    await test_db.commit()

    # Simulate Plex now only reporting 1 file (only 4k remains)
    current_metadata = [
        MediaMetadata(
            file_path="/media/movie_4k.mkv",
            file_size=2000000000,
            resolution="2160p",
            video_codec="hevc",
            audio_codec="aac",
            bitrate=15000,
            width=3840,
            height=2160,
            inode=10000,
            is_hardlink=False,
        ),
    ]

    scoring_engine = ScoringEngine()
    mock_logger = Mock()

    # Reload the set with files relationship
    from sqlalchemy.orm import selectinload

    result = await test_db.execute(
        select(DuplicateSet)
        .options(selectinload(DuplicateSet.files))
        .where(DuplicateSet.id == dup_set.id)
    )
    loaded_set = result.scalar_one()
    set_id = loaded_set.id

    set_valid, files_removed = await verify_and_update_existing_set(
        test_db,
        loaded_set,
        current_metadata,
        scoring_engine,
        [],
        mock_logger,
    )

    assert set_valid is False
    assert files_removed == 1

    # Verify the set was removed entirely
    result = await test_db.execute(
        select(DuplicateSet).where(DuplicateSet.id == set_id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_verify_and_update_existing_set_adds_new_files(test_db: AsyncSession):
    """Test that new files appearing in Plex are added to existing set"""
    from app.services.scan.helpers import verify_and_update_existing_set

    # Create a duplicate set with 2 files
    dup_set = DuplicateSet(
        item_id="12345",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        status="pending",
        space_to_reclaim=1000000000,
    )
    test_db.add(dup_set)
    await test_db.flush()

    # Add 2 files
    for i, (path, score) in enumerate(
        [("/media/movie_4k.mkv", 100), ("/media/movie_1080p.mkv", 50)]
    ):
        dup_file = DuplicateFile(
            set_id=dup_set.id,
            file_path=path,
            file_size=1000000000,
            score=score,
            keep=(i == 0),
            file_metadata='{"resolution": "1080p", "video_codec": "h264"}',
            inode=10000 + i,
            is_hardlink=False,
        )
        test_db.add(dup_file)
    await test_db.commit()

    # Simulate Plex now reporting 3 files (a new 720p was downloaded)
    current_metadata = [
        MediaMetadata(
            file_path="/media/movie_4k.mkv",
            file_size=2000000000,
            resolution="2160p",
            video_codec="hevc",
            audio_codec="aac",
            bitrate=15000,
            width=3840,
            height=2160,
            inode=10000,
            is_hardlink=False,
        ),
        MediaMetadata(
            file_path="/media/movie_1080p.mkv",
            file_size=1000000000,
            resolution="1080p",
            video_codec="h264",
            audio_codec="aac",
            bitrate=5000,
            width=1920,
            height=1080,
            inode=10001,
            is_hardlink=False,
        ),
        MediaMetadata(
            file_path="/media/movie_720p.mkv",
            file_size=500000000,
            resolution="720p",
            video_codec="h264",
            audio_codec="aac",
            bitrate=2500,
            width=1280,
            height=720,
            inode=10002,
            is_hardlink=False,
        ),
    ]

    scoring_engine = ScoringEngine()
    mock_logger = Mock()

    # Reload the set with files relationship
    from sqlalchemy.orm import selectinload

    result = await test_db.execute(
        select(DuplicateSet)
        .options(selectinload(DuplicateSet.files))
        .where(DuplicateSet.id == dup_set.id)
    )
    loaded_set = result.scalar_one()

    set_valid, files_removed = await verify_and_update_existing_set(
        test_db,
        loaded_set,
        current_metadata,
        scoring_engine,
        [],
        mock_logger,
    )

    assert set_valid is True
    assert files_removed == 0

    # Verify 3 files now exist
    result = await test_db.execute(
        select(DuplicateFile).where(DuplicateFile.set_id == dup_set.id)
    )
    all_files = result.scalars().all()
    assert len(all_files) == 3

    # Verify the new file was added
    file_paths = {f.file_path for f in all_files}
    assert "/media/movie_720p.mkv" in file_paths


@pytest.mark.asyncio
async def test_verify_and_update_existing_set_no_changes(test_db: AsyncSession):
    """Test that no changes are made when files match exactly"""
    from app.services.scan.helpers import verify_and_update_existing_set

    # Create a duplicate set with 2 files
    dup_set = DuplicateSet(
        item_id="12345",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        status="pending",
        space_to_reclaim=1000000000,
    )
    test_db.add(dup_set)
    await test_db.flush()

    # Add 2 files
    for i, path in enumerate(["/media/movie_4k.mkv", "/media/movie_1080p.mkv"]):
        dup_file = DuplicateFile(
            set_id=dup_set.id,
            file_path=path,
            file_size=1000000000,
            score=100 - i * 50,
            keep=(i == 0),
            file_metadata='{"resolution": "1080p", "video_codec": "h264"}',
            inode=10000 + i,
            is_hardlink=False,
        )
        test_db.add(dup_file)
    await test_db.commit()

    # Same files reported by Plex
    current_metadata = [
        MediaMetadata(
            file_path="/media/movie_4k.mkv",
            file_size=2000000000,
            resolution="2160p",
            video_codec="hevc",
            audio_codec="aac",
            bitrate=15000,
            width=3840,
            height=2160,
            inode=10000,
            is_hardlink=False,
        ),
        MediaMetadata(
            file_path="/media/movie_1080p.mkv",
            file_size=1000000000,
            resolution="1080p",
            video_codec="h264",
            audio_codec="aac",
            bitrate=5000,
            width=1920,
            height=1080,
            inode=10001,
            is_hardlink=False,
        ),
    ]

    scoring_engine = ScoringEngine()
    mock_logger = Mock()

    # Reload the set with files relationship
    from sqlalchemy.orm import selectinload

    result = await test_db.execute(
        select(DuplicateSet)
        .options(selectinload(DuplicateSet.files))
        .where(DuplicateSet.id == dup_set.id)
    )
    loaded_set = result.scalar_one()

    set_valid, files_removed = await verify_and_update_existing_set(
        test_db,
        loaded_set,
        current_metadata,
        scoring_engine,
        [],
        mock_logger,
    )

    assert set_valid is True
    assert files_removed == 0

    # Verify still 2 files
    result = await test_db.execute(
        select(DuplicateFile).where(DuplicateFile.set_id == dup_set.id)
    )
    all_files = result.scalars().all()
    assert len(all_files) == 2


async def _create_movie_set(test_db, files_metadata):
    await create_duplicate_set(
        test_db,
        "plex",
        "plex-1",
        "Film",
        MediaType.MOVIE,
        files_metadata,
        ScoringEngine(),
        [],
        logging.getLogger("test"),
    )
    await test_db.commit()
    result = await test_db.execute(
        select(DuplicateSet).options(selectinload(DuplicateSet.files))
    )
    return result.scalar_one()


@pytest.mark.asyncio
async def test_verify_set_reranks_when_a_better_file_appears(test_db):
    """A new file joins an existing set: exactly one file is kept, the best one"""
    hd = MediaMetadata(
        file_path="/m/Film.1080p.mkv", file_size=4000, resolution="1080p"
    )
    sd = MediaMetadata(file_path="/m/Film.720p.mkv", file_size=2000, resolution="720p")
    uhd = MediaMetadata(
        file_path="/m/Film.2160p.mkv", file_size=9000, resolution="2160p"
    )
    dup_set = await _create_movie_set(test_db, [hd, sd])

    set_valid, files_removed = await verify_and_update_existing_set(
        test_db, dup_set, [hd, sd, uhd], ScoringEngine(), [], logging.getLogger("test")
    )
    await test_db.commit()

    assert set_valid and files_removed == 0
    files = {f.file_path: f for f in dup_set.files}
    assert len(files) == 3
    assert [path for path, f in files.items() if f.keep] == [uhd.file_path]
    assert dup_set.space_to_reclaim == hd.file_size + sd.file_size


@pytest.mark.asyncio
async def test_verify_set_space_to_reclaim_ignores_removed_files(test_db):
    """A file removed outside Deduparr no longer counts as space to reclaim"""
    best = MediaMetadata(
        file_path="/m/Film.1080p.mkv", file_size=4000, resolution="1080p"
    )
    mid = MediaMetadata(file_path="/m/Film.720p.mkv", file_size=2000, resolution="720p")
    gone = MediaMetadata(file_path="/m/Film.480p.mkv", file_size=500, resolution="480p")
    dup_set = await _create_movie_set(test_db, [best, mid, gone])

    await verify_and_update_existing_set(
        test_db, dup_set, [best, mid], ScoringEngine(), [], logging.getLogger("test")
    )
    await test_db.commit()

    assert {f.file_path for f in dup_set.files} == {best.file_path, mid.file_path}
    assert dup_set.space_to_reclaim == mid.file_size
