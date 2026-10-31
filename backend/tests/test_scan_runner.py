"""Tests for the scan runner shared by the scan endpoint and the scheduler"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models import DuplicateSet
from app.models.duplicate import DuplicateStatus, MediaType
from app.services.media_server import (
    DuplicateGroup,
    MediaServerError,
    MediaServerType,
    save_selected_libraries,
)
from app.services.scan.runner import run_scan
from app.services.scan.scoring_engine import MediaMetadata


def _server(server_type, libraries, movie_groups=(), episode_groups=()):
    server = AsyncMock()
    server.type = server_type
    server.get_libraries.return_value = libraries
    server.find_duplicate_movies.return_value = list(movie_groups)
    server.find_duplicate_episodes.return_value = list(episode_groups)
    return server


async def _scan(test_db, servers, names):
    """Choose the same library names on every server, then scan them all."""
    await save_selected_libraries(test_db, {server.type: names for server in servers})
    with patch(
        "app.services.scan.runner.get_media_servers",
        new_callable=AsyncMock,
        return_value=servers,
    ):
        return await run_scan(test_db)


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

    totals = await _scan(test_db, [plex, jellyfin], ["Movies"])

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

    await _scan(test_db, [server], ["Movies"])

    server.find_duplicate_movies.assert_awaited_once_with("Movies")


@pytest.mark.asyncio
async def test_run_scan_skips_library_types_it_cannot_handle(test_db):
    server = _server(
        MediaServerType.JELLYFIN,
        [{"key": "1", "title": "Music", "type": "music", "count": 1}],
    )

    totals = await _scan(test_db, [server], ["Music"])

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

    totals = await _scan(test_db, [broken, working], ["Movies"])

    assert totals.sets_created == 1
    assert totals.skipped == [f"Jellyfin: {failure}"]


@pytest.mark.asyncio
async def test_run_scan_drops_sets_the_server_no_longer_reports(test_db):
    """A set missing from a later scan of the same server is cleaned up."""
    server = _server(
        MediaServerType.PLEX,
        [{"key": "1", "title": "Movies", "type": "movie", "count": 1}],
        movie_groups=[_group("gone")],
    )

    await _scan(test_db, [server], ["Movies"])
    assert (await test_db.execute(select(DuplicateSet))).scalars().all()

    server.find_duplicate_movies.return_value = []
    totals = await _scan(test_db, [server], ["Movies"])

    assert not (await test_db.execute(select(DuplicateSet))).scalars().all()
    assert totals.sets_created == 0
    assert totals.sets_removed == 1


def _two_movie_libraries():
    server = _server(
        MediaServerType.JELLYFIN,
        [
            {"key": "1", "title": "Movies", "type": "movie", "count": 1},
            {"key": "2", "title": "4K", "type": "movie", "count": 1},
        ],
    )
    server.find_duplicate_movies.side_effect = lambda name: [
        _group("in-movies" if name == "Movies" else "in-4k")
    ]
    return server


@pytest.mark.asyncio
async def test_run_scan_keeps_the_sets_of_every_library_of_a_type(test_db):
    """One library's results say nothing about the sets of another of its type."""
    await _scan(test_db, [_two_movie_libraries()], ["Movies", "4K"])

    items = (await test_db.execute(select(DuplicateSet.item_id))).scalars().all()
    assert sorted(items) == ["in-4k", "in-movies"]


@pytest.mark.asyncio
async def test_run_scan_keeps_the_sets_of_a_library_it_could_not_read(test_db):
    """Going unreported is no sign of staleness when the library never answered."""
    server = _two_movie_libraries()
    await _scan(test_db, [server], ["Movies", "4K"])

    def unreadable_4k(name):
        if name == "4K":
            raise MediaServerError("unreachable")
        return [_group("in-movies")]

    server.find_duplicate_movies.side_effect = unreadable_4k
    totals = await _scan(test_db, [server], ["Movies", "4K"])

    items = (await test_db.execute(select(DuplicateSet.item_id))).scalars().all()
    assert sorted(items) == ["in-4k", "in-movies"]
    assert totals.skipped == ["Jellyfin '4K': unreachable"]


