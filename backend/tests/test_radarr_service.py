"""
Tests for Radarr service
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.radarr_service import RadarrService
from app.models.config import Config


@pytest.mark.asyncio
async def test_radarr_client_initialization(test_db):
    """Test Radarr client initialization with config from database"""
    config_url = Config(key="radarr_url", value="http://localhost:7878")
    config_api_key = Config(key="radarr_api_key", value="test_api_key")

    test_db.add(config_url)
    test_db.add(config_api_key)
    await test_db.commit()

    service = RadarrService(test_db)

    with patch("app.services.radarr_service.RadarrClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        client = await service._get_client()

        mock_client_class.assert_called_once_with(
            base_url="http://localhost:7878", api_key="test_api_key"
        )
        assert client == mock_client


@pytest.mark.asyncio
async def test_radarr_missing_config(test_db):
    """Test error when Radarr config is missing"""
    service = RadarrService(test_db)

    with pytest.raises(ValueError, match="Radarr configuration not found"):
        await service._get_client()


@pytest.mark.asyncio
async def test_find_movie_by_file_path_found(test_db):
    """Test finding movie by file path when movie exists"""
    config_url = Config(key="radarr_url", value="http://localhost:7878")
    config_api_key = Config(key="radarr_api_key", value="test_api_key")

    test_db.add_all([config_url, config_api_key])
    await test_db.commit()

    service = RadarrService(test_db)

    mock_movie = {
        "id": 1,
        "title": "Test Movie",
        "movieFile": {"id": 10, "path": "/media/movies/Test Movie.mkv"},
    }

    with patch("app.services.radarr_service.RadarrClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.get_movie = AsyncMock(return_value=[mock_movie])

        result = await service.find_movie_by_file_path("/media/movies/Test Movie.mkv")

        assert result == mock_movie
        assert result["title"] == "Test Movie"
        mock_client.get_movie.assert_called_once()


@pytest.mark.asyncio
async def test_find_movie_by_file_path_not_found(test_db):
    """Test finding movie when file doesn't match any movies"""
    config_url = Config(key="radarr_url", value="http://localhost:7878")
    config_api_key = Config(key="radarr_api_key", value="test_api_key")

    test_db.add_all([config_url, config_api_key])
    await test_db.commit()

    service = RadarrService(test_db)

    mock_movie = {
        "id": 1,
        "title": "Test Movie",
        "movieFile": {"id": 10, "path": "/media/movies/Test Movie.mkv"},
    }

    with patch("app.services.radarr_service.RadarrClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.get_movie = AsyncMock(return_value=[mock_movie])

        result = await service.find_movie_by_file_path("/media/movies/NonExistent.mkv")

        assert result is None


@pytest.mark.asyncio
async def test_find_movie_no_movie_file(test_db):
    """Test finding movie when movie has no file"""
    config_url = Config(key="radarr_url", value="http://localhost:7878")
    config_api_key = Config(key="radarr_api_key", value="test_api_key")

    test_db.add_all([config_url, config_api_key])
    await test_db.commit()

    service = RadarrService(test_db)

    mock_movie = {"id": 1, "title": "Test Movie"}

    with patch("app.services.radarr_service.RadarrClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.get_movie = AsyncMock(return_value=[mock_movie])

        result = await service.find_movie_by_file_path("/media/movies/Test Movie.mkv")

        assert result is None


@pytest.mark.asyncio
async def test_delete_movie_file_success(test_db):
    """Test successful movie file deletion"""
    config_url = Config(key="radarr_url", value="http://localhost:7878")
    config_api_key = Config(key="radarr_api_key", value="test_api_key")

    test_db.add_all([config_url, config_api_key])
    await test_db.commit()

    service = RadarrService(test_db)

    with patch("app.services.radarr_service.RadarrClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.del_movie_file = AsyncMock()

        result = await service.delete_movie_file(movie_id=1, movie_file_id=10)

        assert result is True
        mock_client.del_movie_file.assert_called_once_with(10)


@pytest.mark.asyncio
async def test_delete_movie_file_failure(test_db):
    """Test movie file deletion failure"""
    config_url = Config(key="radarr_url", value="http://localhost:7878")
    config_api_key = Config(key="radarr_api_key", value="test_api_key")

    test_db.add_all([config_url, config_api_key])
    await test_db.commit()

    service = RadarrService(test_db)

    with patch("app.services.radarr_service.RadarrClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.del_movie_file = AsyncMock(side_effect=Exception("Delete failed"))

        with pytest.raises(Exception, match="Delete failed"):
            await service.delete_movie_file(movie_id=1, movie_file_id=10)


@pytest.mark.asyncio
async def test_test_connection_success(test_db):
    """Test successful connection test"""
    config_url = Config(key="radarr_url", value="http://localhost:7878")
    config_api_key = Config(key="radarr_api_key", value="test_api_key")

    test_db.add_all([config_url, config_api_key])
    await test_db.commit()

    service = RadarrService(test_db)

    with patch("app.services.radarr_service.RadarrClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.get_system_status = AsyncMock(return_value={"version": "4.0.0"})

        result = await service.test_connection()

        assert result["success"] is True
        assert result["version"] == "4.0.0"
        mock_client.get_system_status.assert_called_once()


@pytest.mark.asyncio
async def test_test_connection_failure(test_db):
    """Test connection test failure"""
    from app.services.arr_client import ArrConnectionError

    config_url = Config(key="radarr_url", value="http://localhost:7878")
    config_api_key = Config(key="radarr_api_key", value="test_api_key")

    test_db.add_all([config_url, config_api_key])
    await test_db.commit()

    service = RadarrService(test_db)

    with patch("app.services.radarr_service.RadarrClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_client.get_system_status = AsyncMock(
            side_effect=ArrConnectionError("Connection failed")
        )

        result = await service.test_connection()

        assert result["success"] is False
        assert "error" in result
