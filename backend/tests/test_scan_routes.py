"""
Tests for scan API routes
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.routes.scan import get_configured_media_servers
from app.services.media_server import (
    DuplicateGroup,
    MediaServerType,
    selected_libraries,
)
from app.services.scan.runner import (
    ScanTotals,
    _process_duplicate_groups,
    get_custom_scoring_rules,
)
from app.services.scan.scoring_engine import MediaMetadata, ScoringEngine
from app.models import Config, ScoringRule, DuplicateSet, DuplicateFile
from app.models.duplicate import DuplicateStatus, MediaType


@pytest.mark.asyncio
async def test_get_configured_media_servers_requires_setup(test_db):
    """Scanning refuses with a 400 until some media server has credentials."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await get_configured_media_servers(test_db)

    assert exc_info.value.status_code == 400
    assert "No media server configured" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_get_configured_media_servers_returns_every_one(test_db):
    """Plex and Jellyfin can be set up at the same time, and both come back."""
    test_db.add_all(
        [
            Config(key="plex_auth_token", value="token"),
            Config(key="jellyfin_url", value="http://jellyfin:8096"),
            Config(key="jellyfin_api_key", value="key"),
        ]
    )
    await test_db.commit()

    servers = await get_configured_media_servers(test_db)

    assert {server.type for server in servers} == {
        MediaServerType.PLEX,
        MediaServerType.JELLYFIN,
    }


@pytest.mark.asyncio
async def test_get_custom_scoring_rules_empty(test_db):
    """Test getting custom scoring rules when none exist"""
    rules = await get_custom_scoring_rules(test_db)
    assert rules == []


@pytest.mark.asyncio
async def test_get_custom_scoring_rules(test_db):
    """Test getting enabled custom scoring rules"""
    from app.models.scoring_rule import RuleType

    # Add some scoring rules
    rule1 = ScoringRule(
        rule_type=RuleType.FILENAME_PATTERN,
        pattern=r"remux",
        score_modifier=10000,
        enabled=True,
        description="Prefer remux",
    )
    rule2 = ScoringRule(
        rule_type=RuleType.FILENAME_PATTERN,
        pattern=r"hdtv",
        score_modifier=-5000,
        enabled=True,
        description="Avoid HDTV",
    )
    rule3 = ScoringRule(
        rule_type=RuleType.FILENAME_PATTERN,
        pattern=r"disabled",
        score_modifier=99999,
        enabled=False,
        description="This should not appear",
    )

    test_db.add(rule1)
    test_db.add(rule2)
    test_db.add(rule3)
    await test_db.commit()

    rules = await get_custom_scoring_rules(test_db)

    assert len(rules) == 2
    assert rules[0]["pattern"] == r"remux"
    assert rules[0]["score_modifier"] == 10000
    assert rules[1]["pattern"] == r"hdtv"
    assert rules[1]["score_modifier"] == -5000


@pytest.mark.asyncio
async def test_process_duplicate_groups_keeps_the_best_file(test_db):
    """A group becomes a set, with only the highest scoring file kept."""
    groups = [
        DuplicateGroup(
            item_id="12345",
            title="Test Movie",
            files=[
                MediaMetadata(
                    file_path="/movies/TestMovie.720p.mkv",
                    file_size=2 * 1024**3,
                    resolution="720p",
                    video_codec="h264",
                    inode=12345,
                ),
                MediaMetadata(
                    file_path="/movies/TestMovie.1080p.mkv",
                    file_size=8 * 1024**3,
                    resolution="1080p",
                    video_codec="hevc",
                    inode=67890,
                ),
            ],
        )
    ]

    created, updated, removed = await _process_duplicate_groups(
        test_db, groups, MediaType.MOVIE, "plex", ScoringEngine(), []
    )

    assert (created, updated, removed) == (1, 0, 0)

    result = await test_db.execute(
        select(DuplicateSet).options(selectinload(DuplicateSet.files))
    )
    dup_set = result.scalars().one()
    assert dup_set.title == "Test Movie"
    assert dup_set.item_id == "12345"
    assert dup_set.media_server == "plex"

    kept = [f for f in dup_set.files if f.keep]
    assert len(kept) == 1
    assert kept[0].file_path.endswith("1080p.mkv")
    assert dup_set.space_to_reclaim == 2 * 1024**3


