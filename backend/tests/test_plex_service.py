"""
Tests for Plex service with OAuth authentication
"""

import pytest
from unittest.mock import Mock, patch
from plexapi.exceptions import NotFound, Unauthorized

from app.services.media_server.plex_service import PlexService, PlexAuthService


@pytest.fixture
def mock_plex_account():
    """Create a mock Plex account"""
    account = Mock()
    account.username = "testuser"
    account.email = "test@example.com"
    account.token = "oauth_token_123"
    return account


@pytest.fixture
def mock_plex_server():
    """Create a mock Plex server"""
    server = Mock()
    server.friendlyName = "Test Plex Server"
    server.version = "1.32.5"
    server.platform = "Linux"
    server.platformVersion = "5.15.0"
    return server


@pytest.fixture
def mock_plex_resource():
    """Create a mock Plex resource (server)"""
    resource = Mock()
    resource.name = "Test Server"
    resource.clientIdentifier = "abc123"
    resource.product = "Plex Media Server"
    resource.platform = "Linux"
    resource.owned = True

    # Mock connections
    conn = Mock()
    conn.uri = "http://192.168.1.100:32400"
    conn.local = True
    resource.connections = [conn]

    return resource


# PlexAuthService Tests


@pytest.mark.asyncio
@patch("app.services.media_server.plex_service.requests.post")
async def test_initiate_auth(mock_post):
    """Test initiating OAuth PIN authentication"""
    mock_response = Mock()
    mock_response.json.return_value = {
        "id": 123,
        "code": "ABCD",
    }
    mock_response.raise_for_status = Mock()
    mock_post.return_value = mock_response

    result = await PlexAuthService.initiate_auth()

    assert "auth_url" in result
    assert result["pin_id"] == "123"
    assert result["code"] == "ABCD"
    assert result["expires_in"] == 600
    mock_post.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.media_server.plex_service.requests.get")
@patch("app.services.media_server.plex_service.pin_cache")
@patch("app.services.media_server.plex_service.get_token_manager")
async def test_check_auth_completed(mock_token_manager, mock_cache, mock_get):
    """Test checking auth when user has completed OAuth"""
    mock_cache.get.return_value = {
        "code": "ABCD",
        "client_id": "test-client-id",
        "created_at": "2024-01-01T00:00:00",
    }

    mock_response = Mock()
    mock_response.json.return_value = {
        "authToken": "new_oauth_token",
    }
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    mock_manager = Mock()
    mock_manager.encrypt.return_value = "encrypted_token"
    mock_token_manager.return_value = mock_manager

    token = await PlexAuthService.check_auth("pin123")

    assert token == "encrypted_token"
    mock_cache.get.assert_called_once_with("pin123")
    mock_cache.delete.assert_called_once_with("pin123")


@pytest.mark.asyncio
@patch("app.services.media_server.plex_service.requests.get")
@patch("app.services.media_server.plex_service.pin_cache")
async def test_check_auth_pending(mock_cache, mock_get):
    """Test checking auth when user hasn't completed OAuth yet"""
    mock_cache.get.return_value = {
        "code": "ABCD",
        "client_id": "test-client-id",
        "created_at": "2024-01-01T00:00:00",
    }

    mock_response = Mock()
    mock_response.json.return_value = {}  # No authToken
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    token = await PlexAuthService.check_auth("pin123")

    assert token is None
    mock_cache.get.assert_called_once_with("pin123")


@pytest.mark.asyncio
@patch("app.services.media_server.plex_service.MyPlexAccount")
@patch("app.services.media_server.plex_service.get_token_manager")
async def test_get_servers(
    mock_token_manager, mock_account_class, mock_plex_account, mock_plex_resource
):
    """Test getting list of available servers"""
    mock_plex_account.resources.return_value = [mock_plex_resource]
    mock_account_class.return_value = mock_plex_account

    mock_manager = Mock()
    mock_manager.decrypt.return_value = "decrypted_token"
    mock_token_manager.return_value = mock_manager

    servers = await PlexAuthService.get_servers("encrypted_token_123")

    assert len(servers) == 1
    assert servers[0]["name"] == "Test Server"
    assert servers[0]["product"] == "Plex Media Server"
    assert servers[0]["owned"] is True
    assert len(servers[0]["connections"]) == 1
    mock_account_class.assert_called_once_with(token="decrypted_token")


# PlexService Tests


def test_plex_service_init():
    """Test PlexService initialization"""
    service = PlexService(encrypted_token="oauth_token", server_name="My Server")
    assert service.encrypted_token == "oauth_token"
    assert service.server_name == "My Server"
    assert service._server is None
    assert service._account is None


def test_plex_service_init_from_settings():
    """Test PlexService initialization from settings"""
    with patch("app.services.media_server.plex_service.settings") as mock_settings:
        mock_settings.plex_auth_token = "settings_token"
        mock_settings.plex_server_name = "Settings Server"

        service = PlexService()
        assert service.encrypted_token == "settings_token"
        assert service.server_name == "Settings Server"


