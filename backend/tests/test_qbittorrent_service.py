"""
Tests for qBittorrent service
"""

import pytest
from unittest.mock import MagicMock, patch

from app.services.download.qbittorrent_service import QBittorrentService
from app.models.config import Config
from tests.conftest import encrypt_test_password


@pytest.mark.asyncio
async def test_qbittorrent_client_initialization(test_db):
    """Test qBittorrent client initialization with config from database"""
    config_url = Config(key="qbittorrent_url", value="http://localhost:8080")
    config_username = Config(key="qbittorrent_username", value="admin")
    config_password = Config(
        key="qbittorrent_password", value=encrypt_test_password("adminpass")
    )

    test_db.add(config_url)
    test_db.add(config_username)
    test_db.add(config_password)
    await test_db.commit()

    service = QBittorrentService(test_db)

    with patch("app.services.download.qbittorrent_service.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        client = await service._get_client()

        mock_client_class.assert_called_once_with(
            host="http://localhost:8080",
            username="admin",
            password="adminpass",
        )
        mock_client.auth_log_in.assert_called_once()
        assert client == mock_client


@pytest.mark.asyncio
async def test_qbittorrent_missing_config(test_db):
    """Test error when qBittorrent config is missing"""
    service = QBittorrentService(test_db)

    with pytest.raises(ValueError, match="qBittorrent configuration not found"):
        await service._get_client()


@pytest.mark.asyncio
async def test_find_item_by_file_path_found(test_db):
    """Test finding item by file path when item exists"""
    config_url = Config(key="qbittorrent_url", value="http://localhost:8080")
    config_username = Config(key="qbittorrent_username", value="admin")
    config_password = Config(
        key="qbittorrent_password", value=encrypt_test_password("adminpass")
    )

    test_db.add_all([config_url, config_username, config_password])
    await test_db.commit()

    service = QBittorrentService(test_db)

    mock_item = MagicMock()
    mock_item.hash = "abc123"
    mock_item.name = "Movie"
    mock_item.save_path = "/downloads"

    mock_file = MagicMock()
    mock_file.name = "Movie.mkv"

    with patch("app.services.download.qbittorrent_service.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.torrents_info.return_value = [mock_item]
        mock_client.torrents_files.return_value = [mock_file]

        result = await service.find_item_by_file_path("/downloads/Movie.mkv", 1000)

        assert result is not None
        assert result.hash == "abc123"
        assert result.count == 1
        mock_client.torrents_info.assert_called_once()
        mock_client.torrents_files.assert_called_once_with(torrent_hash="abc123")


@pytest.mark.asyncio
async def test_find_item_by_file_path_not_found(test_db):
    """Test finding item when file doesn't match any items"""
    config_url = Config(key="qbittorrent_url", value="http://localhost:8080")
    config_username = Config(key="qbittorrent_username", value="admin")
    config_password = Config(
        key="qbittorrent_password", value=encrypt_test_password("adminpass")
    )

    test_db.add_all([config_url, config_username, config_password])
    await test_db.commit()

    service = QBittorrentService(test_db)

    mock_item = MagicMock()
    mock_item.hash = "abc123"
    mock_item.name = "OtherMovie"
    mock_item.save_path = "/downloads"

    mock_file = MagicMock()
    mock_file.name = "OtherMovie.mkv"

    with patch("app.services.download.qbittorrent_service.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.torrents_info.return_value = [mock_item]
        mock_client.torrents_files.return_value = [mock_file]

        result = await service.find_item_by_file_path(
            "/downloads/NonExistent.mkv", 1000
        )

        assert result is None


def _torrent(torrent_hash: str, save_path: str, *files: tuple[str, int]):
    torrent = MagicMock(hash=torrent_hash, save_path=save_path)
    torrent.files = []
    for name, size in files:
        torrent_file = MagicMock(size=size)
        torrent_file.name = name
        torrent.files.append(torrent_file)
    return torrent


async def _find(test_db, torrents, file_path: str, file_size: int):
    test_db.add_all(
        [
            Config(key="qbittorrent_url", value="http://localhost:8080"),
            Config(key="qbittorrent_username", value="admin"),
            Config(
                key="qbittorrent_password", value=encrypt_test_password("adminpass")
            ),
        ]
    )
    await test_db.commit()

    with patch("app.services.download.qbittorrent_service.Client") as client_class:
        client = client_class.return_value
        client.torrents_info.return_value = torrents
        client.torrents_files.side_effect = lambda torrent_hash: next(
            t.files for t in torrents if t.hash == torrent_hash
        )
        return await QBittorrentService(test_db).find_item_by_file_path(
            file_path, file_size
        )


@pytest.mark.asyncio
async def test_find_item_needs_more_than_a_shared_name(test_db):
    """Under another mount, a torrent file matches on its name and its size."""
    torrents = [
        _torrent("show_a", "/downloads", ("Show A/S01E01.mkv", 100)),
        _torrent("show_b", "/downloads", ("Show B/S01E01.mkv", 200)),
    ]

    result = await _find(test_db, torrents, "/media/tv/Show B/Season 1/S01E01.mkv", 200)

    assert result.hash == "show_b"
    assert result.count == 1


@pytest.mark.asyncio
async def test_find_item_ignores_a_namesake_of_another_size(test_db):
    torrents = [_torrent("show_a", "/downloads", ("Show A/S01E01.mkv", 100))]

    assert await _find(test_db, torrents, "/media/tv/Show B/S01E01.mkv", 200) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "file_path, file_size, holds_other_videos",
    [("/tv/Show.S01E01.mkv", 100, True), ("/movies/Movie.2020.mkv", 300, False)],
)
async def test_find_item_says_when_the_torrent_holds_other_videos(
    test_db, file_path, file_size, holds_other_videos
):
    """A season pack holds other episodes; a movie's sample does not count."""
    torrents = [
        _torrent(
            "pack",
            "/downloads",
            ("Show.S01/Show.S01E01.mkv", 100),
            ("Show.S01/Show.S01E02.mkv", 100),
        ),
        _torrent(
            "movie",
            "/downloads",
            ("Movie.2020/Movie.2020.mkv", 300),
            ("Movie.2020/Sample/movie-sample.mkv", 3),
            ("Movie.2020/Movie.2020.nfo", 1),
        ),
    ]

    result = await _find(test_db, torrents, file_path, file_size)

    assert result.holds_other_videos is holds_other_videos


@pytest.mark.asyncio
async def test_remove_item_with_files(test_db):
    """Test removing item with file deletion"""
    config_url = Config(key="qbittorrent_url", value="http://localhost:8080")
    config_username = Config(key="qbittorrent_username", value="admin")
    config_password = Config(
        key="qbittorrent_password", value=encrypt_test_password("adminpass")
    )

    test_db.add_all([config_url, config_username, config_password])
    await test_db.commit()

    service = QBittorrentService(test_db)

    with patch("app.services.download.qbittorrent_service.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        result = await service.remove_item("abc123", delete_files=True)

        assert result is True
        mock_client.torrents_delete.assert_called_once_with(
            delete_files=True, torrent_hashes="abc123"
        )


@pytest.mark.asyncio
async def test_remove_item_without_files(test_db):
    """Test removing item without file deletion"""
    config_url = Config(key="qbittorrent_url", value="http://localhost:8080")
    config_username = Config(key="qbittorrent_username", value="admin")
    config_password = Config(
        key="qbittorrent_password", value=encrypt_test_password("adminpass")
    )

    test_db.add_all([config_url, config_username, config_password])
    await test_db.commit()

    service = QBittorrentService(test_db)

    with patch("app.services.download.qbittorrent_service.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        result = await service.remove_item("abc123", delete_files=False)

        assert result is True
        mock_client.torrents_delete.assert_called_once_with(
            delete_files=False, torrent_hashes="abc123"
        )


@pytest.mark.asyncio
async def test_test_connection_success(test_db):
    """Test successful connection test"""
    config_url = Config(key="qbittorrent_url", value="http://localhost:8080")
    config_username = Config(key="qbittorrent_username", value="admin")
    config_password = Config(
        key="qbittorrent_password", value=encrypt_test_password("adminpass")
    )

    test_db.add_all([config_url, config_username, config_password])
    await test_db.commit()

    service = QBittorrentService(test_db)

    with patch("app.services.download.qbittorrent_service.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.app_version.return_value = "v4.5.0"

        result = await service.test_connection()

        assert result["success"] is True
        assert result["version"] == "v4.5.0"
        mock_client.app_version.assert_called_once()


@pytest.mark.asyncio
async def test_test_connection_failure(test_db):
    """Test connection test failure"""
    config_url = Config(key="qbittorrent_url", value="http://localhost:8080")
    config_username = Config(key="qbittorrent_username", value="admin")
    config_password = Config(
        key="qbittorrent_password", value=encrypt_test_password("adminpass")
    )

    test_db.add_all([config_url, config_username, config_password])
    await test_db.commit()

    service = QBittorrentService(test_db)

    with patch("app.services.download.qbittorrent_service.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.app_version.side_effect = Exception("Connection failed")

        result = await service.test_connection()

        assert result["success"] is False
        assert "error" in result


@pytest.mark.asyncio
async def test_wrong_credentials_are_named(test_db):
    """qbittorrent-api's LoginFailed carries no text, so the error says what it means."""
    from qbittorrentapi import LoginFailed

    test_db.add_all(
        [
            Config(key="qbittorrent_url", value="http://localhost:8080"),
            Config(key="qbittorrent_username", value="admin"),
            Config(key="qbittorrent_password", value=encrypt_test_password("nope")),
        ]
    )
    await test_db.commit()

    with patch("app.services.download.qbittorrent_service.Client") as client_class:
        client_class.return_value.auth_log_in.side_effect = LoginFailed()

        with pytest.raises(ValueError, match="rejected the username or password"):
            await QBittorrentService(test_db)._get_client()