@pytest.mark.asyncio
async def test_process_duplicate_groups_separates_servers(test_db):
    """Item ids are per server, so the same id on two servers is two sets."""
    files = [
        MediaMetadata(
            file_path="/movies/a.mkv", file_size=10, resolution="1080p", inode=1
        ),
        MediaMetadata(
            file_path="/movies/b.mkv", file_size=5, resolution="720p", inode=2
        ),
    ]
    group = [DuplicateGroup(item_id="same-id", title="Shared Movie", files=files)]

    for server in ("plex", "jellyfin"):
        created, _, _ = await _process_duplicate_groups(
            test_db, group, MediaType.MOVIE, server, ScoringEngine(), []
        )
        assert created == 1

    result = await test_db.execute(select(DuplicateSet))
    assert sorted(s.media_server for s in result.scalars().all()) == [
        "jellyfin",
        "plex",
    ]


@pytest.mark.asyncio
async def test_process_duplicate_groups_skips_an_unchanged_set(test_db):
    """Re-scanning the same group neither duplicates nor updates it."""
    group = [
        DuplicateGroup(
            item_id="12345",
            title="Test Movie",
            files=[
                MediaMetadata(
                    file_path="/movies/a.mkv", file_size=10, resolution="1080p", inode=1
                ),
                MediaMetadata(
                    file_path="/movies/b.mkv", file_size=5, resolution="720p", inode=2
                ),
            ],
        )
    ]
    engine = ScoringEngine()

    first = await _process_duplicate_groups(
        test_db, group, MediaType.MOVIE, "plex", engine, []
    )
    second = await _process_duplicate_groups(
        test_db, group, MediaType.MOVIE, "plex", engine, []
    )

    assert first == (1, 0, 0)
    assert second == (0, 0, 0)

    result = await test_db.execute(select(func.count(DuplicateSet.id)))
    assert result.scalar() == 1


@pytest.mark.asyncio
async def test_scan_status_endpoint(client, test_db):
    """Test scan status endpoint"""
    # Create some test duplicate sets
    set1 = DuplicateSet(
        item_id="1",
        title="Movie 1",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.PENDING,
        space_to_reclaim=5 * 1024**3,
    )
    set2 = DuplicateSet(
        item_id="2",
        title="Movie 2",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.PROCESSED,
        space_to_reclaim=3 * 1024**3,
    )
    test_db.add(set1)
    test_db.add(set2)
    await test_db.flush()
    test_db.add_all(
        [
            DuplicateFile(set_id=set1.id, file_path="/m/a.mkv", file_size=1, keep=True),
            DuplicateFile(set_id=set1.id, file_path="/m/b.mkv", file_size=1),
            DuplicateFile(set_id=set2.id, file_path="/m/c.mkv", file_size=1),
        ]
    )
    await test_db.commit()

    response = await client.get("/api/scan/status")
    assert response.status_code == 200

    data = response.json()
    assert data["total_duplicate_sets"] == 2
    assert data["pending_sets"] == 1
    # Delete All removes the pending set's file not marked to keep, and no other
    assert data["sets_to_delete"] == 1
    assert data["pending_files_to_delete"] == 1
    # What the pending sets would delete, not the PROCESSED set's file
    assert data["total_space_reclaimable"] == 1


