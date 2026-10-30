"""
Tests for translating paths between Radarr/Sonarr and Plex
"""

import json

import httpx
import pytest

from app.services.arr.client import RadarrClient
from app.services.arr.path_mapping import PathMapper


def test_to_plex_and_to_arr_replace_the_directory_prefix():
    mapper = PathMapper([("/data/movies", "/movies")])

    assert mapper.to_plex("/data/movies/Film (2020)/Film.mkv") == (
        "/movies/Film (2020)/Film.mkv"
    )
    assert mapper.to_arr("/movies/Film (2020)/Film.mkv") == (
        "/data/movies/Film (2020)/Film.mkv"
    )


def test_prefix_matches_whole_directories_only():
    mapper = PathMapper([("/data/movies", "/movies")])

    assert mapper.to_plex("/data/movies-4k/Film.mkv") == "/data/movies-4k/Film.mkv"
    assert mapper.to_plex("/data/movies") == "/movies"
    assert mapper.to_plex("/elsewhere/Film.mkv") == "/elsewhere/Film.mkv"


def test_trailing_slashes_are_ignored():
    mapper = PathMapper([("/data/movies/", "/movies/")])

    assert mapper.to_plex("/data/movies/Film.mkv") == "/movies/Film.mkv"
    assert mapper.to_arr("/movies/Film.mkv") == "/data/movies/Film.mkv"


def test_most_specific_mapping_wins():
    mapper = PathMapper([("/data", "/library"), ("/data/movies", "/movies")])

    assert mapper.to_plex("/data/movies/Film.mkv") == "/movies/Film.mkv"
    assert mapper.to_plex("/data/series/Show.mkv") == "/library/series/Show.mkv"
    assert mapper.to_arr("/movies/Film.mkv") == "/data/movies/Film.mkv"


def test_root_mapping_strips_a_common_prefix():
    mapper = PathMapper([("/data", "/")])

    assert mapper.to_plex("/data/movies/Film.mkv") == "/movies/Film.mkv"
    assert mapper.to_plex("/data") == "/"
    assert mapper.to_arr("/movies/Film.mkv") == "/data/movies/Film.mkv"


def test_from_text_parses_lines_and_ignores_invalid_ones(caplog):
    mapper = PathMapper.from_text(
        "# Radarr\n/data/movies=/movies\n\n  /data/cartoons = /cartoons  \nnot a mapping\nrelative=/x\n"
    )

    assert mapper.to_plex("/data/movies/a.mkv") == "/movies/a.mkv"
    assert mapper.to_plex("/data/cartoons/b.mkv") == "/cartoons/b.mkv"
    assert caplog.text.count("Ignoring invalid path mapping") == 2


def test_from_text_without_mappings_is_empty():
    assert PathMapper.from_text(None).is_empty
    assert PathMapper.from_text("   \n# nothing").is_empty


def test_translate_only_touches_path_keys_recursively():
    mapper = PathMapper([("/data/movies", "/movies")])
    response = [
        {
            "id": 1,
            "title": "/data/movies is not a path here",
            "path": "/data/movies/Film (2020)",
            "movieFile": {
                "path": "/data/movies/Film (2020)/Film.mkv",
                "relativePath": "Film.mkv",
            },
            "unmappedFolders": [{"name": "x", "path": "/data/movies/x"}],
        }
    ]

    assert mapper.translate_to_plex(response) == [
        {
            "id": 1,
            "title": "/data/movies is not a path here",
            "path": "/movies/Film (2020)",
            "movieFile": {
                "path": "/movies/Film (2020)/Film.mkv",
                "relativePath": "Film.mkv",
            },
            "unmappedFolders": [{"name": "x", "path": "/movies/x"}],
        }
    ]


def test_translate_to_arr_covers_params_and_command_bodies():
    mapper = PathMapper([("/data/movies", "/movies")])

    assert mapper.translate_to_arr({"folder": "/movies/Film", "movieId": 3}) == {
        "folder": "/data/movies/Film",
        "movieId": 3,
    }
    assert mapper.translate_to_arr(
        {"name": "ManualImport", "files": [{"path": "/movies/Film/a.mkv"}]}
    ) == {"name": "ManualImport", "files": [{"path": "/data/movies/Film/a.mkv"}]}
    assert mapper.translate_to_arr(None) is None


