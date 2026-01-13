"""
Tests for scan API routes
"""

import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import select

from app.api.routes.scan import (
    get_custom_scoring_rules,
    get_plex_service,
    _process_duplicate_movies,
)
from app.models import Config, ScoringRule, DuplicateSet, DuplicateFile
from app.models.duplicate import DuplicateStatus, MediaType


@pytest.mark.asyncio
async def test_get_plex_service_not_configured(test_db):
    """Test getting Plex service when not configured"""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await get_plex_service(test_db)

    assert exc_info.value.status_code == 400
    assert "Plex not configured" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_get_plex_service_configured(test_db):
    """Test getting Plex service when configured"""
    # Add Plex auth token to database
    token_config = Config(key="plex_auth_token", value="test_token_123")
    server_config = Config(key="plex_server_name", value="TestServer")
    test_db.add(token_config)
    test_db.add(server_config)
    await test_db.commit()

    with patch("app.api.routes.scan.PlexService") as mock_plex:
        await get_plex_service(test_db)
        mock_plex.assert_called_once_with(
            encrypted_token="test_token_123", server_name="TestServer"
        )


@pytest.mark.asyncio
async def test_get_custom_scoring_rules_empty(test_db):
    """Test getting custom scoring rules when none exist"""
    rules = await get_custom_scoring_rules(test_db)
    assert rules == []


@pytest.mark.asyncio
async def test_get_custom_scoring_rules(test_db):
    """Test getting enabled custom scoring rules"""
    from app.models.scoring_rule import RuleType

    # Add some scoring rules
    rule1 = ScoringRule(
        rule_type=RuleType.FILENAME_PATTERN,
        pattern=r"remux",
        score_modifier=10000,
        enabled=True,
        description="Prefer remux",
    )
    rule2 = ScoringRule(
        rule_type=RuleType.FILENAME_PATTERN,
        pattern=r"hdtv",
        score_modifier=-5000,
        enabled=True,
        description="Avoid HDTV",
    )
    rule3 = ScoringRule(
        rule_type=RuleType.FILENAME_PATTERN,
        pattern=r"disabled",
        score_modifier=99999,
        enabled=False,
        description="This should not appear",
    )

    test_db.add(rule1)
    test_db.add(rule2)
    test_db.add(rule3)
    await test_db.commit()

    rules = await get_custom_scoring_rules(test_db)

    assert len(rules) == 2
    assert rules[0]["pattern"] == r"remux"
    assert rules[0]["score_modifier"] == 10000
    assert rules[1]["pattern"] == r"hdtv"
    assert rules[1]["score_modifier"] == -5000