@pytest.mark.asyncio
async def test_scan_status_counts_a_file_both_servers_list_once(client, test_db):
    """Plex and Jellyfin list the same file as two sets; it is deleted once."""
    plex, jellyfin, all_kept = (
        DuplicateSet(
            item_id=item_id,
            title="Movie",
            media_type=MediaType.MOVIE,
            media_server=server,
            status=DuplicateStatus.PENDING,
        )
        for item_id, server in (("1", "plex"), ("a", "jellyfin"), ("2", "plex"))
    )
    test_db.add_all([plex, jellyfin, all_kept])
    await test_db.flush()
    test_db.add_all(
        [
            DuplicateFile(set_id=plex.id, file_path="/m/720p.mkv", file_size=10),
            DuplicateFile(set_id=jellyfin.id, file_path="/m/720p.mkv", file_size=10),
            DuplicateFile(
                set_id=all_kept.id, file_path="/m/k.mkv", file_size=5, keep=True
            ),
        ]
    )
    await test_db.commit()

    data = (await client.get("/api/scan/status")).json()

    assert data["pending_sets"] == 3
    assert data["sets_to_delete"] == 2
    assert data["pending_files_to_delete"] == 1
    assert data["total_space_reclaimable"] == 10


@pytest.mark.asyncio
async def test_delete_all_reports_what_it_could_not_do(client, test_db, tmp_path):
    """A note on a set, such as a service not configured, reaches the result."""
    keep, drop = tmp_path / "keep.mkv", tmp_path / "drop.mkv"
    keep.write_bytes(b"k")
    drop.write_bytes(b"d")
    dup_set = DuplicateSet(
        item_id="1",
        title="Movie",
        media_type=MediaType.MOVIE,
        media_server="disk",
        status=DuplicateStatus.PENDING,
    )
    test_db.add(dup_set)
    await test_db.flush()
    test_db.add_all(
        [
            DuplicateFile(
                set_id=dup_set.id, file_path=str(keep), file_size=1, keep=True
            ),
            DuplicateFile(set_id=dup_set.id, file_path=str(drop), file_size=1),
        ]
    )
    await test_db.commit()

    response = await client.post(
        "/api/scan/duplicates/delete-all", json={"dry_run": False}
    )

    data = response.json()
    assert data["success"] is True
    assert "Note: " in data["message"] and "not configured" in data["message"]
    assert not drop.exists()


@pytest.mark.asyncio
async def test_get_duplicates_endpoint(client, test_db, create_duplicate_set):
    """Test getting duplicates endpoint"""
    # Create test duplicate set with files
    dup_set = await create_duplicate_set(
        item_id="123",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.PENDING,
        space_to_reclaim=5 * 1024**3,
    )

    file1 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/test1.mkv",
        file_size=2 * 1024**3,
        score=10000,
        keep=False,
        file_metadata='{"resolution": "720p"}',
    )
    file2 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/test2.mkv",
        file_size=5 * 1024**3,
        score=20000,
        keep=True,
        file_metadata='{"resolution": "1080p"}',
    )
    test_db.add(file1)
    test_db.add(file2)
    await test_db.commit()

    response = await client.get("/api/scan/duplicates")
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Test Movie"
    assert data[0]["status"] == "pending"
    assert len(data[0]["files"]) == 2


@pytest.mark.asyncio
async def test_get_duplicates_filtered_by_status(client, test_db, create_duplicate_set):
    """Test filtering duplicates by status"""
    await create_duplicate_set(
        item_id="1", title="Pending", status=DuplicateStatus.PENDING
    )
    await create_duplicate_set(
        item_id="2", title="Processed", status=DuplicateStatus.PROCESSED
    )

    response = await client.get("/api/scan/duplicates?status=pending")
    assert response.status_code == 200
    assert response.headers["X-Total-Count"] == "1"

    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_get_duplicates_pages_through_every_set(client, create_duplicate_set):
    """Each set is on exactly one page, newest first, and the header counts all."""
    # Found in the same instant, as sets from one scan can be
    found_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ids = [
        (await create_duplicate_set(item_id=str(n), found_at=found_at)).id
        for n in range(5)
    ]

    pages = []
    for offset in (0, 2, 4):
        response = await client.get(f"/api/scan/duplicates?limit=2&offset={offset}")
        assert response.status_code == 200
        assert response.headers["X-Total-Count"] == "5"
        pages.append([dup_set["id"] for dup_set in response.json()])

    assert pages == [ids[4:2:-1], ids[2:0:-1], ids[:1]]


