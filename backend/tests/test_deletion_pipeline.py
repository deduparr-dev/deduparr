"""
Tests for deletion pipeline
"""

import errno
import os

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.core.config import settings
from app.services.deletion.pipeline import DeletionPipeline
from app.services.download.qbittorrent_service import TorrentMatch
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models import DuplicateSet, DuplicateFile, DeletionHistory
from app.models.duplicate import MediaType, DuplicateStatus
from app.models.config import Config
from app.services.arr.client import ArrConnectionError
from app.services.media_server import MediaServerError
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
        item_id="movie123",
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
        item_id="episode123",
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
    """A file an earlier deletion removed is not deleted twice"""
    history = DeletionHistory(
        duplicate_file_id=movie_duplicate_file.id, deleted_from_disk=True
    )
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
        patch("app.services.download.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.arr.radarr_service.RadarrClient") as mock_radarr,
        patch(
            "app.services.arr.radarr_service.RadarrService.rescan_movie",
            new_callable=AsyncMock,
        ) as mock_rescan_movie,
        patch(
            "app.services.deletion.pipeline.get_media_server",
            new_callable=AsyncMock,
        ) as mock_plex_class,
        patch("os.path.exists") as mock_exists,
        patch("os.remove") as mock_remove,
        patch("os.listdir") as mock_listdir,
    ):
        mock_qbit_instance = MagicMock()
        mock_qbit.return_value = mock_qbit_instance

        # Mock TWO torrents (safety check requires >1 torrent)
        mock_item = MagicMock()
        mock_item.hash = "abc123"
        mock_item.name = "Test Movie"
        mock_item.save_path = "/media/movies"
        mock_file = MagicMock()
        mock_file.name = "Test Movie.mkv"

        # Second torrent (the one we're keeping)
        mock_item2 = MagicMock()
        mock_item2.hash = "def456"
        mock_item2.name = "Test Movie"
        mock_item2.save_path = "/media/movies"
        mock_file2 = MagicMock()
        mock_file2.name = "Test Movie.mkv"

        mock_qbit_instance.torrents_info.return_value = [mock_item, mock_item2]
        # Need 4 calls: 2 for checking deleted file (one per torrent) + 2 for checking kept file (one per torrent)
        mock_qbit_instance.torrents_files.side_effect = [
            [mock_file],  # First torrent, checking deleted file
            [mock_file2],  # Second torrent, checking deleted file
            [],  # First torrent, checking kept file (no match)
            [
                mock_file2
            ],  # Second torrent, checking kept file (match - this is the one we're keeping)
        ]

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
        mock_radarr_instance.delete_movie_file = AsyncMock()
        mock_radarr_instance.post_command = AsyncMock(
            return_value={"id": 1, "status": "queued"}
        )
        # rescan_movie is patched directly on RadarrService class
        mock_rescan_movie.return_value = True

        # qBittorrent deleted the file along with its data, so the path is
        # gone. Returning True here would describe a file that was deleted and
        # is still present, which is what the fallback stage exists to clean up.
        mock_exists.side_effect = lambda path: "Test Movie.mkv" not in str(path)
        mock_listdir.return_value = []  # No associated files

        mock_plex_instance = AsyncMock()
        mock_plex_class.return_value = mock_plex_instance
        # New behavior: refresh_item targets the specific Plex item, fallback to refresh_library if it fails
        mock_plex_instance.refresh_item.return_value = True

        history = await deletion_pipeline.delete_file(movie_duplicate_file.id)

        assert history.deleted_from_qbit is True
        assert history.deleted_from_arr is True
        assert history.deleted_from_disk is True
        assert history.media_server_refreshed is True
        assert history.error is None
        assert history.is_complete is True
        assert history.arr_type == "radarr"
        assert history.qbit_torrent_hash == "abc123"

        # Verify deletion pipeline stages executed in correct order
        # Stage 1: *arr deletion (deletes file from disk)
        mock_radarr_instance.delete_movie_file.assert_called_once_with(10)

        # Stage 2: qBittorrent removal (deletes any remaining files)
        mock_qbit_instance.torrents_delete.assert_called_once_with(
            delete_files=True, torrent_hashes="abc123"
        )

        # Stage 3, the *arr rescan, runs once per set in delete_set
        mock_rescan_movie.assert_not_called()

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
        patch("os.remove") as mock_remove,
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

        # As above: qBittorrent removed the file with its data
        mock_exists.side_effect = lambda path: "S01E01.mkv" not in str(path)
        mock_listdir.return_value = []  # No associated files

        mock_plex_instance = AsyncMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_library.return_value = True

        history = await deletion_pipeline.delete_file(
            episode_duplicate_file.id, skip_qbit=False
        )

        assert history.deleted_from_qbit is True
        assert history.deleted_from_arr is True
        assert history.deleted_from_disk is True
        assert history.media_server_refreshed is True
        assert history.error is None
        assert history.is_complete is True
        assert history.arr_type == "sonarr"

        # Verify deletion pipeline stages executed in correct order
        # Stage 1: *arr deletion (deletes file from disk)
        mock_delete_episode_file.assert_called_once_with(1, 100)

        # Stage 2: qBittorrent removal would be here but torrents_info returned []
        # so qBit stage is skipped

        # Stage 3, the *arr rescan, runs once per set in delete_set
        mock_rescan_series.assert_not_called()

        # Stage 4: Disk cleanup - file already deleted by *arr
        mock_remove.assert_not_called()