@patch("app.services.media_server.plex_service.get_token_manager")
@patch("app.services.media_server.plex_service.MyPlexAccount")
def test_get_account_success(mock_account_class, mock_token_manager, mock_plex_account):
    """Test successful account connection"""
    mock_account_class.return_value = mock_plex_account

    mock_manager = Mock()
    mock_manager.decrypt.return_value = "decrypted_token"
    mock_token_manager.return_value = mock_manager

    service = PlexService(encrypted_token="encrypted_token")
    account = service._get_account()

    assert account == mock_plex_account
    assert account.username == "testuser"
    mock_account_class.assert_called_once_with(token="decrypted_token")


@patch("app.services.media_server.plex_service.get_token_manager")
@patch("app.services.media_server.plex_service.MyPlexAccount")
def test_get_account_unauthorized(mock_account_class, mock_token_manager):
    """Test account connection with invalid token"""
    mock_account_class.side_effect = Unauthorized("Invalid token")

    mock_manager = Mock()
    mock_manager.decrypt.return_value = "decrypted_token"
    mock_token_manager.return_value = mock_manager

    service = PlexService(encrypted_token="bad_token")

    with pytest.raises(
        ValueError, match="Invalid or expired Plex authentication token"
    ):
        service._get_account()


def test_get_account_no_token():
    """Test account connection without token"""
    service = PlexService(encrypted_token=None)

    with pytest.raises(ValueError, match="Plex authentication required"):
        service._get_account()


@patch("app.services.media_server.plex_service.get_token_manager")
@patch("app.services.media_server.plex_service.MyPlexAccount")
def test_get_server_by_name(
    mock_account_class,
    mock_token_manager,
    mock_plex_account,
    mock_plex_server,
    mock_plex_resource,
):
    """Test connecting to specific server by name"""
    mock_plex_resource.connect.return_value = mock_plex_server
    mock_plex_account.resource.return_value = mock_plex_resource
    mock_account_class.return_value = mock_plex_account

    mock_manager = Mock()
    mock_manager.decrypt.return_value = "decrypted_token"
    mock_token_manager.return_value = mock_manager

    service = PlexService(encrypted_token="encrypted_token", server_name="Test Server")
    server = service._get_server()

    assert server == mock_plex_server
    mock_plex_account.resource.assert_called_once_with("Test Server")


@patch("app.services.media_server.plex_service.get_token_manager")
@patch("app.services.media_server.plex_service.MyPlexAccount")
def test_get_server_first_available(
    mock_account_class,
    mock_token_manager,
    mock_plex_account,
    mock_plex_server,
    mock_plex_resource,
):
    """Test connecting to first available server"""
    mock_plex_resource.connect.return_value = mock_plex_server
    mock_plex_account.resources.return_value = [mock_plex_resource]
    mock_account_class.return_value = mock_plex_account

    mock_manager = Mock()
    mock_manager.decrypt.return_value = "decrypted_token"
    mock_token_manager.return_value = mock_manager

    service = PlexService(encrypted_token="encrypted_token")
    server = service._get_server()

    assert server == mock_plex_server
    mock_plex_account.resources.assert_called_once()


@patch("app.services.media_server.plex_service.get_token_manager")
@patch("app.services.media_server.plex_service.MyPlexAccount")
def test_get_server_not_found(
    mock_account_class, mock_token_manager, mock_plex_account
):
    """Test connecting to non-existent server"""
    mock_plex_account.resource.side_effect = NotFound("Server not found")
    mock_account_class.return_value = mock_plex_account

    mock_manager = Mock()
    mock_manager.decrypt.return_value = "decrypted_token"
    mock_token_manager.return_value = mock_manager

    service = PlexService(encrypted_token="encrypted_token", server_name="NonExistent")

    with pytest.raises(ValueError, match="Plex server 'NonExistent' not found"):
        service._get_server()


@patch("app.services.media_server.plex_service.get_token_manager")
@patch("app.services.media_server.plex_service.MyPlexAccount")
def test_test_connection_success(
    mock_account_class,
    mock_token_manager,
    mock_plex_account,
    mock_plex_server,
    mock_plex_resource,
):
    """Test successful connection test"""
    mock_plex_resource.connect.return_value = mock_plex_server
    mock_plex_account.resource.return_value = mock_plex_resource
    mock_account_class.return_value = mock_plex_account

    mock_manager = Mock()
    mock_manager.decrypt.return_value = "decrypted_token"
    mock_token_manager.return_value = mock_manager

    service = PlexService(encrypted_token="encrypted_token", server_name="Test Server")
    result = service.test_connection()

    assert result["success"] is True
    assert result["username"] == "testuser"
    assert result["email"] == "test@example.com"
    assert result["server_name"] == "Test Plex Server"
    assert result["version"] == "1.32.5"


@patch("app.services.media_server.plex_service.get_token_manager")
@patch("app.services.media_server.plex_service.MyPlexAccount")
def test_test_connection_failure(mock_account_class, mock_token_manager):
    """Test failed connection test"""
    mock_account_class.side_effect = Exception("Connection failed")

    mock_manager = Mock()
    mock_manager.decrypt.return_value = "decrypted_token"
    mock_token_manager.return_value = mock_manager

    service = PlexService(encrypted_token="encrypted_token")
    result = service.test_connection()

    assert result["success"] is False
    assert "Connection failed" in result["error"]
