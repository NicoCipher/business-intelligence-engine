"""
tests/test_migration_v8.py — Regression tests for schema v8: knowledge-
graph decay (lifecycle_state / lifecycle_updated_at on entities and
relationships).

Given the DDL-ordering bug class found and fixed twice already in this
project (idx_entities_domain/idx_rel_domain at the v4->v5 boundary,
idx_opp_problem/idx_signals_dedup/idx_reports_week_domain at the v1/v2/v6
boundaries — see docs/PROBLEM_MEMORY_VALIDATION.md and the CI
investigation), this file specifically exercises both failure modes that
class of bug has actually produced before:

  1. A pre-v8 database (lifecycle columns don't exist yet) must migrate
     cleanly — this is the "unconditional DDL references a
     migration-added column" failure mode.
  2. A FRESH database (columns exist from the DDL's own CREATE TABLE)
     must still end up with the indexes — this is the "index creation
     nested inside a column-existence guard, so it never runs when the
     guard is trivially false" failure mode that bit idx_opp_problem.

Run with:
    cd backend && pytest tests/test_migration_v8.py -v
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database


def _seed_pre_v8_database(db_path):
    """A genuine post-v7 (schema version 7), pre-v8 shape: entities and
    relationships exist with every column through problem_id/schema v7,
    but no lifecycle_state or lifecycle_updated_at yet."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE entities (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL,
            domain TEXT NOT NULL DEFAULT 'business',
            description TEXT DEFAULT '', metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX idx_entities_type_name_domain ON entities(type, name, domain);
        CREATE TABLE relationships (
            id TEXT PRIMARY KEY, from_id TEXT NOT NULL, to_id TEXT NOT NULL,
            domain TEXT NOT NULL DEFAULT 'business',
            type TEXT NOT NULL, weight REAL DEFAULT 1.0, metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX idx_rel_from_to_type_domain ON relationships(from_id, to_id, type, domain);
        CREATE TABLE schema_info (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        INSERT INTO schema_info (version, applied_at) VALUES (7, '2026-01-01T00:00:00Z');
        INSERT INTO entities (id, type, name, domain, created_at, updated_at)
            VALUES ('ent1', 'technology', 'Old Entity', 'business',
                    '2026-01-01T00:00:00Z', '2026-01-15T00:00:00Z');
        INSERT INTO relationships (id, from_id, to_id, domain, type, weight, created_at, updated_at)
            VALUES ('rel1', 'ent1', 'ent1', 'business', 'co-occurs', 2.0,
                    '2026-01-01T00:00:00Z', '2026-01-15T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture
def pre_v8_db(tmp_path, monkeypatch):
    db_path = tmp_path / "pre_v8.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    _seed_pre_v8_database(db_path)
    yield db_path


class TestInitializeAgainstPreV8Database:
    def test_initialize_does_not_raise(self, pre_v8_db):
        database.initialize()

    def test_migrates_to_current_version(self, pre_v8_db):
        database.initialize()
        with database.get_connection() as conn:
            version = conn.execute(
                "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
            ).fetchone()["version"]
        assert version == database.SCHEMA_VERSION

    def test_lifecycle_columns_added_to_entities(self, pre_v8_db):
        database.initialize()
        with database.get_connection() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(entities)").fetchall()}
        assert "lifecycle_state" in cols
        assert "lifecycle_updated_at" in cols

    def test_lifecycle_columns_added_to_relationships(self, pre_v8_db):
        database.initialize()
        with database.get_connection() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(relationships)").fetchall()}
        assert "lifecycle_state" in cols
        assert "lifecycle_updated_at" in cols

    def test_existing_entity_backfilled_as_active(self, pre_v8_db):
        database.initialize()
        with database.get_connection() as conn:
            entity = conn.execute("SELECT * FROM entities WHERE id = 'ent1'").fetchone()
        assert entity["lifecycle_state"] == "active"

    def test_existing_entity_lifecycle_updated_at_backfilled_from_updated_at(self, pre_v8_db):
        """The migration's honest backfill: lifecycle_updated_at is set
        to the row's own updated_at, not the migration's run-time."""
        database.initialize()
        with database.get_connection() as conn:
            entity = conn.execute("SELECT * FROM entities WHERE id = 'ent1'").fetchone()
        assert entity["lifecycle_updated_at"] == "2026-01-15T00:00:00Z"

    def test_existing_relationship_backfilled_as_active(self, pre_v8_db):
        database.initialize()
        with database.get_connection() as conn:
            rel = conn.execute("SELECT * FROM relationships WHERE id = 'rel1'").fetchone()
        assert rel["lifecycle_state"] == "active"
        assert rel["lifecycle_updated_at"] == "2026-01-15T00:00:00Z"

    def test_idx_entities_lifecycle_exists_after_migration(self, pre_v8_db):
        database.initialize()
        with database.get_connection() as conn:
            indexes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        assert "idx_entities_lifecycle" in indexes

    def test_idx_rel_lifecycle_exists_after_migration(self, pre_v8_db):
        database.initialize()
        with database.get_connection() as conn:
            indexes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        assert "idx_rel_lifecycle" in indexes

    def test_no_data_lost(self, pre_v8_db):
        database.initialize()
        with database.get_connection() as conn:
            entity = conn.execute("SELECT * FROM entities WHERE id = 'ent1'").fetchone()
            rel = conn.execute("SELECT * FROM relationships WHERE id = 'rel1'").fetchone()
        assert entity["name"] == "Old Entity"
        assert rel["weight"] == 2.0

    def test_idempotent_on_repeated_initialize_calls(self, pre_v8_db):
        database.initialize()
        database.initialize()
        with database.get_connection() as conn:
            version = conn.execute(
                "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
            ).fetchone()["version"]
            entity = conn.execute("SELECT * FROM entities WHERE id = 'ent1'").fetchone()
        assert version == database.SCHEMA_VERSION
        assert entity["lifecycle_state"] == "active"


class TestFreshDatabaseGetsIndexesToo:
    """
    The specific failure mode that bit idx_opp_problem: index creation
    nested inside `if column not in existing_columns` never runs on a
    fresh database, since the column already exists there via the DDL's
    own CREATE TABLE. _migrate_v8() places both index-creation statements
    unconditionally, outside either guard -- these tests are what would
    have caught it if it had been made again.
    """

    @pytest.fixture
    def fresh_db(self, tmp_path, monkeypatch):
        db_path = tmp_path / "fresh.db"
        monkeypatch.setattr(database, "DB_PATH", db_path)
        database.initialize()
        yield db_path

    def test_fresh_database_has_idx_entities_lifecycle(self, fresh_db):
        with database.get_connection() as conn:
            indexes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        assert "idx_entities_lifecycle" in indexes

    def test_fresh_database_has_idx_rel_lifecycle(self, fresh_db):
        with database.get_connection() as conn:
            indexes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        assert "idx_rel_lifecycle" in indexes

    def test_fresh_database_entities_default_to_active(self, fresh_db):
        with database.get_connection() as conn:
            conn.execute(
                "INSERT INTO entities (id, type, name, domain, created_at, updated_at) "
                "VALUES ('e1', 'technology', 'X', 'business', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
            )
            conn.commit()
            entity = conn.execute("SELECT * FROM entities WHERE id = 'e1'").fetchone()
        assert entity["lifecycle_state"] == "active"
