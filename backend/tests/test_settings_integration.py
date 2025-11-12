"""
Integration tests for Settings/Setup functionality
"""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app


@pytest.mark.asyncio
async def test_get_setup_status(client: AsyncClient):
    """Test getting setup status"""
    response = await client.get("/api/setup/status")
    assert response.status_code == 200
    data = response.json()
    assert "is_complete" in data
    assert "missing_required" in data
    assert "configured_services" in data
    assert "database_type" in data


@pytest.mark.asyncio
async def test_plex_oauth_initiate():
    """Test initiating Plex OAuth authentication"""
    with patch("app.services.plex_service.get_token_manager") as mock_token_manager:
        mock_manager = MagicMock()
        mock_manager.generate_state_token.return_value = "test-state"
        mock_token_manager.return_value = mock_manager

        with patch("app.services.plex_service.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": 12345,
                "code": "ABCD",
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/setup/plex/auth/initiate")
                assert response.status_code == 200
                data = response.json()
                assert "pin_id" in data
                assert "code" in data
                assert "auth_url" in data
                assert data["code"] == "ABCD"


@pytest.mark.asyncio
async def test_plex_oauth_check_pending():
    """Test checking Plex OAuth before user completes auth"""
    with patch("app.api.routes.setup.PlexAuthService.check_auth") as mock_check:
        mock_check.return_value = None  # Still pending

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/setup/plex/auth/check/test-pin-id")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert data["encrypted_token"] is None


@pytest.mark.asyncio
async def test_plex_oauth_check_complete():
    """Test checking Plex OAuth after user completes auth"""
    with patch("app.api.routes.setup.PlexAuthService.check_auth") as mock_check:
        mock_check.return_value = "fake-plex-token-12345"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/setup/plex/auth/check/test-pin-id")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["encrypted_token"] == "fake-plex-token-12345"


@pytest.mark.asyncio
async def test_plex_get_servers():
    """Test getting available Plex servers"""
    with patch("app.api.routes.setup.PlexAuthService.get_servers") as mock_get_servers:
        mock_get_servers.return_value = [
            {"name": "Home Server", "owned": True},
            {"name": "Remote Server", "owned": False},
        ]

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/setup/plex/servers/fake-token")
            assert response.status_code == 200
            data = response.json()
            assert "servers" in data
            assert len(data["servers"]) == 2


@pytest.mark.asyncio
async def test_plex_connection_test_success(client: AsyncClient):
    """Test successful Plex connection"""
    with patch(
        "app.services.setup_service.PlexAuthService.get_servers"
    ) as mock_get_servers:
        mock_get_servers.return_value = [{"name": "Test Server"}]

        with patch("app.services.setup_service.PlexService") as mock_plex:
            mock_plex_instance = MagicMock()
            mock_plex_instance.test_connection.return_value = {
                "success": True,
                "username": "testuser",
                "email": "test@example.com",
                "server_name": "Test Server",
                "version": "1.40.0.7998",
                "platform": "Linux",
                "platform_version": "5.15.0",
            }
            mock_plex.return_value = mock_plex_instance

            response = await client.post(
                "/api/setup/test/plex",
                json={"auth_token": "test-token", "server_name": "Test Server"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "version" in data


@pytest.mark.asyncio
async def test_plex_connection_test_failure(client: AsyncClient):
    """Test failed Plex connection"""
    with patch("app.services.setup_service.PlexService") as mock_plex:
        mock_plex_instance = MagicMock()
        mock_plex_instance.get_server.side_effect = Exception("Connection refused")
        mock_plex.return_value = mock_plex_instance

        response = await client.post(
            "/api/setup/test/plex",
            json={"auth_token": "test-token", "server_name": "Test Server"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "error" in data


@pytest.mark.asyncio
async def test_radarr_connection_test_success(client: AsyncClient):
    """Test successful Radarr connection"""
    with patch("app.services.radarr_service.RadarrClient") as mock_radarr:
        mock_instance = AsyncMock()
        mock_instance.get_system_status = AsyncMock(
            return_value={"version": "5.11.0.9244"}
        )
        mock_radarr.return_value = mock_instance

        response = await client.post(
            "/api/setup/test/radarr",
            json={"url": "http://localhost:7878", "api_key": "test-api-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["version"] == "5.11.0.9244"


@pytest.mark.asyncio
async def test_radarr_connection_test_failure(client: AsyncClient):
    """Test failed Radarr connection"""
    with patch("app.services.radarr_service.RadarrClient") as mock_radarr:
        mock_instance = AsyncMock()
        mock_instance.get_system_status = AsyncMock(
            side_effect=Exception("Connection error")
        )
        mock_radarr.return_value = mock_instance

        response = await client.post(
            "/api/setup/test/radarr",
            json={"url": "http://localhost:7878", "api_key": "bad-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "error" in data


@pytest.mark.asyncio
async def test_sonarr_connection_test_success(client: AsyncClient):
    """Test successful Sonarr connection"""
    with patch("app.services.sonarr_service.SonarrClient") as mock_sonarr:
        mock_instance = AsyncMock()
        mock_instance.get_system_status = AsyncMock(
            return_value={"version": "4.0.10.2544"}
        )
        mock_sonarr.return_value = mock_instance

        response = await client.post(
            "/api/setup/test/sonarr",
            json={"url": "http://localhost:8989", "api_key": "test-api-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["version"] == "4.0.10.2544"


@pytest.mark.asyncio
async def test_sonarr_connection_test_failure(client: AsyncClient):
    """Test failed Sonarr connection"""
    with patch("app.services.sonarr_service.SonarrClient") as mock_sonarr:
        mock_instance = AsyncMock()
        mock_instance.get_system_status = AsyncMock(
            side_effect=Exception("Invalid API key")
        )
        mock_sonarr.return_value = mock_instance

        response = await client.post(
            "/api/setup/test/sonarr",
            json={"url": "http://localhost:8989", "api_key": "bad-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "error" in data


@pytest.mark.asyncio
async def test_qbittorrent_connection_test_success(client: AsyncClient):
    """Test successful qBittorrent connection"""
    with patch("app.services.qbittorrent_service.Client") as mock_qbit:
        mock_instance = MagicMock()
        mock_instance.app_version.return_value = "v4.6.7"
        mock_qbit.return_value = mock_instance

        response = await client.post(
            "/api/setup/test/qbittorrent",
            json={
                "url": "http://localhost:8080",
                "username": "admin",
                "password": "adminpass",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["version"] == "v4.6.7"


@pytest.mark.asyncio
async def test_qbittorrent_connection_test_failure(client: AsyncClient):
    """Test failed qBittorrent connection"""
    with patch("app.services.qbittorrent_service.Client") as mock_qbit:
        mock_qbit.side_effect = Exception("Login failed")

        response = await client.post(
            "/api/setup/test/qbittorrent",
            json={
                "url": "http://localhost:8080",
                "username": "admin",
                "password": "wrongpass",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "error" in data


@pytest.mark.asyncio
async def test_save_configuration(client: AsyncClient):
    """Test saving configuration"""
    response = await client.post(
        "/api/setup/save",
        json={
            "config": {
                "plex_server_name": "Home Server",
                "radarr_url": "http://localhost:7878",
                "radarr_api_key": "test-key",
            }
        },
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_invalid_request_format(client: AsyncClient):
    """Test invalid request format returns appropriate error"""
    response = await client.post("/api/setup/test/plex", json={"invalid": "data"})
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_plex_oauth_missing_pin_id():
    """Test checking OAuth with invalid PIN ID"""
    with patch("app.api.routes.setup.PlexAuthService.check_auth") as mock_check:
        mock_check.return_value = None  # PIN not found

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/setup/plex/auth/check/nonexistent-pin")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert data["encrypted_token"] is None
