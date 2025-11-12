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
