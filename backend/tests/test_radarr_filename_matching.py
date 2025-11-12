"""
Tests for Radarr service filename matching to prevent wrong file deletion bug.

Critical Bug Fixed: When two files have identical filenames but different paths
(e.g., /Movie/file.mkv and /Movie (2025)/file.mkv), the service must match by
FULL PATH, not just filename, to avoid deleting the wrong file.
"""

import pytest
from unittest.mock import AsyncMock

from app.services.radarr_service import RadarrService
from app.models.config import Config


@pytest.fixture
def mock_radarr_client():
    """Mock RadarrClient"""
    client = AsyncMock()
    return client


@pytest.fixture
async def radarr_service(test_db, mock_radarr_client):
    """Create RadarrService with mocked client"""
    # Add Radarr config to database
    test_db.add(Config(key="radarr_url", value="http://radarr:7878"))
    test_db.add(Config(key="radarr_api_key", value="test-api-key"))
    await test_db.commit()

    service = RadarrService(test_db)
    service._client = mock_radarr_client
    return service


@pytest.mark.asyncio
async def test_find_movie_by_exact_path_match(radarr_service, mock_radarr_client):
    """Test that find_movie_by_file_path matches by FULL PATH, not just filename"""
    # Two movies with SAME filename but DIFFERENT paths
    mock_radarr_client.get_movie = AsyncMock(
        return_value=[
            {
                "id": 1,
                "title": "Test Movie",
                "movieFile": {
                    "id": 10,
                    "path": "/data/movies/Test Movie (2025)/Test Movie 2024.mkv",
                },
            },
            {
                "id": 2,
                "title": "Another Movie",
                "movieFile": {
                    "id": 20,
                    "path": "/data/movies/Different Movie/file.mkv",
                },
            },
        ]
    )

    # Search for the file in the root directory (NOT in the (2025) folder)
    file_to_find = "/data/movies/Test Movie 2024.mkv"
    result = await radarr_service.find_movie_by_file_path(file_to_find)

    # Should return None because the path doesn't match exactly
    assert result is None


@pytest.mark.asyncio
async def test_find_movie_returns_correct_movie_for_exact_path(
    radarr_service, mock_radarr_client
):
    """Test that exact path match returns the correct movie"""
    mock_radarr_client.get_movie = AsyncMock(
        return_value=[
            {
                "id": 1,
                "title": "Test Movie",
                "movieFile": {
                    "id": 10,
                    "path": "/data/movies/Test Movie (2025)/Test Movie 2024.mkv",
                },
            },
            {
                "id": 2,
                "title": "Test Movie",
                "movieFile": {
                    "id": 20,
                    "path": "/data/movies/Test Movie 2024.mkv",  # Same filename, different path
                },
            },
        ]
    )

    # Search for the exact path of the second movie
    file_to_find = "/data/movies/Test Movie 2024.mkv"
    result = await radarr_service.find_movie_by_file_path(file_to_find)

    # Should return the second movie (ID: 2) because path matches exactly
    assert result is not None
    assert result["id"] == 2
    assert result["movieFile"]["id"] == 20


@pytest.mark.asyncio
async def test_find_movie_different_filenames_same_folder(
    radarr_service, mock_radarr_client
):
    """Test matching when different movies are in same folder"""
    mock_radarr_client.get_movie = AsyncMock(
        return_value=[
            {
                "id": 1,
                "title": "Movie A",
                "movieFile": {
                    "id": 10,
                    "path": "/data/movies/Movie A 2024 1080p.mkv",
                },
            },
            {
                "id": 2,
                "title": "Movie B",
                "movieFile": {
                    "id": 20,
                    "path": "/data/movies/Movie B 2024 1080p.mkv",
                },
            },
        ]
    )

    # Search for Movie A
    result = await radarr_service.find_movie_by_file_path(
        "/data/movies/Movie A 2024 1080p.mkv"
    )

    assert result is not None
    assert result["id"] == 1
    assert result["title"] == "Movie A"


