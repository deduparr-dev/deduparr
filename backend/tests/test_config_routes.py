"""
Tests for configuration API endpoints
"""

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models import Config
from app.models.scoring_rule import ScoringRule, RuleType
from app.services.scheduler import get_scheduler
from app.services.shared.security import (
    SECRET_MASK,
    encrypt_if_sensitive,
    get_token_manager,
)
from tests.conftest import sign_the_old_way


@pytest.mark.asyncio
async def test_get_all_config_empty(test_db):
    """Test getting all config when database is empty"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/config/")
        assert response.status_code == 200
        assert response.json() == {}


@pytest.mark.asyncio
async def test_update_config_creates_new(test_db):
    """Test that updating a non-existent config creates it"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/config/plex_url", json={"value": "http://localhost:32400"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["key"] == "plex_url"
        assert data["value"] == "http://localhost:32400"


@pytest.mark.asyncio
async def test_update_config_modifies_existing(test_db):
    """Test that updating an existing config modifies it"""
    config = Config(key="enable_deep_scan", value="false")
    test_db.add(config)
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/config/enable_deep_scan", json={"value": "true"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["key"] == "enable_deep_scan"
        assert data["value"] == "true"


@pytest.mark.asyncio
async def test_update_config_encrypts_a_secret(test_db):
    """
    A secret written through the config API is not stored in the clear.

    Only the setup wizard used to encrypt, so anything writing a token here -
    the frontend, a script, a test fixture - left it readable in the database.
    """
    from app.services.shared.security import get_token_manager

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/config/plex_auth_token", json={"value": "a-real-token"}
        )
        assert response.status_code == 200

    stored = (
        await test_db.execute(select(Config).where(Config.key == "plex_auth_token"))
    ).scalar_one()
    assert stored.value != "a-real-token"
    assert get_token_manager().decrypt(stored.value) == "a-real-token"


@pytest.mark.asyncio
async def test_update_config_does_not_double_encrypt(test_db):
    """Re-saving an already encrypted value leaves it usable."""
    from app.services.shared.security import get_token_manager

    token_manager = get_token_manager()
    encrypted = token_manager.encrypt("a-real-token")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/config/plex_auth_token", json={"value": encrypted}
        )
        assert response.status_code == 200

    stored = (
        await test_db.execute(select(Config).where(Config.key == "plex_auth_token"))
    ).scalar_one()
    assert token_manager.decrypt(stored.value) == "a-real-token"


@pytest.mark.asyncio
async def test_batch_update_encrypts_secrets_only(test_db):
    """Batch writes encrypt secrets and leave ordinary settings alone."""
    from app.services.shared.security import get_token_manager

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/config/batch",
            json={"jellyfin_api_key": "admin-key", "enable_deep_scan": "true"},
        )
        assert response.status_code == 200

    rows = {
        row.key: row.value
        for row in (await test_db.execute(select(Config))).scalars().all()
    }
    assert rows["enable_deep_scan"] == "true"
    assert rows["jellyfin_api_key"] != "admin-key"
    assert get_token_manager().decrypt(rows["jellyfin_api_key"]) == "admin-key"


