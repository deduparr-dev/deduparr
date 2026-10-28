"""Tests for the media server contract and its two adapters"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import Config
from app.services.media_server import (
    MediaServerType,
    configured_types,
    get_media_servers,
)
from app.services.media_server.file_probe import (
    DEFAULT_SAMPLE_PATTERNS,
    SERVER_SAMPLE_PATTERNS,
    is_sample_file,
    probe_file,
)
from app.services.media_server.jellyfin_adapter import JellyfinAdapter
from app.services.media_server.plex_adapter import PlexAdapter


def test_server_patterns_do_not_discard_titles_containing_extra():
    """
    The disk scanner matches release extras, which a media server never lists.

    Applying the broad list to a server would throw away "Extraction" because
    the path contains "extra", so the two sets stay separate.
    """
    path = "/movies/Extraction (2020)/Extraction (2020) 1080p.mkv"

    assert is_sample_file(path, SERVER_SAMPLE_PATTERNS) is False
    assert is_sample_file(path, DEFAULT_SAMPLE_PATTERNS) is True
    assert is_sample_file("/movies/Thing/Thing-sample.mkv", SERVER_SAMPLE_PATTERNS)
    assert is_sample_file("", SERVER_SAMPLE_PATTERNS) is False


def test_probe_file_reports_what_the_filesystem_knows(tmp_path):
    real = tmp_path / "movie.mkv"
    real.write_bytes(b"x" * 2048)
    link = tmp_path / "movie.hardlink.mkv"
    os.link(real, link)

    probe = probe_file(str(real))
    assert (probe.exists, probe.size, probe.is_hardlink) == (True, 2048, True)
    assert probe.inode == os.stat(real).st_ino

    missing = probe_file(str(tmp_path / "gone.mkv"))
    assert (missing.exists, missing.size, missing.inode, missing.is_hardlink) == (
        False,
        0,
        None,
        False,
    )


@pytest.mark.asyncio
async def test_configured_types_follows_the_stored_credentials(test_db):
    """A server counts as configured once its credentials are present."""
    assert await configured_types(test_db) == []

    test_db.add(Config(key="plex_auth_token", value="token"))
    await test_db.commit()
    assert await configured_types(test_db) == [MediaServerType.PLEX]

    # A url on its own is not enough; Jellyfin also needs its key
    test_db.add(Config(key="jellyfin_url", value="http://jellyfin:8096"))
    await test_db.commit()
    assert await configured_types(test_db) == [MediaServerType.PLEX]

    test_db.add(Config(key="jellyfin_api_key", value="key"))
    await test_db.commit()
    assert set(await configured_types(test_db)) == {
        MediaServerType.PLEX,
        MediaServerType.JELLYFIN,
    }

    servers = await get_media_servers(test_db)
    assert {server.type for server in servers} == {
        MediaServerType.PLEX,
        MediaServerType.JELLYFIN,
    }


def _plex_media(path, size, resolution, codec="h264", width=1920, height=1080):
    part = MagicMock(file=path, size=size)
    return MagicMock(
        parts=[part],
        videoResolution=resolution,
        videoCodec=codec,
        audioCodec="aac",
        bitrate=5000,
        width=width,
        height=height,
    )


@pytest.mark.asyncio
async def test_plex_adapter_groups_multi_version_movies(test_db, tmp_path):
    """One Plex movie holding several files becomes one duplicate group."""
    good = tmp_path / "Movie 1080p.mkv"
    bad = tmp_path / "Movie 720p.mkv"
    good.write_bytes(b"g" * 100)
    bad.write_bytes(b"b" * 50)

    movie = MagicMock(title="A Movie", year=2024, ratingKey=77)
    movie.media = [
        _plex_media(str(good), 100, "1080p"),
        _plex_media(str(bad), 50, "720p", height=720, width=1280),
        _plex_media(str(tmp_path / "Movie-sample.mkv"), 1, "480p"),
    ]
    library = MagicMock()
    library.all.return_value = [movie]
    library.search.return_value = []

    adapter = PlexAdapter(test_db)
    with patch.object(adapter, "_library", return_value=library):
        groups = await adapter.find_duplicate_movies("Movies")

    assert len(groups) == 1
    group = groups[0]
    assert (group.item_id, group.title) == ("77", "A Movie")
    # the sample is left out, and the real files carry their inode
    assert [f.file_path for f in group.files] == [str(good), str(bad)]
    assert all(f.inode is not None for f in group.files)
    assert group.files[0].resolution == "1080p"


@pytest.mark.asyncio
async def test_plex_adapter_ignores_single_file_movies(test_db, tmp_path):
    """A movie with one playable file is not a duplicate."""
    only = tmp_path / "Solo.mkv"
    only.write_bytes(b"s")

    movie = MagicMock(title="Solo", year=2024, ratingKey=1)
    movie.media = [_plex_media(str(only), 1, "1080p")]
    library = MagicMock()
    library.all.return_value = [movie]
    library.search.return_value = []

    adapter = PlexAdapter(test_db)
    with patch.object(adapter, "_library", return_value=library):
        assert await adapter.find_duplicate_movies("Movies") == []


@pytest.mark.asyncio
async def test_plex_adapter_titles_episodes_with_season_and_number(test_db, tmp_path):
    first = tmp_path / "ep 1080p.mkv"
    second = tmp_path / "ep 720p.mkv"
    first.write_bytes(b"1")
    second.write_bytes(b"2")

    episode = MagicMock(
        title="Pilot",
        ratingKey=9,
        grandparentTitle="Example Show",
        seasonNumber=1,
        episodeNumber=2,
    )
    episode.media = [
        _plex_media(str(first), 1, "1080p"),
        _plex_media(str(second), 1, "720p"),
    ]
    library = MagicMock()
    library.search.return_value = [episode]

    adapter = PlexAdapter(test_db)
    with patch.object(adapter, "_library", return_value=library):
        groups = await adapter.find_duplicate_episodes("Shows")

    assert groups[0].title == "Example Show - S01E02 - Pilot"


# Shaped after a live Jellyfin 12.4.0 response
JELLYFIN_MOVIE = {
    "Id": "edb393",
    "Name": "A Movie",
    "Type": "Movie",
    "MediaSources": [
        {
            "Path": "/media/Movies/A Movie/A Movie 1080p.mkv",
            "Protocol": "File",
            "Size": 580255636,
            "Bitrate": 831282,
            "MediaStreams": [
                {"Type": "Video", "Codec": "h264", "Width": 1920, "Height": 1080},
                {"Type": "Audio", "Codec": "aac"},
            ],
        },
        {
            "Path": "/media/Movies/A Movie/A Movie 480p.mkv",
            "Protocol": "File",
            "Size": 100,
            "Bitrate": 1000,
            "MediaStreams": [
                {"Type": "Video", "Codec": "mpeg4", "Width": 640, "Height": 480},
                {"Type": "Audio", "Codec": "mp3"},
            ],
        },
        {"Path": "/media/Movies/A Movie/A Movie-sample.mkv", "Protocol": "File"},
        {"Path": "http://jellyfin/stream", "Protocol": "Http"},
    ],
}


def test_jellyfin_adapter_maps_media_sources():
    """Each real file of an item becomes one MediaMetadata."""
    files = JellyfinAdapter._collect_files(JELLYFIN_MOVIE)

    assert [f.file_path.rsplit("/", 1)[-1] for f in files] == [
        "A Movie 1080p.mkv",
        "A Movie 480p.mkv",
    ]
    best = files[0]
    assert (best.file_size, best.bitrate) == (580255636, 831282)
    assert (best.video_codec, best.audio_codec) == ("h264", "aac")
    assert (best.width, best.height) == (1920, 1080)
    # Jellyfin reports no resolution label, so scoring derives it from height
    assert best.resolution is None


def test_jellyfin_adapter_titles_items():
    assert JellyfinAdapter._title(JELLYFIN_MOVIE) == "A Movie"

    episode = {
        "Id": "e1",
        "Type": "Episode",
        "Name": "Pilot",
        "SeriesName": "Example Show",
        "ParentIndexNumber": 1,
        "IndexNumber": 2,
    }
    assert JellyfinAdapter._title(episode) == "Example Show - S01E02 - Pilot"

    # A special with no numbering still gets a usable title
    assert (
        JellyfinAdapter._title({**episode, "ParentIndexNumber": None})
        == "Example Show - Pilot"
    )


@pytest.mark.asyncio
async def test_jellyfin_adapter_requires_an_admin_key(test_db):
    """A key without admin rights cannot list libraries, and says so."""
    adapter = JellyfinAdapter(test_db)
    adapter._api = MagicMock()
    adapter._api._get = MagicMock(return_value={"Error": "Forbidden"})

    from app.services.media_server.base import MediaServerError

    with pytest.raises(MediaServerError, match="administrator"):
        await adapter.get_libraries()


@pytest.mark.asyncio
async def test_jellyfin_adapter_reads_libraries_and_paths(test_db):
    adapter = JellyfinAdapter(test_db)
    adapter._libraries = [
        {
            "Name": "Movies",
            "CollectionType": "movies",
            "ItemId": "lib-1",
            "Locations": ["/media/movies"],
        },
        {"Name": "Music", "CollectionType": "music", "ItemId": "lib-2"},
    ]
    adapter._count_items = AsyncMock(return_value=11)

    libraries = await adapter.get_libraries()

    # Music is not something Deduparr deduplicates
    assert [lib["title"] for lib in libraries] == ["Movies"]
    assert libraries[0]["type"] == "movie"
    assert libraries[0]["count"] == 11
    assert await adapter.get_library_paths("Movies") == ["/media/movies"]


@pytest.mark.asyncio
async def test_selected_libraries_is_per_server(test_db):
    """
    Each server has its own selection, under its own key.

    Two servers can hold libraries of the same name, and a user running both
    may want only one of them scanned, so one shared list cannot express it.
    """
    from app.services.media_server import libraries_config_key, selected_libraries

    assert libraries_config_key(MediaServerType.PLEX) == "plex_libraries"
    assert libraries_config_key(MediaServerType.JELLYFIN) == "jellyfin_libraries"

    assert await selected_libraries(test_db, MediaServerType.PLEX) == []

    test_db.add_all(
        [
            Config(key="plex_libraries", value="Movies, TV Shows ,"),
            Config(key="jellyfin_libraries", value="Films"),
        ]
    )
    await test_db.commit()

    # Whitespace trimmed and empty entries dropped
    assert await selected_libraries(test_db, MediaServerType.PLEX) == [
        "Movies",
        "TV Shows",
    ]
    assert await selected_libraries(test_db, MediaServerType.JELLYFIN) == ["Films"]


@pytest.mark.asyncio
async def test_plex_adapter_builds_the_service_from_stored_credentials(test_db):
    """
    The adapter must pass the stored token to PlexService, not its session.

    PlexService takes (encrypted_token, server_name) positionally, so handing
    it the database session put an AsyncSession in the X-Plex-Token header and
    every real account failed to authenticate.
    """
    test_db.add_all(
        [
            Config(key="plex_auth_token", value="encrypted-token"),
            Config(key="plex_server_name", value="Living Room"),
        ]
    )
    await test_db.commit()

    adapter = PlexAdapter(test_db)
    service = await adapter._plex()

    assert service.encrypted_token == "encrypted-token"
    assert service.server_name == "Living Room"


@pytest.mark.asyncio
async def test_plex_adapter_says_when_plex_is_not_configured(test_db):
    from app.services.media_server.base import MediaServerError

    with pytest.raises(MediaServerError, match="not configured"):
        await PlexAdapter(test_db)._plex()