@pytest.mark.asyncio
async def test_get_duplicates_filtered_by_media_type(
    client, test_db, create_duplicate_set
):
    """Test filtering duplicates by media type"""
    await create_duplicate_set(item_id="1", title="Movie", media_type=MediaType.MOVIE)
    await create_duplicate_set(
        item_id="2", title="Episode", media_type=MediaType.EPISODE
    )

    response = await client.get("/api/scan/duplicates?media_type=movie")
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 1
    assert data[0]["media_type"] == "movie"


@pytest.mark.asyncio
async def test_start_scan_without_a_media_server(client, test_db):
    """The scan endpoint explains that setup has not been completed."""
    response = await client.post(
        "/api/scan/start", json={"libraries": {"plex": ["Movies"]}}
    )

    assert response.status_code == 400
    assert "No media server configured" in response.text


@pytest.mark.asyncio
async def test_start_scan_reports_what_the_run_did(client, test_db):
    """The endpoint reports the runner's totals."""
    test_db.add(Config(key="plex_auth_token", value="token"))
    await test_db.commit()

    totals = ScanTotals(
        duplicates_found=4, sets_created=2, sets_updated=1, sets_removed=0
    )
    with patch(
        "app.api.routes.scan.run_scan", new_callable=AsyncMock, return_value=totals
    ):
        response = await client.post("/api/scan/start", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["duplicates_found"] == 4
    assert body["sets_created"] == 2
    assert body["sets_updated"] == 1


@pytest.mark.asyncio
async def test_start_scan_says_what_it_skipped(client, test_db):
    """A scan that could not read everything does not report success."""
    test_db.add(Config(key="plex_auth_token", value="token"))
    await test_db.commit()

    totals = ScanTotals(skipped=["Plex: rejected"])
    with patch(
        "app.api.routes.scan.run_scan", new_callable=AsyncMock, return_value=totals
    ):
        response = await client.post("/api/scan/start", json={})

    body = response.json()
    assert body["success"] is False
    assert body["skipped"] == ["Plex: rejected"]


@pytest.mark.asyncio
async def test_start_scan_keeps_the_libraries_it_was_given(client, test_db):
    """
    The libraries a scan starts with become each server's stored selection,
    so a scheduled scan covers the same ground.
    """
    test_db.add_all(
        [
            Config(key="plex_auth_token", value="token"),
            Config(key="jellyfin_libraries", value="Films"),
        ]
    )
    await test_db.commit()

    with patch(
        "app.api.routes.scan.run_scan",
        new_callable=AsyncMock,
        return_value=ScanTotals(),
    ):
        response = await client.post(
            "/api/scan/start",
            json={"libraries": {"plex": ["Movies", "TV Shows"], "jellyfin": []}},
        )

    assert response.status_code == 200
    assert await selected_libraries(test_db, MediaServerType.PLEX) == [
        "Movies",
        "TV Shows",
    ]
    assert await selected_libraries(test_db, MediaServerType.JELLYFIN) == []


@pytest.mark.asyncio
async def test_scoring_picks_the_best_of_several_versions(test_db):
    """Across resolution, codec and bitrate the best file is the one kept."""
    groups = [
        DuplicateGroup(
            item_id="900",
            title="Quality Test",
            files=[
                MediaMetadata(
                    file_path="/movies/QualityTest.2160p.hevc.mkv",
                    file_size=20 * 1024**3,
                    resolution="2160p",
                    video_codec="hevc",
                    bitrate=40000,
                    width=3840,
                    height=2160,
                    inode=1,
                ),
                MediaMetadata(
                    file_path="/movies/QualityTest.1080p.h264.mkv",
                    file_size=8 * 1024**3,
                    resolution="1080p",
                    video_codec="h264",
                    bitrate=12000,
                    width=1920,
                    height=1080,
                    inode=2,
                ),
                MediaMetadata(
                    file_path="/movies/QualityTest.720p.h264.mkv",
                    file_size=2 * 1024**3,
                    resolution="720p",
                    video_codec="h264",
                    bitrate=4000,
                    width=1280,
                    height=720,
                    inode=3,
                ),
            ],
        )
    ]

    await _process_duplicate_groups(
        test_db, groups, MediaType.MOVIE, "plex", ScoringEngine(), []
    )

    result = await test_db.execute(
        select(DuplicateSet).options(selectinload(DuplicateSet.files))
    )
    dup_set = result.scalars().one()

    kept = [f for f in dup_set.files if f.keep]
    assert len(kept) == 1
    assert kept[0].file_path.endswith("2160p.hevc.mkv")
    assert kept[0].score == max(f.score for f in dup_set.files)
    assert dup_set.space_to_reclaim == 10 * 1024**3


@pytest.mark.asyncio
async def test_preview_deletion_endpoint(client, test_db, create_duplicate_set):
    """Test the deletion preview endpoint"""
    # Create a duplicate set with files
    dup_set = await create_duplicate_set(
        item_id="preview_test",
        title="Preview Test Movie",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.PENDING,
        space_to_reclaim=3 * 1024**3,
    )

    # Low quality file to delete
    file1 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/preview.720p.mkv",
        file_size=2 * 1024**3,
        score=10000,
        keep=False,
        file_metadata='{"resolution": "720p", "video_codec": "h264"}',
    )

    # High quality file to keep
    file2 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/preview.1080p.BluRay.mkv",
        file_size=8 * 1024**3,
        score=25000,
        keep=True,
        file_metadata='{"resolution": "1080p", "video_codec": "h264"}',
    )

    test_db.add(file1)
    test_db.add(file2)
    await test_db.commit()

    # Call preview endpoint
    response = await client.get(f"/api/scan/duplicates/{dup_set.id}/preview")
    assert response.status_code == 200

    data = response.json()

    # Verify response structure
    assert data["set_id"] == dup_set.id
    assert data["title"] == "Preview Test Movie"
    assert data["media_type"] == "movie"
    assert data["total_files"] == 2
    assert data["files_to_delete_count"] == 1

    # Verify files to keep
    assert len(data["files_to_keep"]) == 1
    assert "1080p" in data["files_to_keep"][0]["file_path"]
    assert data["files_to_keep"][0]["score"] == 25000

    # Verify files to delete
    assert len(data["files_to_delete"]) == 1
    assert "720p" in data["files_to_delete"][0]["file_path"]
    assert data["files_to_delete"][0]["score"] == 10000

    # Verify space calculations
    assert data["space_to_reclaim"] == 2 * 1024**3
    assert data["space_to_reclaim_mb"] == 2048.0
    assert data["space_to_reclaim_gb"] == 2.0