@pytest.mark.asyncio
async def test_process_duplicate_movies(test_db):
    """Test processing duplicate movies and storing them"""
    from unittest.mock import Mock, patch

    from app.services.scoring_engine import ScoringEngine

    # Create two separate movie objects representing duplicates
    # Plex's native duplicate=True filter returns separate Movie objects
    mock_movie1 = Mock()
    mock_movie1.title = "Test Movie"
    mock_movie1.ratingKey = "12345"
    mock_movie1.reload = Mock()  # Mock the reload method
    mock_movie1.media = [
        Mock(
            parts=[Mock(file="/movies/TestMovie.720p.mkv", size=2 * 1024**3)],
            videoResolution="720p",
            videoCodec="h264",
            audioCodec="aac",
            bitrate=5000,
            width=1280,
            height=720,
        )
    ]

    mock_movie2 = Mock()
    mock_movie2.title = "Test Movie"
    mock_movie2.ratingKey = "12345"  # Same ratingKey = same content, different file
    mock_movie2.reload = Mock()  # Mock the reload method
    mock_movie2.media = [
        Mock(
            parts=[Mock(file="/movies/TestMovie.1080p.BluRay.mkv", size=8 * 1024**3)],
            videoResolution="1080p",
            videoCodec="h264",
            audioCodec="dts",
            bitrate=10000,
            width=1920,
            height=1080,
        )
    ]

    # Plex returns multiple Movie objects with the same ratingKey
    duplicates = {"Test Movie|None": [mock_movie1, mock_movie2]}

    scoring_engine = ScoringEngine()
    custom_rules = []

    # Mock filesystem access to simulate files existing on disk
    with patch("app.services.scan_helpers.os.path.exists", return_value=True), patch(
        "app.services.scan_helpers.os.stat"
    ) as mock_stat, patch(
        "app.services.scan_helpers.is_sample_file", return_value=False
    ):
        # Mock stat info for each file (different inodes)
        mock_stat.side_effect = [
            Mock(st_ino=12345, st_nlink=1),
            Mock(st_ino=67890, st_nlink=1),
        ]

        sets_created, sets_updated, sets_removed = await _process_duplicate_movies(
            test_db, duplicates, scoring_engine, custom_rules
        )

    assert sets_created == 1
    assert sets_updated == 0
    assert sets_removed == 0

    # Check database
    result = await test_db.execute(select(DuplicateSet))
    dup_sets = result.scalars().all()
    assert len(dup_sets) == 1

    dup_set = dup_sets[0]
    assert dup_set.title == "Test Movie"
    assert dup_set.media_type == MediaType.MOVIE
    assert dup_set.status == DuplicateStatus.PENDING
    assert dup_set.space_to_reclaim > 0

    # Check duplicate files
    result = await test_db.execute(select(DuplicateFile))
    dup_files = result.scalars().all()
    assert len(dup_files) == 2

    # Verify scoring - 1080p should be marked to keep
    keep_file = next((f for f in dup_files if f.keep), None)
    delete_file = next((f for f in dup_files if not f.keep), None)

    assert keep_file is not None
    assert delete_file is not None
    assert "1080p" in keep_file.file_path
    assert "720p" in delete_file.file_path
    assert keep_file.score > delete_file.score


@pytest.mark.asyncio
async def test_process_duplicate_movies_skip_existing(test_db):
    """Test that existing duplicate sets with valid files are not recreated"""
    from app.services.scoring_engine import ScoringEngine

    # Create existing duplicate set with files
    existing_set = DuplicateSet(
        plex_item_id="12345",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.PENDING,
        space_to_reclaim=0,
    )
    test_db.add(existing_set)
    await test_db.flush()

    # Create two temp files for this test
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mkv") as tmp1:
        temp_file_path1 = tmp1.name

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mkv") as tmp2:
        temp_file_path2 = tmp2.name

    # Add files to the existing set
    dup_file1 = DuplicateFile(
        set_id=existing_set.id,
        file_path=temp_file_path1,
        file_size=5 * 1024**3,
        score=50,
        keep=False,
    )
    dup_file2 = DuplicateFile(
        set_id=existing_set.id,
        file_path=temp_file_path2,
        file_size=3 * 1024**3,
        score=30,
        keep=True,
    )
    test_db.add(dup_file1)
    test_db.add(dup_file2)
    await test_db.commit()

    try:
        # Mock duplicate movies with two different files
        mock_movie1 = MagicMock()
        mock_movie1.title = "Test Movie"
        mock_movie1.ratingKey = "12345"
        mock_movie1.media = [MagicMock()]
        mock_movie1.media[0].parts = [MagicMock()]
        mock_movie1.media[0].parts[0].file = temp_file_path1
        mock_movie1.media[0].parts[0].size = 5 * 1024**3
        mock_movie1.media[0].videoResolution = "1080p"
        mock_movie1.media[0].videoCodec = "h264"
        mock_movie1.media[0].audioCodec = "aac"
        mock_movie1.media[0].bitrate = 5000
        mock_movie1.media[0].width = 1920
        mock_movie1.media[0].height = 1080

        mock_movie2 = MagicMock()
        mock_movie2.title = "Test Movie"
        mock_movie2.ratingKey = "12345"
        mock_movie2.media = [MagicMock()]
        mock_movie2.media[0].parts = [MagicMock()]
        mock_movie2.media[0].parts[0].file = temp_file_path2
        mock_movie2.media[0].parts[0].size = 3 * 1024**3
        mock_movie2.media[0].videoResolution = "720p"
        mock_movie2.media[0].videoCodec = "h264"
        mock_movie2.media[0].audioCodec = "aac"
        mock_movie2.media[0].bitrate = 3000
        mock_movie2.media[0].width = 1280
        mock_movie2.media[0].height = 720

        duplicates = {"Test Movie|None": [mock_movie1, mock_movie2]}

        scoring_engine = ScoringEngine()
        sets_created, sets_updated, sets_removed = await _process_duplicate_movies(
            test_db, duplicates, scoring_engine, []
        )

        # Should verify existing set and update if needed (no files removed = sets_updated stays 0)
        assert sets_created == 0
        assert sets_removed == 0
    finally:
        # Clean up temp files
        import os

        if os.path.exists(temp_file_path1):
            os.unlink(temp_file_path1)
        if os.path.exists(temp_file_path2):
            os.unlink(temp_file_path2)


