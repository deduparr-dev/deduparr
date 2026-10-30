"""
Tests for Sonarr service filename matching to prevent wrong file deletion bug.

Critical Bug Fixed: When two episode files have identical filenames but different paths
(e.g., /Show/S01E01.mkv and /Show Season 1/S01E01.mkv), the service must match by
FULL PATH, not just filename, to avoid deleting the wrong file.
"""

import pytest
from unittest.mock import AsyncMock

from app.services.arr.sonarr_service import SonarrService
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
            },
            {
                "id": 200,
                "path": "/plexdownloads/TV/Show/Show S01E01.mkv",  # Same filename, root level
            },
        ]
    )

    # Search for the root-level file
    file_to_find = "/plexdownloads/TV/Show/Show S01E01.mkv"
    result = await sonarr_service.find_episode_by_file_path(file_to_find)

    assert result is not None
    assert result["seriesId"] == 1
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
            },
            {
                "id": 200,
                "path": "/plexdownloads/TV/Show/Season 01 (1080p)/Show S01E01 720p.mkv",  # Same filename!
            },
        ]
    )

    # Search for the 1080p folder version
    file_to_find = "/plexdownloads/TV/Show/Season 01 (1080p)/Show S01E01 720p.mkv"
    result = await sonarr_service.find_episode_by_file_path(file_to_find)

    # Should return the correct episode file (ID 200)
    assert result is not None
    assert result["episodeFile"]["id"] == 200
    assert result["episodeFile"]["path"] == file_to_find


@pytest.mark.asyncio
async def test_find_episode_case_sensitive_path(sonarr_service, mock_sonarr_client):
    """Test that path matching is case-sensitive"""
    mock_sonarr_client.get_series = AsyncMock(return_value=[{"id": 1}])
    mock_sonarr_client.get_episode_files_by_series_id = AsyncMock(
        return_value=[
            {
                "id": 100,
                "path": "/plexdownloads/TV/Show/Season 01/Episode.mkv",
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
async def test_find_episode_no_files_in_sonarr(sonarr_service, mock_sonarr_client):
    """Test handling when Sonarr has no episode files"""
    mock_sonarr_client.get_series = AsyncMock(return_value=[{"id": 1}])
    mock_sonarr_client.get_episode_files_by_series_id = AsyncMock(return_value=[])

    result = await sonarr_service.find_episode_by_file_path(
        "/plexdownloads/TV/Show/Show S01E01.mkv"
    )

    assert result is None
