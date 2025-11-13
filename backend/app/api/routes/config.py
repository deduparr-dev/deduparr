"""
Configuration API endpoints
"""

from typing import Dict, List, Optional
from typing_extensions import TypedDict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models import Config
from app.models.scoring_rule import ScoringRule


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


@router.get("/", response_model=Dict[str, Optional[str]])
async def get_all_config(db: AsyncSession = Depends(get_db)):
    """
    Get all configuration settings as a key-value dictionary
    """
    result = await db.execute(select(Config))
    configs = result.scalars().all()
    return {config.key: config.value for config in configs}


@router.get("/deep-scan", response_model=DeepScanResponse)
async def get_deep_scan_setting(db: AsyncSession = Depends(get_db)):
    """
    Get the deep scan setting (filesystem-based duplicate detection)

    Returns:
        enabled: True if deep scan is enabled, False otherwise (default)
    """
    result = await db.execute(select(Config).where(Config.key == "enable_deep_scan"))
    config = result.scalar_one_or_none()

    enabled = config.value == "true" if config else False

    return DeepScanResponse(enabled=enabled)


@router.put("/deep-scan", response_model=DeepScanResponse)
async def update_deep_scan_setting(
    update: DeepScanUpdate, db: AsyncSession = Depends(get_db)
):
    """
    Update the deep scan setting

    Deep scan enables filesystem-based duplicate detection in addition to
    Plex API detection. This is slower but finds duplicates Plex might miss
    (e.g., case-sensitivity differences, cross-directory duplicates).

    Args:
        update: Deep scan setting update

    Returns:
        enabled: Updated deep scan status
    """
    result = await db.execute(select(Config).where(Config.key == "enable_deep_scan"))
    config = result.scalar_one_or_none()

    value = "true" if update.enabled else "false"

    if config:
        config.value = value
    else:
        config = Config(key="enable_deep_scan", value=value)
        db.add(config)

    await db.commit()
    await db.refresh(config)

    return DeepScanResponse(enabled=update.enabled)


# Scheduler configuration endpoints (must come before /{key} catch-all route)
@router.get("/scheduler")
async def get_scheduler_config(db: AsyncSession = Depends(get_db)):
    """Get scheduler configuration settings"""
    result = await db.execute(
        select(Config).where(
            Config.key.in_(
                [
                    "enable_scheduled_scans",
                    "scan_schedule_mode",
                    "scheduled_scan_time",
                    "scan_interval_hours",
                    "enable_scheduled_deletion",
                    "deletion_schedule_mode",
                    "scheduled_deletion_time",
                    "deletion_interval_hours",
                ]
            )
        )
    )
    configs = {item.key: item.value for item in result.scalars().all()}

    return {
        "enable_scheduled_scans": configs.get("enable_scheduled_scans", "false")
        == "true",
        "scan_schedule_mode": configs.get("scan_schedule_mode", "daily"),
        "scheduled_scan_time": configs.get("scheduled_scan_time", "02:00"),
        "scan_interval_hours": int(configs.get("scan_interval_hours", "24")),
        "enable_scheduled_deletion": configs.get("enable_scheduled_deletion", "false")
        == "true",
        "deletion_schedule_mode": configs.get("deletion_schedule_mode", "daily"),
        "scheduled_deletion_time": configs.get("scheduled_deletion_time", "02:30"),
        "deletion_interval_hours": int(configs.get("deletion_interval_hours", "24")),
    }


class SchedulerConfigUpdate(BaseModel):
    """Request model for updating scheduler configuration"""

    enable_scheduled_scans: Optional[bool] = None
    scan_schedule_mode: Optional[str] = None
    scheduled_scan_time: Optional[str] = None
    scan_interval_hours: Optional[int] = None
    enable_scheduled_deletion: Optional[bool] = None
    deletion_schedule_mode: Optional[str] = None
    scheduled_deletion_time: Optional[str] = None
    deletion_interval_hours: Optional[int] = None


