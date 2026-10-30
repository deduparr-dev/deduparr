"""
Configuration API endpoints
"""

from typing import Dict, List, Optional
from typing_extensions import TypedDict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models import Config
from app.services.shared.security import (
    LEFTOVER_TEST_KEYS,
    encrypt_if_sensitive,
    is_masked,
    mask_secret,
)
from app.models.scoring_rule import ScoringRule
from app.services.arr.quality import PREFER_ARR_QUALITY_PROFILE_KEY
from app.services.scheduler import Schedule, get_scheduler, load_schedule


class ScoringRuleImportData(TypedDict, total=False):
    """Type definition for scoring rule import data"""

    rule_type: str
    pattern: str
    score_modifier: int
    enabled: bool
    description: Optional[str]


router = APIRouter()


class ConfigResponse(BaseModel):
    """Response model for config items"""

    model_config = ConfigDict(from_attributes=True)

    key: str
    value: Optional[str] = None


class ConfigUpdate(BaseModel):
    """Request model for updating config"""

    value: Optional[str] = None


class ConfigImport(BaseModel):
    """Request model for importing configuration"""

    config: Dict[str, Optional[str]]
    scoring_rules: Optional[List[ScoringRuleImportData]] = None
    overwrite_existing: bool = False


class DeepScanResponse(BaseModel):
    """Response model for deep scan setting"""

    enabled: bool


class DeepScanUpdate(BaseModel):
    """Request model for updating deep scan setting"""

    enabled: bool


class ArrQualityProfileSetting(BaseModel):
    """Request/response model for the 'Prefer *arr quality profile' setting"""

    enabled: bool


async def _get_bool_config(db: AsyncSession, key: str) -> bool:
    """Read a "true"/"false" config value, defaulting to False"""
    result = await db.execute(select(Config).where(Config.key == key))
    config = result.scalar_one_or_none()
    return config.value == "true" if config else False


async def _set_bool_config(db: AsyncSession, key: str, enabled: bool) -> None:
    """Store a "true"/"false" config value"""
    result = await db.execute(select(Config).where(Config.key == key))
    config = result.scalar_one_or_none()

    value = "true" if enabled else "false"

    if config:
        config.value = value
    else:
        db.add(Config(key=key, value=value))

    await db.commit()


@router.get("/", response_model=Dict[str, Optional[str]])
async def get_all_config(db: AsyncSession = Depends(get_db)):
    """
    Get all configuration settings as a key-value dictionary

    A stored secret shows as the mask, never as its value.
    """
    result = await db.execute(select(Config))
    configs = result.scalars().all()
    return {config.key: mask_secret(config.key, config.value) for config in configs}


@router.get("/deep-scan", response_model=DeepScanResponse)
async def get_deep_scan_setting(db: AsyncSession = Depends(get_db)):
    """
    Get the deep scan setting (filesystem-based duplicate detection)

    Returns:
        enabled: True if deep scan is enabled, False otherwise (default)
    """
    enabled = await _get_bool_config(db, "enable_deep_scan")
    return DeepScanResponse(enabled=enabled)


@router.put("/deep-scan", response_model=DeepScanResponse)
async def update_deep_scan_setting(
    update: DeepScanUpdate, db: AsyncSession = Depends(get_db)
):
    """
    Update the deep scan setting

    Deep scan also walks the library folders on disk and logs duplicate files
    the media server does not list. It creates no duplicate sets, and makes
    scans slower.

    Args:
        update: Deep scan setting update

    Returns:
        enabled: Updated deep scan status
    """
    await _set_bool_config(db, "enable_deep_scan", update.enabled)
    return DeepScanResponse(enabled=update.enabled)


@router.get("/arr-quality-profile", response_model=ArrQualityProfileSetting)
async def get_arr_quality_profile_setting(db: AsyncSession = Depends(get_db)):
    """
    Get the 'Prefer *arr quality profile' setting

    Returns:
        enabled: True if the file to keep is chosen by the Radarr/Sonarr quality
        profile, False if by Deduparr's score (default)
    """
    enabled = await _get_bool_config(db, PREFER_ARR_QUALITY_PROFILE_KEY)
    return ArrQualityProfileSetting(enabled=enabled)