@pytest.mark.asyncio
async def test_scan_status_endpoint(client, test_db):
    """Test scan status endpoint"""
    # Create some test duplicate sets
    set1 = DuplicateSet(
        plex_item_id="1",
        title="Movie 1",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.PENDING,
        space_to_reclaim=5 * 1024**3,
    )
    set2 = DuplicateSet(
        plex_item_id="2",
        title="Movie 2",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.PROCESSED,
        space_to_reclaim=3 * 1024**3,
    )
    test_db.add(set1)
    test_db.add(set2)
    await test_db.commit()

    response = await client.get("/api/scan/status")
    assert response.status_code == 200

    data = response.json()
    assert data["total_duplicate_sets"] == 2
    assert data["pending_sets"] == 1
    # Only PENDING/APPROVED sets count toward reclaimable space (excludes PROCESSED)
    assert data["total_space_reclaimable"] == 5 * 1024**3


@pytest.mark.asyncio
async def test_get_duplicates_endpoint(client, test_db, create_duplicate_set):
    """Test getting duplicates endpoint"""
    # Create test duplicate set with files
    dup_set = await create_duplicate_set(
        plex_item_id="123",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.PENDING,
        space_to_reclaim=5 * 1024**3,
    )

    file1 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/test1.mkv",
        file_size=2 * 1024**3,
        score=10000,
        keep=False,
        file_metadata='{"resolution": "720p"}',
    )
    file2 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/test2.mkv",
        file_size=5 * 1024**3,
        score=20000,
        keep=True,
        file_metadata='{"resolution": "1080p"}',
    )
    test_db.add(file1)
    test_db.add(file2)
    await test_db.commit()

    response = await client.get("/api/scan/duplicates")
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Test Movie"
    assert data[0]["status"] == "pending"
    assert len(data[0]["files"]) == 2


@pytest.mark.asyncio
async def test_get_duplicates_filtered_by_status(client, test_db, create_duplicate_set):
    """Test filtering duplicates by status"""
    await create_duplicate_set(
        plex_item_id="1", title="Pending", status=DuplicateStatus.PENDING
    )
    await create_duplicate_set(
        plex_item_id="2", title="Processed", status=DuplicateStatus.PROCESSED
    )

    response = await client.get("/api/scan/duplicates?status=pending")
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_get_duplicates_filtered_by_media_type(
    client, test_db, create_duplicate_set
):
    """Test filtering duplicates by media type"""
    await create_duplicate_set(
        plex_item_id="1", title="Movie", media_type=MediaType.MOVIE
    )
    await create_duplicate_set(
        plex_item_id="2", title="Episode", media_type=MediaType.EPISODE
    )

    response = await client.get("/api/scan/duplicates?media_type=movie")
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 1
    assert data[0]["media_type"] == "movie"


@pytest.mark.asyncio
async def test_start_scan_no_plex_config(client, test_db):
    """Test scan fails when Plex not configured"""
    response = await client.post(
        "/api/scan/start", json={"library_names": ["Movies"], "media_types": ["movie"]}
    )
    assert response.status_code == 400
    assert "Plex not configured" in response.text


