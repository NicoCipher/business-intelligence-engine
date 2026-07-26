"""
tests/test_migration_v6.py — Regression tests for schema v6: the
`problems` table and opportunities.problem_id backfill.

Covers the exact gap that let a real bug ship unnoticed: _migrate_v6's
backfill loop (`uuid.uuid4()`) was only ever exercised when there's at
least one existing opportunity with an empty problem_id at migration
time. No prior test created an opportunity before running migrations to
a fresh v6 state, so a missing `import uuid` in database.py went
uncaught until this file actually exercised that path.

Run with:
    cd backend && pytest tests/test_migration_v6.py -v
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_migration_v6.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()
    yield db_path


def _insert_raw_pre_v6_opportunity(conn, id_, title, domain, created_at):
    """Simulate an opportunity that existed before problem_id existed —
    inserted with an empty problem_id, exactly the state _migrate_v6's
    backfill loop needs to find and act on."""
    conn.execute(
        """
        INSERT INTO opportunities
          (id, title, description, signal_ids, entity_ids, scores,
           composite_score, status, week_key, created_at, updated_at, domain, problem_id)
        VALUES (?, ?, '', '[]', '[]', '{}', 5.0, 'new', '2026-W01', ?, ?, ?, '')
        """,
        (id_, title, created_at, created_at, domain),
    )


class TestSchemaV6:
    def test_problems_table_exists(self, fresh_db):
        with database.get_connection() as conn:
            tables = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert "problems" in tables

    def test_opportunities_has_problem_id_column(self, fresh_db):
        with database.get_connection() as conn:
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(opportunities)").fetchall()}
        assert "problem_id" in columns

    def test_schema_version_is_6(self, fresh_db):
        with database.get_connection() as conn:
            version = conn.execute(
                "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
            ).fetchone()["version"]
        assert version == database.SCHEMA_VERSION == 6


class TestBackfillOfPreV6Opportunities:
    """
    This is the exact path that was broken: an opportunity with an empty
    problem_id, present when _migrate_v6 runs. Without `import uuid` in
    database.py, this raises NameError the moment it executes.
    """

    def test_backfill_creates_a_problem_and_links_it(self, fresh_db):
        with database.get_connection() as conn:
            _insert_raw_pre_v6_opportunity(
                conn, "opp-1", "Old opportunity from before problems existed",
                "business", "2026-01-01T00:00:00Z",
            )
            conn.commit()

            # Re-running the migration must not raise, and must backfill.
            database._migrate_v6(conn)

            opp_row = conn.execute(
                "SELECT problem_id FROM opportunities WHERE id = 'opp-1'"
            ).fetchone()
            assert opp_row["problem_id"], "problem_id must no longer be empty"

            problem_row = conn.execute(
                "SELECT * FROM problems WHERE id = ?", (opp_row["problem_id"],)
            ).fetchone()
            assert problem_row is not None
            assert problem_row["title"] == "Old opportunity from before problems existed"
            assert problem_row["domain"] == "business"
            assert json.loads(problem_row["entity_ids"]) == []
            assert problem_row["weeks_seen"] == 1

    def test_backfill_gives_each_opportunity_its_own_problem(self, fresh_db):
        """Pre-v6 opportunities have no real entity signature to match
        against each other — each becomes its own independent root,
        exactly as the migration's docstring states, not merged."""
        with database.get_connection() as conn:
            _insert_raw_pre_v6_opportunity(conn, "opp-1", "First old opportunity", "business", "2026-01-01T00:00:00Z")
            _insert_raw_pre_v6_opportunity(conn, "opp-2", "Second old opportunity", "business", "2026-01-02T00:00:00Z")
            conn.commit()

            database._migrate_v6(conn)

            rows = conn.execute("SELECT id, problem_id FROM opportunities ORDER BY id").fetchall()
            assert rows[0]["problem_id"] != rows[1]["problem_id"]
            problem_count = conn.execute("SELECT COUNT(*) c FROM problems").fetchone()["c"]
            assert problem_count == 2

    def test_backfill_is_idempotent(self, fresh_db):
        """Running the migration twice must not create duplicate problems
        or re-backfill already-linked opportunities."""
        with database.get_connection() as conn:
            _insert_raw_pre_v6_opportunity(conn, "opp-1", "An opportunity", "business", "2026-01-01T00:00:00Z")
            conn.commit()

            database._migrate_v6(conn)
            first_problem_id = conn.execute(
                "SELECT problem_id FROM opportunities WHERE id = 'opp-1'"
            ).fetchone()["problem_id"]

            database._migrate_v6(conn)  # should be a no-op the second time
            second_problem_id = conn.execute(
                "SELECT problem_id FROM opportunities WHERE id = 'opp-1'"
            ).fetchone()["problem_id"]

            assert first_problem_id == second_problem_id
            problem_count = conn.execute("SELECT COUNT(*) c FROM problems").fetchone()["c"]
            assert problem_count == 1

    def test_no_unlinked_opportunities_is_a_clean_no_op(self, fresh_db):
        """A fresh database with no opportunities at all must not error —
        this is what every existing test's fresh_db fixture already
        exercises implicitly, asserted here directly."""
        with database.get_connection() as conn:
            database._migrate_v6(conn)  # already ran once via initialize(); must be safe again
            problem_count = conn.execute("SELECT COUNT(*) c FROM problems").fetchone()["c"]
        assert problem_count == 0