@router.put("/arr-quality-profile", response_model=ArrQualityProfileSetting)
async def update_arr_quality_profile_setting(
    update: ArrQualityProfileSetting, db: AsyncSession = Depends(get_db)
):
    """
    Update the 'Prefer *arr quality profile' setting

    When enabled, the file to keep in a duplicate set is the one Radarr/Sonarr
    ranks highest: quality position in the item's quality profile, then
    revision (proper/repack), then custom format score. Sets that cannot be
    fully evaluated by the *arr fall back to Deduparr's score.

    Args:
        update: Setting update

    Returns:
        enabled: Updated setting
    """
    await _set_bool_config(db, PREFER_ARR_QUALITY_PROFILE_KEY, update.enabled)
    return ArrQualityProfileSetting(enabled=update.enabled)


# Scheduler configuration endpoints (must come before /{key} catch-all route)
@router.get("/scheduler", response_model=Schedule)
async def get_scheduler_config(db: AsyncSession = Depends(get_db)):
    """Get the schedule in effect"""
    return await load_schedule(db)


class SchedulerConfigUpdate(BaseModel):
    """Request model for updating scheduler configuration"""

    enable_scheduled_scans: Optional[bool] = None
    scan_schedule_mode: Optional[str] = None
    scheduled_scan_time: Optional[str] = None
    scan_interval_hours: Optional[int] = None
    enable_scheduled_deletion: Optional[bool] = None


# Why the scheduler endpoint refuses a value, for each value it can refuse
INVALID_SCHEDULE_VALUE = {
    "scan_schedule_mode": "Scan schedule mode must be 'daily' or 'interval'",
    "scheduled_scan_time": "Scan time must be in HH:MM format (00:00 - 23:59)",
    "scan_interval_hours": "Scan interval must be between 1 and 168 hours",
}


@router.post("/scheduler")
async def update_scheduler_config(
    config: SchedulerConfigUpdate, db: AsyncSession = Depends(get_db)
):
    """Update scheduler configuration and restart scheduler if needed"""
    updates = config.model_dump(exclude_none=True)
    try:
        Schedule.model_validate({**(await load_schedule(db)).model_dump(), **updates})
    except ValidationError as e:
        field = str(e.errors()[0]["loc"][0])
        raise HTTPException(status_code=400, detail=INVALID_SCHEDULE_VALUE[field])

    for key, value in updates.items():
        if isinstance(value, bool):
            value = "true" if value else "false"
        result = await db.execute(select(Config).where(Config.key == key))
        config_item = result.scalar_one_or_none()

        if config_item:
            config_item.value = str(value)
        else:
            db.add(Config(key=key, value=str(value)))

    await db.commit()

    await get_scheduler().apply(await load_schedule(db))

    return {"status": "success", "message": "Scheduler configuration updated"}


@router.get("/{key}", response_model=ConfigResponse)
async def get_config(key: str, db: AsyncSession = Depends(get_db)):
    """
    Get a specific configuration value by key
    """
    result = await db.execute(select(Config).where(Config.key == key))
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")

    return ConfigResponse(key=key, value=mask_secret(key, config.value))


@router.put("/{key}", response_model=ConfigResponse)
async def update_config(
    key: str, config_update: ConfigUpdate, db: AsyncSession = Depends(get_db)
):
    """
    Update or create a configuration value
    """
    result = await db.execute(select(Config).where(Config.key == key))
    config = result.scalar_one_or_none()

    # Secrets are encrypted here too, not only by the setup wizard, so a value
    # written through this endpoint is never left in the clear. The mask a
    # secret was shown as keeps the stored one.
    if not is_masked(key, config_update.value):
        value = encrypt_if_sensitive(key, config_update.value)

        if config:
            config.value = value
        else:
            config = Config(key=key, value=value)
            db.add(config)

        await db.commit()
        await db.refresh(config)

    return ConfigResponse(
        key=key, value=mask_secret(key, config.value if config else None)
    )


@router.delete("/{key}")
async def delete_config(key: str, db: AsyncSession = Depends(get_db)):
    """
    Delete a configuration key
    """
    result = await db.execute(select(Config).where(Config.key == key))
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")

    await db.delete(config)
    await db.commit()
    return {"status": "deleted", "key": key}