@pytest.mark.asyncio
async def test_start_scan_success(client, test_db):
    """Test successful scan"""
    # Configure Plex
    token_config = Config(key="plex_auth_token", value="test_token")
    server_config = Config(key="plex_server_name", value="TestServer")
    test_db.add(token_config)
    test_db.add(server_config)
    await test_db.commit()

    # Mock PlexService
    with patch("app.api.routes.scan.PlexService") as mock_plex_class:
        mock_plex = MagicMock()
        mock_plex_class.return_value = mock_plex

        # Mock duplicate detection to return empty
        mock_plex.find_duplicate_movies.return_value = {}
        mock_plex.get_all_shows.return_value = []

        response = await client.post(
            "/api/scan/start",
            json={"library_names": ["Movies"], "media_types": ["movie"]},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "duplicates_found" in data


@pytest.mark.asyncio
async def test_duplicate_detection_accuracy(test_db):
    """
    Test that duplicate detection correctly identifies which file to keep

    This test verifies that:
    1. Higher resolution files score better
    2. Higher bitrate files score better
    3. The file with the highest score is marked as 'keep=True'
    4. All other files are marked as 'keep=False'
    """
    from unittest.mock import Mock, patch

    from app.services.scoring_engine import ScoringEngine

    # Create 3 separate movie objects for 3 different quality versions
    # Plex's native duplicate=True filter returns separate Movie objects
    mock_movie_low = Mock()
    mock_movie_low.title = "Quality Test Movie"
    mock_movie_low.ratingKey = "99999"
    mock_movie_low.reload = Mock()  # Mock the reload method
    mock_movie_low.media = [
        Mock(
            parts=[Mock(file="/movies/QualityTest.720p.HDTV.mkv", size=1.5 * 1024**3)],
            videoResolution="720",
            videoCodec="h264",
            audioCodec="aac",
            bitrate=3000,
            width=1280,
            height=720,
        )
    ]

    mock_movie_medium = Mock()
    mock_movie_medium.title = "Quality Test Movie"
    mock_movie_medium.ratingKey = "99999"
    mock_movie_medium.reload = Mock()  # Mock the reload method
    mock_movie_medium.media = [
        Mock(
            parts=[Mock(file="/movies/QualityTest.1080p.WEB-DL.mkv", size=4 * 1024**3)],
            videoResolution="1080",
            videoCodec="h264",
            audioCodec="aac",
            bitrate=8000,
            width=1920,
            height=1080,
        )
    ]

    mock_movie_high = Mock()
    mock_movie_high.title = "Quality Test Movie"
    mock_movie_high.ratingKey = "99999"
    mock_movie_high.reload = Mock()  # Mock the reload method
    mock_movie_high.media = [
        Mock(
            parts=[
                Mock(
                    file="/movies/QualityTest.1080p.BluRay.REMUX.mkv", size=25 * 1024**3
                )
            ],
            videoResolution="1080",
            videoCodec="h264",
            audioCodec="truehd",
            bitrate=20000,
            width=1920,
            height=1080,
        )
    ]

    # Plex returns multiple Movie objects with the same ratingKey
    duplicates = {
        "Quality Test Movie|None": [mock_movie_low, mock_movie_medium, mock_movie_high]
    }

    scoring_engine = ScoringEngine()

    # Add custom rule to boost REMUX files
    custom_rules = [{"pattern": r"REMUX", "score_modifier": 5000, "enabled": True}]

    # Mock filesystem access to simulate files existing on disk
    with patch("app.services.scan_helpers.os.path.exists", return_value=True), patch(
        "app.services.scan_helpers.os.stat"
    ) as mock_stat, patch(
        "app.services.scan_helpers.is_sample_file", return_value=False
    ):
        # Mock stat info for each file (different inodes)
        mock_stat.side_effect = [
            Mock(st_ino=11111, st_nlink=1),
            Mock(st_ino=22222, st_nlink=1),
            Mock(st_ino=33333, st_nlink=1),
        ]

        sets_created, sets_updated, sets_removed = await _process_duplicate_movies(
            test_db, duplicates, scoring_engine, custom_rules
        )

    assert sets_created == 1
    assert sets_updated == 0
    assert sets_removed == 0

    # Fetch the created duplicate set
    result = await test_db.execute(
        select(DuplicateSet).where(DuplicateSet.plex_item_id == "99999")
    )
    dup_set = result.scalar_one()

    # Fetch all files in the set
    result = await test_db.execute(
        select(DuplicateFile).where(DuplicateFile.set_id == dup_set.id)
    )
    files = result.scalars().all()

    assert len(files) == 3

    # Find which file is marked to keep
    files_to_keep = [f for f in files if f.keep]
    files_to_delete = [f for f in files if not f.keep]

    # Should have exactly 1 file to keep and 2 to delete
    assert len(files_to_keep) == 1, "Exactly one file should be marked to keep"
    assert len(files_to_delete) == 2, "Two files should be marked for deletion"

    # The file to keep should be the REMUX (highest quality)
    keep_file = files_to_keep[0]
    assert "REMUX" in keep_file.file_path, "REMUX file should be selected to keep"
    assert keep_file.score == max(
        f.score for f in files
    ), "Kept file should have highest score"

    # Verify the lower quality files are marked for deletion
    assert all("REMUX" not in f.file_path for f in files_to_delete)

    # Verify scoring order: high > medium > low
    file_scores = {f.file_path: f.score for f in files}
    remux_score = file_scores["/movies/QualityTest.1080p.BluRay.REMUX.mkv"]
    webdl_score = file_scores["/movies/QualityTest.1080p.WEB-DL.mkv"]
    hdtv_score = file_scores["/movies/QualityTest.720p.HDTV.mkv"]

    assert remux_score > webdl_score > hdtv_score, "Scores should be ordered by quality"

    # Verify space to reclaim is calculated correctly (sum of files to delete)
    expected_space = sum(f.file_size for f in files_to_delete)
    assert dup_set.space_to_reclaim == expected_space


@pytest.mark.asyncio
async def test_preview_deletion_endpoint(client, test_db, create_duplicate_set):
    """Test the deletion preview endpoint"""
    # Create a duplicate set with files
    dup_set = await create_duplicate_set(
        plex_item_id="preview_test",
        title="Preview Test Movie",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.PENDING,
        space_to_reclaim=3 * 1024**3,
    )

    # Low quality file to delete
    file1 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/preview.720p.mkv",
        file_size=2 * 1024**3,
        score=10000,
        keep=False,
        file_metadata='{"resolution": "720p", "video_codec": "h264"}',
    )

    # High quality file to keep
    file2 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/preview.1080p.BluRay.mkv",
        file_size=8 * 1024**3,
        score=25000,
        keep=True,
        file_metadata='{"resolution": "1080p", "video_codec": "h264"}',
    )

    test_db.add(file1)
    test_db.add(file2)
    await test_db.commit()

    # Call preview endpoint
    response = await client.get(f"/api/scan/duplicates/{dup_set.id}/preview")
    assert response.status_code == 200

    data = response.json()

    # Verify response structure
    assert data["set_id"] == dup_set.id
    assert data["title"] == "Preview Test Movie"
    assert data["media_type"] == "movie"
    assert data["total_files"] == 2
    assert data["files_to_delete_count"] == 1

    # Verify files to keep
    assert len(data["files_to_keep"]) == 1
    assert "1080p" in data["files_to_keep"][0]["file_path"]
    assert data["files_to_keep"][0]["score"] == 25000

    # Verify files to delete
    assert len(data["files_to_delete"]) == 1
    assert "720p" in data["files_to_delete"][0]["file_path"]
    assert data["files_to_delete"][0]["score"] == 10000

    # Verify space calculations
    assert data["space_to_reclaim"] == 2 * 1024**3
    assert data["space_to_reclaim_mb"] == 2048.0
    assert data["space_to_reclaim_gb"] == 2.0


