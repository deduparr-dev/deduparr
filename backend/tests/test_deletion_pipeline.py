"""
Tests for deletion pipeline
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.services.deletion_pipeline import DeletionPipeline
from app.models import DuplicateSet, DuplicateFile, DeletionHistory
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
        Config(key="plex_library_name", value="Movies"),
    ]
    test_db.add_all(configs)
    await test_db.commit()


@pytest.fixture
async def movie_duplicate_file(test_db):
    """Create a movie duplicate file for testing"""
    dup_set = DuplicateSet(
        plex_item_id="movie123",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.APPROVED,
    )
    test_db.add(dup_set)
    await test_db.flush()

    # Create a kept file (better quality)
    kept_file = DuplicateFile(
        set_id=dup_set.id,
        file_path="/media/movies/Test Movie 1080p.mkv",
        file_size=2000000000,
        score=100,
        keep=True,
    )
    test_db.add(kept_file)

    # Create the file to delete (lower quality)
    dup_file = DuplicateFile(
        set_id=dup_set.id,
        file_path="/media/movies/Test Movie.mkv",
        file_size=1000000000,
        score=50,
        keep=False,
    )
    test_db.add(dup_file)
    await test_db.commit()
    return dup_file


@pytest.fixture
async def episode_duplicate_file(test_db):
    """Create an episode duplicate file for testing"""
    dup_set = DuplicateSet(
        plex_item_id="episode123",
        title="Test Episode",
        media_type=MediaType.EPISODE,
        status=DuplicateStatus.APPROVED,
    )
    test_db.add(dup_set)
    await test_db.flush()

    # Create a kept file (better quality)
    kept_file = DuplicateFile(
        set_id=dup_set.id,
        file_path="/media/tv/Test Series/S01E01 1080p.mkv",
        file_size=1000000000,
        score=100,
        keep=True,
    )
    test_db.add(kept_file)

    # Create the file to delete (lower quality)
    dup_file = DuplicateFile(
        set_id=dup_set.id,
        file_path="/media/tv/Test Series/S01E01.mkv",
        file_size=500000000,
        score=30,
        keep=False,
    )
    test_db.add(dup_file)
    await test_db.commit()
    return dup_file


@pytest.mark.asyncio
async def test_delete_file_not_found(deletion_pipeline, test_db, setup_configs):
    """Test deletion when file doesn't exist"""
    with pytest.raises(ValueError, match="DuplicateFile .* not found"):
        await deletion_pipeline.delete_file(99999)


@pytest.mark.asyncio
async def test_delete_file_already_deleted(
    deletion_pipeline, test_db, setup_configs, movie_duplicate_file
):
    """Test deletion when file already has deletion history"""
    history = DeletionHistory(duplicate_file_id=movie_duplicate_file.id)
    test_db.add(history)
    await test_db.commit()

    with pytest.raises(ValueError, match="Deletion already in progress"):
        await deletion_pipeline.delete_file(movie_duplicate_file.id)