@router.post("/batch", response_model=List[ConfigResponse])
async def batch_update_config(
    configs: Dict[str, Optional[str]], db: AsyncSession = Depends(get_db)
):
    """
    Update multiple configuration values at once
    """
    updated_configs = []

    for key, value in configs.items():
        # The mask a secret was shown as keeps the stored one
        if is_masked(key, value):
            continue

        result = await db.execute(select(Config).where(Config.key == key))
        config = result.scalar_one_or_none()

        stored = encrypt_if_sensitive(key, value)

        if config:
            config.value = stored
        else:
            config = Config(key=key, value=stored)
            db.add(config)

        updated_configs.append(config)

    await db.commit()

    for config in updated_configs:
        await db.refresh(config)

    return [
        ConfigResponse(key=config.key, value=mask_secret(config.key, config.value))
        for config in updated_configs
    ]


@router.get("/export/all")
async def export_configuration(db: AsyncSession = Depends(get_db)):
    """
    Export all configuration including settings and scoring rules

    A stored secret shows as the mask, which an import skips.

    Returns:
        JSON with all configuration data
    """
    result = await db.execute(select(Config))
    configs = result.scalars().all()
    config_dict = {
        config.key: mask_secret(config.key, config.value) for config in configs
    }

    result = await db.execute(select(ScoringRule))
    scoring_rules = result.scalars().all()
    rules_list = [
        {
            "rule_type": rule.rule_type.value,
            "pattern": rule.pattern,
            "score_modifier": rule.score_modifier,
            "enabled": rule.enabled,
            "description": rule.description,
        }
        for rule in scoring_rules
    ]

    export_data = {
        "version": "1.0",
        "config": config_dict,
        "scoring_rules": rules_list,
    }

    return JSONResponse(content=export_data)


@router.post("/import/all")
async def import_configuration(
    import_data: ConfigImport, db: AsyncSession = Depends(get_db)
):
    """
    Import configuration from exported JSON

    Secrets are stored encrypted. An export made before they were encrypted
    holds them signed or as typed; a current one holds the mask instead, which
    keeps the stored secret.

    Args:
        import_data: Configuration data to import

    Returns:
        Import summary
    """
    imported_configs = 0
    imported_rules = 0
    skipped_configs = 0
    skipped_rules = 0

    for key, value in import_data.config.items():
        # An old export can also hold what a failed connection test left behind
        if is_masked(key, value) or key in LEFTOVER_TEST_KEYS:
            skipped_configs += 1
            continue
        value = encrypt_if_sensitive(key, value)

        result = await db.execute(select(Config).where(Config.key == key))
        existing_config = result.scalar_one_or_none()

        if existing_config:
            if import_data.overwrite_existing:
                existing_config.value = value
                imported_configs += 1
            else:
                skipped_configs += 1
        else:
            new_config = Config(key=key, value=value)
            db.add(new_config)
            imported_configs += 1

    if import_data.scoring_rules:
        for rule_data in import_data.scoring_rules:
            from app.models.scoring_rule import RuleType

            try:
                rule_type = RuleType(rule_data.get("rule_type"))
            except ValueError:
                skipped_rules += 1
                continue

            result = await db.execute(
                select(ScoringRule).where(
                    ScoringRule.rule_type == rule_type,
                    ScoringRule.pattern == rule_data.get("pattern"),
                )
            )
            existing_rule = result.scalar_one_or_none()

            if existing_rule:
                if import_data.overwrite_existing:
                    existing_rule.score_modifier = rule_data.get("score_modifier", 0)
                    existing_rule.enabled = rule_data.get("enabled", True)
                    existing_rule.description = rule_data.get("description")
                    imported_rules += 1
                else:
                    skipped_rules += 1
            else:
                new_rule = ScoringRule(
                    rule_type=rule_type,
                    pattern=rule_data.get("pattern"),
                    score_modifier=rule_data.get("score_modifier", 0),
                    enabled=rule_data.get("enabled", True),
                    description=rule_data.get("description"),
                )
                db.add(new_rule)
                imported_rules += 1

    await db.commit()

    return {
        "status": "success",
        "imported": {
            "configs": imported_configs,
            "scoring_rules": imported_rules,
        },
        "skipped": {
            "configs": skipped_configs,
            "scoring_rules": skipped_rules,
        },
    }
