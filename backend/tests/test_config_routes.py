"""
Tests for configuration API endpoints
"""

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from app.models import Config
from app.models.scoring_rule import ScoringRule, RuleType


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
    config = Config(key="plex_auth_token", value="old_token")
    test_db.add(config)
    await test_db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/config/plex_auth_token", json={"value": "new_token"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["key"] == "plex_auth_token"
        assert data["value"] == "new_token"


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
        assert data["config"]["plex_auth_token"] == "test_token"
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
