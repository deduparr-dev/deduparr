"""
Tests for scan API routes
"""

import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.routes.scan import get_configured_media_servers
from app.services.media_server import DuplicateGroup, MediaServerType
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
    await test_db.commit()

    response = await client.get("/api/scan/status")
    assert response.status_code == 200

    data = response.json()
    assert data["total_duplicate_sets"] == 2
    assert data["pending_sets"] == 1
    # Only PENDING/APPROVED sets count toward reclaimable space (excludes PROCESSED)
    assert data["total_space_reclaimable"] == 5 * 1024**3


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

    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "pending"


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
        "/api/scan/start", json={"library_names": ["Movies"], "media_types": ["movie"]}
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
        response = await client.post(
            "/api/scan/start",
            json={"library_names": ["Movies"], "media_types": ["movie"]},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["duplicates_found"] == 4
    assert body["sets_created"] == 2
    assert body["sets_updated"] == 1


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
async def test_delete_duplicate_set_dry_run(client, test_db, create_duplicate_set):
    """Test deletion with dry_run=True (default)"""
    # Configure required services in database
    from tests.conftest import encrypt_test_password

    plex_token_config = Config(
        key="plex_auth_token", value=encrypt_test_password("test_token")
    )
    plex_server_config = Config(key="plex_server_name", value="Test Server")
    plex_libraries_config = Config(key="media_libraries", value="Movies,TV Shows")
    test_db.add(plex_token_config)
    test_db.add(plex_server_config)
    test_db.add(plex_libraries_config)
    await test_db.commit()

    # Create duplicate set
    dup_set = await create_duplicate_set(
        item_id="delete_test",
        title="Delete Test Movie",
        media_type=MediaType.MOVIE,
        status=DuplicateStatus.PENDING,
        space_to_reclaim=5 * 1024**3,
    )

    file1 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/delete.720p.mkv",
        file_size=3 * 1024**3,
        score=10000,
        keep=False,
    )
    file2 = DuplicateFile(
        set_id=dup_set.id,
        file_path="/movies/delete.1080p.mkv",
        file_size=8 * 1024**3,
        score=20000,
        keep=True,
    )
    test_db.add(file1)
    test_db.add(file2)
    await test_db.commit()

    # Test dry run (should not actually delete)
    response = await client.post(
        f"/api/scan/duplicates/{dup_set.id}/delete", json={"dry_run": True}
    )

    assert response.status_code == 200
    data = response.json()

    assert data["success"] is True
    assert data["dry_run"] is True
    assert data["files_deleted"] == 1
    assert data["space_reclaimed"] == 3 * 1024**3
    assert "[DRY-RUN]" in data["message"]
    assert len(data["errors"]) == 0

    # Verify set is NOT marked as processed in dry-run mode
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
