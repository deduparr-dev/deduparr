"""Tests for the scan runner shared by the scan endpoint and the scheduler"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models import DuplicateSet
from app.services.media_server import DuplicateGroup, MediaServerError, MediaServerType
from app.services.scan.runner import run_scan
from app.services.scan.scoring_engine import MediaMetadata


def _server(server_type, libraries, movie_groups=(), episode_groups=()):
    server = AsyncMock()
    server.type = server_type
    server.get_libraries.return_value = libraries
    server.find_duplicate_movies.return_value = list(movie_groups)
    server.find_duplicate_episodes.return_value = list(episode_groups)
    return server


def _group(item_id, title="A Movie"):
    return DuplicateGroup(
        item_id=item_id,
        title=title,
        files=[
            MediaMetadata(
                file_path=f"/m/{item_id}-a.mkv",
                file_size=10,
                resolution="1080p",
                inode=1,
            ),
            MediaMetadata(
                file_path=f"/m/{item_id}-b.mkv", file_size=5, resolution="720p", inode=2
            ),
        ],
    )


@pytest.mark.asyncio
async def test_run_scan_covers_every_configured_server(test_db):
    """Plex and Jellyfin are both scanned, each keeping its own set."""
    plex = _server(
        MediaServerType.PLEX,
        [{"key": "1", "title": "Movies", "type": "movie", "count": 1}],
        movie_groups=[_group("plex-1")],
    )
    jellyfin = _server(
        MediaServerType.JELLYFIN,
        [{"key": "2", "title": "Movies", "type": "movie", "count": 1}],
        movie_groups=[_group("jf-1")],
    )

    with patch(
        "app.services.scan.runner.get_media_servers",
        new_callable=AsyncMock,
        return_value=[plex, jellyfin],
    ):
        totals = await run_scan(test_db, ["Movies"])

    assert totals.sets_created == 2
    assert totals.duplicates_found == 4

    result = await test_db.execute(select(DuplicateSet))
    assert sorted(s.media_server for s in result.scalars().all()) == [
        "jellyfin",
        "plex",
    ]


@pytest.mark.asyncio
async def test_run_scan_only_touches_requested_libraries(test_db):
    server = _server(
        MediaServerType.PLEX,
        [
            {"key": "1", "title": "Movies", "type": "movie", "count": 1},
            {"key": "2", "title": "Kids", "type": "movie", "count": 1},
        ],
        movie_groups=[_group("m1")],
    )

    with patch(
        "app.services.scan.runner.get_media_servers",
        new_callable=AsyncMock,
        return_value=[server],
    ):
        await run_scan(test_db, ["Movies"])

    server.find_duplicate_movies.assert_awaited_once_with("Movies")


@pytest.mark.asyncio
async def test_run_scan_skips_library_types_it_cannot_handle(test_db):
    server = _server(
        MediaServerType.JELLYFIN,
        [{"key": "1", "title": "Music", "type": "music", "count": 1}],
    )

    with patch(
        "app.services.scan.runner.get_media_servers",
        new_callable=AsyncMock,
        return_value=[server],
    ):
        totals = await run_scan(test_db, ["Music"])

    assert totals.sets_created == 0
    server.find_duplicate_movies.assert_not_awaited()
    server.find_duplicate_episodes.assert_not_awaited()


@pytest.mark.parametrize(
    "failure",
    [MediaServerError("unreachable"), ValueError("Failed to decrypt token")],
    ids=["media-server-error", "any-other-error"],
)
@pytest.mark.asyncio
async def test_run_scan_carries_on_when_one_server_fails(test_db, failure):
    """
    A broken server does not stop the others being scanned.

    The failure is not always a MediaServerError: a stale Plex token surfaces
    as a ValueError from the SDK layer, and that used to 500 the whole scan.
    """
    broken = AsyncMock()
    broken.type = MediaServerType.JELLYFIN
    broken.get_libraries.side_effect = failure

    working = _server(
        MediaServerType.PLEX,
        [{"key": "1", "title": "Movies", "type": "movie", "count": 1}],
        movie_groups=[_group("ok-1")],
    )

    with patch(
        "app.services.scan.runner.get_media_servers",
        new_callable=AsyncMock,
        return_value=[broken, working],
    ):
        totals = await run_scan(test_db, ["Movies"])

    assert totals.sets_created == 1


@pytest.mark.asyncio
async def test_run_scan_drops_sets_the_server_no_longer_reports(test_db):
    """A set missing from a later scan of the same server is cleaned up."""
    server = _server(
        MediaServerType.PLEX,
        [{"key": "1", "title": "Movies", "type": "movie", "count": 1}],
        movie_groups=[_group("gone")],
    )

    with patch(
        "app.services.scan.runner.get_media_servers",
        new_callable=AsyncMock,
        return_value=[server],
    ):
        await run_scan(test_db, ["Movies"])
        assert (await test_db.execute(select(DuplicateSet))).scalars().all()

        server.find_duplicate_movies.return_value = []
        totals = await run_scan(test_db, ["Movies"])

    assert not (await test_db.execute(select(DuplicateSet))).scalars().all()
    assert totals.sets_created == 0


@pytest.mark.asyncio
async def test_run_scan_persists_what_it_found(test_db):
    """
    The runner commits, so a caller cannot report sets it never saved.

    Expiring the session proves the rows are in the database rather than just
    pending in this session's identity map.
    """
    server = _server(
        MediaServerType.PLEX,
        [{"key": "1", "title": "Movies", "type": "movie", "count": 1}],
        movie_groups=[_group("committed")],
    )

    with patch(
        "app.services.scan.runner.get_media_servers",
        new_callable=AsyncMock,
        return_value=[server],
    ):
        await run_scan(test_db, ["Movies"])

    test_db.expire_all()
    result = await test_db.execute(select(DuplicateSet))
    assert [s.item_id for s in result.scalars().all()] == ["committed"]