@pytest.mark.asyncio
async def test_delete_duplicate_set_dry_run(client, test_db, create_duplicate_set):
    """Test deletion with dry_run=True (default)"""
    # Configure required services in database
    from tests.conftest import encrypt_test_password

    plex_token_config = Config(
        key="plex_auth_token", value=encrypt_test_password("test_token")
    )
    plex_server_config = Config(key="plex_server_name", value="Test Server")
    plex_libraries_config = Config(key="plex_libraries", value="Movies,TV Shows")
    test_db.add(plex_token_config)
    test_db.add(plex_server_config)
    test_db.add(plex_libraries_config)
    await test_db.commit()

    # Create duplicate set
    dup_set = await create_duplicate_set(
        plex_item_id="delete_test",
        title="Delete Test Movie",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.PENDING,
        space_to_reclaim=5 * 1024**3,
    )

    file1 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/delete.720p.mkv",
        file_size=3 * 1024**3,
        score=10000,
        keep=False,
    )
    file2 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/delete.1080p.mkv",
        file_size=8 * 1024**3,
        score=20000,
        keep=True,
    )
    test_db.add(file1)
    test_db.add(file2)
    await test_db.commit()

    # Test dry run (should not actually delete)
    response = await client.post(
        f"/api/scan/duplicates/{dup_set.id}/delete", json={"dry_run": True}
    )

    assert response.status_code == 200
    data = response.json()

    assert data["success"] is True
    assert data["dry_run"] is True
    assert data["files_deleted"] == 1
    assert data["space_reclaimed"] == 3 * 1024**3
    assert "[DRY-RUN]" in data["message"]
    assert len(data["errors"]) == 0

    # Verify set is NOT marked as processed in dry-run mode
    await test_db.refresh(dup_set)
    assert dup_set.status == DuplicateStatus.PENDING


