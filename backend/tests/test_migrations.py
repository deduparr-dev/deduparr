"""Tests for the Alembic migration that renamed the media server columns"""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]

LEGACY_SCHEMA = """
CREATE TABLE duplicate_sets (
  id INTEGER PRIMARY KEY, plex_item_id VARCHAR(255), title VARCHAR(500) NOT NULL,
  media_type VARCHAR(7) NOT NULL, found_at DATETIME NOT NULL,
  status VARCHAR(9) NOT NULL, space_to_reclaim BIGINT);
CREATE TABLE duplicate_files (
  id INTEGER PRIMARY KEY,
  set_id INTEGER NOT NULL REFERENCES duplicate_sets(id) ON DELETE CASCADE,
  file_path VARCHAR(1000) NOT NULL, file_size BIGINT, score INTEGER, keep BOOLEAN,
  file_metadata TEXT, inode VARCHAR(64), is_hardlink BOOLEAN);
CREATE TABLE deletion_history (
  id INTEGER PRIMARY KEY,
  duplicate_file_id INTEGER NOT NULL REFERENCES duplicate_files(id) ON DELETE CASCADE,
  deleted_at DATETIME NOT NULL, deleted_from_qbit BOOLEAN NOT NULL,
  deleted_from_arr BOOLEAN NOT NULL, deleted_from_disk BOOLEAN NOT NULL,
  plex_refreshed BOOLEAN NOT NULL, error TEXT, qbit_torrent_hash TEXT,
  arr_type TEXT, arr_media_id INTEGER);
CREATE TABLE config (id INTEGER PRIMARY KEY, "key" VARCHAR(255), value TEXT,
  updated_at DATETIME);
CREATE TABLE scoring_rules (id INTEGER PRIMARY KEY, name VARCHAR(255),
  pattern VARCHAR(500), score_modifier INTEGER, rule_type VARCHAR(20),
  enabled BOOLEAN, created_at DATETIME);
INSERT INTO duplicate_sets VALUES
  (1, 'rk-42', 'Legacy Movie', 'MOVIE', '2026-01-01 00:00:00', 'PENDING', 1234);
INSERT INTO duplicate_files VALUES (1, 1, '/m/a.mkv', 10, 50, 1, NULL, NULL, 0);
INSERT INTO deletion_history VALUES
  (1, 1, '2026-01-02 00:00:00', 1, 1, 1, 1, NULL, NULL, NULL, NULL);
"""


def _upgrade(db_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "DATABASE_TYPE": "sqlite",
            "DATABASE_URL": f"sqlite:///{db_path}",
            "CONFIG_DIR": str(db_path.parent),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _columns(db_path: Path, table: str) -> set:
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


@pytest.mark.parametrize("seed", [False, True], ids=["fresh", "legacy"])
def test_migration_lands_on_the_current_schema(tmp_path, seed):
    """
    The one migration has to serve both cases.

    Deduparr used to build its schema with create_all, so an existing database
    arrives with the old column names and no Alembic version, while a new one
    arrives empty.
    """
    db_path = tmp_path / "deduparr.db"
    if seed:
        with sqlite3.connect(db_path) as conn:
            conn.executescript(LEGACY_SCHEMA)

    _upgrade(db_path)

    sets = _columns(db_path, "duplicate_sets")
    assert "item_id" in sets and "media_server" in sets
    assert "plex_item_id" not in sets
    assert "media_server_refreshed" in _columns(db_path, "deletion_history")
    assert "plex_refreshed" not in _columns(db_path, "deletion_history")

    with sqlite3.connect(db_path) as conn:
        assert [
            r[0] for r in conn.execute("SELECT version_num FROM alembic_version")
        ] == ["0001"]

        if seed:
            # An upgrade must not cost the user their history
            row = conn.execute(
                "SELECT item_id, media_server, title, space_to_reclaim FROM duplicate_sets"
            ).fetchone()
            assert row == ("rk-42", "plex", "Legacy Movie", 1234)
            assert conn.execute(
                "SELECT media_server_refreshed FROM deletion_history"
            ).fetchone() == (1,)
