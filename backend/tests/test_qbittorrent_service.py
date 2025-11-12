"""
Tests for qBittorrent service
"""

import pytest
from unittest.mock import MagicMock, patch

from app.services.qbittorrent_service import QBittorrentService
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

    with patch("app.services.qbittorrent_service.Client") as mock_client_class:
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

    with patch("app.services.qbittorrent_service.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.torrents_info.return_value = [mock_item]
        mock_client.torrents_files.return_value = [mock_file]

        result = await service.find_item_by_file_path("/downloads/Movie.mkv")

        assert result is not None
        item_hash, count = result
        assert item_hash == "abc123"
        assert count == 1
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

    with patch("app.services.qbittorrent_service.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.torrents_info.return_value = [mock_item]
        mock_client.torrents_files.return_value = [mock_file]

        result = await service.find_item_by_file_path("/downloads/NonExistent.mkv")

        assert result is None


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

    with patch("app.services.qbittorrent_service.Client") as mock_client_class:
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

    with patch("app.services.qbittorrent_service.Client") as mock_client_class:
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

    with patch("app.services.qbittorrent_service.Client") as mock_client_class:
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

    with patch("app.services.qbittorrent_service.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.app_version.side_effect = Exception("Connection failed")

        result = await service.test_connection()

        assert result["success"] is False
        assert "error" in result
