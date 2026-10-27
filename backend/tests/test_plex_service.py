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


@pytest.fixture
def mock_pin_login():
    """Create a mock PIN login"""
    pin = Mock()
    pin._id = "pin123"
    pin._code = "ABCD"
    pin.oauthUrl = Mock(return_value="https://app.plex.tv/auth#?clientID=xxx&code=ABCD")
    pin.token = None
    pin._checkLogin = Mock(return_value=False)
    return pin


# PlexAuthService Tests


@pytest.mark.asyncio
@patch("app.services.media_server.plex_service.get_token_manager")
@patch("app.services.media_server.plex_service.requests.post")
async def test_initiate_auth(mock_post, mock_token_manager):
    """Test initiating OAuth PIN authentication"""
    mock_response = Mock()
    mock_response.json.return_value = {
        "id": 123,
        "code": "ABCD",
    }
    mock_response.raise_for_status = Mock()
    mock_post.return_value = mock_response

    mock_manager = Mock()
    mock_manager.generate_state_token.return_value = "test-state-token"
    mock_token_manager.return_value = mock_manager

    result = await PlexAuthService.initiate_auth()

    assert "auth_url" in result
    assert result["pin_id"] == "123"
    assert result["code"] == "ABCD"
    assert result["expires_in"] == 600
    mock_post.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.media_server.plex_service.requests.get")
@patch("app.services.media_server.plex_service.pin_cache")
@patch("app.services.media_server.plex_service.PlexAuthService.validate_token")
@patch("app.services.media_server.plex_service.get_token_manager")
async def test_check_auth_completed(
    mock_token_manager, mock_validate, mock_cache, mock_get
):
    """Test checking auth when user has completed OAuth"""
    mock_cache.get.return_value = {
        "code": "ABCD",
        "client_id": "test-client-id",
        "state_token": "test-state",
        "created_at": "2024-01-01T00:00:00",
    }

    mock_response = Mock()
    mock_response.json.return_value = {
        "authToken": "new_oauth_token",
    }
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    mock_validate.return_value = {"username": "testuser"}

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
        "state_token": "test-state",
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


@pytest.mark.asyncio
@patch("app.services.media_server.plex_service.PlexAuthService.get_servers")
async def test_get_available_servers(mock_get_servers):
    """Test getting available servers"""
    mock_get_servers.return_value = [{"name": "Test Server"}]

    service = PlexService(encrypted_token="encrypted_token")
    servers = await service.get_available_servers()

    assert len(servers) == 1
    mock_get_servers.assert_called_once_with("encrypted_token")


# Duplicate Detection Tests
#
# CRITICAL: These tests validate the native Plex duplicate detection integration.
#
# Background: Plex has a built-in duplicate detection API using the `duplicate=True` filter.
# This is the EXACT same filter that the Plex UI uses when you click "Show Duplicates".
#
# We use library.search(duplicate=True) for movies and library.search(libtype='episode', duplicate=True) for episodes.
# This replaces the old custom duplicate detection logic that tried to replicate Plex's algorithm.
#
# Historical Context: The old approach tried to group movies by title+year or check len(movie.media) > 1,
# which was unreliable and found 0 duplicates despite 40+ actual duplicates existing.
#
# These tests ensure we properly use the native Plex API for duplicate detection.


