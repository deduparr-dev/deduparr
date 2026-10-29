"""
Tests for arr_helpers module
"""

import logging
import os
from unittest.mock import create_autospec

import pytest

from app.services.arr.client import RadarrClient, SonarrClient
from app.services.arr.helpers import rescan_media_item

LOG = logging.getLogger("test")


def _radarr(path: str = "/movies/Test Movie (2024)", root: str = "/movies/"):
    client = create_autospec(RadarrClient, instance=True)
    client.get_movie.return_value = {
        "id": 1,
        "title": "Test Movie",
        "year": 2024,
        "path": path,
    }
    client.get_root_folder.return_value = [{"path": root}]
    return client


@pytest.mark.asyncio
async def test_rescan_media_item_rescans_the_movie_holding_the_kept_file():
    """
    Radarr re-reads the movie's folder, which imports the kept file.

    The import scan used before refuses a folder that belongs to a movie, so
    it never imported anything.
    """
    client = _radarr()

    await rescan_media_item(client, 1, "/movies/Test Movie (2024)/movie.mkv", LOG)

    client.update_movie.assert_not_awaited()
    client.post_command.assert_awaited_once_with("RescanMovie", movieId=1)


@pytest.mark.asyncio
async def test_rescan_media_item_points_the_movie_at_a_kept_file_elsewhere():
    """A kept file outside the movie's folder moves the movie there first."""
    client = _radarr(path="/movies/Old Path")

    await rescan_media_item(client, 1, "/movies/New Path/movie.mkv", LOG)

    client.update_movie.assert_awaited_once()
    assert client.update_movie.await_args.args[0]["path"] == "/movies/New Path"
    client.post_command.assert_awaited_once_with("RescanMovie", movieId=1)


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
    client.get_root_folder.return_value = [{"path": "/tv/"}]

    await rescan_media_item(
        client, 1, "/tv/Test Series (2024)/Season 1/S01E01.mkv", LOG
    )

    client.update_series.assert_not_awaited()
    client.post_command.assert_awaited_once_with("RescanSeries", seriesId=1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client_class, command",
    [(RadarrClient, "RescanMovie"), (SonarrClient, "RescanSeries")],
)
async def test_rescan_media_item_without_an_item_rescans_the_whole_library(
    client_class, command
):
    """
    The *arr tracked neither file, yet it may hold one under a path of its own
    mount, so every movie or series is re-read from disk.
    """
    client = create_autospec(client_class, instance=True)

    await rescan_media_item(client, None, "/media/Movie (2020)/movie.mkv", LOG)

    client.post_command.assert_awaited_once_with(command)


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
    client = _radarr(
        path=str(root / "Test Movie (2024)"), root=stored_as.format(root=root)
    )

    with pytest.raises(ValueError, match="sits directly in the root folder"):
        await rescan_media_item(client, 1, str(kept), LOG)

    assert os.listdir(root) == [kept.name]
    client.update_movie.assert_not_awaited()
    client.post_command.assert_not_awaited()