@pytest.mark.asyncio
async def test_delete_duplicate_set_dry_run(
    client, test_db, create_duplicate_set, create_duplicate_file, tmp_path
):
    """A dry run reports the deletion without deleting or closing the set"""
    drop, keep = tmp_path / "delete.720p.mkv", tmp_path / "delete.1080p.mkv"
    drop.write_bytes(b"d" * 3)
    keep.write_bytes(b"k" * 8)

    dup_set = await create_duplicate_set(title="Delete Test Movie")
    await create_duplicate_file(dup_set.id, file_path=str(drop), file_size=3)
    await create_duplicate_file(dup_set.id, file_path=str(keep), file_size=8, keep=True)

    response = await client.post(
        f"/api/scan/duplicates/{dup_set.id}/delete", json={"dry_run": True}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["dry_run"] is True
    assert data["files_deleted"] == 1
    assert data["space_reclaimed"] == 3
    assert "[DRY-RUN]" in data["message"]
    assert data["errors"] == []

    assert drop.exists()
    await test_db.refresh(dup_set)
    assert dup_set.status == DuplicateStatus.PENDING


@pytest.mark.asyncio
async def test_delete_reports_a_file_it_could_not_find(
    client, test_db, create_duplicate_set, create_duplicate_file
):
    """A file nothing removed is not reported deleted, and the set stays open"""
    dup_set = await create_duplicate_set(title="Ghost", media_server="disk")
    await create_duplicate_file(dup_set.id, file_path="/nowhere/Ghost.mkv", keep=True)
    await create_duplicate_file(dup_set.id, file_path="/nowhere/Ghost 720p.mkv")

    response = await client.post(
        f"/api/scan/duplicates/{dup_set.id}/delete", json={"dry_run": False}
    )

    data = response.json()
    assert data["success"] is False
    assert data["files_deleted"] == 0
    assert data["space_reclaimed"] == 0
    assert "none of the files to keep is on disk" in data["errors"][0]
    await test_db.refresh(dup_set)
    assert dup_set.status == DuplicateStatus.PENDING


@pytest.mark.asyncio
async def test_delete_duplicate_set_not_found(client, test_db):
    """Test deletion fails when duplicate set doesn't exist"""
    response = await client.post(
        "/api/scan/duplicates/99999/delete", json={"dry_run": True}
    )

    assert response.status_code == 404
    assert "not found" in response.text


@pytest.mark.asyncio
async def test_delete_already_processed_set(client, test_db, create_duplicate_set):
    """Test that deletion fails for already processed sets"""
    dup_set = await create_duplicate_set(
        item_id="processed_test",
        title="Already Processed",
        status=DuplicateStatus.PROCESSED,
    )

    response = await client.post(
        f"/api/scan/duplicates/{dup_set.id}/delete", json={"dry_run": True}
    )

    assert response.status_code == 400
    assert "already been processed" in response.text


@pytest.mark.asyncio
async def test_delete_no_files_marked_for_deletion(
    client, test_db, create_duplicate_set
):
    """Test deletion fails when all files are marked to keep"""
    dup_set = await create_duplicate_set(
        item_id="no_delete_test",
        title="No Deletion Needed",
        status=DuplicateStatus.PENDING,
    )

    # Both files marked to keep (shouldn't happen in reality)
    file1 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file1.mkv",
        file_size=5 * 1024**3,
        score=20000,
        keep=True,
    )
    file2 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file2.mkv",
        file_size=8 * 1024**3,
        score=25000,
        keep=True,
    )
    test_db.add(file1)
    test_db.add(file2)
    await test_db.commit()

    response = await client.post(
        f"/api/scan/duplicates/{dup_set.id}/delete", json={"dry_run": True}
    )

    assert response.status_code == 400
    assert "No files marked for deletion" in response.text


