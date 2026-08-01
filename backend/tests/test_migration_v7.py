"""
tests/test_migration_v7.py — Regression tests for schema v7: the
`problem_history` table and its backfill of pre-v7 problems.

Mirrors tests/test_migration_v6.py's structure and the same discipline
that caught the v6 uuid bug: actually exercise the backfill path against
a database seeded with rows created *before* problem_history existed,
rather than only testing against a freshly-initialized database.

Run with:
    cd backend && pytest tests/test_migration_v7.py -v
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_migration_v7.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()
    yield db_path


def _insert_raw_pre_v7_problem(conn, id_, title, domain, first_seen, weeks_seen=1):
    """Simulate a Problem that existed before problem_history existed —
    inserted directly, with no corresponding history row, exactly the
    state _migrate_v7's backfill loop needs to find and act on."""
    conn.execute(
        """
        INSERT INTO problems (id, domain, title, entity_ids, first_seen, last_seen, weeks_seen, created_at, updated_at)
        VALUES (?, ?, ?, '[]', ?, ?, ?, ?, ?)
        """,
        (id_, domain, title, first_seen, first_seen, weeks_seen, first_seen, first_seen),
    )


class TestSchemaV7:
    def test_problem_history_table_exists(self, fresh_db):
        with database.get_connection() as conn:
            tables = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert "problem_history" in tables

    def test_schema_version_is_at_least_7(self, fresh_db):
        """A fresh database always ends up at the current SCHEMA_VERSION
        (now 8, since schema v8 added knowledge-graph decay) — this test
        just confirms v7's migration ran as part of that chain, not that
        v7 is the final version."""
        with database.get_connection() as conn:
            version = conn.execute(
                "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
            ).fetchone()["version"]
        assert version == database.SCHEMA_VERSION
        assert version >= 7

    def test_problem_history_columns(self, fresh_db):
        with database.get_connection() as conn:
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(problem_history)").fetchall()}
        assert columns == {
            "id", "problem_id", "domain", "event_type", "occurred_at",
            "week_key", "opportunity_id", "metadata", "created_at",
        }


class TestBackfillOfPreV7Problems:
    """
    The exact path a bug could hide in: a Problem with zero history rows,
    present when _migrate_v7 runs.
    """

    def test_backfill_creates_one_created_event(self, fresh_db):
        with database.get_connection() as conn:
            _insert_raw_pre_v7_problem(
                conn, "p1", "Old problem from before history existed",
                "business", "2026-01-01T00:00:00Z", weeks_seen=3,
            )
            conn.commit()

            database._migrate_v7(conn)  # must not raise, must backfill

            rows = conn.execute(
                "SELECT * FROM problem_history WHERE problem_id = 'p1'"
            ).fetchall()
            assert len(rows) == 1
            assert rows[0]["event_type"] == "created"
            assert rows[0]["occurred_at"] == "2026-01-01T00:00:00Z"
            metadata = json.loads(rows[0]["metadata"])
            assert metadata["backfilled"] is True
            assert metadata["title"] == "Old problem from before history existed"

    def test_backfill_does_not_fabricate_per_week_events(self, fresh_db):
        """weeks_seen=5 must NOT produce 5 backfilled events — there's no
        real record of which weeks, so fabricating them would misrepresent
        data that was never actually captured (see migration docstring)."""
        with database.get_connection() as conn:
            _insert_raw_pre_v7_problem(
                conn, "p1", "A problem seen many weeks", "business",
                "2026-01-01T00:00:00Z", weeks_seen=5,
            )
            conn.commit()
            database._migrate_v7(conn)
            count = conn.execute(
                "SELECT COUNT(*) c FROM problem_history WHERE problem_id = 'p1'"
            ).fetchone()["c"]
        assert count == 1

    def test_backfill_covers_every_unbacked_problem(self, fresh_db):
        with database.get_connection() as conn:
            _insert_raw_pre_v7_problem(conn, "p1", "First", "business", "2026-01-01T00:00:00Z")
            _insert_raw_pre_v7_problem(conn, "p2", "Second", "business", "2026-01-02T00:00:00Z")
            conn.commit()
            database._migrate_v7(conn)
            count = conn.execute("SELECT COUNT(*) c FROM problem_history").fetchone()["c"]
        assert count == 2

    def test_backfill_is_idempotent(self, fresh_db):
        with database.get_connection() as conn:
            _insert_raw_pre_v7_problem(conn, "p1", "A problem", "business", "2026-01-01T00:00:00Z")
            conn.commit()

            database._migrate_v7(conn)
            first_count = conn.execute(
                "SELECT COUNT(*) c FROM problem_history WHERE problem_id = 'p1'"
            ).fetchone()["c"]

            database._migrate_v7(conn)  # should be a no-op the second time
            second_count = conn.execute(
                "SELECT COUNT(*) c FROM problem_history WHERE problem_id = 'p1'"
            ).fetchone()["c"]

            assert first_count == second_count == 1

    def test_no_problems_is_a_clean_no_op(self, fresh_db):
        with database.get_connection() as conn:
            database._migrate_v7(conn)  # already ran once via initialize(); must be safe again
            count = conn.execute("SELECT COUNT(*) c FROM problem_history").fetchone()["c"]
        assert count == 0

    def test_problem_with_existing_history_is_not_double_backfilled(self, fresh_db):
        """A problem created after schema v7 already has its own real
        'created' event — the backfill must not add a second one."""
        with database.get_connection() as conn:
            _insert_raw_pre_v7_problem(conn, "p1", "A problem", "business", "2026-01-01T00:00:00Z")
            conn.execute(
                """
                INSERT INTO problem_history
                  (id, problem_id, domain, event_type, occurred_at, week_key, opportunity_id, metadata, created_at)
                VALUES ('h1', 'p1', 'business', 'created', '2026-01-01T00:00:00Z', '', '', '{}', '2026-01-01T00:00:00Z')
                """
            )
            conn.commit()
            database._migrate_v7(conn)
            count = conn.execute(
                "SELECT COUNT(*) c FROM problem_history WHERE problem_id = 'p1'"
            ).fetchone()["c"]
        assert count == 1
