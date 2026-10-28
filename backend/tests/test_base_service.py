"""
Tests for base service class
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import Config
from app.services.shared.base_service import BaseExternalService
from app.services.shared.security import get_token_manager


@pytest.mark.asyncio
async def test_get_encrypted_config_success(test_db: AsyncSession):
    """Test successful config retrieval and decryption"""
    token_manager = get_token_manager()

    config_url = Config(key="test_service_url", value="http://localhost:8080")
    test_db.add(config_url)

    encrypted_key = token_manager.encrypt("my-secret-api-key")
    config_api_key = Config(key="test_service_api_key", value=encrypted_key)
    test_db.add(config_api_key)

    await test_db.commit()

    service = BaseExternalService(test_db)
    config = await service._get_encrypted_config(
        service_name="TestService",
        config_keys={"url": "test_service_url", "api_key": "test_service_api_key"},
    )

    assert config["url"] == "http://localhost:8080"
    assert config["api_key"] == "my-secret-api-key"


@pytest.mark.asyncio
async def test_get_encrypted_config_missing_config(test_db: AsyncSession):
    """Test error when config is missing"""
    service = BaseExternalService(test_db)

    with pytest.raises(ValueError, match="TestService configuration not found"):
        await service._get_encrypted_config(
            service_name="TestService",
            config_keys={"url": "test_service_url", "api_key": "test_service_api_key"},
        )


@pytest.mark.asyncio
async def test_get_encrypted_config_empty_api_key(test_db: AsyncSession):
    """Test error when API key is empty"""
    config_url = Config(key="test_service_url", value="http://localhost:8080")
    test_db.add(config_url)

    config_api_key = Config(key="test_service_api_key", value="")
    test_db.add(config_api_key)

    await test_db.commit()

    service = BaseExternalService(test_db)

    with pytest.raises(ValueError, match="TestService api key is not configured"):
        await service._get_encrypted_config(
            service_name="TestService",
            config_keys={"url": "test_service_url", "api_key": "test_service_api_key"},
        )


@pytest.mark.asyncio
async def test_get_encrypted_config_plaintext_fallback(test_db: AsyncSession):
    """Test fallback to plaintext when decryption fails (backwards compatibility)"""
    config_url = Config(key="test_service_url", value="http://localhost:8080")
    test_db.add(config_url)

    config_api_key = Config(key="test_service_api_key", value="plaintext-api-key")
    test_db.add(config_api_key)

    await test_db.commit()

    service = BaseExternalService(test_db)
    config = await service._get_encrypted_config(
        service_name="TestService",
        config_keys={"url": "test_service_url", "api_key": "test_service_api_key"},
    )

    assert config["url"] == "http://localhost:8080"
    assert config["api_key"] == "plaintext-api-key"


@pytest.mark.asyncio
async def test_get_encrypted_config_password_field(test_db: AsyncSession):
    """Test config retrieval with password field (for qBittorrent)"""
    token_manager = get_token_manager()

    config_url = Config(key="qbit_url", value="http://localhost:8080")
    test_db.add(config_url)

    config_username = Config(key="qbit_username", value="admin")
    test_db.add(config_username)

    encrypted_password = token_manager.encrypt("my-secret-password")
    config_password = Config(key="qbit_password", value=encrypted_password)
    test_db.add(config_password)

    await test_db.commit()

    service = BaseExternalService(test_db)
    config = await service._get_encrypted_config(
        service_name="qBittorrent",
        config_keys={
            "url": "qbit_url",
            "username": "qbit_username",
            "password": "qbit_password",
        },
    )

    assert config["url"] == "http://localhost:8080"
    assert config["username"] == "admin"
    assert config["password"] == "my-secret-password"


@pytest.mark.asyncio
async def test_get_encrypted_config_multiple_services(test_db: AsyncSession):
    """Test that different services can use the same base class"""
    token_manager = get_token_manager()

    radarr_url = Config(key="radarr_url", value="http://localhost:7878")
    test_db.add(radarr_url)
    radarr_key = Config(key="radarr_api_key", value=token_manager.encrypt("radarr-key"))
    test_db.add(radarr_key)

    sonarr_url = Config(key="sonarr_url", value="http://localhost:8989")
    test_db.add(sonarr_url)
    sonarr_key = Config(key="sonarr_api_key", value=token_manager.encrypt("sonarr-key"))
    test_db.add(sonarr_key)

    await test_db.commit()

    service = BaseExternalService(test_db)

    radarr_config = await service._get_encrypted_config(
        service_name="Radarr",
        config_keys={"url": "radarr_url", "api_key": "radarr_api_key"},
    )
    assert radarr_config["url"] == "http://localhost:7878"
    assert radarr_config["api_key"] == "radarr-key"

    sonarr_config = await service._get_encrypted_config(
        service_name="Sonarr",
        config_keys={"url": "sonarr_url", "api_key": "sonarr_api_key"},
    )
    assert sonarr_config["url"] == "http://localhost:8989"
    assert sonarr_config["api_key"] == "sonarr-key"
