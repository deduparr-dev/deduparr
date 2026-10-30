"""
Tests for setup service
"""

from functools import partial

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import select

from app.services.media_server import MediaServerType
from app.services.setup_service import SetupService
from app.models.config import Config
from tests.conftest import encrypt_test_password


@pytest.mark.asyncio
async def test_is_setup_complete_false_when_no_config(test_db):
    """Test setup is not complete when no configuration exists"""
    setup_service = SetupService(test_db)
    is_complete = await setup_service.is_setup_complete()
    assert is_complete is False


@pytest.mark.asyncio
async def test_is_setup_complete_false_when_missing_required(test_db):
    """Test setup is not complete when missing required keys"""
    config = Config(key="setup_completed", value="true")
    test_db.add(config)
    await test_db.commit()

    setup_service = SetupService(test_db)
    is_complete = await setup_service.is_setup_complete()
    assert is_complete is False


@pytest.mark.asyncio
async def test_is_setup_complete_true_when_all_required_present(test_db):
    """Test setup is complete when all required keys are present"""
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

    setup_service = SetupService(test_db)
    is_complete = await setup_service.is_setup_complete()
    assert is_complete is True


@pytest.mark.asyncio
async def test_get_setup_status_empty(test_db):
    """Test getting setup status when database is empty"""
    setup_service = SetupService(test_db)
    status = await setup_service.get_setup_status()

    assert status["is_complete"] is False
    # A media server is the only requirement; which one is up to the user
    assert status["missing_required"] == ["media_server"]
    assert status["configured_services"]["plex"] is False
    assert status["configured_services"]["jellyfin"] is False
    assert status["configured_services"]["radarr"] is False
    assert status["configured_services"]["sonarr"] is False
    assert status["configured_services"]["qbittorrent"] is False
    assert status["database_type"] == "sqlite"


@pytest.mark.asyncio
async def test_get_setup_status_reports_the_database_in_use(test_db):
    with patch("app.services.setup_service.settings.database_type", "postgres"):
        status = await SetupService(test_db).get_setup_status()

    assert status["database_type"] == "postgres"


@pytest.mark.asyncio
async def test_get_setup_status_partial_config(test_db):
    """Test getting setup status with partial configuration"""
    configs = [
        Config(key="plex_auth_token", value="test_token"),
        Config(key="radarr_url", value="http://radarr:7878"),
        Config(key="radarr_api_key", value="test_api_key"),
    ]
    for config in configs:
        test_db.add(config)
    await test_db.commit()

    setup_service = SetupService(test_db)
    status = await setup_service.get_setup_status()

    # The Plex token alone makes it usable, so nothing required is missing;
    # setup is still incomplete until the wizard marks itself finished
    assert status["is_complete"] is False
    assert status["missing_required"] == []
    assert status["configured_services"]["plex"] is True
    assert status["configured_services"]["jellyfin"] is False
    assert status["configured_services"]["radarr"] is True
    assert status["configured_services"]["sonarr"] is False


@pytest.mark.asyncio
async def test_test_plex_connection_success(test_db):
    """Test successful Plex connection"""
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

            setup_service = SetupService(test_db)
            result = await setup_service.test_plex_connection(
                "test_token", "test_server"
            )

            assert result["success"] is True
            assert result["server_name"] == "test_server"
            assert result["version"] == "1.32.5"
            assert result["platform"] == "Linux"


@pytest.mark.asyncio
async def test_test_plex_connection_server_not_found(test_db):
    """Test Plex connection when server is not found"""
    with patch(
        "app.services.setup_service.PlexAuthService.get_servers"
    ) as mock_get_servers:
        mock_get_servers.return_value = [
            {"name": "other_server"},
            {"name": "another_server"},
        ]

        setup_service = SetupService(test_db)
        result = await setup_service.test_plex_connection("test_token", "test_server")

        assert result["success"] is False
        assert "not found" in result["error"]
        assert "other_server" in result["available_servers"]
        assert "another_server" in result["available_servers"]


@pytest.mark.asyncio
async def test_test_plex_connection_exception(test_db):
    """Test Plex connection when exception occurs"""
    with patch(
        "app.services.setup_service.PlexAuthService.get_servers"
    ) as mock_get_servers:
        mock_get_servers.side_effect = Exception("Connection failed")

        setup_service = SetupService(test_db)
        result = await setup_service.test_plex_connection("test_token", "test_server")

        assert result["success"] is False
        assert "Connection failed" in result["error"]


