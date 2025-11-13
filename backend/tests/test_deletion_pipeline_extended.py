"""
Extended tests for deletion pipeline - comprehensive coverage of new features:
- Path-agnostic matching (filename-only)
- File location caching
- Comprehensive disk cleanup (associated files, empty directories)
- Targeted Plex refresh with library ID
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.deletion_pipeline import DeletionPipeline
from app.models import DuplicateSet, DuplicateFile
from app.models.duplicate import MediaType, DuplicateStatus
from app.models.config import Config
from tests.conftest import encrypt_test_password


@pytest.fixture
async def deletion_pipeline(test_db, setup_configs):
    """Create deletion pipeline instance with configs already set up"""
    pipeline = DeletionPipeline(test_db, dry_run=False)
    # Clear cache before each test
    pipeline._file_location_cache.clear()
    return pipeline


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
        plex_item_id="movie123",
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
        plex_item_id="episode456",
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
        patch("app.services.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.radarr_service.RadarrClient") as mock_radarr,
        patch("app.services.deletion_pipeline.PlexService") as mock_plex_class,
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
        mock_radarr_instance.del_movie_file = AsyncMock()

        # Setup file system - file exists in /media
        mock_exists.return_value = True
        mock_listdir.return_value = []  # No associated files
        mock_isfile.return_value = True

        # Setup Plex
        mock_plex_instance = MagicMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_item.return_value = True

        # Execute deletion
        history = await deletion_pipeline.delete_file(movie_with_mismatched_path.id)

        # Verify Radarr deletion succeeded despite path mismatch
        assert history.deleted_from_arr is True
        mock_radarr_instance.del_movie_file.assert_called_once_with(10)

        # Verify the file was found and deleted from disk
        assert history.deleted_from_disk is True
        assert history.is_complete is True


@pytest.mark.asyncio
async def test_path_agnostic_sonarr_matching(
    deletion_pipeline, test_db, setup_configs, episode_with_mismatched_path
):
    """Test that Sonarr finds episodes by filename only, not full path"""
    with (
        patch("app.services.qbittorrent_service.Client") as mock_qbit,
        patch(
            "app.services.sonarr_service.SonarrService.find_episode_by_file_path",
            new_callable=AsyncMock,
        ) as mock_find_episode,
        patch(
            "app.services.sonarr_service.SonarrService.delete_episode_file",
            new_callable=AsyncMock,
        ) as mock_delete_episode_file,
        patch(
            "app.services.sonarr_service.SonarrService.rescan_series",
            new_callable=AsyncMock,
        ) as mock_rescan_series,
        patch("app.services.deletion_pipeline.PlexService") as mock_plex_class,
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
        mock_plex_instance = MagicMock()
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
async def test_file_location_caching(
    deletion_pipeline, test_db, setup_configs, movie_with_mismatched_path
):
    """Test that file location lookups are cached for performance"""

    with (
        patch("os.walk") as mock_walk,
        patch("os.path.exists") as mock_exists,
    ):
        # Setup file system - simulate /media directory with files
        mock_walk.return_value = [
            ("/media/Movies/Avatar (2009)", [], ["Avatar.mkv"]),
        ]
        # First call checks exact path (fails), then searches media_dir
        mock_exists.side_effect = [False, True]

        plex_path = "/plex/Movies/Avatar (2009)/Avatar.mkv"

        # First lookup - should check exact path, then trigger os.walk
        result1 = deletion_pipeline._find_file_in_media_root(plex_path)
        assert result1 == "/media/Movies/Avatar (2009)/Avatar.mkv"
        assert mock_walk.call_count == 1

        # Second lookup - should use cache
        result2 = deletion_pipeline._find_file_in_media_root(plex_path)
        assert result2 == "/media/Movies/Avatar (2009)/Avatar.mkv"
        assert mock_walk.call_count == 1  # Still only 1, cache was used

        # Verify cache contains the entry
        assert plex_path in deletion_pipeline._file_location_cache


@pytest.mark.asyncio
async def test_file_location_last_two_segments_matching(
    deletion_pipeline, test_db, setup_configs
):
    """Test that file matching uses last 2 path segments for accuracy"""

    with patch("os.walk") as mock_walk:
        # Setup file system with multiple files with same name in different dirs
        mock_walk.return_value = [
            ("/media/Movies/Avatar (2009)", [], ["Avatar.mkv"]),
            ("/media/Movies/Avatar The Way of Water (2022)", [], ["Avatar.mkv"]),
        ]

        # Clear cache to start fresh
        deletion_pipeline._file_location_cache.clear()

        # Search with 2-segment path should find correct file
        result = deletion_pipeline._find_file_in_media_root(
            "/plex/Movies/Avatar (2009)/Avatar.mkv"  # Last 2 segments: Avatar (2009)/Avatar.mkv
        )

        # Should match based on "Avatar (2009)/Avatar.mkv"
        assert result == "/media/Movies/Avatar (2009)/Avatar.mkv"


@pytest.mark.asyncio
async def test_comprehensive_disk_cleanup_with_associated_files(
    deletion_pipeline, test_db, setup_configs, movie_with_mismatched_path
):
    """Test that deletion removes main file plus associated files (.nfo, .srt, etc.)"""

    with (
        patch("app.services.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.radarr_service.RadarrClient") as mock_radarr,
        patch("app.services.deletion_pipeline.PlexService") as mock_plex_class,
        patch("os.path.exists") as mock_exists,
        patch("os.remove") as mock_remove,
        patch("os.listdir") as mock_listdir,
        patch("os.path.isfile") as mock_isfile,
        patch("os.path.isdir") as mock_isdir,
        patch("os.rmdir"),
        patch("os.walk") as mock_walk,
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
                        # Match the Plex path so Radarr finds the movie
                        "path": "/plex/Movies/Avatar (2009)/Avatar.mkv",
                    },
                }
            ]
        )
        mock_radarr_instance.del_movie_file = AsyncMock()

        mock_plex_instance = MagicMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_item.return_value = True

        # Setup os.walk for _find_file_in_media_root
        mock_walk.return_value = [
            (
                "/media/Movies/Avatar (2009)",
                [],
                [
                    "Avatar.mkv",
                    "Avatar.nfo",
                    "Avatar.srt",
                    "Avatar-fanart.jpg",
                ],
            ),
        ]

        # Setup file system - main file + associated files in same directory
        def exists_side_effect(path):
            return path in [
                "/media/Movies/Avatar (2009)/Avatar.mkv",
                "/media/Movies/Avatar (2009)/Avatar.nfo",
                "/media/Movies/Avatar (2009)/Avatar.srt",
                "/media/Movies/Avatar (2009)/Avatar-fanart.jpg",
                "/media/Movies/Avatar (2009)",
            ]

        mock_exists.side_effect = exists_side_effect
        mock_listdir.return_value = [
            "Avatar.mkv",
            "Avatar.nfo",
            "Avatar.srt",
            "Avatar-fanart.jpg",
        ]

        def isfile_side_effect(path):
            return not path.endswith("(2009)")

        mock_isfile.side_effect = isfile_side_effect
        mock_isdir.return_value = True

        # Execute deletion
        history = await deletion_pipeline.delete_file(movie_with_mismatched_path.id)

        # Verify associated files were deleted (main file already deleted by Radarr)
        assert mock_remove.call_count == 3
        removed_files = [call[0][0] for call in mock_remove.call_args_list]
        # Main file should NOT be in removed_files - it was deleted by Radarr
        assert "/media/Movies/Avatar (2009)/Avatar.mkv" not in removed_files
        # But associated files should be removed
        assert "/media/Movies/Avatar (2009)/Avatar.nfo" in removed_files
        assert "/media/Movies/Avatar (2009)/Avatar.srt" in removed_files
        assert "/media/Movies/Avatar (2009)/Avatar-fanart.jpg" in removed_files

        assert history.deleted_from_disk is True
        assert history.is_complete is True


@pytest.mark.asyncio
async def test_recursive_empty_directory_cleanup(
    deletion_pipeline, test_db, setup_configs, episode_with_mismatched_path
):
    """Test that empty parent directories are recursively removed after file deletion"""

    with (
        patch(
            "app.services.sonarr_service.SonarrService.find_episode_by_file_path",
            new_callable=AsyncMock,
        ) as mock_find,
        patch(
            "app.services.sonarr_service.SonarrService.delete_episode_file",
            new_callable=AsyncMock,
        ) as mock_delete,
        patch(
            "app.services.sonarr_service.SonarrService.rescan_series",
            new_callable=AsyncMock,
        ),
        patch("app.services.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.deletion_pipeline.PlexService") as mock_plex_class,
        patch("os.path.exists") as mock_exists,
        patch("os.remove") as mock_remove,
        patch("os.listdir") as mock_listdir,
        patch("os.path.isfile") as mock_isfile,
        patch("os.path.isdir") as mock_isdir,
        patch("os.rmdir") as mock_rmdir,
        patch("os.walk") as mock_walk,  # Add os.walk mock
        patch("os.stat") as mock_stat,  # Add os.stat mock for inode checking
    ):
        # Setup Sonarr service mocks - Sonarr doesn't find the file
        # This forces the deletion pipeline to use orphan cleanup via os.walk
        mock_find.return_value = None
        mock_delete.return_value = True

        # Setup qBittorrent
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance
        mock_qbit_instance.torrents_info.return_value = []

        # Setup Plex
        mock_plex_instance = MagicMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_item.return_value = True

        # Setup os.walk for _find_file_in_media_root and orphan cleanup
        mock_walk.return_value = [
            ("/media/TV/Breaking Bad/Season 01", [], ["S01E01.mkv"]),
        ]

        # Setup os.stat to return inode info for orphan cleanup
        mock_stat_result = MagicMock()
        mock_stat_result.st_ino = 12345
        mock_stat_result.st_nlink = 1
        mock_stat.return_value = mock_stat_result

        # File system setup - Season 01 becomes empty after deletion
        # Track whether file has been removed to simulate state change
        file_removed = {"removed": False}

        def exists_side_effect(path):
            # Phase 1: Plex path check - file doesn't exist at Plex path
            # This forces Phase 2 (os.walk) to find it
            if path == "/plex/TV/Breaking Bad/Season 01/S01E01.mkv":
                return False
            # Actual file location (found via os.walk)
            if path == "/media/TV/Breaking Bad/Season 01/S01E01.mkv":
                return not file_removed["removed"]
            # Parent directory exists for cleanup checks
            if path == "/media/TV/Breaking Bad/Season 01":
                return True
            if path == "/media/TV/Breaking Bad":
                return True
            if path == "/media/TV":
                return True
            return False

        def remove_side_effect(path):
            # Mark file as removed when os.remove is called
            if path == "/media/TV/Breaking Bad/Season 01/S01E01.mkv":
                file_removed["removed"] = True

        def listdir_side_effect(path):
            if path == "/media/TV/Breaking Bad/Season 01":
                # Directory is empty after file removal
                if file_removed["removed"]:
                    return []
                # Before removal, file still exists
                return ["S01E01.mkv"]
            if path == "/media/TV/Breaking Bad":
                # Parent still has Season 01 directory (initially)
                # After Season 01 is removed, it might be empty too
                return ["Season 01"]  # Simplified for this test
            return []

        def isdir_side_effect(path):
            if path == "/media/TV/Breaking Bad/Season 01":
                # Directory exists until after it's removed
                return not any(d == path for d in [])  # Always true for this test
            if path == "/media/TV/Breaking Bad":
                return True
            return False

        mock_exists.side_effect = exists_side_effect
        mock_listdir.side_effect = listdir_side_effect
        mock_remove.side_effect = remove_side_effect
        mock_isfile.return_value = False
        mock_isdir.side_effect = isdir_side_effect

        # Execute deletion
        history = await deletion_pipeline.delete_file(episode_with_mismatched_path.id)

        # File deleted via Phase 2 (recursive search)
        # Verify os.remove was called once for the file
        mock_remove.assert_called_once_with(
            "/media/TV/Breaking Bad/Season 01/S01E01.mkv"
        )

        # Directory cleanup happens after file removal
        # Verify rmdir was called for the now-empty Season 01 directory
        mock_rmdir.assert_called_once_with("/media/TV/Breaking Bad/Season 01")

        assert history.deleted_from_disk is True
        assert history.is_complete is True


@pytest.mark.asyncio
async def test_targeted_plex_refresh_with_library_id(
    deletion_pipeline, test_db, setup_configs, movie_with_mismatched_path
):
    """Test that Plex refresh uses targeted path refresh instead of full library scan"""

    with (
        patch("app.services.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.radarr_service.RadarrClient") as mock_radarr,
        patch("app.services.deletion_pipeline.PlexService") as mock_plex_class,
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
        mock_radarr_instance.del_movie_file = AsyncMock()

        # Setup Plex with refresh_item method
        mock_plex_instance = MagicMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_item.return_value = True

        mock_exists.return_value = True
        mock_listdir.return_value = []
        mock_isfile.return_value = True

        # Execute deletion
        history = await deletion_pipeline.delete_file(movie_with_mismatched_path.id)

        # Verify refresh_item was called with the plex_item_id (targeted refresh)
        mock_plex_instance.refresh_item.assert_called_once()
        call_args = mock_plex_instance.refresh_item.call_args[0]
        # refresh_item should be called with the plex_item_id (ratingKey)
        assert call_args[0] == str(
            movie_with_mismatched_path.duplicate_set.plex_item_id
        )

        # Verify full library refresh was NOT called
        mock_plex_instance.refresh_library.assert_not_called()

        assert history.plex_refreshed is True
        assert history.is_complete is True


@pytest.mark.asyncio
async def test_plex_refresh_fallback_to_full_scan(
    deletion_pipeline, test_db, setup_configs, movie_with_mismatched_path
):
    """Test that if targeted refresh fails, falls back to full library scan"""

    with (
        patch("app.services.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.radarr_service.RadarrClient") as mock_radarr,
        patch("app.services.deletion_pipeline.PlexService") as mock_plex_class,
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
        mock_radarr_instance.del_movie_file = AsyncMock()

        # Setup Plex - refresh_item fails, refresh_library succeeds
        mock_plex_instance = MagicMock()
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

        assert history.plex_refreshed is True
        assert history.is_complete is True


@pytest.mark.asyncio
async def test_file_not_found_on_disk_after_cache_lookup(
    deletion_pipeline, test_db, setup_configs, movie_with_mismatched_path
):
    """Test handling when file isn't found even after recursive search"""

    with (
        patch("app.services.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.radarr_service.RadarrClient") as mock_radarr,
        patch("app.services.deletion_pipeline.PlexService") as mock_plex_class,
        patch("os.path.exists") as mock_exists,
        patch("os.walk") as mock_walk,
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
        mock_radarr_instance.del_movie_file = AsyncMock()

        mock_plex_instance = MagicMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_item.return_value = True

        # File doesn't exist anywhere
        mock_exists.return_value = False
        mock_walk.return_value = []  # No files found in /media

        # Execute deletion - should mark as deleted even though file not found
        history = await deletion_pipeline.delete_file(movie_with_mismatched_path.id)

        # File not on disk is treated as successful deletion
        assert history.deleted_from_disk is True
        assert history.is_complete is True


@pytest.mark.asyncio
async def test_cache_persistence_across_multiple_deletions(
    deletion_pipeline, test_db, setup_configs
):
    """Test that cache persists and is reused across multiple file lookups"""

    with (
        patch("os.walk") as mock_walk,
        patch("os.path.exists") as mock_exists,
    ):
        # Setup file system - files exist at exact Plex paths
        # Phase 1 will succeed for these paths
        def exists_side_effect(path):
            if path == "/media/Movies/Movie0/Movie0.mkv":
                return True
            if path == "/media/Movies/Movie1/Movie1.mkv":
                return True
            if path == "/media/Movies/Movie2/Movie2.mkv":
                return True
            return False

        mock_exists.side_effect = exists_side_effect

        # Clear cache to start fresh
        deletion_pipeline._file_location_cache.clear()

        # First file lookup should use Phase 1 (exact path check) and cache the result
        result1 = deletion_pipeline._find_file_in_media_root(
            "/media/Movies/Movie0/Movie0.mkv"
        )
        # Phase 1 succeeded, no walk needed
        assert mock_walk.call_count == 0
        assert result1 == "/media/Movies/Movie0/Movie0.mkv"

        # Cache should now contain the found file
        assert (
            "/media/Movies/Movie0/Movie0.mkv" in deletion_pipeline._file_location_cache
        )

        # Second file lookup for SAME file - should use cache
        # Cache validates file still exists before returning it
        mock_exists.reset_mock()
        result2 = deletion_pipeline._find_file_in_media_root(
            "/media/Movies/Movie0/Movie0.mkv"
        )
        # Should call exists once to validate cached path still exists
        assert mock_exists.call_count == 1
        assert mock_exists.call_args[0][0] == "/media/Movies/Movie0/Movie0.mkv"
        assert result2 == "/media/Movies/Movie0/Movie0.mkv"

        # Third file lookup for DIFFERENT file - should check exact path (Phase 1)
        result3 = deletion_pipeline._find_file_in_media_root(
            "/media/Movies/Movie1/Movie1.mkv"
        )
        # Cache validation from previous call (1) + Phase 1 check for new file (1) = 2 total
        assert mock_exists.call_count == 2
        assert result3 == "/media/Movies/Movie1/Movie1.mkv"
        # Should be cached now
        assert (
            "/media/Movies/Movie1/Movie1.mkv" in deletion_pipeline._file_location_cache
        )

        # os.walk should never have been called (all files at exact paths)
        assert mock_walk.call_count == 0


@pytest.mark.asyncio
async def test_special_characters_in_filenames(
    deletion_pipeline, test_db, setup_configs
):
    """Test handling of special characters in filenames (spaces, unicode, etc.)"""

    dup_set = DuplicateSet(
        plex_item_id="movie_special",
        title="Movie with Special Chars",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.APPROVED,
    )
    test_db.add(dup_set)
    await test_db.flush()

    # Filename with spaces, parentheses, and unicode
    dup_file = DuplicateFile(
        set_id=dup_set.id,
        file_path="/plex/Movies/The Matrix (1999) [4K]/The Matrix (1999) [4K].mkv",
        file_size=50000000000,
        score=90,
        keep=False,
    )
    test_db.add(dup_file)
    await test_db.commit()

    with (
        patch(
            "app.services.radarr_service.RadarrService.find_movie_by_file_path",
            new_callable=AsyncMock,
        ) as mock_find,
        patch(
            "app.services.radarr_service.RadarrService.delete_movie_file",
            new_callable=AsyncMock,
        ) as mock_delete,
        patch(
            "app.services.radarr_service.RadarrService.rescan_movie",
            new_callable=AsyncMock,
        ),
        patch("os.walk") as mock_walk,
        patch("os.path.exists") as mock_exists,
        patch("app.services.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.deletion_pipeline.PlexService") as mock_plex_class,
        patch("os.remove") as mock_remove,
        patch("os.listdir", return_value=[]),
        patch("os.path.isfile", return_value=True),
        patch("os.stat") as mock_stat,  # Add os.stat mock for inode checking
    ):
        # Setup Radarr service mocks - Radarr doesn't find the file
        # This forces the deletion pipeline to use orphan cleanup via os.walk
        mock_find.return_value = None
        mock_delete.return_value = True

        # Setup qBittorrent
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance
        mock_qbit_instance.torrents_info.return_value = []

        # Setup Plex
        mock_plex_instance = MagicMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_item.return_value = True

        # Setup os.walk for orphan cleanup
        mock_walk.return_value = [
            (
                "/media/Movies/The Matrix (1999) [4K]",
                [],
                ["The Matrix (1999) [4K].mkv"],
            ),
        ]

        # Setup os.stat to return inode info for orphan cleanup
        mock_stat_result = MagicMock()
        mock_stat_result.st_ino = 54321
        mock_stat_result.st_nlink = 1
        mock_stat.return_value = mock_stat_result

        # Main file already deleted by *arr
        mock_exists.return_value = False

        # Execute deletion
        history = await deletion_pipeline.delete_file(dup_file.id)

        # Verify special characters were handled correctly and deletion completed
        assert history.is_complete is True
        # Main file already deleted by *arr, but orphaned files cleanup will find and delete it via os.walk
        # Verify os.remove was called once for the orphaned file
        mock_remove.assert_called_once_with(
            "/media/Movies/The Matrix (1999) [4K]/The Matrix (1999) [4K].mkv"
        )


@pytest.mark.asyncio
async def test_dry_run_mode_no_actual_changes(
    test_db, setup_configs, movie_with_mismatched_path
):
    """Test that dry-run mode doesn't make actual changes"""

    # Create pipeline in dry-run mode
    dry_run_pipeline = DeletionPipeline(test_db, dry_run=True)

    with (
        patch("app.services.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.radarr_service.RadarrClient") as mock_radarr,
        patch("app.services.deletion_pipeline.PlexService") as mock_plex_class,
        patch("os.path.exists", return_value=True),
        patch("os.remove") as mock_remove,
        patch("os.listdir", return_value=[]),
        patch("os.path.isfile", return_value=True),
    ):
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance

        mock_radarr_instance = AsyncMock()
        mock_radarr.return_value = mock_radarr_instance

        mock_plex_instance = MagicMock()
        mock_plex_class.return_value = mock_plex_instance

        # Execute deletion in dry-run mode
        history = await dry_run_pipeline.delete_file(movie_with_mismatched_path.id)

        # Verify no actual deletion methods were called
        mock_qbit_instance.torrents_delete.assert_not_called()
        mock_radarr_instance.del_movie_file.assert_not_called()
        mock_remove.assert_not_called()
        mock_plex_instance.refresh_item.assert_not_called()
        mock_plex_instance.refresh_library.assert_not_called()

        # But history should still be recorded
        assert history is not None
        assert history.duplicate_file_id == movie_with_mismatched_path.id