@pytest.mark.asyncio
async def test_delete_file_skip_qbit(
    deletion_pipeline, test_db, setup_configs, movie_duplicate_file
):
    """Test deletion pipeline with qBittorrent skipped"""
    file_path = movie_duplicate_file.file_path

    with (
        patch("app.services.arr.radarr_service.RadarrClient") as mock_radarr,
        patch(
            "app.services.deletion.pipeline.get_media_server",
            new_callable=AsyncMock,
        ) as mock_plex_class,
        patch("os.path.exists") as mock_exists,
        patch("os.remove"),
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
        mock_radarr_instance.delete_movie_file = AsyncMock()

        mock_exists.return_value = True
        mock_listdir.return_value = []  # No associated files

        mock_plex_instance = AsyncMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_item.return_value = True

        history = await deletion_pipeline.delete_file(
            movie_duplicate_file.id, skip_qbit=True
        )

        assert history.deleted_from_qbit is False
        assert history.deleted_from_arr is True
        assert history.deleted_from_disk is True
        assert history.media_server_refreshed is True


@pytest.mark.asyncio
async def test_delete_file_not_on_disk(
    deletion_pipeline, test_db, setup_configs, movie_duplicate_file
):
    """Test deletion when file doesn't exist on disk"""
    file_path = movie_duplicate_file.file_path

    with (
        patch("app.services.download.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.arr.radarr_service.RadarrClient") as mock_radarr,
        patch(
            "app.services.deletion.pipeline.get_media_server",
            new_callable=AsyncMock,
        ) as mock_plex_class,
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
        mock_radarr_instance.delete_movie_file = AsyncMock()

        mock_exists.return_value = False

        mock_plex_instance = AsyncMock()
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
            "app.services.arr.radarr_service.RadarrService.find_movie_by_file_path",
            new_callable=AsyncMock,
        ) as mock_find,
        patch(
            "app.services.arr.radarr_service.RadarrService.delete_movie_file",
            new_callable=AsyncMock,
        ) as mock_delete,
        patch(
            "app.services.arr.radarr_service.RadarrService.rescan_movie",
            new_callable=AsyncMock,
        ),
        patch("app.services.download.qbittorrent_service.Client") as mock_qbit,
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
        patch("app.services.download.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.arr.radarr_service.RadarrClient") as mock_radarr,
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
        patch("app.services.download.qbittorrent_service.Client") as mock_qbit,
        patch("app.services.arr.radarr_service.RadarrClient") as mock_radarr,
        patch(
            "app.services.deletion.pipeline.get_media_server",
            new_callable=AsyncMock,
        ) as mock_plex_class,
        patch("os.path.exists") as mock_exists,
        patch("os.remove") as mock_remove,
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
        mock_radarr_instance.delete_movie_file = AsyncMock()

        mock_plex_instance = AsyncMock()
        mock_plex_class.return_value = mock_plex_instance
        mock_plex_instance.refresh_item.return_value = True

        mock_exists.return_value = True
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
    """A refresh failure after the file is gone is recorded, not raised"""
    file_id = movie_duplicate_file.id
    file_path = movie_duplicate_file.file_path

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
        mock_radarr_instance.delete_movie_file = AsyncMock()

        mock_exists.return_value = True
        mock_listdir.return_value = []  # No associated files

        mock_plex_instance = AsyncMock()
        mock_plex_class.return_value = mock_plex_instance
        # Both targeted and library refresh fail by raising exception
        mock_plex_instance.refresh_item.side_effect = Exception(
            "Plex connection failed"
        )

        history = await deletion_pipeline.delete_file(file_id)

        assert "Plex connection failed" in history.error
        assert history.deleted_from_qbit is True
        assert history.deleted_from_arr is True
        assert history.deleted_from_disk is True
        assert history.media_server_refreshed is False


@pytest.mark.asyncio
async def test_protected_files_not_deleted(deletion_pipeline, test_db, setup_configs):
    """
    Test that files marked keep=True are NOT deleted during cleanup

    Regression test for bug where deletion pipeline would search for
    files with the same name and delete ALL of them, including the
    file we wanted to keep.
    """
    import tempfile
    from pathlib import Path

    # Create a duplicate set with real temp files
    dup_set = DuplicateSet(
        item_id="movie999",
        title="Sonic the Hedgehog 2",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.APPROVED,
    )
    test_db.add(dup_set)
    await test_db.flush()

    # Create temp directories to simulate the structure
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create the "keep" file in organized folder
        keep_dir = Path(tmpdir) / "Sonic the Hedgehog 2 (2022)"
        keep_dir.mkdir()
        keep_file_path = keep_dir / "Sonic.the.Hedgehog.2.2022.mkv"
        keep_file_path.write_text("keep this file")

        # Create the "delete" file in release folder
        delete_dir = Path(tmpdir) / "Sonic.the.Hedgehog.2.2022.Release"
        delete_dir.mkdir()
        delete_file_path = delete_dir / "Sonic.the.Hedgehog.2.2022.mkv"
        delete_file_path.write_text("delete this file")

        # Create kept file record
        kept_file = DuplicateFile(
            set_id=dup_set.id,
            file_path=str(keep_file_path),
            file_size=14,
            score=100,
            keep=True,
        )
        test_db.add(kept_file)

        # Create the file to delete
        dup_file = DuplicateFile(
            set_id=dup_set.id,
            file_path=str(delete_file_path),
            file_size=16,
            score=50,
            keep=False,
        )
        test_db.add(dup_file)
        await test_db.commit()

        # Mock services to simulate orphaned file case (not found in qBit/Radarr)
        # Also mock Plex service creation
        mock_plex = AsyncMock()
        mock_plex.refresh_item.return_value = True

        with (
            patch.object(
                deletion_pipeline.qbit_service,
                "find_item_by_file_path",
                return_value=None,
            ),
            patch.object(
                deletion_pipeline.radarr_service,
                "find_movie_by_file_path",
                return_value=None,
            ),
            patch(
                "app.services.deletion.pipeline.get_media_server",
                new_callable=AsyncMock,
                return_value=mock_plex,
            ),
        ):
            # Execute deletion
            await deletion_pipeline.delete_file(dup_file.id)

            # CRITICAL: The kept file should still exist
            assert (
                keep_file_path.exists()
            ), "PROTECTED FILE WAS DELETED! This is the bug we're testing for."
            assert keep_file_path.read_text() == "keep this file"

            # The deleted file should be gone
            assert not delete_file_path.exists(), "File to delete should be removed"


@pytest.mark.asyncio
async def test_disk_stage_removes_a_file_an_earlier_stage_only_claimed_to_delete(
    test_db, tmp_path
):
    """An earlier stage reporting the file deleted does not stop its removal."""
    leftover = tmp_path / "Still Here.mkv"
    leftover.write_bytes(b"x" * 1024)

    history = DeletionHistory(duplicate_file_id=1, deleted_from_disk=True)
    await DeletionPipeline(test_db, dry_run=False)._stage_disk_removal(
        str(leftover), history, str(leftover)
    )

    assert not leftover.exists()
    assert history.deleted_from_disk is True


@pytest.mark.asyncio
async def test_disk_stage_cleans_up_beside_a_remapped_file(test_db, tmp_path):
    """
    Associated files are found where the file actually lived.

    The media server reports a path this container cannot see, and the *arr
    has already removed the file, so only the location resolved beforehand
    leads to the leftovers.
    """
    movie_dir = tmp_path / "media" / "Movies" / "Avatar (2009)"
    movie_dir.mkdir(parents=True)
    leftovers = [movie_dir / "Avatar.nfo", movie_dir / "Avatar.srt"]
    for path in leftovers:
        path.write_text("x")
    unrelated = movie_dir / "poster.jpg"
    unrelated.write_text("x")

    history = DeletionHistory(duplicate_file_id=1, deleted_from_arr=True)
    await DeletionPipeline(test_db, dry_run=False)._stage_disk_removal(
        "/plexdownloads/Movies/Avatar (2009)/Avatar.mkv",
        history,
        str(movie_dir / "Avatar.mkv"),
    )

    assert not any(path.exists() for path in leftovers)
    assert unrelated.exists()
    assert history.deleted_from_disk is True


@pytest.mark.asyncio
async def test_disk_stage_never_touches_a_same_named_file_elsewhere(
    test_db, tmp_path, monkeypatch
):
    """Another show's S01E01.mkv is not a leftover of this one's."""
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    show_a = tmp_path / "tv" / "Show A" / "Season 1"
    show_b = tmp_path / "tv" / "Show B" / "Season 1"
    show_a.mkdir(parents=True)
    show_b.mkdir(parents=True)
    other_show = show_b / "S01E01.mkv"
    other_show.write_bytes(b"x" * 1024)

    # Sonarr has already removed Show A's copy
    pipeline = DeletionPipeline(test_db, dry_run=False)
    gone = str(show_a / "S01E01.mkv")
    located = pipeline._locate_file(gone, 1024)
    history = DeletionHistory(duplicate_file_id=1, deleted_from_arr=True)
    await pipeline._stage_disk_removal(gone, history, located)

    assert located is None
    assert other_show.exists()


@pytest.mark.asyncio
async def test_disk_stage_leaves_the_kept_version_and_its_files(test_db, tmp_path):
    """
    Only files named after the deleted video go with it.

    The kept version and an extra both start with the deleted file's name,
    which used to be enough to delete them.
    """
    movie = tmp_path / "movies" / "Movie (2020)"
    movie.mkdir(parents=True)
    unwanted = movie / "Movie (2020).mkv"
    its_files = [
        movie / "Movie (2020).nfo",
        movie / "Movie (2020).en.srt",
        movie / "Movie (2020)-poster.jpg",
    ]
    others = [
        movie / "Movie (2020) - 1080p.mkv",
        movie / "Movie (2020) - 1080p.en.srt",
        movie / "Movie (2020)-trailer.mkv",
        movie / "poster.jpg",
    ]
    for path in [unwanted, *its_files, *others]:
        path.write_text("x")

    history = DeletionHistory(duplicate_file_id=1)
    await DeletionPipeline(test_db, dry_run=False)._stage_disk_removal(
        str(unwanted), history, str(unwanted)
    )

    assert not unwanted.exists()
    assert not any(path.exists() for path in its_files)
    assert all(path.exists() for path in others)
    assert history.deleted_from_disk is True


@pytest.mark.asyncio
async def test_disk_stage_keeps_folders_another_video_still_uses(test_db, tmp_path):
    """Deleting one episode leaves the season's Subs folder to the others."""
    season = tmp_path / "tv" / "Show" / "Season 1"
    (season / "Subs").mkdir(parents=True)
    subtitles = season / "Subs" / "Show - S01E02.en.srt"
    subtitles.write_text("x")
    unwanted = season / "Show - S01E01 - 720p.mkv"
    for path in [unwanted, season / "Show - S01E01 - 1080p.mkv"]:
        path.write_text("x")

    history = DeletionHistory(duplicate_file_id=1)
    await DeletionPipeline(test_db, dry_run=False)._stage_disk_removal(
        str(unwanted), history, str(unwanted)
    )

    assert not unwanted.exists()
    assert subtitles.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [False, True])
