"""
Scan runner.

Finds duplicates across every configured media server and records them, so the
scan API route and the scheduler share one implementation.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import DuplicateSet, ScoringRule
from app.models.duplicate import DuplicateStatus, MediaType
from app.services.arr.quality import ArrQualityRanker
from app.services.media_server import (
    DuplicateGroup,
    MediaServerType,
    get_media_servers,
    selected_libraries,
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

# Sets are only committed once a scan has read every library and stored every
# group, so a second scan started meanwhile cannot see them and creates its own
# set for each item it reaches first, which later scans then fail on.
_scan_lock = asyncio.Lock()


ALREADY_RUNNING = "A scan is already running"


@dataclass
class ScanTotals:
    """What a scan did, summed over every server and library."""

    duplicates_found: int = 0
    sets_created: int = 0
    sets_updated: int = 0
    sets_removed: int = 0
    # What was actually scanned, which is not the caller's request when the
    # stored per-server selection is used.
    libraries_scanned: List[str] = field(default_factory=list)
    # The servers and libraries that could not be read, and why.
    skipped: List[str] = field(default_factory=list)


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


async def run_scan(db: AsyncSession) -> ScanTotals:
    """
    Scan every configured media server over the libraries chosen for it.

    Each server has its own stored selection, so an instance running both Plex
    and Jellyfin scans only what was chosen for each. Sets are keyed per
    server, so each one's view is kept separately.

    One scan runs at a time: a request made while another is running is
    answered at once, with the reason in ``skipped``, instead of starting a
    second pass over the same items.
    """
    if _scan_lock.locked():
        logger.warning("A scan is already running - not starting another")
        return ScanTotals(skipped=[ALREADY_RUNNING])

    async with _scan_lock:
        return await _scan_every_server(db)


async def _scan_every_server(db: AsyncSession) -> ScanTotals:
    """Scan every configured media server; ``run_scan`` makes sure only one does."""
    scoring_engine = ScoringEngine()
    custom_rules = await get_custom_scoring_rules(db)
    totals = ScanTotals()
    servers = await get_media_servers(db)

    for server_type in set(MediaServerType) - {server.type for server in servers}:
        totals.sets_removed += await drop_pending_sets(db, server_type)

    for server in servers:
        name = server.type.value
        wanted = set(await selected_libraries(db, server.type))
        if not wanted:
            logger.info(f"No libraries selected for {name} - skipping")
            continue

        orchestrator = ScanOrchestrator(server, db)

        try:
            libraries = await server.get_libraries()
        except Exception as e:
            # Any failure here is specific to this server - unreachable, bad
            # credentials, an SDK error - and must not abandon the others.
            logger.error(f"Skipping {name}: {e}")
            totals.skipped.append(f"{name.title()}: {e}")
            continue

        # A set belongs to a server and a type, not to a library, so what is
        # stale only shows once every library of that type has been read.
        found: Dict[MediaType, List[DuplicateGroup]] = {}
        unread: Set[MediaType] = set()

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
                    f"Could not scan '{library['title']}' on {name}: {e}",
                    exc_info=True,
                )
                totals.skipped.append(f"{name.title()} '{library['title']}': {e}")
                unread.add(media_type)
                continue

            found.setdefault(media_type, []).extend(groups)
            totals.libraries_scanned.append(library["title"])
            totals.duplicates_found += sum(len(group.files) for group in groups)

        for media_type, groups in found.items():
            if media_type not in unread:
                totals.sets_removed += await _cleanup_stale_duplicate_sets(
                    db, groups, media_type, name
                )
            created, updated, removed = await _process_duplicate_groups(
                db, groups, media_type, name, scoring_engine, custom_rules
            )
            totals.sets_created += created
            totals.sets_updated += updated
            totals.sets_removed += removed

    # Committed here so every caller persists what it found; leaving it to them
    # meant an API scan could report sets it never saved.
    await db.commit()
    return totals


async def drop_pending_sets(db: AsyncSession, server_type: MediaServerType) -> int:
    """Drop the pending sets of a server that can no longer report on them."""
    dropped = 0
    for media_type in MediaType:
        dropped += await _cleanup_stale_duplicate_sets(
            db, [], media_type, server_type.value
        )
    return dropped


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
                # A processed set records an earlier deletion; the item being
                # reported again is a new duplicate to review.
                DuplicateSet.status != DuplicateStatus.PROCESSED,
            )
            .order_by(DuplicateSet.id)
        )
        existing_sets = existing.scalars().all()
        existing_set = existing_sets[0] if existing_sets else None

        # Scans that overlapped, on an install from before they were serialised,
        # left several sets for one item, and a lookup for "the" set then raised
        # on every later scan. Keep the oldest and drop the pending others; a
        # decided set is a record, so it stays.
        for extra in existing_sets[1:]:
            if extra.status == DuplicateStatus.PENDING:
                logger.warning(
                    f"Removing duplicate set {extra.id} of '{group.title}': "
                    f"set {existing_set.id} already covers the item"
                )
                await db.delete(extra)
                sets_removed += 1

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