@pytest.mark.asyncio
async def test_get_plex_libraries_success(test_db):
    """Test getting Plex libraries successfully"""
    mock_library1 = MagicMock()
    mock_library1.key = "1"
    mock_library1.title = "Movies"
    mock_library1.type = "movie"
    mock_library1.agent = "com.plexapp.agents.imdb"

    mock_library2 = MagicMock()
    mock_library2.key = "2"
    mock_library2.title = "TV Shows"
    mock_library2.type = "show"
    mock_library2.agent = "com.plexapp.agents.thetvdb"

    mock_server = MagicMock()
    mock_server.library.sections.return_value = [mock_library1, mock_library2]

    with patch("app.services.setup_service.PlexService") as mock_plex_service:
        mock_plex_instance = MagicMock()
        mock_plex_instance._get_server.return_value = mock_server
        mock_plex_service.return_value = mock_plex_instance

        setup_service = SetupService(test_db)
        libraries = await setup_service.get_plex_libraries("test_token", "test_server")

        assert len(libraries) == 2
        assert libraries[0]["title"] == "Movies"
        assert libraries[0]["type"] == "movie"
        assert libraries[1]["title"] == "TV Shows"
        assert libraries[1]["type"] == "show"


@pytest.mark.asyncio
async def test_get_plex_libraries_exception(test_db):
    """Test getting Plex libraries when exception occurs"""
    with patch("app.services.setup_service.PlexService") as mock_plex_service:
        mock_plex_instance = MagicMock()
        mock_plex_instance._get_server.side_effect = Exception("Auth failed")
        mock_plex_service.return_value = mock_plex_instance

        setup_service = SetupService(test_db)

        with pytest.raises(ValueError, match="Failed to get Plex libraries"):
            await setup_service.get_plex_libraries("test_token", "test_server")


@pytest.mark.asyncio
async def test_save_configuration_new_keys(test_db):
    """Test saving new configuration keys with encryption for sensitive data"""
    from app.services.shared.security import get_token_manager

    setup_service = SetupService(test_db)
    config_data = {
        "plex_auth_token": "new_plex_token",
        "plex_server_name": "my_server",
        "qbittorrent_password": "my_password",
        "radarr_api_key": "radarr_key",
    }

    await setup_service.save_configuration(config_data)

    # Check encrypted values
    token_manager = get_token_manager()

    result = await test_db.execute(
        select(Config).where(Config.key == "plex_auth_token")
    )
    config = result.scalar_one_or_none()
    assert config is not None
    # Should be encrypted, so not plain text
    assert config.value != "new_plex_token"
    # Should decrypt to original value
    assert token_manager.decrypt(config.value) == "new_plex_token"

    result = await test_db.execute(
        select(Config).where(Config.key == "qbittorrent_password")
    )
    config = result.scalar_one_or_none()
    assert config is not None
    assert config.value != "my_password"
    assert token_manager.decrypt(config.value) == "my_password"

    result = await test_db.execute(select(Config).where(Config.key == "radarr_api_key"))
    config = result.scalar_one_or_none()
    assert config is not None
    assert config.value != "radarr_key"
    assert token_manager.decrypt(config.value) == "radarr_key"

    # Check non-encrypted value
    result = await test_db.execute(
        select(Config).where(Config.key == "plex_server_name")
    )
    config = result.scalar_one_or_none()
    assert config is not None
    assert config.value == "my_server"  # Not encrypted


@pytest.mark.asyncio
async def test_save_configuration_update_existing(test_db):
    """Test updating existing configuration keys with encryption"""
    from app.services.shared.security import get_token_manager

    token_manager = get_token_manager()
    old_encrypted = token_manager.encrypt("old_password")

    config = Config(key="qbittorrent_password", value=old_encrypted)
    test_db.add(config)
    await test_db.commit()

    setup_service = SetupService(test_db)
    config_data = {"qbittorrent_password": "updated_password"}

    await setup_service.save_configuration(config_data)

    result = await test_db.execute(
        select(Config).where(Config.key == "qbittorrent_password")
    )
    config = result.scalar_one_or_none()
    assert config is not None
    # Should not be plain text
    assert config.value != "updated_password"
    # Should not be old value
    assert config.value != old_encrypted
    # Should decrypt to new value
    assert token_manager.decrypt(config.value) == "updated_password"


@pytest.mark.asyncio
async def test_mark_setup_complete_new(test_db):
    """Test marking setup as complete when key doesn't exist"""
    setup_service = SetupService(test_db)
    await setup_service.mark_setup_complete()

    result = await test_db.execute(
        select(Config).where(Config.key == "setup_completed")
    )
    config = result.scalar_one_or_none()
    assert config is not None
    assert config.value == "true"


@pytest.mark.asyncio
async def test_mark_setup_complete_update(test_db):
    """Test marking setup as complete when key already exists"""
    config = Config(key="setup_completed", value="false")
    test_db.add(config)
    await test_db.commit()

    setup_service = SetupService(test_db)
    await setup_service.mark_setup_complete()

    result = await test_db.execute(
        select(Config).where(Config.key == "setup_completed")
    )
    config = result.scalar_one_or_none()
    assert config is not None
    assert config.value == "true"


@pytest.mark.asyncio
async def test_test_jellyfin_connection_reports_the_server(test_db):
    """A successful test names the server, using credentials not yet saved."""
    setup_service = SetupService(test_db)

    with patch(
        "app.services.setup_service.JellyfinAdapter.test_connection",
        new_callable=AsyncMock,
        return_value={"success": True, "server_name": "Home", "version": "12.4.0"},
    ):
        result = await setup_service.test_jellyfin_connection(
            "http://jellyfin:8096", "admin-key"
        )

    assert result == {"success": True, "server_name": "Home", "version": "12.4.0"}