async def test_disk_stage_removes_a_release_folder_with_its_last_video(
    test_db, tmp_path, dry_run
):
    """A release folder goes with its only video, unless this is a dry run."""
    library = tmp_path / "movies"
    release = library / "Movie.2020.720p"
    (release / "Sample").mkdir(parents=True)
    (release / "Sample" / "movie-sample.mkv").write_text("x")
    video = release / "Movie.2020.720p.mkv"
    video.write_text("x")
    (release / "Movie.2020.720p.nfo").write_text("x")
    (library / "Other (2021)").mkdir()

    history = DeletionHistory(duplicate_file_id=1)
    await DeletionPipeline(test_db, dry_run=dry_run)._stage_disk_removal(
        str(video), history, str(video), str(library)
    )

    assert release.exists() is dry_run
    assert video.exists() is dry_run
    assert (library / "Other (2021)").exists()
    assert history.deleted_from_disk is True


@pytest.mark.asyncio
async def test_disk_stage_reports_a_file_it_could_not_delete(
    test_db, tmp_path, monkeypatch
):
    """A read-only mount leaves the file in place, and the deletion says so."""
    video = tmp_path / "Movie.mkv"
    video.write_text("x")

    def read_only(path):
        raise OSError(errno.EROFS, "Read-only file system", path)

    monkeypatch.setattr(os, "remove", read_only)
    history = DeletionHistory(duplicate_file_id=1)
    await DeletionPipeline(test_db, dry_run=False)._stage_disk_removal(
        str(video), history, str(video)
    )

    assert video.exists()
    assert history.deleted_from_disk is False
    assert "Read-only file system" in history.error


