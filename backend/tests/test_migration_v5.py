"""
tests/test_migration_v5.py — Regression test for a real bug found and
fixed in a live CI investigation: initialize() crashed against any
database that predates schema v5.

Root cause: conn.executescript(_SCHEMA_DDL) runs unconditionally on
every initialize() call, BEFORE the version check and BEFORE any
migration function runs. _SCHEMA_DDL used to contain
`CREATE INDEX idx_entities_domain ON entities(domain)` and the
relationships equivalent — but on a database that predates v5, the
`domain` column doesn't exist yet (CREATE TABLE IF NOT EXISTS is a
no-op against the existing table), so those two statements failed with
"no such column: domain" immediately, before _migrate_v5() ever got the
chance to ALTER TABLE and add it.

This wasn't caught by the existing test suite because every other test
in this file (and test_migration_v6.py / test_migration_v7.py) builds a
pre-migration database shape and then calls the specific `_migrate_vN()`
function directly — never the full initialize() path against a
genuinely pre-v5 database, which is the actual code path any real
upgrade (including the collect.yml GitHub Actions workflow's cached
`bia.db`, restored via a prefix key with no schema-aware invalidation)
goes through.

Fix: those two index-creation statements were removed from the
unconditional DDL block. _migrate_v5() already creates them itself
(after its own ALTER TABLE calls), exactly mirroring the reasoning
already documented for the neighboring UNIQUE indexes in the same DDL
block — this bug was really just that same reasoning not being applied
consistently to two more lines right next to the ones that already had
it right.

Run with:
    cd backend && pytest tests/test_migration_v5.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database


@pytest.fixture
def pre_v5_db(tmp_path, monkeypatch):
    """
    A database shaped exactly like one that existed before schema v5:
    entities/relationships tables with no `domain` column, schema_info
    pinned at version 4. Not hand-waved — this is the real upgrade
    entry point (initialize()), not a direct call to _migrate_v5().
    """
    db_path = tmp_path / "pre_v5.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE entities (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL,
            description TEXT DEFAULT '', metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE relationships (
            id TEXT PRIMARY KEY, from_id TEXT NOT NULL, to_id TEXT NOT NULL,
            type TEXT NOT NULL, weight REAL DEFAULT 1.0, metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE schema_info (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        INSERT INTO schema_info (version, applied_at) VALUES (4, '2025-01-01T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()
    yield db_path


class TestInitializeAgainstPreV5Database:
    def test_initialize_does_not_raise(self, pre_v5_db):
        """This is the exact call that crashed before the fix — no
        exception should propagate out of it."""
        database.initialize()  # must not raise OperationalError

    def test_migrates_all_the_way_to_current_version(self, pre_v5_db):
        database.initialize()
        with database.get_connection() as conn:
            version = conn.execute(
                "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
            ).fetchone()["version"]
        assert version == database.SCHEMA_VERSION

    def test_domain_columns_exist_after_migration(self, pre_v5_db):
        database.initialize()
        with database.get_connection() as conn:
            entity_cols = {r["name"] for r in conn.execute("PRAGMA table_info(entities)").fetchall()}
            rel_cols = {r["name"] for r in conn.execute("PRAGMA table_info(relationships)").fetchall()}
        assert "domain" in entity_cols
        assert "domain" in rel_cols

    def test_domain_indexes_exist_after_migration(self, pre_v5_db):
        """The whole point: these indexes must still get created, just
        by _migrate_v5() instead of the unconditional DDL block."""
        database.initialize()
        with database.get_connection() as conn:
            indexes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        assert "idx_entities_domain" in indexes
        assert "idx_rel_domain" in indexes

    def test_idempotent_on_repeated_initialize_calls(self, pre_v5_db):
        database.initialize()
        database.initialize()  # must not raise the second time either
        with database.get_connection() as conn:
            version = conn.execute(
                "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
            ).fetchone()["version"]
        assert version == database.SCHEMA_VERSION


class TestFreshDatabaseStillGetsTheIndexes:
    """Guard against fixing the pre-v5 case by accident breaking the
    much more common fresh-database case."""

    def test_fresh_database_has_domain_indexes(self, tmp_path, monkeypatch):
        db_path = tmp_path / "fresh.db"
        monkeypatch.setattr(database, "DB_PATH", db_path)
        database.initialize()
        with database.get_connection() as conn:
            indexes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        assert "idx_entities_domain" in indexes
        assert "idx_rel_domain" in indexes
