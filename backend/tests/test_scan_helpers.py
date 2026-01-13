"""Tests for scan helper functions"""

import json
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import DuplicateFile, DuplicateSet, MediaType
from app.services.scan_helpers import (
    cleanup_stale_set,
    collect_media_metadata,
    create_duplicate_set,
    validate_duplicate_files,
)
from app.services.scoring_engine import MediaMetadata, ScoringEngine


@pytest.mark.asyncio
async def test_collect_media_metadata_with_movie(caplog):
    """Test collecting metadata from movie media"""
    mock_movie = Mock()
    mock_movie.title = "Test Movie"
    mock_movie.media = [
        Mock(
            parts=[Mock(file="/media/movie1.mkv", size=1000000000)],
            videoResolution="1080p",
            videoCodec="h264",
            audioCodec="aac",
            bitrate=5000,
            width=1920,
            height=1080,
        ),
        Mock(
            parts=[Mock(file="/media/movie2.mkv", size=2000000000)],
            videoResolution="2160p",
            videoCodec="hevc",
            audioCodec="aac",
            bitrate=15000,
            width=3840,
            height=2160,
        ),
    ]
    mock_logger = Mock()

    with patch("app.services.scan_helpers.os.path.exists", return_value=True), patch(
        "app.services.scan_helpers.os.stat"
    ) as mock_stat, patch(
        "app.services.scan_helpers.is_sample_file", return_value=False
    ):

        # First file: regular file
        mock_stat.side_effect = [
            Mock(st_ino=12345, st_nlink=1),
            Mock(st_ino=67890, st_nlink=1),
        ]

        result = await collect_media_metadata([mock_movie], "movie", mock_logger)

    assert len(result) == 2
    assert result[0].file_path == "/media/movie1.mkv"
    assert result[0].file_size == 1000000000
    assert result[0].resolution == "1080p"
    assert result[0].inode == 12345
    assert result[0].is_hardlink is False
    assert result[1].file_path == "/media/movie2.mkv"
    assert result[1].inode == 67890


@pytest.mark.asyncio
async def test_collect_media_metadata_skips_samples(caplog):
    """Test that sample files are filtered out"""
    mock_movie = Mock()
    mock_movie.title = "Test Movie"
    mock_movie.media = [
        Mock(
            parts=[Mock(file="/media/movie-sample.mkv", size=50000000)],
            videoResolution="1080p",
            videoCodec="h264",
            audioCodec="aac",
            bitrate=5000,
            width=1920,
            height=1080,
        )
    ]
    mock_logger = Mock()

    with patch("app.services.scan_helpers.os.path.exists", return_value=True), patch(
        "app.services.scan_helpers.is_sample_file", return_value=True
    ):

        result = await collect_media_metadata([mock_movie], "movie", mock_logger)

    assert len(result) == 0
    mock_logger.info.assert_any_call("Skipping sample file: /media/movie-sample.mkv")


@pytest.mark.asyncio
async def test_collect_media_metadata_detects_hardlinks(caplog):
    """Test detection of hardlinked files"""
    mock_movie = Mock()
    mock_movie.title = "Test Movie"
    mock_movie.media = [
        Mock(
            parts=[Mock(file="/media/movie1.mkv", size=1000000000)],
            videoResolution="1080p",
            videoCodec="h264",
            audioCodec="aac",
            bitrate=5000,
            width=1920,
            height=1080,
        )
    ]
    mock_logger = Mock()

    with patch("app.services.scan_helpers.os.path.exists", return_value=True), patch(
        "app.services.scan_helpers.os.stat"
    ) as mock_stat, patch(
        "app.services.scan_helpers.is_sample_file", return_value=False
    ):

        # Hardlink (st_nlink > 1)
        mock_stat.return_value = Mock(st_ino=12345, st_nlink=2)

        result = await collect_media_metadata([mock_movie], "movie", mock_logger)

    assert len(result) == 1
    assert result[0].is_hardlink is True


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
        plex_item_id="12345",
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
        .where(DuplicateSet.plex_item_id == "12345")
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
    assert file1.inode == 12345
    assert file1.is_hardlink is False

    file_metadata = json.loads(file1.file_metadata)
    assert file_metadata["resolution"] == "1080p"
    assert file_metadata["video_codec"] == "h264"


@pytest.mark.asyncio
async def test_cleanup_stale_set(test_db: AsyncSession):
    """Test cleanup of stale duplicate set"""
    # Create a duplicate set
    dup_set = DuplicateSet(
        plex_item_id="12345",
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
    from app.services.scan_helpers import verify_and_update_existing_set

    # Create a duplicate set with 3 files
    dup_set = DuplicateSet(
        plex_item_id="12345",
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
    from app.services.scan_helpers import verify_and_update_existing_set

    # Create a duplicate set with 2 files
    dup_set = DuplicateSet(
        plex_item_id="12345",
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
    from app.services.scan_helpers import verify_and_update_existing_set

    # Create a duplicate set with 2 files
    dup_set = DuplicateSet(
        plex_item_id="12345",
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
    from app.services.scan_helpers import verify_and_update_existing_set

    # Create a duplicate set with 2 files
    dup_set = DuplicateSet(
        plex_item_id="12345",
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