@pytest.mark.asyncio
async def test_update_file_keep_flag_success(client, test_db, create_duplicate_set):
    """Test successfully toggling a file's keep flag"""
    dup_set = await create_duplicate_set(
        item_id="toggle_test",
        title="Toggle Test",
        status=DuplicateStatus.PENDING,
    )

    # Add files - one keep, one delete
    file1 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file1.mkv",
        file_size=5 * 1024**3,
        score=25000,
        keep=True,
    )
    file2 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file2.mkv",
        file_size=3 * 1024**3,
        score=15000,
        keep=False,
    )
    test_db.add(file1)
    test_db.add(file2)
    await test_db.commit()

    # Toggle file2 to keep
    response = await client.patch(
        f"/api/scan/duplicates/{dup_set.id}/files/{file2.id}",
        json={"keep": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["file_id"] == file2.id
    assert data["keep"] is True
    assert data["space_to_reclaim"] == 0  # Both files now kept

    # Verify in database
    await test_db.refresh(file2)
    assert file2.keep is True


@pytest.mark.asyncio
async def test_update_file_keep_flag_reaches_the_other_server(client, test_db):
    """
    Plex and Jellyfin list the same files as two sets. A copy marked to keep on
    one was still deleted through the other.
    """
    plex, jellyfin = (
        DuplicateSet(
            item_id=item_id,
            title="Movie",
            media_type=MediaType.MOVIE,
            media_server=server,
            status=DuplicateStatus.PENDING,
        )
        for item_id, server in (("1", "plex"), ("a", "jellyfin"))
    )
    test_db.add_all([plex, jellyfin])
    await test_db.flush()
    plex_best, plex_other = None, None
    for dup_set in (plex, jellyfin):
        best = DuplicateFile(
            set_id=dup_set.id, file_path="/m/2160p.mkv", file_size=20, keep=True
        )
        other = DuplicateFile(set_id=dup_set.id, file_path="/m/1080p.mkv", file_size=10)
        test_db.add_all([best, other])
        plex_best, plex_other = plex_best or best, plex_other or other
    await test_db.flush()
    plex_id, jellyfin_id = plex.id, jellyfin.id
    toggles = ((plex_other.id, True), (plex_best.id, False))
    await test_db.commit()

    for file_id, keep in toggles:
        response = await client.patch(
            f"/api/scan/duplicates/{plex_id}/files/{file_id}", json={"keep": keep}
        )
        assert response.status_code == 200

    rows = await test_db.execute(
        select(DuplicateFile.file_path, DuplicateFile.keep).where(
            DuplicateFile.set_id == jellyfin_id
        )
    )
    assert dict(rows.all()) == {"/m/2160p.mkv": False, "/m/1080p.mkv": True}
    assert (
        await test_db.scalar(
            select(DuplicateSet.space_to_reclaim).where(DuplicateSet.id == jellyfin_id)
        )
        == 20
    )


@pytest.mark.asyncio
async def test_update_file_keep_flag_prevents_all_delete(
    client, test_db, create_duplicate_set
):
    """Test that we can't mark all files for deletion"""
    dup_set = await create_duplicate_set(
        item_id="prevent_all_delete",
        title="Prevent All Delete",
        status=DuplicateStatus.PENDING,
    )

    # Add files - one keep, one delete
    file1 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file1.mkv",
        file_size=5 * 1024**3,
        score=25000,
        keep=True,
    )
    file2 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file2.mkv",
        file_size=3 * 1024**3,
        score=15000,
        keep=False,
    )
    test_db.add(file1)
    test_db.add(file2)
    await test_db.commit()

    # Try to mark the only kept file for deletion
    response = await client.patch(
        f"/api/scan/duplicates/{dup_set.id}/files/{file1.id}",
        json={"keep": False},
    )

    assert response.status_code == 400
    assert "At least one file must be marked to keep" in response.text


