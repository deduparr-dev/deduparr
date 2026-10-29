"""
Extended tests for deletion pipeline:
- Media server paths that differ from this container's mount
- Disk cleanup of what a deleted file leaves behind
- Targeted media server refresh
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import settings
from app.services.deletion.pipeline import DeletionPipeline
from app.models import DeletionHistory, DuplicateFile, DuplicateSet
from app.models.duplicate import MediaType, DuplicateStatus
from app.models.config import Config
from tests.conftest import encrypt_test_password


@pytest.fixture
async def deletion_pipeline(test_db, setup_configs):
    """Create deletion pipeline instance with configs already set up"""
    return DeletionPipeline(test_db, dry_run=False)


@pytest.fixture
async def setup_configs(test_db):
    """Setup required configuration"""
    configs = [
        Config(key="qbittorrent_url", value="http://localhost:8080"),
        Config(key="qbittorrent_username", value="admin"),
        Config(key="qbittorrent_password", value=encrypt_test_password("adminpass")),
        Config(key="radarr_url", value="http://localhost:7878"),
        Config(key="radarr_api_key", value="radarr_key"),
        Config(key="sonarr_url", value="http://localhost:8989"),
        Config(key="sonarr_api_key", value="sonarr_key"),
        Config(key="plex_auth_token", value=encrypt_test_password("test_plex_token")),
        Config(key="plex_server_name", value="Test Server"),
        Config(key="plex_libraries", value="Movies,TV Shows"),
    ]
    test_db.add_all(configs)
    await test_db.commit()
    return configs


@pytest.fixture
async def movie_with_mismatched_path(test_db):
    """
    Create a movie file where Plex path differs from Deduparr path
    Plex: /plex/Movies/Avatar (2009)/Avatar.mkv
    Deduparr: /media/Movies/Avatar (2009)/Avatar.mkv
    """
    dup_set = DuplicateSet(
        item_id="movie123",
        title="Avatar",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.APPROVED,
    )
    test_db.add(dup_set)
    await test_db.flush()

    # Create a kept file (better quality)
    kept_file = DuplicateFile(
        set_id=dup_set.id,
        file_path="/plex/Movies/Avatar (2009)/Avatar 1080p.mkv",
        file_size=15000000000,
        score=100,
        keep=True,
    )
    test_db.add(kept_file)

    # Create the file to delete (lower quality)
    dup_file = DuplicateFile(
        set_id=dup_set.id,
        file_path="/plex/Movies/Avatar (2009)/Avatar.mkv",  # Plex path
        file_size=10000000000,
        score=50,
        keep=False,
    )
    test_db.add(dup_file)
    await test_db.commit()
    return dup_file


@pytest.fixture
async def episode_with_mismatched_path(test_db):
    """
    Create an episode file where paths differ
    Plex: /plex/TV/Breaking Bad/Season 01/S01E01.mkv
    Deduparr: /media/TV/Breaking Bad/Season 01/S01E01.mkv
    """
    dup_set = DuplicateSet(
        item_id="episode456",
        title="Breaking Bad - S01E01",
        media_type=MediaType.EPISODE,
        status=DuplicateStatus.APPROVED,
    )
    test_db.add(dup_set)
    await test_db.flush()

    # Create a kept file (better quality)
    kept_file = DuplicateFile(
        set_id=dup_set.id,
        file_path="/plex/TV/Breaking Bad/Season 01/S01E01 1080p.mkv",
        file_size=3000000000,
        score=100,
        keep=True,
    )
    test_db.add(kept_file)

    # Create the file to delete (lower quality)
    dup_file = DuplicateFile(
        set_id=dup_set.id,
        file_path="/plex/TV/Breaking Bad/Season 01/S01E01.mkv",
        file_size=2000000000,
        score=30,
        keep=False,
    )
    test_db.add(dup_file)
    await test_db.commit()
    return dup_file


@pytest.mark.asyncio
async def test_path_agnostic_radarr_matching(
    deletion_pipeline, test_db, setup_configs, movie_with_mismatched_path
):
    """Test that Radarr deletion works correctly with mocked Radarr API"""
    with (
        patch("app.services.download.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.arr.radarr_service.RadarrClient") as mock_radarr,
        patch(
            "app.services.deletion.pipeline.get_media_server",
            new_callable=AsyncMock,
        ) as mock_plex_class,
        patch("os.path.exists") as mock_exists,
        patch("os.remove"),
        patch("os.listdir") as mock_listdir,
        patch("os.path.isfile") as mock_isfile,
    ):
        # Setup qBit
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance
        mock_qbit_instance.torrents_info.return_value = []

        # Setup Radarr - movie file should match the path from fixture
        mock_radarr_instance = AsyncMock()
        mock_radarr.return_value = mock_radarr_instance
        mock_radarr_instance.get_movie = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "title": "Avatar",
                    "movieFile": {
                        "id": 10,
                        "path": "/plex/Movies/Avatar (2009)/Avatar.mkv",  # Exact path match required
                    },
                }
            ]
        )
        mock_radarr_instance.delete_movie_file = AsyncMock()

        # Setup file system - file exists in /media
        mock_exists.return_value = True
        mock_listdir.return_value = []  # No associated files
        mock_isfile.return_value = True

        # Setup Plex
        mock_plex_instance = AsyncMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_item.return_value = True

        # Execute deletion
        history = await deletion_pipeline.delete_file(movie_with_mismatched_path.id)

        # Verify Radarr deletion succeeded despite path mismatch
        assert history.deleted_from_arr is True
        mock_radarr_instance.delete_movie_file.assert_called_once_with(10)

        # Verify the file was found and deleted from disk
        assert history.deleted_from_disk is True
        assert history.is_complete is True


@pytest.mark.asyncio
async def test_path_agnostic_sonarr_matching(
    deletion_pipeline, test_db, setup_configs, episode_with_mismatched_path
):
    """Test that Sonarr finds episodes by filename only, not full path"""
    with (
        patch("app.services.download.qbittorrent_service.Client") as mock_qbit,
        patch(
            "app.services.arr.sonarr_service.SonarrService.find_episode_by_file_path",
            new_callable=AsyncMock,
        ) as mock_find_episode,
        patch(
            "app.services.arr.sonarr_service.SonarrService.delete_episode_file",
            new_callable=AsyncMock,
        ) as mock_delete_episode_file,
        patch(
            "app.services.arr.sonarr_service.SonarrService.rescan_series",
            new_callable=AsyncMock,
        ) as mock_rescan_series,
        patch(
            "app.services.deletion.pipeline.get_media_server",
            new_callable=AsyncMock,
        ) as mock_plex_class,
        patch("os.path.exists") as mock_exists,
        patch("os.remove"),
        patch("os.listdir") as mock_listdir,
        patch("os.path.isfile") as mock_isfile,
    ):
        # Setup qBit
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance
        mock_qbit_instance.torrents_info.return_value = []

        # Setup Sonarr - mock find_episode to return episode with different path
        mock_find_episode.return_value = {
            "id": 10,
            "title": "Pilot",
            "seriesId": 1,
            "seasonNumber": 1,
            "episodeNumber": 1,
            "episodeFile": {
                "id": 100,
                "path": "/mnt/plex/TV/Breaking Bad/Season 01/S01E01.mkv",  # Different base!
            },
        }
        mock_delete_episode_file.return_value = None
        mock_rescan_series.return_value = True

        # Setup file system
        mock_exists.return_value = True
        mock_listdir.return_value = []
        mock_isfile.return_value = True

        # Setup Plex
        mock_plex_instance = AsyncMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_item.return_value = True

        # Execute deletion
        history = await deletion_pipeline.delete_file(episode_with_mismatched_path.id)

        # Verify Sonarr deletion succeeded despite path mismatch
        assert history.deleted_from_arr is True
        mock_delete_episode_file.assert_called_once_with(1, 100)

        # Verify completion
        assert history.deleted_from_disk is True
        assert history.is_complete is True


@pytest.mark.asyncio
async def test_remapped_movie_deletion_cleans_up_and_spares_the_kept_file(
    test_db,
    setup_configs,
    create_duplicate_set,
    create_duplicate_file,
    tmp_path,
    monkeypatch,
):
    """
    Plex reports /plex/..., this container mounts the library at the media
    directory. Radarr deletes the file, and the leftovers beside it go too,
    while the kept version in the same folder stays.
    """
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    movie_dir = tmp_path / "Movies" / "Avatar (2009)"
    movie_dir.mkdir(parents=True)
    unwanted = movie_dir / "Avatar.mkv"
    unwanted.write_bytes(b"x" * 10)
    leftovers = [movie_dir / "Avatar.nfo", movie_dir / "Avatar-fanart.jpg"]
    for path in leftovers:
        path.write_text("x")
    kept = movie_dir / "Avatar 1080p.mkv"
    kept.write_bytes(b"x" * 20)

    dup_set = await create_duplicate_set(title="Avatar")
    await create_duplicate_file(
        dup_set.id,
        file_path="/plex/Movies/Avatar (2009)/Avatar 1080p.mkv",
        file_size=20,
        keep=True,
    )
    dup_file = await create_duplicate_file(
        dup_set.id,
        file_path="/plex/Movies/Avatar (2009)/Avatar.mkv",
        file_size=10,
        keep=False,
    )

    with (
        patch("app.services.download.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.arr.radarr_service.RadarrClient") as mock_radarr,
        patch(
            "app.services.deletion.pipeline.get_media_server",
            new_callable=AsyncMock,
        ) as mock_server,
    ):
        mock_qbit.return_value.torrents_info.return_value = []
        radarr = mock_radarr.return_value = AsyncMock()
        radarr.get_movie.return_value = [
            {
                "id": 1,
                "title": "Avatar",
                "movieFile": {"id": 10, "path": dup_file.file_path},
            }
        ]
        radarr.delete_movie_file.side_effect = lambda file_id: unwanted.unlink()
        mock_server.return_value.refresh_item.return_value = True

        history = await DeletionPipeline(test_db, dry_run=False).delete_file(
            dup_file.id
        )

    radarr.delete_movie_file.assert_awaited_once_with(10)
    assert not unwanted.exists()
    assert not any(path.exists() for path in leftovers)
    assert kept.exists()
    assert history.is_complete is True


@pytest.mark.asyncio
async def test_targeted_plex_refresh_with_library_id(
    deletion_pipeline, test_db, setup_configs, movie_with_mismatched_path
):
    """Test that Plex refresh uses targeted path refresh instead of full library scan"""

    with (
        patch("app.services.download.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.arr.radarr_service.RadarrClient") as mock_radarr,
        patch(
            "app.services.deletion.pipeline.get_media_server",
            new_callable=AsyncMock,
        ) as mock_plex_class,
        patch("os.path.exists") as mock_exists,
        patch("os.remove"),
        patch("os.listdir") as mock_listdir,
        patch("os.path.isfile") as mock_isfile,
    ):
        # Setup services
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance
        mock_qbit_instance.torrents_info.return_value = []

        mock_radarr_instance = AsyncMock()
        mock_radarr.return_value = mock_radarr_instance
        mock_radarr_instance.get_movie = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "title": "Avatar",
                    "movieFile": {
                        "id": 10,
                        "path": "/plex/Movies/Avatar (2009)/Avatar.mkv",
                    },
                }
            ]
        )
        mock_radarr_instance.delete_movie_file = AsyncMock()

        # Setup Plex with refresh_item method
        mock_plex_instance = AsyncMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_item.return_value = True

        mock_exists.return_value = True
        mock_listdir.return_value = []
        mock_isfile.return_value = True

        # Execute deletion
        history = await deletion_pipeline.delete_file(movie_with_mismatched_path.id)

        # Verify refresh_item was called with the item_id (targeted refresh)
        mock_plex_instance.refresh_item.assert_called_once()
        call_args = mock_plex_instance.refresh_item.call_args[0]
        # refresh_item should be called with the item_id (ratingKey)
        assert call_args[0] == str(movie_with_mismatched_path.duplicate_set.item_id)

        # Verify full library refresh was NOT called
        mock_plex_instance.refresh_library.assert_not_called()

        assert history.media_server_refreshed is True
        assert history.is_complete is True


@pytest.mark.asyncio
async def test_plex_refresh_fallback_to_full_scan(
    deletion_pipeline, test_db, setup_configs, movie_with_mismatched_path
):
    """Test that if targeted refresh fails, falls back to full library scan"""

    with (
        patch("app.services.download.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.arr.radarr_service.RadarrClient") as mock_radarr,
        patch(
            "app.services.deletion.pipeline.get_media_server",
            new_callable=AsyncMock,
        ) as mock_plex_class,
        patch("os.path.exists") as mock_exists,
        patch("os.remove"),
        patch("os.listdir") as mock_listdir,
        patch("os.path.isfile") as mock_isfile,
    ):
        # Setup services
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance
        mock_qbit_instance.torrents_info.return_value = []

        mock_radarr_instance = AsyncMock()
        mock_radarr.return_value = mock_radarr_instance
        mock_radarr_instance.get_movie = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "title": "Avatar",
                    "movieFile": {
                        "id": 10,
                        "path": "/plex/Movies/Avatar (2009)/Avatar.mkv",
                    },
                }
            ]
        )
        mock_radarr_instance.delete_movie_file = AsyncMock()

        # Setup Plex - refresh_item fails, refresh_library succeeds
        mock_plex_instance = AsyncMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_item.return_value = False  # Targeted refresh fails
        mock_plex_instance.refresh_library.return_value = True  # Full scan succeeds

        mock_exists.return_value = True
        mock_listdir.return_value = []
        mock_isfile.return_value = True

        # Execute deletion
        history = await deletion_pipeline.delete_file(movie_with_mismatched_path.id)

        # Verify both methods were called (targeted first, then fallback)
        mock_plex_instance.refresh_item.assert_called_once()
        # Fallback refreshes all configured libraries (Movies,TV Shows = 2 calls)
        assert mock_plex_instance.refresh_library.call_count == 2

        assert history.media_server_refreshed is True
        assert history.is_complete is True


@pytest.mark.asyncio
async def test_file_already_gone_counts_as_deleted(
    deletion_pipeline, test_db, setup_configs, movie_with_mismatched_path
):
    """A file no longer on disk anywhere counts as deleted"""

    with (
        patch("app.services.download.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.arr.radarr_service.RadarrClient") as mock_radarr,
        patch(
            "app.services.deletion.pipeline.get_media_server",
            new_callable=AsyncMock,
        ) as mock_plex_class,
        patch("os.path.exists") as mock_exists,
    ):
        # Setup services
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance
        mock_qbit_instance.torrents_info.return_value = []

        mock_radarr_instance = AsyncMock()
        mock_radarr.return_value = mock_radarr_instance
        mock_radarr_instance.get_movie = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "title": "Avatar",
                    "movieFile": {"id": 10, "path": "/different/path/Avatar.mkv"},
                }
            ]
        )
        mock_radarr_instance.delete_movie_file = AsyncMock()

        mock_plex_instance = AsyncMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_item.return_value = True

        # File doesn't exist anywhere
        mock_exists.return_value = False

        # Execute deletion - should mark as deleted even though file not found
        history = await deletion_pipeline.delete_file(movie_with_mismatched_path.id)

        # File not on disk is treated as successful deletion
        assert history.deleted_from_disk is True
        assert history.is_complete is True


@pytest.mark.asyncio
async def test_special_characters_in_filenames(test_db, tmp_path):
    """Spaces, brackets and non-ASCII characters do not break the disk stage."""
    movie_dir = tmp_path / "The Matrix (1999) [4K]"
    movie_dir.mkdir()
    stem = "The Matrix (1999) [4K] – Ünïcødé"
    main = movie_dir / f"{stem}.mkv"
    associated = [movie_dir / f"{stem}.nfo", movie_dir / f"{stem}.en.srt"]
    for path in [main, *associated]:
        path.write_text("x")
    unrelated = movie_dir / "folder.jpg"
    unrelated.write_text("x")

    history = DeletionHistory(duplicate_file_id=1)
    await DeletionPipeline(test_db, dry_run=False)._stage_disk_removal(
        str(main), history, str(main)
    )

    assert not main.exists()
    assert not any(path.exists() for path in associated)
    assert unrelated.exists()
    assert history.deleted_from_disk is True


@pytest.mark.asyncio
async def test_dry_run_mode_no_actual_changes(
    test_db, setup_configs, movie_with_mismatched_path
):
    """Test that dry-run mode doesn't make actual changes"""

    # Create pipeline in dry-run mode
    dry_run_pipeline = DeletionPipeline(test_db, dry_run=True)

    with (
        patch("app.services.download.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.arr.radarr_service.RadarrClient") as mock_radarr,
        patch(
            "app.services.deletion.pipeline.get_media_server",
            new_callable=AsyncMock,
        ) as mock_plex_class,
        patch("os.path.exists", return_value=True),
        patch("os.remove") as mock_remove,
        patch("os.listdir", return_value=[]),
        patch("os.path.isfile", return_value=True),
    ):
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance

        mock_radarr_instance = AsyncMock()
        mock_radarr.return_value = mock_radarr_instance

        mock_plex_instance = AsyncMock()
        mock_plex_class.return_value = mock_plex_instance

        # Execute deletion in dry-run mode
        history = await dry_run_pipeline.delete_file(movie_with_mismatched_path.id)

        # Verify no actual deletion methods were called
        mock_qbit_instance.torrents_delete.assert_not_called()
        mock_radarr_instance.delete_movie_file.assert_not_called()
        mock_remove.assert_not_called()
        mock_plex_instance.refresh_item.assert_not_called()
        mock_plex_instance.refresh_library.assert_not_called()

        # But history should still be recorded
        assert history is not None
        assert history.duplicate_file_id == movie_with_mismatched_path.id