@pytest.mark.asyncio
async def test_locate_file_follows_a_remapped_mount(test_db, tmp_path, monkeypatch):
    """
    A path from another mount is found by its tail, at the size the server
    reported, never by its name alone.
    """
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    wanted = tmp_path / "movies" / "Avatar (2009)" / "Avatar.mkv"
    namesake = tmp_path / "movies" / "Avatar (2022)" / "Avatar.mkv"
    for path in [wanted, namesake]:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"x" * 10)
    pipeline = DeletionPipeline(test_db, dry_run=False)

    server_path = "/data/movies/Avatar (2009)/Avatar.mkv"
    assert pipeline._locate_file(server_path, 10) == str(wanted)
    # Same place, different file: the kept copy of another library, say
    assert pipeline._locate_file(server_path, 11) is None
    assert pipeline._locate_file("/data/movies/Gone (2001)/Avatar.mkv", 10) is None


@pytest.mark.asyncio
async def test_qbit_stage_leaves_a_torrent_that_holds_other_videos(
    test_db, create_duplicate_set, create_duplicate_file
):
    """Removing a season pack with its data would take the other episodes too."""
    dup_set = await create_duplicate_set(media_type=MediaType.EPISODE)
    unwanted = await create_duplicate_file(dup_set.id, keep=False)
    kept = await create_duplicate_file(dup_set.id, keep=True)

    pipeline = DeletionPipeline(test_db, dry_run=False)
    pipeline.qbit_service = AsyncMock()
    pipeline.qbit_service.find_item_by_file_path.side_effect = [
        TorrentMatch(hash="pack", count=1, holds_other_videos=True),
        None,  # the kept file has no torrent of its own
    ]
    history = DeletionHistory(duplicate_file_id=unwanted.id)

    assert (
        await pipeline._stage_qbittorrent_removal(unwanted, history, None, kept) is None
    )
    pipeline.qbit_service.remove_item.assert_not_awaited()
    assert history.deleted_from_qbit is True