@pytest.mark.asyncio
async def test_delete_movie_full_pipeline_success(
    deletion_pipeline, test_db, setup_configs, movie_duplicate_file
):
    """Test successful full deletion pipeline for movie"""
    file_path = movie_duplicate_file.file_path

    with (
        patch("app.services.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.radarr_service.RadarrClient") as mock_radarr,
        patch(
            "app.services.radarr_service.RadarrService.rescan_movie",
            new_callable=AsyncMock,
        ) as mock_rescan_movie,
        patch("app.services.deletion_pipeline.PlexService") as mock_plex_class,
        patch("os.path.exists") as mock_exists,
        patch("os.remove") as mock_remove,
        patch("os.walk") as mock_walk,
        patch("os.listdir") as mock_listdir,
    ):
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance

        mock_item = MagicMock()
        mock_item.hash = "abc123"
        mock_item.name = "Test Movie"
        mock_item.save_path = "/media/movies"
        mock_file = MagicMock()
        mock_file.name = "Test Movie.mkv"

        mock_qbit_instance.torrents_info.return_value = [mock_item]
        mock_qbit_instance.torrents_files.return_value = [mock_file]

        mock_radarr_instance = AsyncMock()
        mock_radarr.return_value = mock_radarr_instance
        mock_radarr_instance.get_movie = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "title": "Test Movie",
                    "movieFile": {"id": 10, "path": file_path},
                }
            ]
        )
        mock_radarr_instance.del_movie_file = AsyncMock()
        mock_radarr_instance.post_command = AsyncMock(
            return_value={"id": 1, "status": "queued"}
        )
        # rescan_movie is patched directly on RadarrService class
        mock_rescan_movie.return_value = True

        mock_exists.return_value = True
        # Mock os.walk for _find_file_in_media_root
        mock_walk.return_value = [
            ("/media/movies", [], ["Test Movie.mkv"]),
        ]
        mock_listdir.return_value = []  # No associated files

        mock_plex_instance = MagicMock()
        mock_plex_class.return_value = mock_plex_instance
        # New behavior: refresh_item targets the specific Plex item, fallback to refresh_library if it fails
        mock_plex_instance.refresh_item.return_value = True

        history = await deletion_pipeline.delete_file(movie_duplicate_file.id)

        assert history.deleted_from_qbit is True
        assert history.deleted_from_arr is True
        assert history.deleted_from_disk is True
        assert history.plex_refreshed is True
        assert history.error is None
        assert history.is_complete is True
        assert history.arr_type == "radarr"
        assert history.qbit_torrent_hash == "abc123"

        # Verify deletion pipeline stages executed in correct order
        # Stage 1: *arr deletion (deletes file from disk)
        mock_radarr_instance.del_movie_file.assert_called_once_with(10)

        # Stage 2: qBittorrent removal (deletes any remaining files)
        mock_qbit_instance.torrents_delete.assert_called_once_with(
            delete_files=True, torrent_hashes="abc123"
        )

        # Stage 3: *arr rescan (finds and imports the better file we kept)
        mock_rescan_movie.assert_called_once_with(
            1, "/media/movies/Test Movie 1080p.mkv"
        )

        # Stage 4: Disk cleanup is skipped when qBit already deleted files
        # (os.remove should NOT be called)
        mock_remove.assert_not_called()

        # Stage 5: Targeted Plex refresh
        mock_plex_instance.refresh_item.assert_called_once()


@pytest.mark.asyncio
async def test_delete_episode_full_pipeline_success(
    deletion_pipeline, test_db, setup_configs, episode_duplicate_file
):
    """Test successful full deletion pipeline for episode"""
    file_path = episode_duplicate_file.file_path

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
        patch("os.remove") as mock_remove,
        patch("os.walk") as mock_walk,
        patch("os.listdir") as mock_listdir,
    ):
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance
        mock_qbit_instance.torrents_info.return_value = []

        # Mock find_episode to return episode data with episodeFile
        mock_find_episode.return_value = {
            "id": 10,
            "title": "Test Episode",
            "seriesId": 1,
            "seasonNumber": 1,
            "episodeNumber": 1,
            "episodeFile": {"id": 100, "path": file_path},
        }
        # Mock the deletion method
        mock_delete_episode_file.return_value = None
        # Mock rescan
        mock_rescan_series.return_value = True

        mock_exists.return_value = True
        # Mock os.walk for _find_file_in_media_root
        mock_walk.return_value = [
            ("/media/tv/Test Series", [], ["S01E01.mkv"]),
        ]
        mock_listdir.return_value = []  # No associated files

        mock_plex_instance = MagicMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_library.return_value = True

        history = await deletion_pipeline.delete_file(
            episode_duplicate_file.id, skip_qbit=False
        )

        assert history.deleted_from_qbit is True
        assert history.deleted_from_arr is True
        assert history.deleted_from_disk is True
        assert history.plex_refreshed is True
        assert history.error is None
        assert history.is_complete is True
        assert history.arr_type == "sonarr"

        # Verify deletion pipeline stages executed in correct order
        # Stage 1: *arr deletion (deletes file from disk)
        mock_delete_episode_file.assert_called_once_with(1, 100)

        # Stage 2: qBittorrent removal would be here but torrents_info returned []
        # so qBit stage is skipped

        # Stage 3: *arr rescan (finds and imports the better file we kept)
        mock_rescan_series.assert_called_once_with(
            1, "/media/tv/Test Series/S01E01 1080p.mkv"
        )

        # Stage 4: Disk cleanup - file already deleted by *arr
        mock_remove.assert_not_called()


