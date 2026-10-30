"""
Tests for the path mappings between Radarr/Sonarr and the media server
"""

import json

import httpx
import pytest

from app.models.config import Config
from app.services.arr.client import RadarrClient
from app.services.arr.path_mapping import PathMapper
from app.services.arr.radarr_service import RadarrService
from app.services.arr.sonarr_service import SonarrService


def test_the_most_specific_mapping_wins_on_whole_directories():
    mapper = PathMapper.from_text("/data=/library\n/data/movies/=/movies/")

    assert mapper.to_media_server("/data/movies/a.mkv") == "/movies/a.mkv"
    assert mapper.to_media_server("/data/tv/a.mkv") == "/library/tv/a.mkv"
    assert mapper.to_media_server("/data2/a.mkv") == "/data2/a.mkv"
    assert mapper.to_arr("/movies/a.mkv") == "/data/movies/a.mkv"
    assert mapper.to_arr("/movies-4k/a.mkv") == "/movies-4k/a.mkv"
    assert not mapper.covers("/movies-4k")


def test_a_mapping_to_the_root_drops_a_common_prefix():
    mapper = PathMapper.from_text("/data=/")

    assert mapper.to_media_server("/data/movies/a.mkv") == "/movies/a.mkv"
    assert mapper.to_media_server("/data") == "/"
    assert mapper.to_arr("/movies/a.mkv") == "/data/movies/a.mkv"


def test_without_a_valid_mapping_there_is_nothing_to_translate(caplog):
    assert not PathMapper.from_text(None)
    assert not PathMapper.from_text("# Radarr\n\nnot a mapping\nrelative=/movies")
    assert caplog.text.count("Ignoring invalid path mapping") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mappings, seen", [("/data/movies=/movies", "/movies"), ("", "/data/movies")]
)
async def test_the_client_translates_what_it_sends_and_receives(mappings, seen):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.method == "PUT":
            return httpx.Response(202, json=json.loads(request.content))
        movie_file = {"path": "/data/movies/Film/a.mkv", "relativePath": "a.mkv"}
        return httpx.Response(
            200, json=[{"id": 1, "path": "/data/movies/Film", "movieFile": movie_file}]
        )

    client = RadarrClient(
        base_url="http://radarr",
        api_key="key",
        path_mapper=PathMapper.from_text(mappings),
    )
    client._client = httpx.AsyncClient(
        base_url="http://radarr/api/v3", transport=httpx.MockTransport(handler)
    )

    [movie] = await client.get_movie()
    await client.get_manual_import(folder=f"{seen}/Film")
    await client.update_movie(movie)

    assert movie["path"] == f"{seen}/Film"
    assert movie["movieFile"] == {"path": f"{seen}/Film/a.mkv", "relativePath": "a.mkv"}
    assert sent[1].url.params["folder"] == "/data/movies/Film"
    assert json.loads(sent[2].content)["movieFile"]["path"] == "/data/movies/Film/a.mkv"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "service_class, name", [(RadarrService, "radarr"), (SonarrService, "sonarr")]
)
async def test_services_give_their_client_the_stored_mappings(
    test_db, service_class, name
):
    test_db.add_all(
        [
            Config(key=f"{name}_url", value="http://arr"),
            Config(key=f"{name}_api_key", value="key"),
            Config(key=f"{name}_path_mappings", value="/data=/"),
        ]
    )
    await test_db.commit()

    client = await service_class(test_db)._get_client()

    assert client.path_mapper.to_arr("/tv/a.mkv") == "/data/tv/a.mkv"