@pytest.mark.asyncio
async def test_delete_duplicate_set_not_found(client, test_db):
    """Test deletion fails when duplicate set doesn't exist"""
    response = await client.post(
        "/api/scan/duplicates/99999/delete", json={"dry_run": True}
    )

    assert response.status_code == 404
    assert "not found" in response.text


@pytest.mark.asyncio
async def test_delete_already_processed_set(client, test_db, create_duplicate_set):
    """Test that deletion fails for already processed sets"""
    dup_set = await create_duplicate_set(
        plex_item_id="processed_test",
        title="Already Processed",
        status=DuplicateStatus.PROCESSED,
    )

    response = await client.post(
        f"/api/scan/duplicates/{dup_set.id}/delete", json={"dry_run": True}
    )

    assert response.status_code == 400
    assert "already been processed" in response.text


@pytest.mark.asyncio
async def test_delete_no_files_marked_for_deletion(
    client, test_db, create_duplicate_set
):
    """Test deletion fails when all files are marked to keep"""
    dup_set = await create_duplicate_set(
        plex_item_id="no_delete_test",
        title="No Deletion Needed",
        status=DuplicateStatus.PENDING,
    )

    # Both files marked to keep (shouldn't happen in reality)
    file1 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file1.mkv",
        file_size=5 * 1024**3,
        score=20000,
        keep=True,
    )
    file2 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file2.mkv",
        file_size=8 * 1024**3,
        score=25000,
        keep=True,
    )
    test_db.add(file1)
    test_db.add(file2)
    await test_db.commit()

    response = await client.post(
        f"/api/scan/duplicates/{dup_set.id}/delete", json={"dry_run": True}
    )

    assert response.status_code == 400
    assert "No files marked for deletion" in response.text


