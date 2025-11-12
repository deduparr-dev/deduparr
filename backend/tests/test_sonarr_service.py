"""
Tests for Sonarr service
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.services.sonarr_service import SonarrService
from app.models.config import Config


@pytest.mark.asyncio
async def test_sonarr_client_initialization(test_db):
    """Test Sonarr client initialization with config from database"""
    config_url = Config(key="sonarr_url", value="http://localhost:8989")
    config_api_key = Config(key="sonarr_api_key", value="test_api_key")

    test_db.add(config_url)
    test_db.add(config_api_key)
    await test_db.commit()

    service = SonarrService(test_db)

    with patch("app.services.sonarr_service.SonarrClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client

        client = await service._get_client()

        mock_client_class.assert_called_once_with(
            base_url="http://localhost:8989", api_key="test_api_key"
        )
        assert client == mock_client


@pytest.mark.asyncio
async def test_sonarr_missing_config(test_db):
    """Test error when Sonarr config is missing"""
    service = SonarrService(test_db)

    with pytest.raises(ValueError, match="Sonarr configuration not found"):
        await service._get_client()


@pytest.mark.asyncio
async def test_find_episode_by_file_path_found(test_db):
    """Test finding episode by file path when episode exists"""
    config_url = Config(key="sonarr_url", value="http://localhost:8989")
    config_api_key = Config(key="sonarr_api_key", value="test_api_key")

    test_db.add_all([config_url, config_api_key])
    await test_db.commit()

    service = SonarrService(test_db)

    file_path = "/media/tv/Test Series/S01E01.mkv"
    mock_series = {"id": 1, "title": "Test Series"}
    mock_episode_file = {
        "id": 100,
        "path": file_path,
        "seriesId": 1,
        "episodeFileId": 100,
        "episodeIds": [10],  # This is required for the service to find episodes
    }
    mock_episode = {
        "id": 10,
        "title": "Test Episode",
        "seriesId": 1,
        "seasonNumber": 1,
        "episodeNumber": 1,
        "episodeFileId": 100,
    }

    with patch("app.services.sonarr_service.SonarrClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.get_series = AsyncMock(return_value=[mock_series])
        mock_client.get_episode_files_by_series_id = AsyncMock(
            return_value=[mock_episode_file]
        )
        mock_client.get_episode = AsyncMock(return_value=[mock_episode])

        result = await service.find_episode_by_file_path(file_path)

        assert result is not None
        assert result["title"] == "Test Episode"
        assert result["episodeFile"]["path"] == file_path
        # Verify we iterate through series to get episode files
        mock_client.get_episode_files_by_series_id.assert_called_once_with(1)
        mock_client.get_episode.assert_called_once_with(10)


@pytest.mark.asyncio
async def test_find_episode_by_file_path_not_found(test_db):
    """Test finding episode when file doesn't match any episodes"""
    config_url = Config(key="sonarr_url", value="http://localhost:8989")
    config_api_key = Config(key="sonarr_api_key", value="test_api_key")

    test_db.add_all([config_url, config_api_key])
    await test_db.commit()

    service = SonarrService(test_db)

    mock_series = {"id": 1, "title": "Test Series"}
    mock_episode = {
        "id": 10,
        "title": "Test Episode",
        "seriesId": 1,
        "episodeFile": {"id": 100, "path": "/media/tv/Test Series/S01E01.mkv"},
    }

    with patch("app.services.sonarr_service.SonarrClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.get_series = AsyncMock(return_value=[mock_series])
        mock_client.get_episode = AsyncMock(return_value=[mock_episode])

        result = await service.find_episode_by_file_path(
            "/media/tv/Test Series/S01E02.mkv"
        )

        assert result is None


@pytest.mark.asyncio
async def test_find_episode_no_episode_file(test_db):
    """Test finding episode when episode has no file"""
    config_url = Config(key="sonarr_url", value="http://localhost:8989")
    config_api_key = Config(key="sonarr_api_key", value="test_api_key")

    test_db.add_all([config_url, config_api_key])
    await test_db.commit()

    service = SonarrService(test_db)

    mock_series = {"id": 1, "title": "Test Series"}
    mock_episode = {"id": 10, "title": "Test Episode", "seriesId": 1}

    with patch("app.services.sonarr_service.SonarrClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.get_series = AsyncMock(return_value=[mock_series])
        mock_client.get_episode = AsyncMock(return_value=[mock_episode])

        result = await service.find_episode_by_file_path(
            "/media/tv/Test Series/S01E01.mkv"
        )

        assert result is None


@pytest.mark.asyncio
async def test_delete_episode_file_success(test_db):
    """Test successful episode file deletion"""
    config_url = Config(key="sonarr_url", value="http://localhost:8989")
    config_api_key = Config(key="sonarr_api_key", value="test_api_key")

    test_db.add_all([config_url, config_api_key])
    await test_db.commit()

    service = SonarrService(test_db)

    with patch("app.services.sonarr_service.SonarrClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.del_episode_file = AsyncMock()

        result = await service.delete_episode_file(series_id=1, episode_file_id=100)

        assert result is True
        mock_client.del_episode_file.assert_called_once_with(100)


@pytest.mark.asyncio
async def test_delete_episode_file_failure(test_db):
    """Test episode file deletion failure"""
    config_url = Config(key="sonarr_url", value="http://localhost:8989")
    config_api_key = Config(key="sonarr_api_key", value="test_api_key")

    test_db.add_all([config_url, config_api_key])
    await test_db.commit()

    service = SonarrService(test_db)

    with patch("app.services.sonarr_service.SonarrClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.del_episode_file = AsyncMock(side_effect=Exception("Delete failed"))

        with pytest.raises(Exception, match="Delete failed"):
            await service.delete_episode_file(series_id=1, episode_file_id=100)


@pytest.mark.asyncio
async def test_test_connection_success(test_db):
    """Test successful connection test"""
    config_url = Config(key="sonarr_url", value="http://localhost:8989")
    config_api_key = Config(key="sonarr_api_key", value="test_api_key")

    test_db.add_all([config_url, config_api_key])
    await test_db.commit()

    service = SonarrService(test_db)

    with patch("app.services.sonarr_service.SonarrClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.get_system_status = AsyncMock(return_value={"version": "3.0.0"})

        result = await service.test_connection()

        assert result["success"] is True
        assert result["version"] == "3.0.0"
        mock_client.get_system_status.assert_called_once()


@pytest.mark.asyncio
async def test_test_connection_failure(test_db):
    """Test connection test failure"""
    from app.services.arr_client import ArrConnectionError

    config_url = Config(key="sonarr_url", value="http://localhost:8989")
    config_api_key = Config(key="sonarr_api_key", value="test_api_key")

    test_db.add_all([config_url, config_api_key])
    await test_db.commit()

    service = SonarrService(test_db)

    with patch("app.services.sonarr_service.SonarrClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.get_system_status = AsyncMock(
            side_effect=ArrConnectionError("Connection failed")
        )

        result = await service.test_connection()

        assert result["success"] is False
        assert "error" in result
