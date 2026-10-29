"""
Tests for arr_helpers module
"""

import logging
import os
from unittest.mock import AsyncMock, MagicMock, call, create_autospec, patch

import pytest

from app.services.arr.client import RadarrClient, SonarrClient
from app.services.arr.helpers import (
    manual_import_file,
    rescan_media_item,
    trigger_full_library_scan,
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
    """
    A kept file outside the movie's folder moves the movie there.

    The client is spec'd so a call it would reject fails here too: a plain
    mock accepted update_movie(data=...), which the real client turns down.
    """
    client = create_autospec(RadarrClient, instance=True)
    client.get_movie.return_value = {
        "id": 1,
        "title": "Test Movie",
        "year": 2024,
        "path": "/movies/Old Path",
    }
    client.get_root_folder.return_value = [{"path": "/movies"}]

    result = await rescan_media_item(
        client=client,
        media_id=1,
        media_type="movie",
        kept_file_path="/movies/New Path/movie.mkv",
        logger_instance=logging.getLogger("test"),
    )

    assert result is True
    client.update_movie.assert_awaited_once()
    assert client.update_movie.await_args.args[0]["path"] == "/movies/New Path"


@pytest.mark.asyncio
async def test_rescan_media_item_keeps_a_series_path_over_its_season_folder():
    """
    Episodes live in season folders inside the series folder. That is not a
    path mismatch, and the series must not be moved into its own season.
    """
    client = create_autospec(SonarrClient, instance=True)
    client.get_series.return_value = {
        "id": 1,
        "title": "Test Series",
        "path": "/tv/Test Series (2024)",
    }
    client.get_root_folder.return_value = [{"path": "/tv"}]

    result = await rescan_media_item(
        client=client,
        media_id=1,
        media_type="series",
        kept_file_path="/tv/Test Series (2024)/Season 1/S01E01.mkv",
        logger_instance=logging.getLogger("test"),
    )

    assert result is True
    client.update_series.assert_not_awaited()
    client.post_command.assert_awaited_once_with(
        "DownloadedEpisodesScan", path="/tv/Test Series (2024)/Season 1"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_as", ["{root}", "{root}/"])
async def test_rescan_media_item_leaves_a_kept_file_in_a_root_folder(
    tmp_path, stored_as
):
    """
    Radarr cannot import a file that sits directly in a root folder, so the
    kept file stays where it is and the user is told why.

    A root folder picked in Radarr's folder browser is stored with a trailing
    slash. That form was not recognised, so the movie was pointed at the root
    folder, which Radarr refuses; the other form moved the kept file.
    """
    root = tmp_path / "movies"
    root.mkdir()
    kept = root / "Test Movie (2024).mkv"
    kept.write_text("x")
    client = create_autospec(RadarrClient, instance=True)
    client.get_movie.return_value = {
        "id": 1,
        "title": "Test Movie",
        "year": 2024,
        "path": str(root / "Test Movie (2024)"),
    }
    client.get_root_folder.return_value = [{"path": stored_as.format(root=root)}]

    with pytest.raises(ValueError, match="sits directly in the root folder"):
        await rescan_media_item(
            client=client,
            media_id=1,
            media_type="movie",
            kept_file_path=str(kept),
            logger_instance=logging.getLogger("test"),
        )

    assert os.listdir(root) == [kept.name]
    client.update_movie.assert_not_awaited()
    client.post_command.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_manual_import_file_movie_queues_import(tmp_path):
    """Manual import scans the file's folder, then queues a ManualImport command"""
    media_file = tmp_path / "Film.2020.1080p.mkv"
    media_file.write_bytes(b"x")
    client = RadarrClient(base_url="http://radarr:7878", api_key="key")
    request = AsyncMock(
        side_effect=[
            [
                {
                    "path": str(media_file),
                    "quality": {"quality": {"id": 7}},
                    "languages": [{"id": 1}],
                    "releaseGroup": "GRP",
                }
            ],
            {"id": 99},
        ]
    )

    with patch.object(client, "_request", request):
        result = await manual_import_file(
            client, str(media_file), 42, "movie", logging.getLogger("test")
        )

    assert result is True
    assert request.await_args_list[0] == call(
        "GET",
        "/manualimport",
        params={"folder": str(tmp_path), "filterExistingFiles": True, "movieId": 42},
    )
    assert request.await_args_list[1] == call(
        "POST",
        "/command",
        json_data={
            "name": "ManualImport",
            "files": [
                {
                    "path": str(media_file),
                    "movieId": 42,
                    "quality": {"quality": {"id": 7}},
                    "languages": [{"id": 1}],
                    "releaseGroup": "GRP",
                }
            ],
            "importMode": "Move",
        },
    )


@pytest.mark.asyncio
async def test_manual_import_file_series_queues_import(tmp_path):
    """Series manual import filters by seriesId and sends the matched episode IDs"""
    media_file = tmp_path / "Show.S01E01.1080p.mkv"
    media_file.write_bytes(b"x")
    client = SonarrClient(base_url="http://sonarr:8989", api_key="key")
    request = AsyncMock(
        side_effect=[
            [
                {
                    "path": str(media_file),
                    "quality": {"quality": {"id": 7}},
                    "episodes": [{"id": 5}, {"id": 6}],
                }
            ],
            {"id": 100},
        ]
    )

    with patch.object(client, "_request", request):
        result = await manual_import_file(
            client, str(media_file), 7, "series", logging.getLogger("test")
        )

    assert result is True
    assert request.await_args_list[0] == call(
        "GET",
        "/manualimport",
        params={"folder": str(tmp_path), "filterExistingFiles": True, "seriesId": 7},
    )
    command = request.await_args_list[1].kwargs["json_data"]
    assert command["name"] == "ManualImport"
    assert command["files"][0]["seriesId"] == 7
    assert command["files"][0]["episodeIds"] == [5, 6]
