"""
tests/test_migration_v9.py — Regression tests for schema v9: Problem
lifecycle & trend (two independent axes: lifecycle_state/
lifecycle_updated_at and trend/trend_updated_at).

Same two failure modes this project's DDL-ordering bug class has
actually produced before (see test_migration_v8.py's docstring for the
full history): a pre-v9 database, and a fresh database where index
creation nested inside a column-existence guard would silently never run.

Run with:
    cd backend && pytest tests/test_migration_v9.py -v
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database


def _seed_pre_v9_database(db_path):
    """A genuine post-v8, pre-v9 shape: problems exists with every
    column through schema v8, but no lifecycle_state/trend yet."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE problems (
            id TEXT PRIMARY KEY, domain TEXT NOT NULL DEFAULT 'business',
            title TEXT NOT NULL, entity_ids TEXT DEFAULT '[]',
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            weeks_seen INTEGER DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE problem_history (
            id TEXT PRIMARY KEY, problem_id TEXT NOT NULL, domain TEXT NOT NULL DEFAULT 'business',
            event_type TEXT NOT NULL, occurred_at TEXT NOT NULL, week_key TEXT DEFAULT '',
            opportunity_id TEXT DEFAULT '', metadata TEXT DEFAULT '{}', created_at TEXT NOT NULL
        );
        CREATE TABLE schema_info (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        INSERT INTO schema_info (version, applied_at) VALUES (8, '2026-01-01T00:00:00Z');
        INSERT INTO problems (id, domain, title, entity_ids, first_seen, last_seen, weeks_seen, created_at, updated_at)
            VALUES ('p1', 'business', 'Old problem', '[]',
                    '2026-01-01T00:00:00Z', '2026-01-15T00:00:00Z', 2,
                    '2026-01-01T00:00:00Z', '2026-01-15T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture
def pre_v9_db(tmp_path, monkeypatch):
    db_path = tmp_path / "pre_v9.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    _seed_pre_v9_database(db_path)
    yield db_path


class TestInitializeAgainstPreV9Database:
    def test_initialize_does_not_raise(self, pre_v9_db):
        database.initialize()

    def test_migrates_to_current_version(self, pre_v9_db):
        database.initialize()
        with database.get_connection() as conn:
            version = conn.execute(
                "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
            ).fetchone()["version"]
        assert version == database.SCHEMA_VERSION

    def test_lifecycle_and_trend_columns_added(self, pre_v9_db):
        database.initialize()
        with database.get_connection() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(problems)").fetchall()}
        assert "lifecycle_state" in cols
        assert "lifecycle_updated_at" in cols
        assert "trend" in cols
        assert "trend_updated_at" in cols

    def test_existing_problem_backfilled_as_new_and_unknown(self, pre_v9_db):
        database.initialize()
        with database.get_connection() as conn:
            problem = conn.execute("SELECT * FROM problems WHERE id = 'p1'").fetchone()
        assert problem["lifecycle_state"] == "new"
        assert problem["trend"] == "unknown"

    def test_existing_problem_updated_at_backfills_both_axes(self, pre_v9_db):
        database.initialize()
        with database.get_connection() as conn:
            problem = conn.execute("SELECT * FROM problems WHERE id = 'p1'").fetchone()
        assert problem["lifecycle_updated_at"] == "2026-01-15T00:00:00Z"
        assert problem["trend_updated_at"] == "2026-01-15T00:00:00Z"

    def test_idx_problems_lifecycle_exists_after_migration(self, pre_v9_db):
        database.initialize()
        with database.get_connection() as conn:
            indexes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        assert "idx_problems_lifecycle" in indexes

    def test_idx_problems_trend_exists_after_migration(self, pre_v9_db):
        database.initialize()
        with database.get_connection() as conn:
            indexes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        assert "idx_problems_trend" in indexes

    def test_no_data_lost(self, pre_v9_db):
        database.initialize()
        with database.get_connection() as conn:
            problem = conn.execute("SELECT * FROM problems WHERE id = 'p1'").fetchone()
        assert problem["title"] == "Old problem"
        assert problem["weeks_seen"] == 2

    def test_idempotent_on_repeated_initialize_calls(self, pre_v9_db):
        database.initialize()
        database.initialize()
        with database.get_connection() as conn:
            version = conn.execute(
                "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
            ).fetchone()["version"]
            problem = conn.execute("SELECT * FROM problems WHERE id = 'p1'").fetchone()
        assert version == database.SCHEMA_VERSION
        assert problem["lifecycle_state"] == "new"
        assert problem["trend"] == "unknown"


class TestFreshDatabaseGetsIndexesToo:
    """The idx_opp_problem failure mode, checked again for v9's two new
    indexes — see test_migration_v8.py's docstring for the full history."""

    @pytest.fixture
    def fresh_db(self, tmp_path, monkeypatch):
        db_path = tmp_path / "fresh.db"
        monkeypatch.setattr(database, "DB_PATH", db_path)
        database.initialize()
        yield db_path

    def test_fresh_database_has_idx_problems_lifecycle(self, fresh_db):
        with database.get_connection() as conn:
            indexes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        assert "idx_problems_lifecycle" in indexes

    def test_fresh_database_has_idx_problems_trend(self, fresh_db):
        with database.get_connection() as conn:
            indexes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        assert "idx_problems_trend" in indexes

    def test_fresh_database_problems_default_to_new_and_unknown(self, fresh_db):
        with database.get_connection() as conn:
            conn.execute(
                "INSERT INTO problems (id, domain, title, first_seen, last_seen, weeks_seen, created_at, updated_at) "
                "VALUES ('p1', 'business', 'X', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 1, "
                "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
            )
            conn.commit()
            problem = conn.execute("SELECT * FROM problems WHERE id = 'p1'").fetchone()
        assert problem["lifecycle_state"] == "new"
        assert problem["trend"] == "unknown"