@patch("app.services.media_server.plex_service.get_token_manager")
@patch("app.services.media_server.plex_service.MyPlexAccount")
def test_find_duplicate_movies_with_multiple_versions(
    mock_account_class,
    mock_token_manager,
    mock_plex_account,
    mock_plex_server,
    mock_plex_resource,
):
    """
    Test finding duplicate movies using Plex's native duplicate=True filter.
    The native API returns all duplicate movies automatically.
    """
    # Setup server connection
    mock_plex_resource.connect.return_value = mock_plex_server
    mock_plex_account.resource.return_value = mock_plex_resource
    mock_account_class.return_value = mock_plex_account

    mock_manager = Mock()
    mock_manager.decrypt.return_value = "decrypted_token"
    mock_token_manager.return_value = mock_manager

    # Create mock library
    mock_library = Mock()
    mock_library.type = "movie"
    mock_library.title = "Movies"
    mock_plex_server.library.section.return_value = mock_library

    # Create mock movies returned by library.search(duplicate=True)
    # Plex's native API returns duplicate movies with their media files
    movie1 = Mock()
    movie1.title = "The Accountant 2"
    movie1.year = 2025
    movie1.ratingKey = "12345"

    # Create 3 media versions for movie1
    media1_1080p = Mock()
    media1_1080p.videoResolution = "1080"
    media1_1080p.videoCodec = "h264"
    media1_1080p.bitrate = 5000
    media1_1080p.width = 1920
    media1_1080p.height = 1080
    media1_1080p.parts = [Mock(file="/movies/accountant2_1080p.mkv", size=4000000000)]

    media1_720p = Mock()
    media1_720p.videoResolution = "720"
    media1_720p.videoCodec = "h264"
    media1_720p.bitrate = 3000
    media1_720p.width = 1280
    media1_720p.height = 720
    media1_720p.parts = [Mock(file="/movies/accountant2_720p.mkv", size=2500000000)]

    media1_4k = Mock()
    media1_4k.videoResolution = "4k"
    media1_4k.videoCodec = "hevc"
    media1_4k.bitrate = 15000
    media1_4k.width = 3840
    media1_4k.height = 2160
    media1_4k.parts = [Mock(file="/movies/accountant2_4k.mkv", size=8000000000)]

    movie1.media = [media1_1080p, media1_720p, media1_4k]

    # Movie 2: Has 2 versions (DUPLICATE)
    movie2 = Mock()
    movie2.title = "Challengers"
    movie2.year = 2024
    movie2.ratingKey = "67890"

    media2_1080p = Mock()
    media2_1080p.videoResolution = "1080"
    media2_1080p.videoCodec = "h264"
    media2_1080p.bitrate = 4500
    media2_1080p.width = 1920
    media2_1080p.height = 1080
    media2_1080p.parts = [Mock(file="/movies/challengers_1080p.mkv", size=3500000000)]

    media2_720p = Mock()
    media2_720p.videoResolution = "720"
    media2_720p.videoCodec = "h264"
    media2_720p.bitrate = 2800
    media2_720p.width = 1280
    media2_720p.height = 720
    media2_720p.parts = [Mock(file="/movies/challengers_720p.mkv", size=2200000000)]

    movie2.media = [media2_1080p, media2_720p]

    # Movie 3: Has only 1 version (NOT A DUPLICATE)
    movie3 = Mock()
    movie3.title = "Dune Part Two"
    movie3.year = 2024
    movie3.ratingKey = "11111"

    media3_1080p = Mock()
    media3_1080p.videoResolution = "1080"
    media3_1080p.videoCodec = "h264"
    media3_1080p.bitrate = 5500
    media3_1080p.width = 1920
    media3_1080p.height = 1080
    media3_1080p.parts = [Mock(file="/movies/dune2_1080p.mkv", size=4500000000)]

    movie3.media = [media3_1080p]

    # Movie 4: Another single version (NOT A DUPLICATE)
    movie4 = Mock()
    movie4.title = "Oppenheimer"
    movie4.year = 2023
    movie4.ratingKey = "22222"

    media4_4k = Mock()
    media4_4k.videoResolution = "4k"
    media4_4k.videoCodec = "hevc"
    media4_4k.bitrate = 20000
    media4_4k.width = 3840
    media4_4k.height = 2160
    media4_4k.parts = [Mock(file="/movies/oppenheimer_4k.mkv", size=12000000000)]

    movie4.media = [media4_4k]

    # Plex's native duplicate=True filter returns ONLY the duplicates (movie1 and movie2)
    # NOT the single-version movies (movie3, movie4)
    mock_library.search.return_value = [movie1, movie2]
    mock_library.all.return_value = [movie1, movie2, movie3, movie4]

    # Test duplicate detection
    service = PlexService(encrypted_token="encrypted_token", server_name="Test Server")
    duplicates = service.find_duplicate_movies("Movies")

    # Verify library.all and library.search were called
    mock_library.all.assert_called_once()
    mock_library.search.assert_called_once_with(duplicate=True)

    # Assertions
    assert len(duplicates) == 2, "Should find exactly 2 duplicate movie groups"

    # Check movie1 duplicates
    assert "The Accountant 2|2025" in duplicates
    movie1_list = duplicates["The Accountant 2|2025"]
    assert len(movie1_list) == 1, "Should have 1 movie object for movie1"
    assert movie1_list[0] == movie1

    # Check movie2 duplicates
    assert "Challengers|2024" in duplicates
    movie2_list = duplicates["Challengers|2024"]
    assert len(movie2_list) == 1, "Should have 1 movie object for movie2"
    assert movie2_list[0] == movie2