@pytest.mark.asyncio
async def test_update_file_keep_flag_not_found(client, test_db, create_duplicate_set):
    """Test updating a non-existent file"""
    dup_set = await create_duplicate_set(
        item_id="not_found_test",
        title="Not Found Test",
        status=DuplicateStatus.PENDING,
    )

    response = await client.patch(
        f"/api/scan/duplicates/{dup_set.id}/files/99999",
        json={"keep": True},
    )

    assert response.status_code == 404
    assert "File 99999 not found" in response.text


@pytest.mark.asyncio
async def test_update_file_keep_flag_set_not_found(client, test_db):
    """Test updating a file in a non-existent set"""
    response = await client.patch(
        "/api/scan/duplicates/99999/files/1",
        json={"keep": True},
    )

    assert response.status_code == 404
    assert "Duplicate set 99999 not found" in response.text


@pytest.mark.asyncio
async def test_update_file_keep_flag_processed_set(
    client, test_db, create_duplicate_set
):
    """Test that we can't modify files in processed sets"""
    dup_set = await create_duplicate_set(
        item_id="processed_set",
        title="Processed Set",
        status=DuplicateStatus.PROCESSED,
    )

    file1 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file1.mkv",
        file_size=5 * 1024**3,
        score=25000,
        keep=True,
    )
    test_db.add(file1)
    await test_db.commit()

    response = await client.patch(
        f"/api/scan/duplicates/{dup_set.id}/files/{file1.id}",
        json={"keep": False},
    )

    assert response.status_code == 400
    assert "Cannot modify files in a processed duplicate set" in response.text