@pytest.mark.asyncio
async def test_no_response_holds_a_secret(test_db):
    """
    A stored secret comes back only as the mask, encrypted or not.

    Every value used to be returned as stored, and a signed secret reads
    without the key, so anyone who could reach the API could read them.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        responses = [
            await client.put("/api/config/radarr_api_key", json={"value": "a-key"}),
            await client.post("/api/config/batch", json={"smtp_password": "a-pass"}),
            await client.get("/api/config/"),
            await client.get("/api/config/radarr_api_key"),
            await client.get("/api/config/export/all"),
        ]
        stored = [
            row.value for row in (await test_db.execute(select(Config))).scalars()
        ]

        for response in responses:
            assert response.status_code == 200
            for secret in ["a-key", "a-pass", *stored]:
                assert secret not in response.text

        assert responses[2].json()["radarr_api_key"] == SECRET_MASK
        assert responses[4].json()["config"]["smtp_password"] == SECRET_MASK

        # Sent back as shown, the mask keeps the stored secret
        await client.put("/api/config/radarr_api_key", json={"value": SECRET_MASK})
        await client.post("/api/config/batch", json={"smtp_password": SECRET_MASK})

    rows = {
        row.key: row.value
        for row in (await test_db.execute(select(Config))).scalars().all()
    }
    assert get_token_manager().decrypt(rows["radarr_api_key"]) == "a-key"
    assert get_token_manager().decrypt(rows["smtp_password"]) == "a-pass"


@pytest.mark.asyncio
async def test_get_config_success(test_db):
    """Test getting a specific config value"""
    config = Config(key="test_key", value="test_value")
    test_db.add(config)
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/config/test_key")
        assert response.status_code == 200
        data = response.json()
        assert data["key"] == "test_key"
        assert data["value"] == "test_value"


@pytest.mark.asyncio
async def test_get_config_not_found(test_db):
    """Test getting a non-existent config returns 404"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/config/nonexistent")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_config_success(test_db):
    """Test deleting a config key"""
    config = Config(key="to_delete", value="delete_me")
    test_db.add(config)
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete("/api/config/to_delete")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"
        assert data["key"] == "to_delete"

    result = await test_db.execute(select(Config).where(Config.key == "to_delete"))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_config_not_found(test_db):
    """Test deleting a non-existent config returns 404"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete("/api/config/nonexistent")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_batch_update_config(test_db):
    """Test batch updating multiple config values"""
    existing = Config(key="existing_key", value="old_value")
    test_db.add(existing)
    await test_db.commit()

    batch_data = {
        "existing_key": "updated_value",
        "new_key1": "value1",
        "new_key2": "value2",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/config/batch", json=batch_data)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

        keys = {item["key"]: item["value"] for item in data}
        assert keys["existing_key"] == "updated_value"
        assert keys["new_key1"] == "value1"
        assert keys["new_key2"] == "value2"


@pytest.mark.asyncio
async def test_get_all_config_with_data(test_db):
    """Test getting all config with existing data"""
    configs = [
        Config(key="key1", value="value1"),
        Config(key="key2", value="value2"),
        Config(key="key3", value="value3"),
    ]
    for config in configs:
        test_db.add(config)
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/config/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        assert data["key1"] == "value1"
        assert data["key2"] == "value2"
        assert data["key3"] == "value3"


@pytest.mark.asyncio
async def test_update_config_with_null_value(test_db):
    """Test that updating config with null value works"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put("/api/config/nullable_key", json={"value": None})
        assert response.status_code == 200
        data = response.json()
        assert data["key"] == "nullable_key"
        assert data["value"] is None