@pytest.mark.asyncio
async def test_run_scan_drops_the_pending_sets_of_a_server_no_longer_set_up(test_db):
    """Nothing can report on them again. History and disk-scan sets stay."""
    for server, status in (
        ("plex", DuplicateStatus.PENDING),
        ("plex", DuplicateStatus.PROCESSED),
        ("disk", DuplicateStatus.PENDING),
    ):
        test_db.add(
            DuplicateSet(
                media_server=server,
                item_id=f"{server}-{status.value}",
                title="Old",
                media_type=MediaType.MOVIE,
                status=status,
            )
        )
    await test_db.commit()

    jellyfin = _server(
        MediaServerType.JELLYFIN,
        [{"key": "1", "title": "Movies", "type": "movie", "count": 1}],
    )
    totals = await _scan(test_db, [jellyfin], ["Movies"])

    items = (await test_db.execute(select(DuplicateSet.item_id))).scalars().all()
    assert sorted(items) == ["disk-pending", "plex-processed"]
    assert totals.sets_removed == 1


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

    await _scan(test_db, [server], ["Movies"])

    test_db.expire_all()
    result = await test_db.execute(select(DuplicateSet))
    assert [s.item_id for s in result.scalars().all()] == ["committed"]


@pytest.mark.asyncio
async def test_run_scan_uses_each_servers_own_selection(test_db):
    """Each server scans only what was chosen for it."""
    from app.models import Config

    plex = _server(
        MediaServerType.PLEX,
        [
            {"key": "1", "title": "Movies", "type": "movie", "count": 1},
            {"key": "2", "title": "Kids", "type": "movie", "count": 1},
        ],
        movie_groups=[_group("p1")],
    )
    jellyfin = _server(
        MediaServerType.JELLYFIN,
        [{"key": "3", "title": "Films", "type": "movie", "count": 1}],
        movie_groups=[_group("j1")],
    )

    test_db.add_all(
        [
            Config(key="plex_libraries", value="Movies"),
            Config(key="jellyfin_libraries", value="Films"),
        ]
    )
    await test_db.commit()

    with patch(
        "app.services.scan.runner.get_media_servers",
        new_callable=AsyncMock,
        return_value=[plex, jellyfin],
    ):
        await run_scan(test_db)

    plex.find_duplicate_movies.assert_awaited_once_with("Movies")
    jellyfin.find_duplicate_movies.assert_awaited_once_with("Films")


@pytest.mark.asyncio
async def test_run_scan_skips_a_server_with_nothing_selected(test_db):
    """A server the user chose no libraries for is left alone."""
    plex = _server(
        MediaServerType.PLEX,
        [{"key": "1", "title": "Movies", "type": "movie", "count": 1}],
        movie_groups=[_group("p1")],
    )

    with patch(
        "app.services.scan.runner.get_media_servers",
        new_callable=AsyncMock,
        return_value=[plex],
    ):
        totals = await run_scan(test_db)

    assert totals.sets_created == 0
    plex.get_libraries.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_processed_item_duplicated_again_gets_a_new_set(test_db):
    """
    A processed set records a deletion. When the server reports the item with
    more than one file again, that is a new duplicate to review, not an update
    to the record, which no list or deletion would ever show.
    """
    from app.models import DuplicateStatus

    server = _server(
        MediaServerType.JELLYFIN,
        [{"key": "1", "title": "Movies", "type": "movie", "count": 1}],
        movie_groups=[_group("again")],
    )
    await _scan(test_db, [server], ["Movies"])
    first = (await test_db.execute(select(DuplicateSet))).scalar_one()
    first.status = DuplicateStatus.PROCESSED
    await test_db.commit()

    totals = await _scan(test_db, [server], ["Movies"])

    statuses = (await test_db.execute(select(DuplicateSet.status))).scalars().all()
    assert sorted(statuses) == [DuplicateStatus.PENDING, DuplicateStatus.PROCESSED]
    assert totals.sets_created == 1