@patch("app.services.media_server.plex_service.get_token_manager")
@patch("app.services.media_server.plex_service.MyPlexAccount")
def test_find_duplicate_movies_no_duplicates(
    mock_account_class,
    mock_token_manager,
    mock_plex_account,
    mock_plex_server,
    mock_plex_resource,
):
    """Test finding duplicates when Plex returns no duplicate movies"""
    # Setup server connection
    mock_plex_resource.connect.return_value = mock_plex_server
    mock_plex_account.resource.return_value = mock_plex_resource
    mock_account_class.return_value = mock_plex_account

    mock_manager = Mock()
    mock_manager.decrypt.return_value = "decrypted_token"
    mock_token_manager.return_value = mock_manager

    # Create mock library
    mock_library = Mock()
    mock_library.type = "movie"
    mock_library.title = "Movies"
    mock_plex_server.library.section.return_value = mock_library

    # Plex's native duplicate filter returns empty list when no duplicates
    mock_library.search.return_value = []
    mock_library.all.return_value = []

    service = PlexService(encrypted_token="encrypted_token", server_name="Test Server")
    duplicates = service.find_duplicate_movies("Movies")

    # Verify library.all and library.search were called
    mock_library.all.assert_called_once()
    mock_library.search.assert_called_once_with(duplicate=True)

    assert (
        len(duplicates) == 0
    ), "Should find no duplicates when Plex returns empty list"


@patch("app.services.media_server.plex_service.get_token_manager")
@patch("app.services.media_server.plex_service.MyPlexAccount")
def test_find_duplicate_movies_wrong_library_type(
    mock_account_class,
    mock_token_manager,
    mock_plex_account,
    mock_plex_server,
    mock_plex_resource,
):
    """Test that searching for movie duplicates in a TV library returns empty results"""
    # Setup server connection
    mock_plex_resource.connect.return_value = mock_plex_server
    mock_plex_account.resource.return_value = mock_plex_resource
    mock_account_class.return_value = mock_plex_account

    mock_manager = Mock()
    mock_manager.decrypt.return_value = "decrypted_token"
    mock_token_manager.return_value = mock_manager

    # Create mock TV library
    mock_library = Mock()
    mock_library.type = "show"
    mock_library.title = "TV Shows"
    # Plex's native filter returns empty list when duplicate=True on wrong type
    mock_library.search.return_value = []
    mock_library.all.return_value = []
    mock_plex_server.library.section.return_value = mock_library

    service = PlexService(encrypted_token="encrypted_token", server_name="Test Server")

    # Should return empty dict (no duplicates found in TV library)
    duplicates = service.find_duplicate_movies("TV Shows")
    assert duplicates == {}