@pytest.mark.asyncio
async def test_export_configuration_empty(test_db):
    """Test exporting configuration when database is empty"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/config/export/all")
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == "1.0"
        assert data["config"] == {}
        assert data["scoring_rules"] == []


@pytest.mark.asyncio
async def test_export_configuration_with_data(test_db):
    """Test exporting configuration with data"""
    configs = [
        Config(key="plex_url", value="http://localhost:32400"),
        Config(key="plex_auth_token", value="test_token"),
    ]
    for config in configs:
        test_db.add(config)

    rule = ScoringRule(
        rule_type=RuleType.RESOLUTION,
        pattern="1080p",
        score_modifier=5,
        enabled=True,
        description="HD quality",
    )
    test_db.add(rule)
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/config/export/all")
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == "1.0"
        assert len(data["config"]) == 2
        assert data["config"]["plex_url"] == "http://localhost:32400"
        assert data["config"]["plex_auth_token"] == SECRET_MASK
        assert len(data["scoring_rules"]) == 1
        assert data["scoring_rules"][0]["rule_type"] == "resolution"
        assert data["scoring_rules"][0]["pattern"] == "1080p"
        assert data["scoring_rules"][0]["score_modifier"] == 5


@pytest.mark.asyncio
async def test_import_configuration_new(test_db):
    """Test importing configuration into empty database"""
    import_data = {
        "config": {
            "plex_url": "http://localhost:32400",
            "plex_auth_token": "imported_token",
        },
        "scoring_rules": [
            {
                "rule_type": "resolution",
                "pattern": "4K",
                "score_modifier": 10,
                "enabled": True,
                "description": "4K quality",
            }
        ],
        "overwrite_existing": False,
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/config/import/all", json=import_data)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["imported"]["configs"] == 2
        assert data["imported"]["scoring_rules"] == 1
        assert data["skipped"]["configs"] == 0
        assert data["skipped"]["scoring_rules"] == 0

    result = await test_db.execute(select(Config).where(Config.key == "plex_url"))
    config = result.scalar_one_or_none()
    assert config is not None
    assert config.value == "http://localhost:32400"

    result = await test_db.execute(select(ScoringRule))
    rules = result.scalars().all()
    assert len(rules) == 1
    assert rules[0].pattern == "4K"


@pytest.mark.asyncio
async def test_import_encrypts_secrets(test_db):
    """
    An import stores a secret encrypted, whether an older export held it as
    typed or signed, and the mask a current export holds keeps the stored one.
    What failed connection tests left in an older export stays out.
    """
    test_db.add(Config(key="smtp_password", value=get_token_manager().encrypt("kept")))
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/config/import/all",
            json={
                "config": {
                    "radarr_api_key": "typed-key",
                    "sonarr_api_key": sign_the_old_way("signed-key"),
                    "smtp_password": SECRET_MASK,
                    "temp_sonarr_api_key": "typed-in-a-test",
                },
                "overwrite_existing": True,
            },
        )
    assert response.json()["imported"]["configs"] == 2

    rows = {
        row.key: row.value
        for row in (await test_db.execute(select(Config))).scalars().all()
    }
    token_manager = get_token_manager()
    assert token_manager.decrypt(rows["radarr_api_key"]) == "typed-key"
    assert token_manager.decrypt(rows["sonarr_api_key"]) == "signed-key"
    assert token_manager.decrypt(rows["smtp_password"]) == "kept"
    assert "temp_sonarr_api_key" not in rows


@pytest.mark.asyncio
async def test_import_configuration_overwrite_false(test_db):
    """Test importing configuration without overwriting existing data"""
    existing_config = Config(key="plex_url", value="existing_url")
    test_db.add(existing_config)

    existing_rule = ScoringRule(
        rule_type=RuleType.RESOLUTION,
        pattern="4K",
        score_modifier=5,
        enabled=True,
    )
    test_db.add(existing_rule)
    await test_db.commit()

    import_data = {
        "config": {
            "plex_url": "new_url",
            "new_key": "new_value",
        },
        "scoring_rules": [
            {
                "rule_type": "resolution",
                "pattern": "4K",
                "score_modifier": 20,
                "enabled": False,
            }
        ],
        "overwrite_existing": False,
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/config/import/all", json=import_data)
        assert response.status_code == 200
        data = response.json()
        assert data["imported"]["configs"] == 1
        assert data["skipped"]["configs"] == 1
        assert data["skipped"]["scoring_rules"] == 1

    result = await test_db.execute(select(Config).where(Config.key == "plex_url"))
    config = result.scalar_one_or_none()
    assert config.value == "existing_url"

    result = await test_db.execute(
        select(ScoringRule).where(ScoringRule.pattern == "4K")
    )
    rule = result.scalar_one_or_none()
    assert rule.score_modifier == 5


@pytest.mark.asyncio
async def test_import_configuration_overwrite_true(test_db):
    """Test importing configuration with overwriting existing data"""
    existing_config = Config(key="plex_url", value="existing_url")
    test_db.add(existing_config)

    existing_rule = ScoringRule(
        rule_type=RuleType.RESOLUTION,
        pattern="4K",
        score_modifier=5,
        enabled=True,
    )
    test_db.add(existing_rule)
    await test_db.commit()

    import_data = {
        "config": {
            "plex_url": "new_url",
            "new_key": "new_value",
        },
        "scoring_rules": [
            {
                "rule_type": "resolution",
                "pattern": "4K",
                "score_modifier": 20,
                "enabled": False,
            }
        ],
        "overwrite_existing": True,
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/config/import/all", json=import_data)
        assert response.status_code == 200
        data = response.json()
        assert data["imported"]["configs"] == 2
        assert data["imported"]["scoring_rules"] == 1
        assert data["skipped"]["configs"] == 0
        assert data["skipped"]["scoring_rules"] == 0

    result = await test_db.execute(select(Config).where(Config.key == "plex_url"))
    config = result.scalar_one_or_none()
    assert config.value == "new_url"

    result = await test_db.execute(
        select(ScoringRule).where(ScoringRule.pattern == "4K")
    )
    rule = result.scalar_one_or_none()
    assert rule.score_modifier == 20
    assert rule.enabled is False


@pytest.mark.asyncio
async def test_import_configuration_invalid_rule_type(test_db):
    """Test importing configuration with invalid rule type"""
    import_data = {
        "config": {},
        "scoring_rules": [
            {
                "rule_type": "invalid_type",
                "pattern": "test",
                "score_modifier": 10,
                "enabled": True,
            }
        ],
        "overwrite_existing": False,
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/config/import/all", json=import_data)
        assert response.status_code == 200
        data = response.json()
        assert data["skipped"]["scoring_rules"] == 1
        assert data["imported"]["scoring_rules"] == 0


@pytest.mark.asyncio
async def test_import_configuration_without_scoring_rules(test_db):
    """Test importing configuration without scoring rules"""
    import_data = {
        "config": {
            "test_key": "test_value",
        },
        "overwrite_existing": False,
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/config/import/all", json=import_data)
        assert response.status_code == 200
        data = response.json()
        assert data["imported"]["configs"] == 1
        assert data["imported"]["scoring_rules"] == 0


@pytest.mark.asyncio
async def test_get_deep_scan_default(test_db):
    """Test getting deep scan setting when not set (should default to False)"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/config/deep-scan")
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False


