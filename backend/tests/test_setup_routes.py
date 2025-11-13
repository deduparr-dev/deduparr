"""
Tests for setup API routes
"""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import MagicMock, patch

from app.main import app
from app.models.config import Config
from tests.conftest import encrypt_test_password


@pytest.mark.asyncio
async def test_get_setup_status_incomplete(test_db):
    """Test getting setup status when setup is incomplete"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/setup/status")
        assert response.status_code == 200
        data = response.json()
        assert data["is_complete"] is False
        assert len(data["missing_required"]) > 0


@pytest.mark.asyncio
async def test_get_setup_status_complete(test_db):
    """Test getting setup status when setup is complete"""
    configs = [
        Config(key="setup_completed", value="true"),
        Config(key="plex_auth_token", value="test_token"),
        Config(key="plex_server_name", value="test_server"),
        Config(key="qbittorrent_url", value="http://qbittorrent:8080"),
        Config(key="qbittorrent_username", value="admin"),
        Config(key="qbittorrent_password", value=encrypt_test_password("password")),
        Config(key="radarr_url", value="http://radarr:7878"),
        Config(key="radarr_api_key", value="test_api_key"),
    ]
    for config in configs:
        test_db.add(config)
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/setup/status")
        assert response.status_code == 200
        data = response.json()
        assert data["is_complete"] is True
        assert len(data["missing_required"]) == 0


@pytest.mark.asyncio
async def test_initiate_plex_auth(test_db):
    """Test initiating Plex OAuth authentication"""
    with patch("app.api.routes.setup.PlexAuthService.initiate_auth") as mock_initiate:
        mock_initiate.return_value = {
            "auth_url": "https://plex.tv/auth",
            "pin_id": "12345",
            "code": "ABCD",
            "expires_in": 600,
        }

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/setup/plex/auth/initiate")
            assert response.status_code == 200
            data = response.json()
            assert data["auth_url"] == "https://plex.tv/auth"
            assert data["pin_id"] == "12345"
            assert data["code"] == "ABCD"


@pytest.mark.asyncio
async def test_check_plex_auth_complete(test_db):
    """Test checking Plex auth when complete"""
    with patch("app.api.routes.setup.PlexAuthService.check_auth") as mock_check:
        mock_check.return_value = "test_auth_token"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/setup/plex/auth/check/12345")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["encrypted_token"] == "test_auth_token"


@pytest.mark.asyncio
async def test_check_plex_auth_pending(test_db):
    """Test checking Plex auth when still pending"""
    with patch("app.api.routes.setup.PlexAuthService.check_auth") as mock_check:
        mock_check.return_value = None

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/setup/plex/auth/check/12345")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert data["encrypted_token"] is None


@pytest.mark.asyncio
async def test_get_plex_servers(test_db):
    """Test getting available Plex servers"""
    with patch("app.api.routes.setup.PlexAuthService.get_servers") as mock_get_servers:
        mock_get_servers.return_value = [
            {"name": "Server1", "owned": True},
            {"name": "Server2", "owned": False},
        ]

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/setup/plex/servers", json={"auth_token": "test_token"}
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["servers"]) == 2
            assert data["servers"][0]["name"] == "Server1"


@pytest.mark.asyncio
async def test_test_plex_connection_success(test_db):
    """Test Plex connection test endpoint - success"""
    with patch(
        "app.services.setup_service.PlexAuthService.get_servers"
    ) as mock_get_servers:
        mock_get_servers.return_value = [{"name": "test_server"}]

        with patch("app.services.setup_service.PlexService") as mock_plex_service:
            mock_plex_instance = MagicMock()
            mock_plex_instance.test_connection.return_value = {
                "success": True,
                "username": "testuser",
                "email": "test@example.com",
                "server_name": "test_server",
                "version": "1.32.5",
                "platform": "Linux",
                "platform_version": "5.15.0",
            }
            mock_plex_service.return_value = mock_plex_instance

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/setup/test/plex",
                    json={"auth_token": "test_token", "server_name": "test_server"},
                )
                assert response.status_code == 200
                data = response.json()
                assert data["success"] is True
                assert data["version"] == "1.32.5"


@pytest.mark.asyncio
async def test_test_plex_connection_failure(test_db):
    """Test Plex connection test endpoint - failure"""
    with patch(
        "app.services.setup_service.PlexAuthService.get_servers"
    ) as mock_get_servers:
        mock_get_servers.return_value = []

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/setup/test/plex",
                json={"auth_token": "test_token", "server_name": "test_server"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert "error" in data


@pytest.mark.asyncio
async def test_get_plex_libraries_success(test_db):
    """Test getting Plex libraries - success"""
    mock_library1 = MagicMock()
    mock_library1.key = "1"
    mock_library1.title = "Movies"
    mock_library1.type = "movie"
    mock_library1.agent = "com.plexapp.agents.imdb"

    mock_server = MagicMock()
    mock_server.library.sections.return_value = [mock_library1]

    with patch("app.services.setup_service.PlexService") as mock_plex_service:
        mock_plex_instance = MagicMock()
        mock_plex_instance._get_server.return_value = mock_server
        mock_plex_service.return_value = mock_plex_instance

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/setup/plex/libraries",
                json={"auth_token": "test_token", "server_name": "test_server"},
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["title"] == "Movies"
            assert data[0]["type"] == "movie"


@pytest.mark.asyncio
async def test_get_plex_libraries_failure(test_db):
    """Test getting Plex libraries - failure"""
    with patch("app.services.setup_service.PlexService") as mock_plex_service:
        mock_plex_instance = MagicMock()
        mock_plex_instance._get_server.side_effect = Exception("Auth failed")
        mock_plex_service.return_value = mock_plex_instance

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/setup/plex/libraries",
                json={"auth_token": "test_token", "server_name": "test_server"},
            )
            assert response.status_code == 400


@pytest.mark.asyncio
async def test_save_configuration(test_db):
    """Test saving configuration"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/setup/save",
            json={
                "config": {
                    "plex_auth_token": "test_token",
                    "plex_server_name": "test_server",
                }
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"


@pytest.mark.asyncio
async def test_mark_setup_complete_success(test_db):
    """Test marking setup as complete when all required config present"""
    configs = [
        Config(key="plex_auth_token", value="test_token"),
        Config(key="plex_server_name", value="test_server"),
        Config(key="qbittorrent_url", value="http://qbittorrent:8080"),
        Config(key="qbittorrent_username", value="admin"),
        Config(key="qbittorrent_password", value=encrypt_test_password("password")),
        Config(key="radarr_url", value="http://radarr:7878"),
        Config(key="radarr_api_key", value="test_api_key"),
    ]
    for config in configs:
        test_db.add(config)
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/setup/complete")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"


@pytest.mark.asyncio
async def test_mark_setup_complete_missing_config(test_db):
    """Test marking setup as complete when missing required config"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/setup/complete")
        assert response.status_code == 400
        data = response.json()
        assert "Missing required configuration" in data["detail"]


@pytest.mark.asyncio
@patch("app.services.email_service.EmailService")
async def test_test_email_connection_success(mock_email_service, test_db):
    """Test successful email connection test"""
    # Mock email service
    mock_service_instance = MagicMock()
    mock_service_instance.send_test_email.return_value = (True, None)
    mock_email_service.return_value = mock_service_instance

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/setup/test/email",
            json={
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "smtp_user": "user@gmail.com",
                "smtp_password": "password123",
                "notification_email": "test@example.com",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "sent successfully" in data["message"]


@pytest.mark.asyncio
@patch("app.services.email_service.EmailService")
async def test_test_email_connection_failure(mock_email_service, test_db):
    """Test failed email connection test"""
    # Mock email service to fail
    mock_service_instance = MagicMock()
    mock_service_instance.send_test_email.return_value = (
        False,
        "Authentication failed",
    )
    mock_email_service.return_value = mock_service_instance

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/setup/test/email",
            json={
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "smtp_user": "user@gmail.com",
                "smtp_password": "wrong_password",
                "notification_email": "test@example.com",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Authentication failed" in data["error"]


@pytest.mark.asyncio
@patch("app.services.email_service.EmailService")
async def test_test_email_connection_exception(mock_email_service, test_db):
    """Test email connection test with exception"""
    # Mock email service to raise exception
    mock_email_service.side_effect = Exception("Network error")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/setup/test/email",
            json={
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "smtp_user": "user@gmail.com",
                "smtp_password": "password123",
                "notification_email": "test@example.com",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Network error" in data["error"]


@pytest.mark.asyncio
@patch("app.services.email_service.EmailService")
@patch("app.api.routes.setup.get_token_manager")
async def test_test_email_connection_with_encrypted_password(
    mock_get_token_manager, mock_email_service, test_db
):
    """Test email connection with encrypted password"""
    # Mock token manager to decrypt password
    mock_token_manager = MagicMock()
    mock_token_manager.decrypt.return_value = "decrypted_password"
    mock_get_token_manager.return_value = mock_token_manager

    # Mock email service
    mock_service_instance = MagicMock()
    mock_service_instance.send_test_email.return_value = (True, None)
    mock_email_service.return_value = mock_service_instance

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/setup/test/email",
            json={
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "smtp_user": "user@gmail.com",
                # Simulated encrypted password (has . and is long)
                "smtp_password": "InRlc3RfcGFzc3dvcmQi.encrypted_token_here_very_long_string",
                "notification_email": "test@example.com",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify decryption was attempted
        mock_token_manager.decrypt.assert_called_once()