@pytest.mark.asyncio
async def test_update_file_keep_recalculates_space(
    client, test_db, create_duplicate_set
):
    """Test that space_to_reclaim is recalculated correctly"""
    dup_set = await create_duplicate_set(
        item_id="space_test",
        title="Space Calculation Test",
        status=DuplicateStatus.PENDING,
    )

    # Add 3 files
    file1 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file1.mkv",
        file_size=5 * 1024**3,  # 5 GB
        score=25000,
        keep=True,
    )
    file2 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file2.mkv",
        file_size=3 * 1024**3,  # 3 GB
        score=15000,
        keep=False,
    )
    file3 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/file3.mkv",
        file_size=2 * 1024**3,  # 2 GB
        score=10000,
        keep=False,
    )
    test_db.add_all([file1, file2, file3])
    await test_db.commit()

    # Toggle file2 to keep
    response = await client.patch(
        f"/api/scan/duplicates/{dup_set.id}/files/{file2.id}",
        json={"keep": True},
    )

    assert response.status_code == 200
    data = response.json()
    # Now only file3 (2 GB) should be reclaimable
    assert data["space_to_reclaim"] == file3.file_size


@pytest.mark.asyncio
async def test_delete_all_nothing_pending(client):
    """Delete-all succeeds with zero counts when there is nothing pending"""
    response = await client.post(
        "/api/scan/duplicates/delete-all", json={"dry_run": True}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["sets_processed"] == 0
    assert data["files_deleted"] == 0


@pytest.mark.asyncio
async def test_delete_all_dry_run_spans_every_pending_set(client, test_db, tmp_path):
    """Delete-all covers every pending set at once and keeps dry runs harmless"""
    for n in (1, 2):
        dup_set = DuplicateSet(
            item_id=f"item-{n}",
            title=f"Movie {n}",
            media_type=MediaType.MOVIE,
            status=DuplicateStatus.PENDING,
        )
        test_db.add(dup_set)
        await test_db.flush()
        drop = tmp_path / f"drop{n}.mkv"
        drop.write_bytes(b"d" * 1024)
        (tmp_path / f"keep{n}.mkv").write_bytes(b"k" * 1024)
        test_db.add_all(
            [
                DuplicateFile(
                    set_id=dup_set.id,
                    file_path=str(tmp_path / f"keep{n}.mkv"),
                    file_size=2048,
                    score=90,
                    keep=True,
                ),
                DuplicateFile(
                    set_id=dup_set.id,
                    file_path=str(drop),
                    file_size=1024,
                    score=10,
                    keep=False,
                ),
            ]
        )
    await test_db.commit()

    response = await client.post(
        "/api/scan/duplicates/delete-all", json={"dry_run": True}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert data["sets_processed"] == 2
    assert data["files_deleted"] == 2
    assert "[DRY-RUN]" in data["message"]

    # Nothing removed, nothing marked processed
    assert (tmp_path / "drop1.mkv").exists()
    statuses = (await test_db.execute(select(DuplicateSet.status))).scalars().all()
    assert all(s == DuplicateStatus.PENDING for s in statuses)
