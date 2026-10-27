"""
Scan runner.

Finds duplicates across every configured media server and records them, so the
scan API route and the scheduler share one implementation.
"""

import logging
from dataclasses import dataclass
from typing import List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import DuplicateSet, ScoringRule
from app.models.duplicate import DuplicateStatus, MediaType
from app.services.arr.quality import ArrQualityRanker
from app.services.media_server import (
    DuplicateGroup,
    MediaServerError,
    get_media_servers,
)
from app.services.scan.helpers import (
    cleanup_stale_set,
    create_duplicate_set,
    validate_duplicate_files,
    verify_and_update_existing_set,
)
from app.services.scan.orchestrator import ScanOrchestrator
from app.services.scan.scoring_engine import ScoringEngine

logger = logging.getLogger(__name__)


@dataclass
class ScanTotals:
    """What a scan did, summed over every server and library."""

    duplicates_found: int = 0
    sets_created: int = 0
    sets_updated: int = 0
    sets_removed: int = 0


async def get_custom_scoring_rules(db: AsyncSession) -> List[dict]:
    """Enabled custom scoring rules, in the shape the scoring engine wants."""
    result = await db.execute(select(ScoringRule).where(ScoringRule.enabled))
    return [
        {
            "pattern": rule.pattern,
            "score_modifier": rule.score_modifier,
            "rule_type": rule.rule_type.value,
        }
        for rule in result.scalars().all()
    ]


async def run_scan(db: AsyncSession, library_names: List[str]) -> ScanTotals:
    """
    Scan the named libraries on every configured media server.

    A library name is looked up per server, so an instance running both Plex
    and Jellyfin over the same media covers both without the caller choosing.
    Sets are keyed per server, so each one's view is kept separately.
    """
    scoring_engine = ScoringEngine()
    custom_rules = await get_custom_scoring_rules(db)
    totals = ScanTotals()
    wanted = set(library_names)

    for server in await get_media_servers(db):
        orchestrator = ScanOrchestrator(server, db)

        try:
            libraries = await server.get_libraries()
        except MediaServerError as e:
            logger.error(f"Skipping {server.type.value}: {e}")
            continue

        for library in libraries:
            if library["title"] not in wanted:
                continue

            scan = {
                "movie": (orchestrator.scan_movies, MediaType.MOVIE),
                "show": (orchestrator.scan_episodes, MediaType.EPISODE),
            }.get(library["type"])

            if scan is None:
                logger.warning(
                    f"Unsupported library type '{library['type']}' for "
                    f"'{library['title']}' - skipping"
                )
                continue

            find, media_type = scan
            try:
                groups = await find(library["title"])
            except Exception as e:
                logger.error(
                    f"Could not scan '{library['title']}' on "
                    f"{server.type.value}: {e}",
                    exc_info=True,
                )
                continue

            await _cleanup_stale_duplicate_sets(
                db, groups, media_type, server.type.value
            )
            created, updated, removed = await _process_duplicate_groups(
                db, groups, media_type, server.type.value, scoring_engine, custom_rules
            )

            totals.duplicates_found += sum(len(group.files) for group in groups)
            totals.sets_created += created
            totals.sets_updated += updated
            totals.sets_removed += removed

    return totals


async def _cleanup_stale_duplicate_sets(
    db: AsyncSession,
    groups: List[DuplicateGroup],
    media_type: MediaType,
    media_server: str,
) -> int:
    """
    Drop pending sets this server no longer reports as duplicates.

    That happens when files are removed outside Deduparr, or when the server
    stops considering them duplicates after a manual split. Only PENDING sets
    go: approved, rejected and processed ones are a record of a decision.

    Scoped to one server, so a set found by Plex is not discarded because
    Jellyfin has not been scanned yet.
    """
    result = await db.execute(
        select(DuplicateSet)
        .options(selectinload(DuplicateSet.files))
        .where(
            DuplicateSet.media_type == media_type,
            DuplicateSet.media_server == media_server,
            DuplicateSet.status == DuplicateStatus.PENDING,
        )
    )
    db_sets = result.scalars().all()
    current_ids = {group.item_id for group in groups}

    cleaned = 0
    for db_set in db_sets:
        if db_set.item_id not in current_ids:
            logger.info(
                f"Cleaning up stale PENDING duplicate set: {db_set.title} "
                f"(item_id={db_set.item_id} on {media_server})"
            )
            await db.delete(db_set)
            cleaned += 1

    if cleaned:
        await db.flush()
        logger.info(
            f"Cleaned up {cleaned} stale PENDING duplicate set(s) for "
            f"{media_type.value} on {media_server}"
        )

    return cleaned


async def _process_duplicate_groups(
    db: AsyncSession,
    groups: List[DuplicateGroup],
    media_type: MediaType,
    media_server: str,
    scoring_engine: ScoringEngine,
    custom_rules: List[dict],
) -> Tuple[int, int, int]:
    """
    Store duplicate groups, creating new sets and refreshing existing ones.

    Returns:
        tuple[int, int, int]: (sets_created, sets_updated, sets_removed)
    """
    arr_ranker = await ArrQualityRanker.from_config(db)
    sets_created = 0
    sets_updated = 0
    sets_removed = 0

    for group in groups:
        existing = await db.execute(
            select(DuplicateSet)
            .options(selectinload(DuplicateSet.files))
            .where(
                DuplicateSet.item_id == group.item_id,
                DuplicateSet.media_server == media_server,
                DuplicateSet.media_type == media_type,
            )
        )
        existing_set = existing.scalar_one_or_none()

        validation_error = validate_duplicate_files(group.files, group.title, logger)
        if validation_error:
            logger.info(f"Skipping '{group.title}' - {validation_error.lower()}")
            await cleanup_stale_set(db, existing_set, validation_error, logger)
            if existing_set:
                sets_removed += 1
            continue

        if existing_set:
            set_valid, files_removed = await verify_and_update_existing_set(
                db,
                existing_set,
                group.files,
                scoring_engine,
                custom_rules,
                logger,
                arr_ranker,
            )
            if not set_valid:
                sets_removed += 1
            elif files_removed:
                sets_updated += 1
                logger.info(
                    f"Updated duplicate set '{group.title}' "
                    f"(removed {files_removed} stale file(s))"
                )
            continue

        await create_duplicate_set(
            db,
            media_server,
            group.item_id,
            group.title,
            media_type,
            group.files,
            scoring_engine,
            custom_rules,
            logger,
            arr_ranker,
        )
        sets_created += 1

    return sets_created, sets_updated, sets_removed
