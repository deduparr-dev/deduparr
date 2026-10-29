"""Tests for the Alembic migrations, against the schemas old releases really created"""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]

# What Base.metadata.create_all built in 0.5.7, the last release before Alembic,
# dumped from a database 0.5.7 created. Its init_db also added the _init table.
SCHEMA_0_5_7 = """
CREATE TABLE _init (id INTEGER PRIMARY KEY);
CREATE TABLE config (
  id INTEGER NOT NULL,
  "key" VARCHAR(255) NOT NULL,
  value TEXT,
  updated_at DATETIME,
  PRIMARY KEY (id)
);
CREATE TABLE deletion_history (
  id INTEGER NOT NULL,
  duplicate_file_id INTEGER NOT NULL,
  deleted_at DATETIME NOT NULL,
  deleted_from_qbit BOOLEAN NOT NULL,
  deleted_from_arr BOOLEAN NOT NULL,
  deleted_from_disk BOOLEAN NOT NULL,
  plex_refreshed BOOLEAN NOT NULL,
  error TEXT,
  qbit_torrent_hash TEXT,
  arr_type TEXT,
  arr_media_id INTEGER,
  PRIMARY KEY (id),
  FOREIGN KEY(duplicate_file_id) REFERENCES duplicate_files (id) ON DELETE CASCADE
);
CREATE TABLE duplicate_files (
  id INTEGER NOT NULL,
  set_id INTEGER NOT NULL,
  file_path TEXT NOT NULL,
  file_size BIGINT NOT NULL,
  score INTEGER NOT NULL,
  keep BOOLEAN NOT NULL,
  inode VARCHAR(32),
  is_hardlink BOOLEAN NOT NULL,
  file_metadata TEXT,
  PRIMARY KEY (id),
  FOREIGN KEY(set_id) REFERENCES duplicate_sets (id) ON DELETE CASCADE
);
CREATE TABLE duplicate_sets (
  id INTEGER NOT NULL,
  plex_item_id VARCHAR(255),
  title VARCHAR(500) NOT NULL,
  media_type VARCHAR(7) NOT NULL,
  found_at DATETIME NOT NULL,
  status VARCHAR(9) NOT NULL,
  space_to_reclaim BIGINT,
  PRIMARY KEY (id)
);
CREATE TABLE scoring_rules (
  id INTEGER NOT NULL,
  rule_type VARCHAR(16) NOT NULL,
  pattern TEXT NOT NULL,
  score_modifier INTEGER NOT NULL,
  enabled BOOLEAN NOT NULL,
  created_at DATETIME NOT NULL,
  description TEXT,
  PRIMARY KEY (id)
);
CREATE INDEX ix_config_id ON config (id);
CREATE UNIQUE INDEX ix_config_key ON config ("key");
CREATE INDEX idx_deleted_at_desc ON deletion_history (deleted_at);
CREATE INDEX ix_deletion_history_deleted_at ON deletion_history (deleted_at);
CREATE INDEX ix_deletion_history_duplicate_file_id ON deletion_history (duplicate_file_id);
CREATE INDEX ix_deletion_history_id ON deletion_history (id);
CREATE INDEX idx_set_file ON duplicate_files (set_id, file_path);
CREATE INDEX ix_duplicate_files_file_path ON duplicate_files (file_path);
CREATE INDEX ix_duplicate_files_id ON duplicate_files (id);
CREATE INDEX ix_duplicate_files_inode ON duplicate_files (inode);
CREATE INDEX ix_duplicate_files_set_id ON duplicate_files (set_id);
CREATE INDEX idx_status_found_at ON duplicate_sets (status, found_at);
CREATE INDEX ix_duplicate_sets_found_at ON duplicate_sets (found_at);
CREATE INDEX ix_duplicate_sets_id ON duplicate_sets (id);
CREATE INDEX ix_duplicate_sets_plex_item_id ON duplicate_sets (plex_item_id);
CREATE INDEX ix_duplicate_sets_status ON duplicate_sets (status);
CREATE INDEX idx_enabled_type ON scoring_rules (enabled, rule_type);
CREATE INDEX ix_scoring_rules_enabled ON scoring_rules (enabled);
CREATE INDEX ix_scoring_rules_id ON scoring_rules (id);
CREATE INDEX ix_scoring_rules_rule_type ON scoring_rules (rule_type);
"""

# 0.1.1, the first release, differed in the two columns 0.2.0 and 0.5.3 changed
SCHEMA_0_1_1 = SCHEMA_0_5_7.replace(
    "plex_item_id VARCHAR(255),", "plex_item_id VARCHAR(255) NOT NULL,"
).replace("inode VARCHAR(32),", "inode BIGINT,")

# Each release that predates migrations, and the revision whose schema it has
RELEASES = [("0.1.1", "0001", SCHEMA_0_1_1), ("0.5.7", "0003", SCHEMA_0_5_7)]

