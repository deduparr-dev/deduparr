"""
Tests for how secrets are stored
"""

import base64

import pytest
from sqlalchemy import select

from app.models import Config
from app.services.arr.radarr_service import RadarrService
from app.services.notifications.helpers import get_email_service_from_config
from app.services.shared.security import (
    InvalidTokenError,
    TokenManager,
    get_token_manager,
    secure_stored_secrets,
)
from tests.conftest import sign_the_old_way


def test_encryption_round_trip():
    """A secret encrypted cannot be read, or decrypted, without the key."""
    token_manager = get_token_manager()

    encrypted = token_manager.encrypt("radarr-api-key")

    assert b"radarr-api-key" not in base64.urlsafe_b64decode(encrypted)
    assert token_manager.decrypt(encrypted) == "radarr-api-key"
    with pytest.raises(InvalidTokenError):
        TokenManager("another key").decrypt(encrypted)


@pytest.mark.asyncio
async def test_secrets_stored_before_are_encrypted_at_startup(test_db):
    """
    A secret an earlier version stored signed, or as typed, is encrypted and
    keeps working, and what failed connection tests left behind is removed.
    """
    test_db.add_all(
        [
            Config(key="radarr_url", value="http://radarr:7878"),
            Config(key="radarr_api_key", value=sign_the_old_way("radarr-key")),
            Config(key="smtp_host", value="smtp.example.com"),
            Config(key="smtp_port", value="587"),
            Config(key="smtp_user", value="user@example.com"),
            Config(key="smtp_password", value="typed-password"),
            Config(key="temp_radarr_api_key", value="typed-in-a-test"),
        ]
    )
    await test_db.commit()

    await secure_stored_secrets(test_db)
    rows = {
        row.key: row.value for row in (await test_db.execute(select(Config))).scalars()
    }

    token_manager = get_token_manager()
    assert token_manager.decrypt(rows["radarr_api_key"]) == "radarr-key"
    assert token_manager.decrypt(rows["smtp_password"]) == "typed-password"
    assert rows["radarr_url"] == "http://radarr:7878"
    assert "temp_radarr_api_key" not in rows

    # Once encrypted, they are left as they are
    await secure_stored_secrets(test_db)
    assert {
        row.key: row.value for row in (await test_db.execute(select(Config))).scalars()
    } == rows

    radarr = await RadarrService(test_db)._get_encrypted_config(
        "Radarr", {"api_key": "radarr_api_key"}
    )
    assert radarr["api_key"] == "radarr-key"
    email_service, _, _ = await get_email_service_from_config(test_db)
    assert email_service.smtp_password == "typed-password"
