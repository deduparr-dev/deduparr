"""
Tests for Sonarr service filename matching to prevent wrong file deletion bug.

Critical Bug Fixed: When two episode files have identical filenames but different paths
(e.g., /Show/S01E01.mkv and /Show Season 1/S01E01.mkv), the service must match by
FULL PATH, not just filename, to avoid deleting the wrong file.
"""

import pytest
from unittest.mock import AsyncMock

from app.services.sonarr_service import SonarrService
from app.models.config import Config


@pytest.fixture
def mock_sonarr_client():
    """Mock SonarrClient"""
    client = AsyncMock()
    return client


@pytest.fixture
async def sonarr_service(test_db, mock_sonarr_client):
    """Create SonarrService with mocked client"""
    # Add Sonarr config to database
    test_db.add(Config(key="sonarr_url", value="http://sonarr:8989"))
    test_db.add(Config(key="sonarr_api_key", value="test-api-key"))
    await test_db.commit()

    service = SonarrService(test_db)
    service._client = mock_sonarr_client
    return service


@pytest.mark.asyncio
async def test_find_episode_by_exact_path_match(sonarr_service, mock_sonarr_client):
    """Test that find_episode_by_file_path matches by FULL PATH, not just filename"""
    # Mock get_series to return a series
    mock_sonarr_client.get_series = AsyncMock(
        return_value=[
            {
                "id": 1,
                "title": "Test Show",
            }
        ]
    )

    # Two episode files with SAME filename but DIFFERENT paths
    mock_sonarr_client.get_episode_files_by_series_id = AsyncMock(
        return_value=[
            {
                "id": 100,
                "path": "/plexdownloads/TV/Show/Season 01/Show S01E01.mkv",
                "episodeIds": [1],
            },
            {
                "id": 200,
                "path": "/plexdownloads/TV/Show/Show S01E01.mkv",  # Same filename, root level
                "episodeIds": [2],
            },
        ]
    )

    # Mock get_episode to return episode for ID 2
    mock_sonarr_client.get_episode = AsyncMock(
        return_value={
            "id": 2,
            "title": "Episode 1 (duplicate)",
            "seasonNumber": 1,
            "episodeNumber": 1,
        }
    )

    # Search for the root-level file
    file_to_find = "/plexdownloads/TV/Show/Show S01E01.mkv"
    result = await sonarr_service.find_episode_by_file_path(file_to_find)

    # Should return the episode with ID 2 (exact path match)
    assert result is not None
    assert result["id"] == 2
    assert result["episodeFile"]["id"] == 200


@pytest.mark.asyncio
async def test_find_episode_no_match_for_different_path(
    sonarr_service, mock_sonarr_client
):
    """Test that episode is not found when path doesn't match exactly"""
    mock_sonarr_client.get_series = AsyncMock(return_value=[{"id": 1}])
    mock_sonarr_client.get_episode_files_by_series_id = AsyncMock(
        return_value=[
            {
                "id": 100,
                "path": "/plexdownloads/TV/Show/Season 01/Show S01E01.mkv",
                "episodeIds": [1],
            }
        ]
    )

    # Search for non-existent path (same filename, different location)
    file_to_find = "/plexdownloads/TV/Show/Show S01E01.mkv"
    result = await sonarr_service.find_episode_by_file_path(file_to_find)

    # Should return None because path doesn't match exactly
    assert result is None


@pytest.mark.asyncio
async def test_find_episode_multiple_versions_same_filename(
    sonarr_service, mock_sonarr_client
):
    """Test handling multiple quality versions with same filename in different folders"""
    mock_sonarr_client.get_series = AsyncMock(return_value=[{"id": 1}])
    mock_sonarr_client.get_episode_files_by_series_id = AsyncMock(
        return_value=[
            {
                "id": 100,
                "path": "/plexdownloads/TV/Show/Season 01/Show S01E01 720p.mkv",
                "episodeIds": [1],
            },
            {
                "id": 200,
                "path": "/plexdownloads/TV/Show/Season 01 (1080p)/Show S01E01 720p.mkv",  # Same filename!
                "episodeIds": [1],
            },
        ]
    )

    mock_sonarr_client.get_episode = AsyncMock(
        return_value={
            "id": 1,
            "title": "Pilot",
            "seasonNumber": 1,
            "episodeNumber": 1,
        }
    )

    # Search for the 1080p folder version
    file_to_find = "/plexdownloads/TV/Show/Season 01 (1080p)/Show S01E01 720p.mkv"
    result = await sonarr_service.find_episode_by_file_path(file_to_find)

    # Should return the correct episode file (ID 200)
    assert result is not None
    assert result["episodeFile"]["id"] == 200
    assert result["episodeFile"]["path"] == file_to_find


@pytest.mark.asyncio
async def test_find_episode_without_episode_ids(sonarr_service, mock_sonarr_client):
    """Test handling episode files without episodeIds (orphaned files)"""
    mock_sonarr_client.get_series = AsyncMock(return_value=[{"id": 1}])
    mock_sonarr_client.get_episode_files_by_series_id = AsyncMock(
        return_value=[
            {
                "id": 100,
                "path": "/plexdownloads/TV/Show/Show S01E01.mkv",
                "seriesId": 1,
                "seasonNumber": 1,
                # Missing episodeIds - orphaned file
            }
        ]
    )

    result = await sonarr_service.find_episode_by_file_path(
        "/plexdownloads/TV/Show/Show S01E01.mkv"
    )

    # Should return minimal episode object with orphaned flag
    assert result is not None
    assert result["_orphaned"] is True
    assert result["seriesId"] == 1
    assert result["seasonNumber"] == 1
    assert result["episodeFile"]["id"] == 100
    assert result["id"] is None  # No episode ID for orphaned files