@pytest.mark.asyncio
async def test_get_deep_scan_enabled(test_db):
    """Test getting deep scan setting when enabled"""
    config = Config(key="enable_deep_scan", value="true")
    test_db.add(config)
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/config/deep-scan")
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True


@pytest.mark.asyncio
async def test_get_deep_scan_disabled(test_db):
    """Test getting deep scan setting when explicitly disabled"""
    config = Config(key="enable_deep_scan", value="false")
    test_db.add(config)
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/config/deep-scan")
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False


@pytest.mark.asyncio
async def test_update_deep_scan_enable(test_db):
    """Test enabling deep scan"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put("/api/config/deep-scan", json={"enabled": True})
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True

        result = await test_db.execute(
            select(Config).where(Config.key == "enable_deep_scan")
        )
        config = result.scalar_one_or_none()
        assert config is not None
        assert config.value == "true"


@pytest.mark.asyncio
async def test_update_deep_scan_disable(test_db):
    """Test disabling deep scan"""
    config = Config(key="enable_deep_scan", value="true")
    test_db.add(config)
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put("/api/config/deep-scan", json={"enabled": False})
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False

        result = await test_db.execute(
            select(Config).where(Config.key == "enable_deep_scan")
        )
        config = result.scalar_one_or_none()
        assert config is not None
        assert config.value == "false"


@pytest.mark.asyncio
async def test_update_deep_scan_toggle(test_db):
    """Test toggling deep scan on and off multiple times"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put("/api/config/deep-scan", json={"enabled": True})
        assert response.status_code == 200
        assert response.json()["enabled"] is True

        response = await client.put("/api/config/deep-scan", json={"enabled": False})
        assert response.status_code == 200
        assert response.json()["enabled"] is False

        response = await client.put("/api/config/deep-scan", json={"enabled": True})
        assert response.status_code == 200
        assert response.json()["enabled"] is True


@pytest.mark.asyncio
async def test_get_scheduler_config_defaults(test_db):
    """Test getting scheduler config with default values"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/config/scheduler")
        assert response.status_code == 200
        data = response.json()

        # Verify defaults (deletion timing removed - runs 30 min after scan)
        assert data["enable_scheduled_scans"] is False
        assert data["scan_schedule_mode"] == "daily"
        assert data["scheduled_scan_time"] == "02:00"
        assert data["scan_interval_hours"] == 24
        assert data["enable_scheduled_deletion"] is False


@pytest.mark.asyncio
async def test_get_scheduler_config_with_values(test_db):
    """Test getting scheduler config with custom values"""
    # Setup custom config (deletion timing removed)
    configs = [
        Config(key="enable_scheduled_scans", value="true"),
        Config(key="scan_schedule_mode", value="interval"),
        Config(key="scheduled_scan_time", value="03:30"),
        Config(key="scan_interval_hours", value="6"),
        Config(key="enable_scheduled_deletion", value="true"),
    ]
    test_db.add_all(configs)
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/config/scheduler")
        assert response.status_code == 200
        data = response.json()

        assert data["enable_scheduled_scans"] is True
        assert data["scan_schedule_mode"] == "interval"
        assert data["scheduled_scan_time"] == "03:30"
        assert data["scan_interval_hours"] == 6
        assert data["enable_scheduled_deletion"] is True


@pytest.mark.asyncio
async def test_get_scheduler_config_falls_back_to_the_environment(test_db, monkeypatch):
    """A value Settings has not saved comes from the environment; a saved one wins."""
    monkeypatch.setattr(settings, "enable_scheduled_scans", True)
    monkeypatch.setattr(settings, "scan_interval_hours", 12)
    test_db.add(Config(key="scan_interval_hours", value="6"))
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        data = (await client.get("/api/config/scheduler")).json()

    assert data["enable_scheduled_scans"] is True
    assert data["scan_interval_hours"] == 6


@pytest.mark.asyncio
async def test_update_scheduler_config_enable_scans(test_db):
    """Test enabling scheduled scans"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/config/scheduler", json={"enable_scheduled_scans": True}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

        # Verify in database
        result = await test_db.execute(
            select(Config).where(Config.key == "enable_scheduled_scans")
        )
        config = result.scalar_one_or_none()
        assert config is not None
        assert config.value == "true"

        # Running, on this test's event loop, which closes after it
        assert get_scheduler().is_running
        await get_scheduler().stop()