@pytest.mark.asyncio
async def test_update_file_keep_flag_success(client, test_db, create_duplicate_set):
    """Test successfully toggling a file's keep flag"""
    dup_set = await create_duplicate_set(
        plex_item_id="toggle_test",
        title="Toggle Test",
        status=DuplicateStatus.PENDING,
    )

    # Add files - one keep, one delete
    file1 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file1.mkv",
        file_size=5 * 1024**3,
        score=25000,
        keep=True,
    )
    file2 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file2.mkv",
        file_size=3 * 1024**3,
        score=15000,
        keep=False,
    )
    test_db.add(file1)
    test_db.add(file2)
    await test_db.commit()

    # Toggle file2 to keep
    response = await client.patch(
        f"/api/scan/duplicates/{dup_set.id}/files/{file2.id}",
        json={"keep": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["file_id"] == file2.id
    assert data["keep"] is True
    assert data["space_to_reclaim"] == 0  # Both files now kept

    # Verify in database
    await test_db.refresh(file2)
    assert file2.keep is True


@pytest.mark.asyncio
async def test_update_file_keep_flag_prevents_all_delete(
    client, test_db, create_duplicate_set
):
    """Test that we can't mark all files for deletion"""
    dup_set = await create_duplicate_set(
        plex_item_id="prevent_all_delete",
        title="Prevent All Delete",
        status=DuplicateStatus.PENDING,
    )

    # Add files - one keep, one delete
    file1 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file1.mkv",
        file_size=5 * 1024**3,
        score=25000,
        keep=True,
    )
    file2 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file2.mkv",
        file_size=3 * 1024**3,
        score=15000,
        keep=False,
    )
    test_db.add(file1)
    test_db.add(file2)
    await test_db.commit()

    # Try to mark the only kept file for deletion
    response = await client.patch(
        f"/api/scan/duplicates/{dup_set.id}/files/{file1.id}",
        json={"keep": False},
    )

    assert response.status_code == 400
    assert "At least one file must be marked to keep" in response.text


@pytest.mark.asyncio
async def test_update_file_keep_flag_not_found(client, test_db, create_duplicate_set):
    """Test updating a non-existent file"""
    dup_set = await create_duplicate_set(
        plex_item_id="not_found_test",
        title="Not Found Test",
        status=DuplicateStatus.PENDING,
    )

    response = await client.patch(
        f"/api/scan/duplicates/{dup_set.id}/files/99999",
        json={"keep": True},
    )

    assert response.status_code == 404
    assert "File 99999 not found" in response.text


@pytest.mark.asyncio
async def test_update_file_keep_flag_set_not_found(client, test_db):
    """Test updating a file in a non-existent set"""
    response = await client.patch(
        "/api/scan/duplicates/99999/files/1",
        json={"keep": True},
    )

    assert response.status_code == 404
    assert "Duplicate set 99999 not found" in response.text


@pytest.mark.asyncio
async def test_update_file_keep_flag_processed_set(
    client, test_db, create_duplicate_set
):
    """Test that we can't modify files in processed sets"""
    dup_set = await create_duplicate_set(
        plex_item_id="processed_set",
        title="Processed Set",
        status=DuplicateStatus.PROCESSED,
    )

    file1 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file1.mkv",
        file_size=5 * 1024**3,
        score=25000,
        keep=True,
    )
    test_db.add(file1)
    await test_db.commit()

    response = await client.patch(
        f"/api/scan/duplicates/{dup_set.id}/files/{file1.id}",
        json={"keep": False},
    )

    assert response.status_code == 400
    assert "Cannot modify files in a processed duplicate set" in response.text


@pytest.mark.asyncio
async def test_update_file_keep_recalculates_space(
    client, test_db, create_duplicate_set
):
    """Test that space_to_reclaim is recalculated correctly"""
    dup_set = await create_duplicate_set(
        plex_item_id="space_test",
        title="Space Calculation Test",
        status=DuplicateStatus.PENDING,
    )

    # Add 3 files
    file1 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file1.mkv",
        file_size=5 * 1024**3,  # 5 GB
        score=25000,
        keep=True,
    )
    file2 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file2.mkv",
        file_size=3 * 1024**3,  # 3 GB
        score=15000,
        keep=False,
    )
    file3 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file3.mkv",
        file_size=2 * 1024**3,  # 2 GB
        score=10000,
        keep=False,
    )
    test_db.add_all([file1, file2, file3])
    await test_db.commit()

    # Toggle file2 to keep
    response = await client.patch(
        f"/api/scan/duplicates/{dup_set.id}/files/{file2.id}",
        json={"keep": True},
    )

    assert response.status_code == 200
    data = response.json()
    # Now only file3 (2 GB) should be reclaimable
    assert data["space_to_reclaim"] == file3.file_size