@router.post("/scheduler")
async def update_scheduler_config(
    config: SchedulerConfigUpdate, db: AsyncSession = Depends(get_db)
):
    """Update scheduler configuration and restart scheduler if needed"""
    import re

    updates = {}

    if config.enable_scheduled_scans is not None:
        updates["enable_scheduled_scans"] = (
            "true" if config.enable_scheduled_scans else "false"
        )

    if config.scan_schedule_mode is not None:
        if config.scan_schedule_mode not in ["daily", "interval"]:
            raise HTTPException(
                status_code=400,
                detail="Scan schedule mode must be 'daily' or 'interval'",
            )
        updates["scan_schedule_mode"] = config.scan_schedule_mode

    if config.scheduled_scan_time is not None:
        # Validate time format (HH:MM)
        if not re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", config.scheduled_scan_time):
            raise HTTPException(
                status_code=400,
                detail="Scan time must be in HH:MM format (00:00 - 23:59)",
            )
        updates["scheduled_scan_time"] = config.scheduled_scan_time

    if config.scan_interval_hours is not None:
        if not (1 <= config.scan_interval_hours <= 168):
            raise HTTPException(
                status_code=400, detail="Scan interval must be between 1 and 168 hours"
            )
        updates["scan_interval_hours"] = str(config.scan_interval_hours)

    if config.enable_scheduled_deletion is not None:
        updates["enable_scheduled_deletion"] = (
            "true" if config.enable_scheduled_deletion else "false"
        )

    if config.deletion_schedule_mode is not None:
        if config.deletion_schedule_mode not in ["daily", "interval"]:
            raise HTTPException(
                status_code=400,
                detail="Deletion schedule mode must be 'daily' or 'interval'",
            )
        updates["deletion_schedule_mode"] = config.deletion_schedule_mode

    if config.scheduled_deletion_time is not None:
        # Validate time format (HH:MM)
        if not re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", config.scheduled_deletion_time):
            raise HTTPException(
                status_code=400,
                detail="Deletion time must be in HH:MM format (00:00 - 23:59)",
            )
        updates["scheduled_deletion_time"] = config.scheduled_deletion_time

    if config.deletion_interval_hours is not None:
        if not (1 <= config.deletion_interval_hours <= 168):
            raise HTTPException(
                status_code=400,
                detail="Deletion interval must be between 1 and 168 hours",
            )
        updates["deletion_interval_hours"] = str(config.deletion_interval_hours)

    # Update database
    for key, value in updates.items():
        result = await db.execute(select(Config).where(Config.key == key))
        config_item = result.scalar_one_or_none()

        if config_item:
            config_item.value = value
        else:
            db.add(Config(key=key, value=value))

    await db.commit()

    # Restart scheduler with new settings
    from app.services.scheduler import get_scheduler

    scheduler = get_scheduler()
    # Stop scheduler if running. Catch RuntimeError which can occur in tests
    # if the event loop is already closed (defensive; scheduler is optional).
    try:
        await scheduler.stop()
    except RuntimeError:
        # Don't fail the request if the loop is closed in the test harness.
        import logging

        logging.getLogger(__name__).warning(
            "Scheduler stop raised RuntimeError (loop closed); continuing"
        )

    # Get updated config values
    result = await db.execute(
        select(Config).where(
            Config.key.in_(
                [
                    "enable_scheduled_scans",
                    "scan_schedule_mode",
                    "scheduled_scan_time",
                    "scan_interval_hours",
                    "deletion_schedule_mode",
                    "scheduled_deletion_time",
                    "deletion_interval_hours",
                ]
            )
        )
    )
    configs = {item.key: item.value for item in result.scalars().all()}

    enable_scans = configs.get("enable_scheduled_scans", "false") == "true"
    scan_mode = configs.get("scan_schedule_mode", "daily")
    scan_time = configs.get("scheduled_scan_time", "02:00")
    scan_interval_hours = int(configs.get("scan_interval_hours", "24"))
    deletion_mode = configs.get("deletion_schedule_mode", "daily")
    deletion_time = configs.get("scheduled_deletion_time", "02:30")
    deletion_interval_hours = int(configs.get("deletion_interval_hours", "24"))

    if enable_scans:
        await scheduler.start(
            scan_mode=scan_mode,
            scan_time=scan_time,
            scan_interval_hours=scan_interval_hours,
            deletion_mode=deletion_mode,
            deletion_time=deletion_time,
            deletion_interval_hours=deletion_interval_hours,
        )

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

    return config


@router.put("/{key}", response_model=ConfigResponse)
async def update_config(
    key: str, config_update: ConfigUpdate, db: AsyncSession = Depends(get_db)
):
    """
    Update or create a configuration value
    """
    result = await db.execute(select(Config).where(Config.key == key))
    config = result.scalar_one_or_none()

    if config:
        config.value = config_update.value
    else:
        config = Config(key=key, value=config_update.value)
        db.add(config)

    await db.commit()
    await db.refresh(config)
    return config


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
        result = await db.execute(select(Config).where(Config.key == key))
        config = result.scalar_one_or_none()

        if config:
            config.value = value
        else:
            config = Config(key=key, value=value)
            db.add(config)

        updated_configs.append(config)

    await db.commit()

    for config in updated_configs:
        await db.refresh(config)

    return updated_configs


@router.get("/export/all")
async def export_configuration(db: AsyncSession = Depends(get_db)):
    """
    Export all configuration including settings and scoring rules

    Returns:
        JSON with all configuration data
    """
    result = await db.execute(select(Config))
    configs = result.scalars().all()
    config_dict = {config.key: config.value for config in configs}

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