@pytest.mark.asyncio
async def test_client_translates_requests_and_responses():
    """End to end through the HTTP layer: Plex paths in, Plex paths out"""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/movie"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 42,
                        "path": "/data/movies/Film (2020)",
                        "movieFile": {"path": "/data/movies/Film (2020)/Film.mkv"},
                    }
                ],
            )
        return httpx.Response(200, json={"id": 7})

    client = RadarrClient(
        base_url="http://radarr:7878",
        api_key="key",
        path_mapper=PathMapper([("/data/movies", "/movies")]),
    )
    client._client = httpx.AsyncClient(
        base_url="http://radarr:7878/api/v3",
        transport=httpx.MockTransport(handler),
    )

    movies = await client.get_movie()
    await client.get_manual_import(folder="/movies/Film (2020)", movie_id=42)
    await client.post_command("DownloadedMoviesScan", path="/movies/Film (2020)")

    assert movies[0]["path"] == "/movies/Film (2020)"
    assert movies[0]["movieFile"]["path"] == "/movies/Film (2020)/Film.mkv"
    assert seen[1].url.params["folder"] == "/data/movies/Film (2020)"
    assert json.loads(seen[2].content) == {
        "name": "DownloadedMoviesScan",
        "path": "/data/movies/Film (2020)",
    }


@pytest.mark.asyncio
async def test_client_without_mapper_leaves_paths_untouched():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": 1, "path": "/data/movies/Film"}])

    client = RadarrClient(base_url="http://radarr:7878", api_key="key")
    client._client = httpx.AsyncClient(
        base_url="http://radarr:7878/api/v3", transport=httpx.MockTransport(handler)
    )

    assert (await client.get_movie())[0]["path"] == "/data/movies/Film"


def _radarr_with_data_mount() -> RadarrClient:
    """A Radarr that sees the library under /data, while Plex sees it under /movies"""
    profile = {
        "id": 4,
        "items": [
            {"quality": {"id": 3, "name": "WEBDL-1080p"}, "items": []},
            {"quality": {"id": 7, "name": "Bluray-1080p"}, "items": []},
        ],
        "formatItems": [],
    }

    def quality(quality_id: int, name: str) -> dict:
        return {
            "quality": {"id": quality_id, "name": name},
            "revision": {"version": 1, "real": 0},
        }

    def handler(request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.removeprefix("/api/v3")
        if endpoint == "/movie":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 42,
                        "title": "Film",
                        "path": "/data/movies/Film (2020)",
                        "qualityProfileId": 4,
                        "movieFile": {
                            "path": "/data/movies/Film (2020)/Film.WEBDL-1080p.mkv"
                        },
                    }
                ],
            )
        if endpoint == "/qualityprofile/4":
            return httpx.Response(200, json=profile)
        if endpoint == "/moviefile":
            return httpx.Response(
                200,
                json=[
                    {
                        "path": "/data/movies/Film (2020)/Film.WEBDL-1080p.mkv",
                        "quality": quality(3, "WEBDL-1080p"),
                        "customFormatScore": 0,
                    }
                ],
            )
        if endpoint == "/manualimport":
            assert request.url.params["folder"] == "/data/movies/Film (2020)/extra"
            return httpx.Response(
                200,
                json=[
                    {
                        "path": "/data/movies/Film (2020)/extra/Film.Bluray-1080p.mkv",
                        "quality": quality(7, "Bluray-1080p"),
                        "customFormatScore": 0,
                    }
                ],
            )
        return httpx.Response(404)

    client = RadarrClient(
        base_url="http://radarr:7878",
        api_key="key",
        path_mapper=PathMapper.from_text("/data=/"),
    )
    client._client = httpx.AsyncClient(
        base_url="http://radarr:7878/api/v3", transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_plex_paths_find_the_movie_in_a_radarr_with_a_different_mount():
    from app.services.arr.helpers import find_movie_by_file_path
    import logging

    movie = await find_movie_by_file_path(
        _radarr_with_data_mount(),
        "/movies/Film (2020)/Film.WEBDL-1080p.mkv",
        logging.getLogger("test"),
    )

    assert movie["id"] == 42


@pytest.mark.asyncio
async def test_quality_ranking_works_with_different_mounts(test_db):
    from unittest.mock import AsyncMock, patch

    from app.models.duplicate import MediaType
    from app.services.arr.quality import ArrQualityRanker

    ranker = ArrQualityRanker(test_db)
    tracked = "/movies/Film (2020)/Film.WEBDL-1080p.mkv"
    untracked = "/movies/Film (2020)/extra/Film.Bluray-1080p.mkv"

    with patch.object(
        ranker.radarr_service,
        "_get_client",
        AsyncMock(return_value=_radarr_with_data_mount()),
    ):
        qualities = await ranker.evaluate(MediaType.MOVIE, [tracked, untracked])

    assert qualities[tracked].quality_name == "WEBDL-1080p"
    assert qualities[untracked].quality_name == "Bluray-1080p"
    assert qualities[untracked].quality_rank > qualities[tracked].quality_rank