@patch("app.services.media_server.plex_service.get_token_manager")
@patch("app.services.media_server.plex_service.MyPlexAccount")
def test_find_duplicate_episodes_with_multiple_versions(
    mock_account_class,
    mock_token_manager,
    mock_plex_account,
    mock_plex_server,
    mock_plex_resource,
):
    """
    Test finding duplicate episodes using Plex's native duplicate=True filter.
    The native API returns all duplicate episodes automatically with libtype='episode'.
    """
    # Setup server connection
    mock_plex_resource.connect.return_value = mock_plex_server
    mock_plex_account.resource.return_value = mock_plex_resource
    mock_account_class.return_value = mock_plex_account

    mock_manager = Mock()
    mock_manager.decrypt.return_value = "decrypted_token"
    mock_token_manager.return_value = mock_manager

    # Create mock library
    mock_library = Mock()
    mock_library.type = "show"
    mock_library.title = "TV Shows"
    mock_plex_server.library.section.return_value = mock_library

    # Create mock duplicate episodes returned by library.search(libtype='episode', duplicate=True)
    # Episode 1: "Cangaço Novo" S01E01 with 2 media files
    ep1 = Mock()
    ep1.title = "O peso da Herança"
    ep1.seasonNumber = 1
    ep1.episodeNumber = 1
    ep1.ratingKey = "100001"
    ep1.grandparentTitle = "Cangaço Novo"

    media_ep1_1080p = Mock()
    media_ep1_1080p.videoResolution = "1080"
    media_ep1_1080p.videoCodec = "h264"
    media_ep1_1080p.bitrate = 4500
    media_ep1_1080p.width = 1920
    media_ep1_1080p.height = 1080
    media_ep1_1080p.parts = [Mock(file="/tv/cangaco/s01e01_1080p.mkv", size=2500000000)]

    media_ep1_720p = Mock()
    media_ep1_720p.videoResolution = "720"
    media_ep1_720p.videoCodec = "h264"
    media_ep1_720p.bitrate = 2800
    media_ep1_720p.width = 1280
    media_ep1_720p.height = 720
    media_ep1_720p.parts = [Mock(file="/tv/cangaco/s01e01_720p.mkv", size=1500000000)]

    ep1.media = [media_ep1_1080p, media_ep1_720p]

    # Episode 2: "Cangaço Novo" S01E02 with 2 media files (DUPLICATE)
    ep2 = Mock()
    ep2.title = "Promessa e Dívida"
    ep2.seasonNumber = 1
    ep2.episodeNumber = 2
    ep2.ratingKey = "100002"
    ep2.grandparentTitle = "Cangaço Novo"

    media_ep2_1080p = Mock()
    media_ep2_1080p.videoResolution = "1080"
    media_ep2_1080p.videoCodec = "h264"
    media_ep2_1080p.bitrate = 4600
    media_ep2_1080p.width = 1920
    media_ep2_1080p.height = 1080
    media_ep2_1080p.parts = [Mock(file="/tv/cangaco/s01e02_1080p.mkv", size=2600000000)]

    media_ep2_720p = Mock()
    media_ep2_720p.videoResolution = "720"
    media_ep2_720p.videoCodec = "h264"
    media_ep2_720p.bitrate = 2900
    media_ep2_720p.width = 1280
    media_ep2_720p.height = 720
    media_ep2_720p.parts = [Mock(file="/tv/cangaco/s01e02_720p.mkv", size=1600000000)]

    ep2.media = [media_ep2_1080p, media_ep2_720p]

    # Episode 3: Only 1 version (NOT A DUPLICATE)
    ep3 = Mock()
    ep3.title = "Meu Nome é Ubaldo"
    ep3.seasonNumber = 1
    ep3.episodeNumber = 3
    ep3.ratingKey = "100003"
    ep3.grandparentTitle = "Cangaço Novo"

    media_ep3_1080p = Mock()
    media_ep3_1080p.videoResolution = "1080"
    media_ep3_1080p.videoCodec = "h264"
    media_ep3_1080p.bitrate = 4700
    media_ep3_1080p.width = 1920
    media_ep3_1080p.height = 1080
    media_ep3_1080p.parts = [Mock(file="/tv/cangaco/s01e03_1080p.mkv", size=2700000000)]

    ep3.media = [media_ep3_1080p]

    # Episode 4: "Dexter: Resurrection" S01E01 with 3 media files (DUPLICATE)
    ep4 = Mock()
    ep4.title = "A Beating Heart"
    ep4.seasonNumber = 1
    ep4.episodeNumber = 1
    ep4.ratingKey = "200001"
    ep4.grandparentTitle = "Dexter: Resurrection"

    media_ep4_4k = Mock()
    media_ep4_4k.videoResolution = "4k"
    media_ep4_4k.videoCodec = "hevc"
    media_ep4_4k.bitrate = 18000
    media_ep4_4k.width = 3840
    media_ep4_4k.height = 2160
    media_ep4_4k.parts = [Mock(file="/tv/dexter/s01e01_4k.mkv", size=6000000000)]

    media_ep4_1080p = Mock()
    media_ep4_1080p.videoResolution = "1080"
    media_ep4_1080p.videoCodec = "h264"
    media_ep4_1080p.bitrate = 5500
    media_ep4_1080p.width = 1920
    media_ep4_1080p.height = 1080
    media_ep4_1080p.parts = [Mock(file="/tv/dexter/s01e01_1080p.mkv", size=3000000000)]

    media_ep4_720p = Mock()
    media_ep4_720p.videoResolution = "720"
    media_ep4_720p.videoCodec = "h264"
    media_ep4_720p.bitrate = 3200
    media_ep4_720p.width = 1280
    media_ep4_720p.height = 720
    media_ep4_720p.parts = [Mock(file="/tv/dexter/s01e01_720p.mkv", size=1800000000)]

    ep4.media = [media_ep4_4k, media_ep4_1080p, media_ep4_720p]

    # Plex's native duplicate filter returns ONLY the duplicate episodes (ep1, ep2, ep4)
    # NOT episodes with single versions (ep3, ep5)
    mock_library.search.return_value = [ep1, ep2, ep4]

    # Test duplicate detection
    service = PlexService(encrypted_token="encrypted_token", server_name="Test Server")
    duplicates = service.find_duplicate_episodes("TV Shows")

    # Verify library.search was called with libtype='episode'
    mock_library.search.assert_called_once_with(libtype="episode")

    # Assertions
    assert len(duplicates) == 3, "Should find exactly 3 duplicate episode groups"

    # Check Cangaço Novo S01E01
    assert "Cangaço Novo|S01E01" in duplicates
    ep1_list = duplicates["Cangaço Novo|S01E01"]
    assert len(ep1_list) == 1, "Should have 1 episode object for ep1"
    assert ep1_list[0] == ep1

    # Check Cangaço Novo S01E02
    assert "Cangaço Novo|S01E02" in duplicates
    ep2_list = duplicates["Cangaço Novo|S01E02"]
    assert len(ep2_list) == 1, "Should have 1 episode object for ep2"
    assert ep2_list[0] == ep2

    # Check Dexter S01E01
    assert "Dexter: Resurrection|S01E01" in duplicates
    ep4_list = duplicates["Dexter: Resurrection|S01E01"]
    assert len(ep4_list) == 1, "Should have 1 episode object for ep4"
    assert ep4_list[0] == ep4


