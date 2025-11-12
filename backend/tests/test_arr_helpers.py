"""
Tests for arr_helpers module
"""

import logging
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.arr_helpers import (
    rescan_media_item,
    trigger_full_library_scan,
    _create_media_subfolder,
)


@pytest.mark.asyncio
async def test_rescan_media_item_movie_with_kept_file():
    """Test rescanning a movie with a kept file path"""
    mock_client = MagicMock()
    mock_client.get_movie = AsyncMock(
        return_value={
            "id": 1,
            "title": "Test Movie",
            "year": 2024,
            "path": "/movies/Test Movie (2024)",
        }
    )
    mock_client.get_root_folder = AsyncMock(return_value=[{"path": "/movies"}])
    mock_client.post_command = AsyncMock()

    logger = logging.getLogger("test")

    result = await rescan_media_item(
        client=mock_client,
        media_id=1,
        media_type="movie",
        kept_file_path="/movies/Test Movie (2024)/movie.mkv",
        logger_instance=logger,
    )

    assert result is True
    mock_client.get_movie.assert_called_once_with(1)
    mock_client.post_command.assert_called_once_with(
        "DownloadedMoviesScan", path="/movies/Test Movie (2024)"
    )


@pytest.mark.asyncio
async def test_rescan_media_item_series_with_kept_file():
    """Test rescanning a series with a kept file path"""
    mock_client = MagicMock()
    mock_client.get_series = AsyncMock(
        return_value={
            "id": 1,
            "title": "Test Series",
            "year": 2024,
            "path": "/tv/Test Series (2024)",
        }
    )
    mock_client.get_root_folder = AsyncMock(return_value=[{"path": "/tv"}])
    mock_client.post_command = AsyncMock()

    logger = logging.getLogger("test")

    result = await rescan_media_item(
        client=mock_client,
        media_id=1,
        media_type="series",
        kept_file_path="/tv/Test Series (2024)/S01E01.mkv",
        logger_instance=logger,
    )

    assert result is True
    mock_client.get_series.assert_called_once_with(1)
    mock_client.post_command.assert_called_once_with(
        "DownloadedEpisodesScan", path="/tv/Test Series (2024)"
    )


@pytest.mark.asyncio
async def test_rescan_media_item_without_kept_file():
    """Test rescanning when no kept file path is provided"""
    mock_client = MagicMock()
    mock_client.get_movie = AsyncMock(
        return_value={
            "id": 1,
            "title": "Test Movie",
            "year": 2024,
            "path": "/movies/Test Movie (2024)",
        }
    )
    mock_client.post_command = AsyncMock()

    logger = logging.getLogger("test")

    result = await rescan_media_item(
        client=mock_client,
        media_id=1,
        media_type="movie",
        kept_file_path=None,
        logger_instance=logger,
    )

    assert result is True
    mock_client.post_command.assert_called_once_with(
        "DownloadedMoviesScan", path="/movies/Test Movie (2024)"
    )


@pytest.mark.asyncio
async def test_rescan_media_item_path_mismatch():
    """Test that path is updated when it doesn't match the kept file's directory"""
    mock_client = MagicMock()
    mock_client.get_movie = AsyncMock(
        return_value={
            "id": 1,
            "title": "Test Movie",
            "year": 2024,
            "path": "/movies/Old Path",
        }
    )
    mock_client.get_root_folder = AsyncMock(return_value=[{"path": "/movies"}])
    mock_client.update_movie = AsyncMock()
    mock_client.post_command = AsyncMock()

    logger = logging.getLogger("test")

    result = await rescan_media_item(
        client=mock_client,
        media_id=1,
        media_type="movie",
        kept_file_path="/movies/New Path/movie.mkv",
        logger_instance=logger,
    )

    assert result is True
    mock_client.update_movie.assert_called_once()
    updated_movie = mock_client.update_movie.call_args[1]["data"]
    assert updated_movie["path"] == "/movies/New Path"


@pytest.mark.asyncio
async def test_rescan_media_item_media_not_found():
    """Test error handling when media item is not found"""
    mock_client = MagicMock()
    mock_client.get_movie = AsyncMock(return_value=None)

    logger = logging.getLogger("test")

    result = await rescan_media_item(
        client=mock_client,
        media_id=999,
        media_type="movie",
        kept_file_path=None,
        logger_instance=logger,
    )

    assert result is False


@pytest.mark.asyncio
async def test_trigger_full_library_scan_movie():
    """Test triggering full library scan for movies"""
    mock_client = MagicMock()
    mock_client.get_root_folder = AsyncMock(
        return_value=[
            {"path": "/movies"},
            {"path": "/movies2"},
        ]
    )
    mock_client.post_command = AsyncMock()

    logger = logging.getLogger("test")

    result = await trigger_full_library_scan(
        client=mock_client, media_type="movie", logger_instance=logger
    )

    assert result is True
    assert mock_client.post_command.call_count == 2
    mock_client.post_command.assert_any_call("DownloadedMoviesScan", path="/movies")
    mock_client.post_command.assert_any_call("DownloadedMoviesScan", path="/movies2")


@pytest.mark.asyncio
async def test_trigger_full_library_scan_series():
    """Test triggering full library scan for series"""
    mock_client = MagicMock()
    mock_client.get_root_folder = AsyncMock(return_value=[{"path": "/tv"}])
    mock_client.post_command = AsyncMock()

    logger = logging.getLogger("test")

    result = await trigger_full_library_scan(
        client=mock_client, media_type="series", logger_instance=logger
    )

    assert result is True
    mock_client.post_command.assert_called_once_with(
        "DownloadedEpisodesScan", path="/tv"
    )


def test_create_media_subfolder_success():
    """Test creating media subfolder and moving file"""
    logger = logging.getLogger("test")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test file
        test_file = os.path.join(tmpdir, "movie.mkv")
        with open(test_file, "w") as f:
            f.write("test content")

        media_item = {"title": "Test Movie", "year": 2024}

        result = _create_media_subfolder(
            media_item=media_item,
            media_type="movie",
            library_root=tmpdir,
            kept_file_path=test_file,
            logger_instance=logger,
        )

        expected_folder = os.path.join(tmpdir, "Test Movie (2024)")
        assert result == expected_folder
        assert os.path.exists(expected_folder)
        assert os.path.exists(os.path.join(expected_folder, "movie.mkv"))
        assert not os.path.exists(test_file)


def test_create_media_subfolder_special_characters():
    """Test creating subfolder with special characters in title"""
    logger = logging.getLogger("test")

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "movie.mkv")
        with open(test_file, "w") as f:
            f.write("test content")

        media_item = {"title": 'Test: "Movie" <2024>', "year": 2024}

        result = _create_media_subfolder(
            media_item=media_item,
            media_type="movie",
            library_root=tmpdir,
            kept_file_path=test_file,
            logger_instance=logger,
        )

        # Special characters should be removed
        expected_folder = os.path.join(tmpdir, "Test Movie 2024 (2024)")
        assert result == expected_folder
        assert os.path.exists(expected_folder)


def test_create_media_subfolder_no_year():
    """Test creating subfolder when year is not available"""
    logger = logging.getLogger("test")

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "series.mkv")
        with open(test_file, "w") as f:
            f.write("test content")

        media_item = {"title": "Test Series", "year": ""}

        result = _create_media_subfolder(
            media_item=media_item,
            media_type="series",
            library_root=tmpdir,
            kept_file_path=test_file,
            logger_instance=logger,
        )

        expected_folder = os.path.join(tmpdir, "Test Series")
        assert result == expected_folder
        assert os.path.exists(expected_folder)