@pytest.mark.asyncio
async def test_delete_file_skip_qbit(
    deletion_pipeline, test_db, setup_configs, movie_duplicate_file
):
    """Test deletion pipeline with qBittorrent skipped"""
    file_path = movie_duplicate_file.file_path

    with (
        patch("app.services.radarr_service.RadarrClient") as mock_radarr,
        patch("app.services.deletion_pipeline.PlexService") as mock_plex_class,
        patch("os.path.exists") as mock_exists,
        patch("os.remove"),
        patch("os.walk") as mock_walk,
        patch("os.listdir") as mock_listdir,
    ):
        mock_radarr_instance = AsyncMock()
        mock_radarr.return_value = mock_radarr_instance
        mock_radarr_instance.get_movie = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "title": "Test Movie",
                    "movieFile": {"id": 10, "path": file_path},
                }
            ]
        )
        mock_radarr_instance.del_movie_file = AsyncMock()

        mock_exists.return_value = True
        mock_walk.return_value = [
            ("/media/movies", [], ["Test Movie.mkv"]),
        ]
        mock_listdir.return_value = []  # No associated files

        mock_plex_instance = MagicMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_item.return_value = True

        history = await deletion_pipeline.delete_file(
            movie_duplicate_file.id, skip_qbit=True
        )

        assert history.deleted_from_qbit is False
        assert history.deleted_from_arr is True
        assert history.deleted_from_disk is True
        assert history.plex_refreshed is True


@pytest.mark.asyncio
async def test_delete_file_not_on_disk(
    deletion_pipeline, test_db, setup_configs, movie_duplicate_file
):
    """Test deletion when file doesn't exist on disk"""
    file_path = movie_duplicate_file.file_path

    with (
        patch("app.services.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.radarr_service.RadarrClient") as mock_radarr,
        patch("app.services.deletion_pipeline.PlexService") as mock_plex_class,
        patch("os.path.exists") as mock_exists,
    ):
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance
        mock_qbit_instance.torrents_info.return_value = []

        mock_radarr_instance = AsyncMock()
        mock_radarr.return_value = mock_radarr_instance
        mock_radarr_instance.get_movie = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "title": "Test Movie",
                    "movieFile": {"id": 10, "path": file_path},
                }
            ]
        )
        mock_radarr_instance.del_movie_file = AsyncMock()

        mock_exists.return_value = False

        mock_plex_instance = MagicMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_library.return_value = True

        history = await deletion_pipeline.delete_file(movie_duplicate_file.id)

        assert history.deleted_from_disk is True
        assert history.is_complete is True


@pytest.mark.asyncio
async def test_delete_file_qbit_failure(
    deletion_pipeline, test_db, setup_configs, movie_duplicate_file
):
    """Test rollback when qBittorrent deletion fails - history should be cleaned up"""
    file_id = movie_duplicate_file.id

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
        patch("app.services.qbittorrent_service.Client") as mock_qbit,
    ):
        # Setup Radarr service mocks to allow pipeline to reach qBit stage
        mock_find.return_value = (1, 10)  # (movie_id, file_id)
        mock_delete.return_value = True

        # Setup qBit to fail
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance
        mock_qbit_instance.torrents_info.side_effect = Exception(
            "qBit connection failed"
        )

        with pytest.raises(Exception, match="qBit connection failed"):
            await deletion_pipeline.delete_file(file_id)

        from sqlalchemy import select

        # History should be deleted during rollback since no destructive operations occurred
        result = await test_db.execute(
            select(DeletionHistory).where(DeletionHistory.duplicate_file_id == file_id)
        )
        history = result.scalar_one_or_none()
        assert history is None  # Should be cleaned up


@pytest.mark.asyncio
async def test_delete_file_arr_failure(
    deletion_pipeline, test_db, setup_configs, movie_duplicate_file
):
    """Test rollback when Radarr deletion fails - history cleaned up when no item found"""
    file_id = movie_duplicate_file.id

    with (
        patch("app.services.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.radarr_service.RadarrClient") as mock_radarr,
    ):
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance
        mock_qbit_instance.torrents_info.return_value = []  # No item found

        mock_radarr_instance = AsyncMock()
        mock_radarr.return_value = mock_radarr_instance
        mock_radarr_instance.get_movie = AsyncMock(
            side_effect=Exception("Radarr connection failed")
        )

        with pytest.raises(Exception, match="Radarr connection failed"):
            await deletion_pipeline.delete_file(file_id)

        from sqlalchemy import select

        # History should be deleted during rollback since:
        # - qBit found no item (item_hash=None, so no actual removal occurred)
        # - Radarr failed before removal
        # - No destructive operations occurred
        result = await test_db.execute(
            select(DeletionHistory).where(DeletionHistory.duplicate_file_id == file_id)
        )
        history = result.scalar_one_or_none()
        assert history is None  # Should be cleaned up