@pytest.mark.asyncio
async def test_find_movie_no_match(radarr_service, mock_radarr_client):
    """Test that no match returns None"""
    mock_radarr_client.get_movie = AsyncMock(
        return_value=[
            {
                "id": 1,
                "title": "Some Movie",
                "movieFile": {
                    "id": 10,
                    "path": "/data/movies/Some Movie.mkv",
                },
            }
        ]
    )

    # Search for non-existent file
    result = await radarr_service.find_movie_by_file_path(
        "/data/movies/Non-existent Movie.mkv"
    )

    assert result is None


@pytest.mark.asyncio
async def test_find_movie_case_sensitive_path(radarr_service, mock_radarr_client):
    """Test that path matching is case-sensitive"""
    mock_radarr_client.get_movie = AsyncMock(
        return_value=[
            {
                "id": 1,
                "title": "Movie",
                "movieFile": {
                    "id": 10,
                    "path": "/data/movies/Movie.mkv",
                },
            }
        ]
    )

    # Different case in path
    result = await radarr_service.find_movie_by_file_path(
        "/data/movies/movie.mkv"  # lowercase (was /plexdownloads/filmer/)
    )

    # Should NOT match due to case difference
    assert result is None


@pytest.mark.asyncio
async def test_find_movie_without_movie_file(radarr_service, mock_radarr_client):
    """Test handling of movies without movieFile data"""
    mock_radarr_client.get_movie = AsyncMock(
        return_value=[
            {
                "id": 1,
                "title": "Movie Without File",
                # No movieFile key
            },
            {
                "id": 2,
                "title": "Movie With Null File",
                "movieFile": None,  # Null movieFile
            },
            {
                "id": 3,
                "title": "Movie With Empty File",
                "movieFile": {},  # Empty movieFile
            },
        ]
    )

    result = await radarr_service.find_movie_by_file_path("/data/movies/some-file.mkv")

    # Should return None gracefully without errors
    assert result is None


@pytest.mark.asyncio
async def test_deletion_bug_regression(radarr_service, mock_radarr_client):
    """
    Regression test for THE BUG: Deleting /Filmer/Movie.mkv should NOT match
    /Filmer/Movie (2025)/Movie.mkv even though they have the same filename.

    This is the exact scenario that caused both "Test Movie" files to be deleted.
    """
    # Radarr only knows about the file in the organized folder
    mock_radarr_client.get_movie = AsyncMock(
        return_value=[
            {
                "id": 220,
                "title": "Test Movie",
                "movieFile": {
                    "id": 186,
                    "path": "/data/movies/Test Movie (2025)/Test Movie 2024 Hybrid 2160p UHD BluRay TrueHD 7.1 Atmos DV HDR10+ x265-HiDt.mkv",
                },
            }
        ]
    )

    # We want to delete the root-level file (NOT the one Radarr knows about)
    file_to_delete = "/data/movies/Test Movie 2024 Hybrid 2160p UHD BluRay TrueHD 7.1 Atmos DV HDR10+ x265-HiDt.mkv"
    result = await radarr_service.find_movie_by_file_path(file_to_delete)

    # CRITICAL: Must return None because paths don't match exactly
    # If this returns a movie, we would delete the WRONG file (the one we want to keep)
    assert result is None, (
        "CRITICAL BUG: find_movie_by_file_path matched by filename instead of full path! "
        "This would cause deletion of the wrong file."
    )


@pytest.mark.asyncio
async def test_find_movie_with_special_characters(radarr_service, mock_radarr_client):
    """Test path matching with special characters in filenames"""
    mock_radarr_client.get_movie = AsyncMock(
        return_value=[
            {
                "id": 1,
                "title": "Movie: The Return",
                "movieFile": {
                    "id": 10,
                    "path": "/data/movies/Movie - The Return (2024)/Movie: The Return [2024] 1080p.mkv",
                },
            }
        ]
    )

    # Exact match should work
    result = await radarr_service.find_movie_by_file_path(
        "/data/movies/Movie - The Return (2024)/Movie: The Return [2024] 1080p.mkv"
    )

    assert result is not None
    assert result["id"] == 1
