"""
tests/test_migration_v6_upgrade.py — Regression tests for a second
instance of the same DDL-ordering bug class fixed in test_migration_v5.py:
initialize() crashed with "no such column: problem_id" against any
database that predates schema v6.

Same root cause, one migration boundary later: conn.executescript(
_SCHEMA_DDL) ran unconditionally, before any migration, and used to
contain `CREATE INDEX idx_opp_problem ON opportunities(problem_id)` — a
column that only exists after _migrate_v6() runs. Against a pre-v6
database, opportunities already exists (CREATE TABLE IF NOT EXISTS is a
no-op), so that index statement failed immediately.

This is also where a third and fourth instance of the same bug class
were found and fixed in the same pass: idx_signals_dedup (references
signals.domain, added by _migrate_v2) and idx_reports_week_domain
(references reports.domain, also added by _migrate_v2) had the identical
problem. idx_reports_week_domain needed no new code (_migrate_v3 already
created it unconditionally); idx_signals_dedup needed _migrate_v3's
existing "rebuild if wrong shape" check hardened to also "create if
missing entirely", since the DDL block could no longer be relied on to
have created some version of it first.

Run with:
    cd backend && pytest tests/test_migration_v6_upgrade.py -v
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database


def _seed_pre_v6_database(db_path):
    """A genuine post-v5, pre-v6 shape: entities/relationships have
    domain, opportunities does NOT have problem_id yet, no problems or
    problem_history tables."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE entities (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL,
            domain TEXT NOT NULL DEFAULT 'business',
            description TEXT DEFAULT '', metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE relationships (
            id TEXT PRIMARY KEY, from_id TEXT NOT NULL, to_id TEXT NOT NULL,
            domain TEXT NOT NULL DEFAULT 'business',
            type TEXT NOT NULL, weight REAL DEFAULT 1.0, metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE signals (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
            url TEXT DEFAULT '', title TEXT NOT NULL, content TEXT DEFAULT '',
            platform_score INTEGER DEFAULT 0, comment_count INTEGER DEFAULT 0,
            entity_ids TEXT DEFAULT '[]', tags TEXT DEFAULT '[]', raw_metadata TEXT DEFAULT '{}',
            collected_at TEXT NOT NULL, processed INTEGER DEFAULT 0,
            domain TEXT NOT NULL DEFAULT 'business'
        );
        CREATE UNIQUE INDEX idx_signals_dedup ON signals(source, source_id, domain);
        CREATE TABLE opportunities (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
            signal_ids TEXT DEFAULT '[]', entity_ids TEXT DEFAULT '[]',
            scores TEXT DEFAULT '{}', composite_score REAL DEFAULT 0.0,
            status TEXT DEFAULT 'new', week_key TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            domain TEXT NOT NULL DEFAULT 'business'
        );
        CREATE TABLE reports (
            id TEXT PRIMARY KEY, week_key TEXT NOT NULL, period_start TEXT NOT NULL,
            period_end TEXT NOT NULL, content TEXT DEFAULT '{}', opp_count INTEGER DEFAULT 0,
            signal_count INTEGER DEFAULT 0, created_at TEXT NOT NULL,
            domain TEXT NOT NULL DEFAULT 'business'
        );
        CREATE UNIQUE INDEX idx_reports_week_domain ON reports(week_key, domain);
        CREATE TABLE schema_info (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        INSERT INTO schema_info (version, applied_at) VALUES (5, '2025-06-01T00:00:00Z');
        INSERT INTO opportunities (id, title, description, week_key, created_at, updated_at, domain)
            VALUES ('opp1', 'A pre-v6 opportunity', 'desc', '2025-W20',
                    '2025-06-01T00:00:00Z', '2025-06-01T00:00:00Z', 'business');
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture
def pre_v6_db(tmp_path, monkeypatch):
    db_path = tmp_path / "pre_v6.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    _seed_pre_v6_database(db_path)
    yield db_path


class TestInitializeAgainstPreV6Database:
    def test_initialize_does_not_raise(self, pre_v6_db):
        """The exact reported crash: OperationalError: no such column: problem_id."""
        database.initialize()

    def test_migrates_all_the_way_to_current_version(self, pre_v6_db):
        database.initialize()
        with database.get_connection() as conn:
            version = conn.execute(
                "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
            ).fetchone()["version"]
        assert version == database.SCHEMA_VERSION

    def test_idx_opp_problem_exists_after_migration(self, pre_v6_db):
        database.initialize()
        with database.get_connection() as conn:
            indexes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        assert "idx_opp_problem" in indexes

    def test_pre_existing_opportunity_gets_backfilled_problem_id(self, pre_v6_db):
        """Confirms _migrate_v6()'s own backfill still runs correctly once
        initialize() no longer crashes before reaching it."""
        database.initialize()
        with database.get_connection() as conn:
            opp = conn.execute("SELECT * FROM opportunities WHERE id = 'opp1'").fetchone()
        assert opp["problem_id"] != ""
        problem_id = opp["problem_id"]
        with database.get_connection() as conn:
            problem = conn.execute("SELECT * FROM problems WHERE id = ?", (problem_id,)).fetchone()
        assert problem is not None
        assert problem["title"] == "A pre-v6 opportunity"

    def test_idempotent_on_repeated_initialize_calls(self, pre_v6_db):
        database.initialize()
        database.initialize()
        with database.get_connection() as conn:
            version = conn.execute(
                "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
            ).fetchone()["version"]
            count = conn.execute("SELECT COUNT(*) c FROM opportunities").fetchone()["c"]
        assert version == database.SCHEMA_VERSION
        assert count == 1  # no duplicate backfill


class TestFullUpgradePathV1ToV7:
    """
    The comprehensive test that would have caught every instance of this
    bug class at once: a genuine v1-shaped database (no schema_info row
    at all, no domain columns anywhere, old inline UNIQUE(week_key) on
    reports, old 2-column dedup index on signals) run through the real
    initialize() path, all the way to the current schema version, with
    real seeded data in every affected table to confirm nothing is lost.
    """

    @pytest.fixture
    def v1_db(self, tmp_path, monkeypatch):
        db_path = tmp_path / "v1.db"
        monkeypatch.setattr(database, "DB_PATH", db_path)
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
            CREATE TABLE signals (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
                url TEXT DEFAULT '', title TEXT NOT NULL, content TEXT DEFAULT '',
                platform_score INTEGER DEFAULT 0, comment_count INTEGER DEFAULT 0,
                entity_ids TEXT DEFAULT '[]', tags TEXT DEFAULT '[]', raw_metadata TEXT DEFAULT '{}',
                collected_at TEXT NOT NULL, processed INTEGER DEFAULT 0
            );
            CREATE UNIQUE INDEX idx_signals_dedup ON signals(source, source_id);
            CREATE TABLE opportunities (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
                signal_ids TEXT DEFAULT '[]', entity_ids TEXT DEFAULT '[]',
                scores TEXT DEFAULT '{}', composite_score REAL DEFAULT 0.0,
                status TEXT DEFAULT 'new', week_key TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE reports (
                id TEXT PRIMARY KEY, week_key TEXT NOT NULL UNIQUE, period_start TEXT NOT NULL,
                period_end TEXT NOT NULL, content TEXT DEFAULT '{}', opp_count INTEGER DEFAULT 0,
                signal_count INTEGER DEFAULT 0, created_at TEXT NOT NULL
            );
            INSERT INTO signals (id, source, source_id, title, collected_at)
                VALUES ('sig1', 'hn', '1', 'A real old signal', '2025-01-01T00:00:00Z');
            INSERT INTO opportunities (id, title, description, week_key, created_at, updated_at)
                VALUES ('opp1', 'Old opportunity', 'desc', '2025-W01',
                        '2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z');
            INSERT INTO reports (id, week_key, period_start, period_end, created_at)
                VALUES ('rep1', '2025-W01', '2025-01-01', '2025-01-07', '2025-01-01T00:00:00Z');
            """
        )
        conn.commit()
        conn.close()
        yield db_path

    def test_initialize_does_not_raise(self, v1_db):
        database.initialize()

    def test_reaches_current_schema_version(self, v1_db):
        database.initialize()
        with database.get_connection() as conn:
            version = conn.execute(
                "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
            ).fetchone()["version"]
        assert version == database.SCHEMA_VERSION

    @pytest.mark.parametrize("index_name", [
        "idx_signals_dedup",
        "idx_opp_problem",
        "idx_reports_week_domain",
        "idx_entities_domain",
        "idx_rel_domain",
        "idx_problems_domain",
        "idx_problem_history_problem",
        "idx_entities_lifecycle",
        "idx_rel_lifecycle",
    ])
    def test_every_domain_or_problem_dependent_index_exists(self, v1_db, index_name):
        database.initialize()
        with database.get_connection() as conn:
            indexes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        assert index_name in indexes

    def test_no_data_lost_across_the_full_upgrade(self, v1_db):
        database.initialize()
        with database.get_connection() as conn:
            sig = conn.execute("SELECT * FROM signals WHERE id = 'sig1'").fetchone()
            opp = conn.execute("SELECT * FROM opportunities WHERE id = 'opp1'").fetchone()
            rep = conn.execute("SELECT * FROM reports WHERE id = 'rep1'").fetchone()
        assert sig is not None and sig["domain"] == "business"
        assert opp is not None and opp["domain"] == "business" and opp["problem_id"] != ""
        assert rep is not None and rep["domain"] == "business"

    def test_idempotent_on_repeated_initialize_calls(self, v1_db):
        database.initialize()
        database.initialize()
        with database.get_connection() as conn:
            version = conn.execute(
                "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
            ).fetchone()["version"]
        assert version == database.SCHEMA_VERSION


class TestFreshDatabaseUnaffected:
    """Guard against the fix accidentally breaking the far more common
    fresh-database path — every index must still exist there too."""

    @pytest.mark.parametrize("index_name", [
        "idx_signals_dedup",
        "idx_opp_problem",
        "idx_reports_week_domain",
        "idx_entities_domain",
        "idx_rel_domain",
    ])
    def test_fresh_database_has_every_index(self, tmp_path, monkeypatch, index_name):
        db_path = tmp_path / "fresh.db"
        monkeypatch.setattr(database, "DB_PATH", db_path)
        database.initialize()
        with database.get_connection() as conn:
            indexes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        assert index_name in indexes

    def test_fresh_signals_dedup_index_has_correct_columns(self, tmp_path, monkeypatch):
        db_path = tmp_path / "fresh.db"
        monkeypatch.setattr(database, "DB_PATH", db_path)
        database.initialize()
        with database.get_connection() as conn:
            cols = [r["name"] for r in conn.execute("PRAGMA index_info(idx_signals_dedup)").fetchall()]
        assert cols == ["source", "source_id", "domain"]
