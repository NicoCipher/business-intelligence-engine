"""
tests/test_problem_history.py — Tests for opportunity_engine/problem_history.py

Covers the write path (record_event) and read paths (list_for_problem,
count_for_problem) in isolation from canonicalizer.py's matching logic,
which has its own integration tests in test_canonicalizer.py.

Run with:
    cd backend && pytest tests/test_problem_history.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database
from models import Problem, ProblemHistoryEvent
from opportunity_engine import problem_history


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_problem_history.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()
    yield db_path


def _insert_problem(conn, id_="p1", domain="business"):
    problem = Problem(id=id_, title="A problem", domain=domain)
    row = problem.to_db_row()
    conn.execute(
        """
        INSERT INTO problems (id, domain, title, entity_ids, first_seen, last_seen, weeks_seen, created_at, updated_at)
        VALUES (:id, :domain, :title, :entity_ids, :first_seen, :last_seen, :weeks_seen, :created_at, :updated_at)
        """,
        row,
    )
    return problem


class TestModelValidation:
    def test_invalid_event_type_rejected(self):
        with pytest.raises(ValueError):
            ProblemHistoryEvent(problem_id="p1", event_type="not_a_real_type")

    def test_all_documented_event_types_accepted(self):
        for event_type in [
            "created", "evidence_added", "confidence_updated",
            "status_changed", "merged", "split",
        ]:
            ProblemHistoryEvent(problem_id="p1", event_type=event_type)  # must not raise


class TestRecordEvent:
    def test_record_event_persists_a_row(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            conn.commit()
            event_id = problem_history.record_event(conn, "p1", "business", "created")
            conn.commit()
            row = conn.execute("SELECT * FROM problem_history WHERE id = ?", (event_id,)).fetchone()
        assert row is not None
        assert row["problem_id"] == "p1"
        assert row["event_type"] == "created"
        assert row["domain"] == "business"

    def test_metadata_round_trips_through_json(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            conn.commit()
            problem_history.record_event(
                conn, "p1", "business", "evidence_added",
                metadata={"match_score": 0.83, "matched_title": "Something"},
            )
            conn.commit()
            events = problem_history.list_for_problem(conn, "p1")
        assert events[0].metadata == {"match_score": 0.83, "matched_title": "Something"}

    def test_opportunity_id_and_week_key_are_recorded(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            conn.commit()
            problem_history.record_event(
                conn, "p1", "business", "created",
                week_key="2026-W10", opportunity_id="opp-42",
            )
            conn.commit()
            events = problem_history.list_for_problem(conn, "p1")
        assert events[0].week_key == "2026-W10"
        assert events[0].opportunity_id == "opp-42"

    def test_default_metadata_is_empty_dict_not_none(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            conn.commit()
            problem_history.record_event(conn, "p1", "business", "created")
            conn.commit()
            events = problem_history.list_for_problem(conn, "p1")
        assert events[0].metadata == {}

    def test_never_updates_or_deletes_existing_rows(self, fresh_db):
        """Append-only by construction: two calls produce two rows, never
        one row mutated in place."""
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            conn.commit()
            problem_history.record_event(conn, "p1", "business", "created")
            problem_history.record_event(conn, "p1", "business", "evidence_added")
            conn.commit()
            count = problem_history.count_for_problem(conn, "p1")
        assert count == 2


class TestListForProblem:
    def test_returns_chronological_order(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            conn.commit()
            problem_history.record_event(conn, "p1", "business", "created", occurred_at="2026-01-01T00:00:00Z")
            problem_history.record_event(conn, "p1", "business", "evidence_added", occurred_at="2026-01-08T00:00:00Z")
            problem_history.record_event(conn, "p1", "business", "evidence_added", occurred_at="2026-01-15T00:00:00Z")
            conn.commit()
            events = problem_history.list_for_problem(conn, "p1")
        assert [e.occurred_at for e in events] == [
            "2026-01-01T00:00:00Z", "2026-01-08T00:00:00Z", "2026-01-15T00:00:00Z",
        ]

    def test_only_returns_events_for_the_requested_problem(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_problem(conn, "p2")
            conn.commit()
            problem_history.record_event(conn, "p1", "business", "created")
            problem_history.record_event(conn, "p2", "business", "created")
            conn.commit()
            events = problem_history.list_for_problem(conn, "p1")
        assert len(events) == 1
        assert events[0].problem_id == "p1"

    def test_limit_returns_oldest_events_not_most_recent(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            conn.commit()
            problem_history.record_event(conn, "p1", "business", "created", occurred_at="2026-01-01T00:00:00Z")
            problem_history.record_event(conn, "p1", "business", "evidence_added", occurred_at="2026-01-08T00:00:00Z")
            conn.commit()
            events = problem_history.list_for_problem(conn, "p1", limit=1)
        assert len(events) == 1
        assert events[0].occurred_at == "2026-01-01T00:00:00Z"

    def test_no_events_returns_empty_list(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            conn.commit()
            events = problem_history.list_for_problem(conn, "p1")
        assert events == []


class TestCountForProblem:
    def test_counts_without_materializing_rows(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            conn.commit()
            problem_history.record_event(conn, "p1", "business", "created")
            problem_history.record_event(conn, "p1", "business", "evidence_added")
            conn.commit()
            assert problem_history.count_for_problem(conn, "p1") == 2

    def test_zero_for_unknown_problem(self, fresh_db):
        with database.get_connection() as conn:
            assert problem_history.count_for_problem(conn, "does-not-exist") == 0