DATA = """
INSERT INTO duplicate_sets
  (id, plex_item_id, title, media_type, found_at, status, space_to_reclaim)
  VALUES (1, 'rk-42', 'Legacy Movie', 'MOVIE', '2026-01-01 00:00:00', 'PENDING', 1234);
INSERT INTO duplicate_files (id, set_id, file_path, file_size, score, keep, is_hardlink)
  VALUES (1, 1, '/m/a.mkv', 10, 50, 1, 0);
INSERT INTO deletion_history (id, duplicate_file_id, deleted_at, deleted_from_qbit,
  deleted_from_arr, deleted_from_disk, plex_refreshed)
  VALUES (1, 1, '2026-01-02 00:00:00', 1, 1, 1, 1);
INSERT INTO config ("key", value) VALUES ('plex_auth_token', 'tok');
INSERT INTO config ("key", value) VALUES ('plex_libraries', 'Movies,TV Shows');
"""


def _env(db_path: Path) -> dict:
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "DATABASE_TYPE": "sqlite",
        "DATABASE_URL": f"sqlite:///{db_path}",
        "CONFIG_DIR": str(db_path.parent),
    }


def _alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=_env(db_path),
        capture_output=True,
        text=True,
    )


def _start_app(db_path: Path) -> None:
    """Prepare the database the way the app does when it starts"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import asyncio; from app.core.database import init_db; asyncio.run(init_db())",
        ],
        cwd=BACKEND_DIR,
        env=_env(db_path),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _upgrade_by_hand(db_path: Path) -> None:
    result = _alembic(db_path, "upgrade", "head")
    assert result.returncode == 0, result.stderr


def _check(db_path: Path) -> None:
    """Autogenerate finds nothing between this database and the models"""
    result = _alembic(db_path, "check")
    assert result.returncode == 0, result.stdout + result.stderr


def _version(db_path: Path) -> list:
    with sqlite3.connect(db_path) as conn:
        return [r[0] for r in conn.execute("SELECT version_num FROM alembic_version")]


def _head_revision() -> str:
    """The newest revision, read from Alembic rather than hardcoded."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=BACKEND_DIR,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "DATABASE_TYPE": "sqlite"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.split()[0]


def _schema(db_path: Path) -> dict:
    """Each table's columns, indexes and foreign keys, as SQLite describes them"""
    with sqlite3.connect(db_path) as conn:
        tables = [
            name
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
                " AND name NOT IN ('_init', 'alembic_version')"
            )
        ]
        return {
            table: {
                # Name, type, not null, default and primary key: not the position
                "columns": sorted(
                    row[1:] for row in conn.execute(f"PRAGMA table_info('{table}')")
                ),
                "indexes": sorted(
                    (
                        index,
                        unique,
                        [c[2] for c in conn.execute(f"PRAGMA index_info('{index}')")],
                    )
                    for (_, index, unique, *_) in conn.execute(
                        f"PRAGMA index_list('{table}')"
                    )
                ),
                "foreign keys": sorted(
                    row[2:]
                    for row in conn.execute(f"PRAGMA foreign_key_list('{table}')")
                ),
            }
            for table in tables
        }


def _schema_of(tmp_path: Path, script: str) -> dict:
    db_path = tmp_path / "release.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(script)
    return _schema(db_path)


@pytest.mark.parametrize(
    "revision, schema", [r[1:] for r in RELEASES], ids=[r[0] for r in RELEASES]
)
def test_a_release_revision_has_that_release_schema(tmp_path, revision, schema):
    """0001 is the schema of 0.1.1, and 0003 the schema of 0.5.7"""
    db_path = tmp_path / "deduparr.db"

    result = _alembic(db_path, "upgrade", revision)
    assert result.returncode == 0, result.stderr

    assert _schema(db_path) == _schema_of(tmp_path, schema)


def test_a_new_install_matches_the_models(tmp_path):
    db_path = tmp_path / "deduparr.db"

    _start_app(db_path)

    assert _version(db_path) == [_head_revision()]
    _check(db_path)


@pytest.mark.parametrize(
    "schema", [r[2] for r in RELEASES], ids=[r[0] for r in RELEASES]
)
@pytest.mark.parametrize(
    "upgrade", [_start_app, _upgrade_by_hand], ids=["app start", "alembic upgrade"]
)
def test_an_install_from_before_migrations_is_upgraded(tmp_path, schema, upgrade):
    db_path = tmp_path / "deduparr.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema + DATA)

    upgrade(db_path)
    # A second run finds nothing left to do
    upgrade(db_path)

    assert _version(db_path) == [_head_revision()]
    _check(db_path)
    with sqlite3.connect(db_path) as conn:
        # An upgrade must not cost the user their history or settings
        row = conn.execute(
            "SELECT plex_item_id, media_server, title, space_to_reclaim"
            " FROM duplicate_sets"
        ).fetchone()
        assert row == ("rk-42", "plex", "Legacy Movie", 1234)
        assert conn.execute(
            "SELECT plex_refreshed FROM deletion_history"
        ).fetchone() == (1,)
        settings = dict(conn.execute('SELECT "key", value FROM config').fetchall())
        assert settings == {
            "plex_auth_token": "tok",
            "plex_libraries": "Movies,TV Shows",
        }


@pytest.mark.parametrize(
    "revision, schema", [r[1:] for r in RELEASES], ids=[r[0] for r in RELEASES]
)
def test_downgrading_restores_a_release_schema(tmp_path, revision, schema):
    db_path = tmp_path / "deduparr.db"
    _start_app(db_path)

    result = _alembic(db_path, "downgrade", revision)
    assert result.returncode == 0, result.stderr

    assert _schema(db_path) == _schema_of(tmp_path, schema)
