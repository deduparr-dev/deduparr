"""Integration tests for deep scan feature."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Config


@pytest.mark.asyncio
async def test_deep_scan_default_disabled(test_db: AsyncSession):
    """Deep scan should be disabled by default."""
    result = await test_db.execute(
        select(Config).where(Config.key == "enable_deep_scan")
    )
    config = result.scalar_one_or_none()

    # Should not exist or be "false"
    if config:
        assert config.value == "false"


@pytest.mark.asyncio
async def test_enable_deep_scan(test_db: AsyncSession):
    """Test enabling deep scan."""
    config = Config(key="enable_deep_scan", value="true")
    test_db.add(config)
    await test_db.commit()

    result = await test_db.execute(
        select(Config).where(Config.key == "enable_deep_scan")
    )
    saved = result.scalar_one()
    assert saved.value == "true"


@pytest.mark.asyncio
async def test_disable_deep_scan(test_db: AsyncSession):
    """Test disabling deep scan."""
    config = Config(key="enable_deep_scan", value="false")
    test_db.add(config)
    await test_db.commit()

    result = await test_db.execute(
        select(Config).where(Config.key == "enable_deep_scan")
    )
    saved = result.scalar_one()
    assert saved.value == "false"


@pytest.mark.asyncio
async def test_deep_scan_toggle(test_db: AsyncSession):
    """Test toggling deep scan on and off."""
    # Enable
    config = Config(key="enable_deep_scan", value="true")
    test_db.add(config)
    await test_db.commit()

    result = await test_db.execute(
        select(Config).where(Config.key == "enable_deep_scan")
    )
    saved = result.scalar_one()
    assert saved.value == "true"

    # Disable
    saved.value = "false"
    await test_db.commit()

    result = await test_db.execute(
        select(Config).where(Config.key == "enable_deep_scan")
    )
    saved = result.scalar_one()
    assert saved.value == "false"