@pytest.mark.asyncio
async def test_find_episode_empty_episode_ids(sonarr_service, mock_sonarr_client):
    """Test handling episode files with empty episodeIds array (orphaned files)"""
    mock_sonarr_client.get_series = AsyncMock(return_value=[{"id": 1}])
    mock_sonarr_client.get_episode_files_by_series_id = AsyncMock(
        return_value=[
            {
                "id": 100,
                "path": "/plexdownloads/TV/Show/Show S01E01.mkv",
                "episodeIds": [],  # Empty array - orphaned file
                "seriesId": 1,
                "seasonNumber": 1,
            }
        ]
    )

    result = await sonarr_service.find_episode_by_file_path(
        "/plexdownloads/TV/Show/Show S01E01.mkv"
    )

    # Should return minimal episode object with orphaned flag
    assert result is not None
    assert result["_orphaned"] is True
    assert result["seriesId"] == 1
    assert result["seasonNumber"] == 1
    assert result["episodeFile"]["id"] == 100
    assert result["id"] is None  # No episode ID for orphaned files


@pytest.mark.asyncio
async def test_find_episode_case_sensitive_path(sonarr_service, mock_sonarr_client):
    """Test that path matching is case-sensitive"""
    mock_sonarr_client.get_series = AsyncMock(return_value=[{"id": 1}])
    mock_sonarr_client.get_episode_files_by_series_id = AsyncMock(
        return_value=[
            {
                "id": 100,
                "path": "/plexdownloads/TV/Show/Season 01/Episode.mkv",
                "episodeIds": [1],
            }
        ]
    )

    # Different case in path
    result = await sonarr_service.find_episode_by_file_path(
        "/plexdownloads/tv/show/season 01/episode.mkv"  # lowercase
    )

    # Should NOT match due to case difference
    assert result is None


@pytest.mark.asyncio
async def test_deletion_bug_regression_sonarr(sonarr_service, mock_sonarr_client):
    """
    Regression test for episode deletion bug: Deleting /Show/S01E01.mkv should NOT match
    /Show/Season 01/S01E01.mkv even though they have the same filename.
    """
    # Sonarr knows about the organized file
    mock_sonarr_client.get_series = AsyncMock(return_value=[{"id": 1}])
    mock_sonarr_client.get_episode_files_by_series_id = AsyncMock(
        return_value=[
            {
                "id": 500,
                "path": "/plexdownloads/TV/Dexter Resurrection/Season 01/Dexter Resurrection S01E01.mkv",
                "episodeIds": [1],
            }
        ]
    )

    # We want to delete the root-level file (NOT the one Sonarr knows about)
    file_to_delete = (
        "/plexdownloads/TV/Dexter Resurrection/Dexter Resurrection S01E01.mkv"
    )
    result = await sonarr_service.find_episode_by_file_path(file_to_delete)

    # CRITICAL: Must return None because paths don't match exactly
    assert result is None, (
        "CRITICAL BUG: find_episode_by_file_path matched by filename instead of full path! "
        "This would cause deletion of the wrong file."
    )


@pytest.mark.asyncio
async def test_find_episode_multi_episode_file(sonarr_service, mock_sonarr_client):
    """Test handling multi-episode files (e.g., S01E01-E02)"""
    mock_sonarr_client.get_series = AsyncMock(return_value=[{"id": 1}])
    mock_sonarr_client.get_episode_files_by_series_id = AsyncMock(
        return_value=[
            {
                "id": 100,
                "path": "/plexdownloads/TV/Show/Show S01E01-E02.mkv",
                "episodeIds": [1, 2],  # Multiple episodes
            }
        ]
    )

    mock_sonarr_client.get_episode = AsyncMock(
        return_value={
            "id": 1,
            "title": "Episode 1",
            "seasonNumber": 1,
            "episodeNumber": 1,
        }
    )

    result = await sonarr_service.find_episode_by_file_path(
        "/plexdownloads/TV/Show/Show S01E01-E02.mkv"
    )

    # Should return the first episode with file attached
    assert result is not None
    assert result["id"] == 1
    assert result["episodeFile"]["id"] == 100


@pytest.mark.asyncio
async def test_find_episode_special_characters(sonarr_service, mock_sonarr_client):
    """Test path matching with special characters in filenames"""
    mock_sonarr_client.get_series = AsyncMock(return_value=[{"id": 1}])
    mock_sonarr_client.get_episode_files_by_series_id = AsyncMock(
        return_value=[
            {
                "id": 100,
                "path": "/plexdownloads/TV/Show: The Series/Season 01/Episode #1 - Pilot [2024].mkv",
                "episodeIds": [1],
            }
        ]
    )

    mock_sonarr_client.get_episode = AsyncMock(
        return_value={
            "id": 1,
            "title": "Pilot",
            "seasonNumber": 1,
            "episodeNumber": 1,
        }
    )

    # Exact match should work with special characters
    result = await sonarr_service.find_episode_by_file_path(
        "/plexdownloads/TV/Show: The Series/Season 01/Episode #1 - Pilot [2024].mkv"
    )

    assert result is not None
    assert result["id"] == 1


@pytest.mark.asyncio
async def test_find_episode_no_files_in_sonarr(sonarr_service, mock_sonarr_client):
    """Test handling when Sonarr has no episode files"""
    mock_sonarr_client.get_series = AsyncMock(return_value=[{"id": 1}])
    mock_sonarr_client.get_episode_files_by_series_id = AsyncMock(return_value=[])

    result = await sonarr_service.find_episode_by_file_path(
        "/plexdownloads/TV/Show/Show S01E01.mkv"
    )

    assert result is None