async def _with_files(test_db, set_id: int) -> DuplicateSet:
    return (
        await test_db.execute(
            select(DuplicateSet)
            .options(selectinload(DuplicateSet.files))
            .where(DuplicateSet.id == set_id)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_delete_set_retries_only_what_an_earlier_attempt_left(
    test_db, create_duplicate_set, create_duplicate_file, tmp_path
):
    """
    A file that could not be found is an error and keeps the set pending.
    Once it is back, the next attempt deletes it and skips the one already gone.
    """
    keep, first, second = (tmp_path / f"{n}.mkv" for n in ("keep", "first", "second"))
    keep.write_bytes(b"k" * 30)
    first.write_bytes(b"f" * 10)

    dup_set = await create_duplicate_set(media_server="disk")
    await create_duplicate_file(
        dup_set.id, file_path=str(keep), file_size=30, keep=True
    )
    await create_duplicate_file(dup_set.id, file_path=str(first), file_size=10)
    await create_duplicate_file(dup_set.id, file_path=str(second), file_size=20)

    dup_set = await _with_files(test_db, dup_set.id)
    outcome = await DeletionPipeline(test_db, dry_run=False).delete_set(dup_set)

    assert (outcome.files_deleted, outcome.space_reclaimed) == (1, 10)
    assert len(outcome.errors) == 1
    assert "File not found for deletion" in outcome.errors[0]
    assert dup_set.status == DuplicateStatus.PENDING

    second.write_bytes(b"s" * 20)
    dup_set = await _with_files(test_db, dup_set.id)
    outcome = await DeletionPipeline(test_db, dry_run=False).delete_set(dup_set)

    assert (outcome.files_deleted, outcome.errors) == (1, [])
    assert not first.exists() and not second.exists() and keep.exists()
    assert dup_set.status == DuplicateStatus.PROCESSED


@pytest.mark.asyncio
async def test_delete_set_counts_a_deleted_file_when_the_refresh_fails(
    test_db, create_duplicate_set, create_duplicate_file, tmp_path, monkeypatch
):
    """The file is gone, so the set is done; the failed refresh is a warning."""
    server = AsyncMock()
    server.refresh_item.side_effect = Exception("Plex connection failed")
    monkeypatch.setattr(
        "app.services.deletion.pipeline.get_media_server",
        AsyncMock(return_value=server),
    )
    keep, drop = tmp_path / "keep.mkv", tmp_path / "drop.mkv"
    keep.write_bytes(b"k" * 30)
    drop.write_bytes(b"d" * 10)

    dup_set = await create_duplicate_set()
    await create_duplicate_file(
        dup_set.id, file_path=str(keep), file_size=30, keep=True
    )
    await create_duplicate_file(dup_set.id, file_path=str(drop), file_size=10)

    dup_set = await _with_files(test_db, dup_set.id)
    outcome = await DeletionPipeline(test_db, dry_run=False).delete_set(dup_set)

    assert (outcome.files_deleted, outcome.errors) == (1, [])
    assert any("Plex refresh failed" in warning for warning in outcome.warnings)
    assert not drop.exists()
    assert dup_set.status == DuplicateStatus.PROCESSED


@pytest.mark.asyncio
@pytest.mark.parametrize("tracked", [True, False])
async def test_delete_set_rescans_the_arr_once_after_every_file(
    test_db, create_duplicate_set, create_duplicate_file, tmp_path, tracked
):
    """
    Radarr rescans the movie once its unwanted files are all gone. A movie
    Radarr tracks under neither path is looked for in its whole library.
    """
    keep, first, second = (tmp_path / f"{n}.mkv" for n in ("keep", "first", "second"))
    for path in (keep, first, second):
        path.write_bytes(b"x" * 10)
    dup_set = await create_duplicate_set(media_server="disk")
    await create_duplicate_file(
        dup_set.id, file_path=str(keep), file_size=10, keep=True
    )
    for path in (first, second):
        await create_duplicate_file(dup_set.id, file_path=str(path), file_size=10)

    pipeline = DeletionPipeline(test_db, dry_run=False)
    pipeline.radarr_service = AsyncMock()
    pipeline.radarr_service.find_movie_by_file_path.side_effect = lambda path: (
        {"id": 7, "movieFile": {"id": 70}} if tracked and path != str(keep) else None
    )
    outcome = await pipeline.delete_set(await _with_files(test_db, dup_set.id))

    assert outcome.files_deleted == 2
    pipeline.radarr_service.rescan_movie.assert_awaited_once_with(
        7 if tracked else None, str(keep)
    )


@pytest.mark.asyncio
async def test_delete_set_reports_a_rescan_radarr_never_got(
    test_db, create_duplicate_set, create_duplicate_file, tmp_path
):
    """Radarr being down after the deletion is for the user to know, not only the log."""
    keep, drop = tmp_path / "keep.mkv", tmp_path / "drop.mkv"
    for path in (keep, drop):
        path.write_bytes(b"x" * 10)
    dup_set = await create_duplicate_set(media_server="disk")
    await create_duplicate_file(
        dup_set.id, file_path=str(keep), file_size=10, keep=True
    )
    await create_duplicate_file(dup_set.id, file_path=str(drop), file_size=10)

    pipeline = DeletionPipeline(test_db, dry_run=False)
    pipeline.radarr_service = AsyncMock()
    pipeline.radarr_service.find_movie_by_file_path.return_value = None
    pipeline.radarr_service.rescan_movie.side_effect = ArrConnectionError(
        "Failed to connect to http://radarr:7878: connection refused"
    )
    outcome = await pipeline.delete_set(await _with_files(test_db, dup_set.id))

    assert (outcome.files_deleted, outcome.errors) == (1, [])
    assert (
        "Radarr was not asked to rescan: Failed to connect to "
        "http://radarr:7878: connection refused"
    ) in outcome.warnings


@pytest.mark.asyncio
async def test_delete_set_reports_what_the_arr_could_not_import(
    test_db, create_duplicate_set, create_duplicate_file, tmp_path
):
    """A kept file the *arr cannot take is in the result, not only the log."""
    keep, drop = tmp_path / "keep.mkv", tmp_path / "drop.mkv"
    keep.write_bytes(b"k" * 30)
    drop.write_bytes(b"d" * 10)
    dup_set = await create_duplicate_set(media_server="disk")
    await create_duplicate_file(
        dup_set.id, file_path=str(keep), file_size=30, keep=True
    )
    await create_duplicate_file(dup_set.id, file_path=str(drop), file_size=10)

    pipeline = DeletionPipeline(test_db, dry_run=False)
    problem = f"Radarr cannot import {keep}: it sits directly in the root folder"
    with patch.object(
        pipeline, "rescan_for_kept_file", AsyncMock(side_effect=ValueError(problem))
    ):
        outcome = await pipeline.delete_set(await _with_files(test_db, dup_set.id))

    assert (outcome.files_deleted, outcome.errors) == (1, [])
    assert problem in outcome.warnings
    assert dup_set.status == DuplicateStatus.PROCESSED


async def _split_movie(test_db, create_duplicate_set, create_duplicate_file, root):
    """A movie kept in movies/ whose other copy is the only title in movies-4k/."""
    kept = root / "movies" / "Movie (2020)" / "Movie (2020) 1080p.mkv"
    dropped = root / "movies-4k" / "Movie (2020)" / "Movie (2020) 2160p.mkv"
    for path in (kept, dropped):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"x" * 10)

    dup_set = await create_duplicate_set(media_server="jellyfin")
    for path, keep in ((kept, True), (dropped, False)):
        await create_duplicate_file(
            dup_set.id, file_path=str(path), file_size=10, keep=keep
        )
    return await _with_files(test_db, dup_set.id), kept, dropped


@pytest.mark.asyncio
@pytest.mark.parametrize("server_mount", [None, "/data"])
async def test_deleting_the_last_title_in_a_library_folder_keeps_the_folder(
    test_db,
    create_duplicate_set,
    create_duplicate_file,
    tmp_path,
    monkeypatch,
    server_mount,
):
    """
    The copy's own folder goes, its library folder stays: Radarr, Sonarr and
    the media server still point at it. The server may mount the media
    somewhere else than this container does.
    """
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    dup_set, kept, dropped = await _split_movie(
        test_db, create_duplicate_set, create_duplicate_file, tmp_path
    )
    mount = server_mount or str(tmp_path)
    for file in dup_set.files:
        file.file_path = file.file_path.replace(str(tmp_path), mount)
    server = AsyncMock()
    server.get_libraries.return_value = [{"title": "Movies"}]
    server.get_library_paths.return_value = [f"{mount}/movies", f"{mount}/movies-4k"]
    monkeypatch.setattr(
        "app.services.deletion.pipeline.get_media_server",
        AsyncMock(return_value=server),
    )

    outcome = await DeletionPipeline(test_db, dry_run=False).delete_set(dup_set)

    assert (outcome.files_deleted, outcome.errors) == (1, [])
    assert not dropped.parent.exists()
    assert (tmp_path / "movies-4k").is_dir()
    assert kept.exists()


@pytest.mark.asyncio
async def test_folders_stay_when_the_library_folders_cannot_be_listed(
    test_db, create_duplicate_set, create_duplicate_file, tmp_path, monkeypatch
):
    """Without the library folder there is no telling where removing must stop."""
    dup_set, kept, dropped = await _split_movie(
        test_db, create_duplicate_set, create_duplicate_file, tmp_path
    )
    server = AsyncMock()
    server.get_libraries.side_effect = MediaServerError("Jellyfin is unreachable")
    monkeypatch.setattr(
        "app.services.deletion.pipeline.get_media_server",
        AsyncMock(return_value=server),
    )

    outcome = await DeletionPipeline(test_db, dry_run=False).delete_set(dup_set)

    assert (outcome.files_deleted, outcome.errors) == (1, [])
    assert not dropped.exists()
    assert dropped.parent.is_dir()


@pytest.mark.asyncio
async def test_arr_stage_deletes_an_orphaned_sonarr_file(
    test_db, create_duplicate_set, create_duplicate_file
):
    """
    Sonarr can hold a file no episode points at. It has no episode number,
    which the stage used to format into its log line and crash on.
    """
    dup_set = await create_duplicate_set(media_type=MediaType.EPISODE)
    created = await create_duplicate_file(dup_set.id, file_path="/tv/Show/S01E02.mkv")
    unwanted = (
        await test_db.execute(
            select(DuplicateFile)
            .options(selectinload(DuplicateFile.duplicate_set))
            .where(DuplicateFile.id == created.id)
        )
    ).scalar_one()

    pipeline = DeletionPipeline(test_db, dry_run=False)
    pipeline.sonarr_service = AsyncMock()
    pipeline.sonarr_service.find_episode_by_file_path.return_value = {
        "seriesId": 7,
        "seasonNumber": 1,
        "episodeFile": {"id": 70, "path": unwanted.file_path},
        "title": "Orphaned S01 file",
    }
    history = DeletionHistory(duplicate_file_id=unwanted.id)

    assert await pipeline._stage_arr_removal(unwanted, history) == ("sonarr", 7)
    pipeline.sonarr_service.delete_episode_file.assert_awaited_once_with(7, 70)
    assert history.deleted_from_arr is True