@pytest.mark.asyncio
async def test_update_scheduler_config_daily_mode(test_db):
    """Test updating scheduler to daily mode"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/config/scheduler",
            json={
                "scan_schedule_mode": "daily",
                "scheduled_scan_time": "01:30",
            },
        )
        assert response.status_code == 200

        # Verify in database
        result = await test_db.execute(
            select(Config).where(Config.key == "scan_schedule_mode")
        )
        config = result.scalar_one_or_none()
        assert config.value == "daily"

        result = await test_db.execute(
            select(Config).where(Config.key == "scheduled_scan_time")
        )
        config = result.scalar_one_or_none()
        assert config.value == "01:30"


@pytest.mark.asyncio
async def test_update_scheduler_config_interval_mode(test_db):
    """Test updating scheduler to interval mode"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/config/scheduler",
            json={"scan_schedule_mode": "interval", "scan_interval_hours": 8},
        )
        assert response.status_code == 200

        # Verify in database
        result = await test_db.execute(
            select(Config).where(Config.key == "scan_schedule_mode")
        )
        config = result.scalar_one_or_none()
        assert config.value == "interval"

        result = await test_db.execute(
            select(Config).where(Config.key == "scan_interval_hours")
        )
        config = result.scalar_one_or_none()
        assert config.value == "8"


@pytest.mark.asyncio
async def test_update_scheduler_config_invalid_mode(test_db):
    """Test validation of invalid schedule mode"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/config/scheduler", json={"scan_schedule_mode": "weekly"}
        )
        assert response.status_code == 400
        assert "must be 'daily' or 'interval'" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_scheduler_config_invalid_time_format(test_db):
    """Test validation of invalid time format"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/config/scheduler", json={"scheduled_scan_time": "25:00"}
        )
        assert response.status_code == 400
        assert "HH:MM format" in response.json()["detail"]

        response = await client.post(
            "/api/config/scheduler", json={"scheduled_scan_time": "12:60"}
        )
        assert response.status_code == 400

        response = await client.post(
            "/api/config/scheduler", json={"scheduled_scan_time": "1:30"}
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_update_scheduler_config_invalid_interval(test_db):
    """Test validation of invalid interval hours"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Too small
        response = await client.post(
            "/api/config/scheduler", json={"scan_interval_hours": 0}
        )
        assert response.status_code == 400
        assert "between 1 and 168" in response.json()["detail"]

        # Too large
        response = await client.post(
            "/api/config/scheduler", json={"scan_interval_hours": 200}
        )
        assert response.status_code == 400
        assert "between 1 and 168" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_scheduler_config_deletion_settings(test_db):
    """Test updating scheduled deletion settings"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/config/scheduler",
            json={
                "enable_scheduled_deletion": True,
                "deletion_schedule_mode": "interval",
                "deletion_time": "05:00",
                "deletion_interval_hours": 4,
            },
        )
        assert response.status_code == 200

        # Verify deletion enabled
        result = await test_db.execute(
            select(Config).where(Config.key == "enable_scheduled_deletion")
        )
        config = result.scalar_one_or_none()
        assert config.value == "true"


@pytest.mark.asyncio
async def test_update_scheduler_config_partial_update(test_db):
    """Test partial update of scheduler config"""
    # Setup initial config
    test_db.add(Config(key="scan_schedule_mode", value="daily"))
    test_db.add(Config(key="scheduled_scan_time", value="02:00"))
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Update only the time, leave mode unchanged
        response = await client.post(
            "/api/config/scheduler", json={"scheduled_scan_time": "03:00"}
        )
        assert response.status_code == 200

        # Verify mode unchanged
        result = await test_db.execute(
            select(Config).where(Config.key == "scan_schedule_mode")
        )
        config = result.scalar_one_or_none()
        assert config.value == "daily"  # Unchanged

        # Verify time updated
        result = await test_db.execute(
            select(Config).where(Config.key == "scheduled_scan_time")
        )
        config = result.scalar_one_or_none()
        assert config.value == "03:00"  # Updated


def test_a_secret_from_another_key_file_is_left_alone(tmp_path, monkeypatch):
    """Encrypted again, it could never be read back once the key is restored."""
    key_file = tmp_path / ".key"
    monkeypatch.setenv("ENCRYPTION_KEY_FILE", str(key_file))
    key_file.write_text("the-first-key-of-enough-length")
    encrypted = get_token_manager().encrypt("a-real-token")

    key_file.write_text("the-other-key-of-enough-length")
    assert encrypt_if_sensitive("radarr_api_key", encrypted) == encrypted