@pytest.mark.asyncio
async def test_delete_file_disk_failure(
    deletion_pipeline, test_db, setup_configs, movie_duplicate_file
):
    """Test rollback when disk deletion fails"""
    file_id = movie_duplicate_file.id
    file_path = movie_duplicate_file.file_path

    with (
        patch("app.services.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.radarr_service.RadarrClient") as mock_radarr,
        patch("app.services.deletion_pipeline.PlexService") as mock_plex_class,
        patch("os.path.exists") as mock_exists,
        patch("os.remove") as mock_remove,
        patch("os.walk") as mock_walk,
        patch("os.listdir") as mock_listdir,
    ):
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance
        mock_qbit_instance.torrents_info.return_value = []

        mock_radarr_instance = AsyncMock()
        mock_radarr.return_value = mock_radarr_instance
        mock_radarr_instance.get_movie = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "title": "Test Movie",
                    "movieFile": {"id": 10, "path": file_path},
                }
            ]
        )
        mock_radarr_instance.del_movie_file = AsyncMock()

        mock_plex_instance = MagicMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_item.return_value = True

        mock_exists.return_value = True
        # Mock os.walk for _find_file_in_media_root
        mock_walk.return_value = [
            ("/media/movies", [], ["Test Movie.mkv"]),
        ]
        mock_listdir.return_value = []  # No associated files
        mock_remove.side_effect = PermissionError("Permission denied")

        # New behavior: PermissionError on disk deletion is handled gracefully
        # (readonly filesystems are OK since Radarr/Sonarr handle deletion)
        history = await deletion_pipeline.delete_file(file_id)

        # Verify deletion marked as successful despite readonly filesystem
        assert history.deleted_from_qbit is True
        assert history.deleted_from_arr is True
        assert history.deleted_from_disk is True  # Marked as success
        assert history.error is None  # No error recorded
        assert history.is_complete is True


@pytest.mark.asyncio
async def test_delete_file_plex_failure(
    deletion_pipeline, test_db, setup_configs, movie_duplicate_file
):
    """Test rollback when Plex refresh fails"""
    file_id = movie_duplicate_file.id
    file_path = movie_duplicate_file.file_path

    with (
        patch("app.services.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.radarr_service.RadarrClient") as mock_radarr,
        patch("app.services.deletion_pipeline.PlexService") as mock_plex_class,
        patch("os.path.exists") as mock_exists,
        patch("os.remove"),
        patch("os.walk") as mock_walk,
        patch("os.listdir") as mock_listdir,
    ):
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance
        mock_qbit_instance.torrents_info.return_value = []

        mock_radarr_instance = AsyncMock()
        mock_radarr.return_value = mock_radarr_instance
        mock_radarr_instance.get_movie = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "title": "Test Movie",
                    "movieFile": {"id": 10, "path": file_path},
                }
            ]
        )
        mock_radarr_instance.del_movie_file = AsyncMock()

        mock_exists.return_value = True
        # Mock os.walk for _find_file_in_media_root
        mock_walk.return_value = [
            ("/media/movies", [], ["Test Movie.mkv"]),
        ]
        mock_listdir.return_value = []  # No associated files

        mock_plex_instance = MagicMock()
        mock_plex_class.return_value = mock_plex_instance
        # Both targeted and library refresh fail by raising exception
        mock_plex_instance.refresh_item.side_effect = Exception(
            "Plex connection failed"
        )

        with pytest.raises(Exception, match="Plex connection failed"):
            await deletion_pipeline.delete_file(file_id)

        from sqlalchemy import select

        result = await test_db.execute(
            select(DeletionHistory).where(DeletionHistory.duplicate_file_id == file_id)
        )
        history = result.scalar_one()

        assert "Plex connection failed" in history.error
        assert history.deleted_from_qbit is True
        assert history.deleted_from_arr is True
        assert history.deleted_from_disk is True
        assert history.plex_refreshed is False