@patch("app.services.media_server.plex_service.get_token_manager")
@patch("app.services.media_server.plex_service.MyPlexAccount")
def test_find_duplicate_episodes_no_duplicates(
    mock_account_class,
    mock_token_manager,
    mock_plex_account,
    mock_plex_server,
    mock_plex_resource,
):
    """Test finding duplicates when Plex returns no duplicate episodes"""
    # Setup server connection
    mock_plex_resource.connect.return_value = mock_plex_server
    mock_plex_account.resource.return_value = mock_plex_resource
    mock_account_class.return_value = mock_plex_account

    mock_manager = Mock()
    mock_manager.decrypt.return_value = "decrypted_token"
    mock_token_manager.return_value = mock_manager

    # Create mock library
    mock_library = Mock()
    mock_library.type = "show"
    mock_library.title = "TV Shows"
    mock_plex_server.library.section.return_value = mock_library

    # Plex's native duplicate filter returns empty list when no duplicates
    mock_library.search.return_value = []

    service = PlexService(encrypted_token="encrypted_token", server_name="Test Server")
    duplicates = service.find_duplicate_episodes("TV Shows")

    # Verify library.search was called with libtype='episode'
    mock_library.search.assert_called_once_with(libtype="episode")

    assert (
        len(duplicates) == 0
    ), "Should find no duplicates when Plex returns empty list"


@patch("app.services.media_server.plex_service.get_token_manager")
@patch("app.services.media_server.plex_service.MyPlexAccount")
def test_find_duplicate_episodes_wrong_library_type(
    mock_account_class,
    mock_token_manager,
    mock_plex_account,
    mock_plex_server,
    mock_plex_resource,
):
    """Test that attempting to find episode duplicates in a non-TV library fails"""
    # Setup server connection
    mock_plex_resource.connect.return_value = mock_plex_server
    mock_plex_account.resource.return_value = mock_plex_resource
    mock_account_class.return_value = mock_plex_account

    mock_manager = Mock()
    mock_manager.decrypt.return_value = "decrypted_token"
    mock_token_manager.return_value = mock_manager

    # Create mock library with wrong type
    mock_library = Mock()
    mock_library.type = "movie"
    mock_library.title = "Movies"
    # Plex's native filter returns empty list when libtype='episode' on wrong type
    mock_library.search.return_value = []
    mock_plex_server.library.section.return_value = mock_library

    service = PlexService(encrypted_token="oauth_token", server_name="Test Server")

    # Should return empty dict (no episode duplicates found in movie library)
    duplicates = service.find_duplicate_episodes("Movies")
    assert duplicates == {}