@pytest.mark.asyncio
async def test_test_jellyfin_connection_surfaces_the_error(test_db):
    setup_service = SetupService(test_db)

    with patch(
        "app.services.setup_service.JellyfinAdapter.test_connection",
        new_callable=AsyncMock,
        return_value={"success": False, "error": "key must belong to an administrator"},
    ):
        result = await setup_service.test_jellyfin_connection("http://jellyfin", "bad")

    assert result["success"] is False
    assert "administrator" in result["error"]


@pytest.mark.asyncio
async def test_get_media_libraries_labels_each_server(test_db):
    """Libraries from both servers come back tagged with their origin."""
    plex = AsyncMock()
    plex.type = MediaServerType.PLEX
    plex.get_libraries.return_value = [
        {"key": "1", "title": "Movies", "type": "movie", "count": 10}
    ]
    jellyfin = AsyncMock()
    jellyfin.type = MediaServerType.JELLYFIN
    jellyfin.get_libraries.return_value = [
        {"key": "2", "title": "Movies", "type": "movie", "count": 11}
    ]

    with patch(
        "app.services.setup_service.get_media_servers",
        new_callable=AsyncMock,
        return_value=[plex, jellyfin],
    ):
        libraries = await SetupService(test_db).get_media_libraries()

    assert [(lib["server"], lib["count"]) for lib in libraries] == [
        ("plex", 10),
        ("jellyfin", 11),
    ]


@pytest.mark.asyncio
async def test_get_media_libraries_survives_one_server_failing(test_db):
    """One unreachable server must not hide the other's libraries."""
    broken = AsyncMock()
    broken.type = MediaServerType.JELLYFIN
    broken.get_libraries.side_effect = RuntimeError("unreachable")
    plex = AsyncMock()
    plex.type = MediaServerType.PLEX
    plex.get_libraries.return_value = [
        {"key": "1", "title": "Movies", "type": "movie", "count": 1}
    ]

    with patch(
        "app.services.setup_service.get_media_servers",
        new_callable=AsyncMock,
        return_value=[broken, plex],
    ):
        libraries = await SetupService(test_db).get_media_libraries()

    assert [lib["server"] for lib in libraries] == ["plex"]


@pytest.mark.asyncio
@pytest.mark.parametrize("saved", [False, True])
async def test_test_jellyfin_connection_takes_the_saved_key_too(test_db, saved):
    """
    Settings keeps a saved key out of its field: a test runs with the key
    typed, or with the saved one when the field was left blank.
    """
    test_db.add_all(
        [
            Config(key="jellyfin_url", value="http://jf:8096"),
            Config(key="jellyfin_api_key", value=encrypt_test_password("saved-key")),
        ]
    )
    await test_db.commit()
    key = "" if saved else "typed-key"
    seen: dict = {}

    async def connect(adapter):
        seen.update(
            await adapter._get_encrypted_config(
                "Jellyfin", {"api_key": "jellyfin_api_key"}
            )
        )
        return {"success": True, "server_name": "Home", "version": "12.4.0"}

    with patch(
        "app.services.setup_service.JellyfinAdapter.test_connection",
        autospec=True,
        side_effect=connect,
    ):
        await SetupService(test_db).test_jellyfin_connection("http://jf:8096", key)

    assert seen["api_key"] == ("saved-key" if saved else "typed-key")


@pytest.mark.asyncio
@pytest.mark.parametrize("saved", [False, True])
async def test_test_qbittorrent_connection_takes_the_saved_password_too(test_db, saved):
    """
    Settings keeps a saved password out of its field: a test logs in with the
    password typed, or with the saved one when the field was left blank.
    """
    test_db.add_all(
        [
            Config(key="qbittorrent_url", value="http://qbit:8080"),
            Config(
                key="qbittorrent_password", value=encrypt_test_password("saved-pass")
            ),
        ]
    )
    await test_db.commit()
    password = "" if saved else "typed-pass"

    with patch("app.services.download.qbittorrent_service.Client") as client:
        client.return_value.app_version.return_value = "v4.6.0"
        result = await SetupService(test_db).test_qbittorrent_connection(
            "http://qbit:8080", "admin", password
        )

    assert result["success"] is True
    assert client.call_args.kwargs["password"] == (
        "saved-pass" if saved else "typed-pass"
    )


@pytest.mark.asyncio
async def test_a_stored_secret_goes_only_to_the_server_stored_with_it(test_db):
    """With no login, anyone could otherwise have it sent to a server of theirs."""
    test_db.add_all(
        [
            Config(key="radarr_url", value="http://radarr:7878"),
            Config(key="radarr_api_key", value="stored"),
        ]
    )
    await test_db.commit()
    service = SetupService(test_db)
    secret = partial(service.secret_or_stored, "radarr_api_key", "", "radarr_url")

    assert await secret("http://radarr:7878") == "stored"
    assert await secret("http://elsewhere:7878") == ""
