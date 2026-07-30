"""
tests/test_canonicalizer.py — Tests for opportunity_engine/canonicalizer.py

Covers the actual headline capability from the architecture review:
the same pain point should not fragment into multiple opportunities
because of wording, as long as the underlying entities overlap.

Run with:
    cd backend && pytest tests/test_canonicalizer.py -v
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database
from opportunity_engine import canonicalizer, problem_history
from knowledge_graph.extractor import EntityExtractor


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_canonicalizer.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()
    yield db_path


def _insert_problem(conn, id_, title, domain, entity_ids, last_seen, weeks_seen=1):
    conn.execute(
        """
        INSERT INTO problems (id, domain, title, entity_ids, first_seen, last_seen, weeks_seen, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (id_, domain, title, json.dumps(entity_ids), last_seen, last_seen, weeks_seen, last_seen, last_seen),
    )


class TestResolveEntityIds:
    def test_empty_cluster_returns_empty_list(self, fresh_db):
        assert canonicalizer.resolve_entity_ids([], "business") == []

    def test_resolves_ids_for_extracted_entities(self, fresh_db, make_signal):
        extractor = EntityExtractor()
        sig = make_signal(title="Using Claude with Rust for automation")
        extractor.persist_results(extractor.extract_batch([sig]), domain="business")

        ids = canonicalizer.resolve_entity_ids([sig], "business")
        assert len(ids) >= 2  # Claude and Rust, at minimum

    def test_domain_scoping_only_resolves_within_domain(self, fresh_db, make_signal):
        extractor = EntityExtractor()
        sig = make_signal(title="Using Claude for automation")
        extractor.persist_results(extractor.extract_batch([sig]), domain="business")

        # Same entity extracted for cybersecurity, but never persisted there.
        ids = canonicalizer.resolve_entity_ids([sig], "cybersecurity")
        assert ids == []

    def test_no_matching_entities_returns_empty(self, fresh_db, make_signal):
        sig = make_signal(title="The quick brown fox jumps over the lazy dog")
        assert canonicalizer.resolve_entity_ids([sig], "business") == []


class TestFindMatch:
    def test_no_problems_at_all_returns_none(self, fresh_db):
        with database.get_connection() as conn:
            assert canonicalizer.find_match(["e1"], "Some title", "business", conn) is None

    def test_strong_entity_overlap_matches(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", "Therapist notes tool", "business",
                             ["e1", "e2", "e3"], "2026-01-01T00:00:00Z")
            conn.commit()
            match = canonicalizer.find_match(["e1", "e2"], "Clinical session documentation", "business", conn)
        assert match is not None
        assert match["problem_id"] == "p1"

    def test_no_entity_overlap_and_weak_title_overlap_does_not_match(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", "Therapist notes tool", "business",
                             ["e1", "e2"], "2026-01-01T00:00:00Z")
            conn.commit()
            match = canonicalizer.find_match(["e9", "e10"], "Completely unrelated invoice reconciliation", "business", conn)
        assert match is None

    def test_weak_entity_overlap_with_strong_title_overlap_matches(self, fresh_db):
        """Secondary path: some entity overlap + strong title support is
        also sufficient, even below the entity-alone threshold."""
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", "Therapist session notes automation tool", "business",
                             ["e1", "e2", "e3", "e4"], "2026-01-01T00:00:00Z")
            conn.commit()
            # Only 1 of 4 entities overlaps (below 0.5 alone), but title is nearly identical.
            match = canonicalizer.find_match(["e1", "e9", "e10", "e11"], "Therapist session notes automation", "business", conn)
        assert match is not None

    def test_domain_isolation_never_matches_across_domains(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", "Therapist notes tool", "cybersecurity",
                             ["e1", "e2", "e3"], "2026-01-01T00:00:00Z")
            conn.commit()
            match = canonicalizer.find_match(["e1", "e2", "e3"], "Therapist notes tool", "business", conn)
        assert match is None

    def test_best_match_chosen_among_multiple_candidates(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", "Weak match", "business", ["e1"], "2026-01-01T00:00:00Z")
            _insert_problem(conn, "p2", "Strong match", "business", ["e1", "e2", "e3"], "2026-01-01T00:00:00Z")
            conn.commit()
            match = canonicalizer.find_match(["e1", "e2", "e3"], "Strong match exactly", "business", conn)
        assert match["problem_id"] == "p2"


class TestResolveProblem:
    def test_no_match_creates_new_problem(self, fresh_db):
        with database.get_connection() as conn:
            problem_id, match = canonicalizer.resolve_problem(
                ["e1", "e2"], "A brand new pattern", "business", "2026-W01", conn,
            )
            conn.commit()
            row = conn.execute("SELECT * FROM problems WHERE id = ?", (problem_id,)).fetchone()
        assert match is None
        assert row["title"] == "A brand new pattern"
        assert row["weeks_seen"] == 1
        assert json.loads(row["entity_ids"]) == ["e1", "e2"]

    def test_match_links_to_existing_problem(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", "Therapist notes tool", "business",
                             ["e1", "e2", "e3"], "2026-01-01T00:00:00Z")
            conn.commit()
            problem_id, match = canonicalizer.resolve_problem(
                ["e1", "e2"], "Clinical session documentation", "business", "2026-W02", conn,
            )
        assert problem_id == "p1"
        assert match is not None

    def test_entity_ids_accumulate_as_union_on_match(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", "Therapist notes tool", "business",
                             ["e1", "e2"], "2026-01-01T00:00:00Z")
            conn.commit()
            # jaccard({e1,e2}, {e1,e2,e3}) = 2/3 >= 0.5 -> clears the match threshold.
            canonicalizer.resolve_problem(["e1", "e2", "e3"], "Therapist notes tool variant", "business", "2026-W02", conn)
            conn.commit()
            row = conn.execute("SELECT entity_ids FROM problems WHERE id = 'p1'").fetchone()
        assert set(json.loads(row["entity_ids"])) == {"e1", "e2", "e3"}

    def test_weeks_seen_increments_on_new_week(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", "Therapist notes tool", "business",
                             ["e1", "e2"], "2026-01-01T00:00:00Z", weeks_seen=1)  # 2026-W01
            conn.commit()
            canonicalizer.resolve_problem(["e1", "e2"], "Same pattern", "business", "2026-W02", conn)
            conn.commit()
            row = conn.execute("SELECT weeks_seen FROM problems WHERE id = 'p1'").fetchone()
        assert row["weeks_seen"] == 2

    def test_weeks_seen_does_not_double_count_within_same_week(self, fresh_db):
        """Two different clusters in the same pipeline run matching the
        same Problem must not inflate weeks_seen by more than one real week."""
        from datetime import date
        # A timestamp that genuinely falls within ISO week 2026-W01, computed
        # rather than guessed, to avoid exactly this kind of off-by-one bug.
        w01_timestamp = date.fromisocalendar(2026, 1, 3).isoformat() + "T00:00:00Z"

        with database.get_connection() as conn:
            _insert_problem(conn, "p1", "Therapist notes tool", "business",
                             ["e1", "e2"], w01_timestamp, weeks_seen=1)
            conn.commit()
            # Same week (2026-W01) as the problem's last_seen.
            canonicalizer.resolve_problem(["e1", "e2"], "Same pattern, different signal", "business", "2026-W01", conn)
            conn.commit()
            row = conn.execute("SELECT weeks_seen FROM problems WHERE id = 'p1'").fetchone()
        assert row["weeks_seen"] == 1

    def test_domain_isolation_creates_separate_problems(self, fresh_db):
        with database.get_connection() as conn:
            biz_id, _ = canonicalizer.resolve_problem(["e1"], "Same title", "business", "2026-W01", conn)
            conn.commit()
            sec_id, match = canonicalizer.resolve_problem(["e1"], "Same title", "cybersecurity", "2026-W01", conn)
            conn.commit()
        assert biz_id != sec_id
        assert match is None  # cybersecurity has no prior problems of its own


class TestResolveProblemHistory:
    """
    Schema v7: resolve_problem must write exactly one problem_history
    event per call, in the same transaction as the problems table write,
    so a Problem row and its origin event can never diverge.
    """

    def test_new_problem_writes_a_created_event(self, fresh_db):
        with database.get_connection() as conn:
            problem_id, _ = canonicalizer.resolve_problem(
                ["e1", "e2"], "A brand new pattern", "business", "2026-W01", conn,
            )
            conn.commit()
            events = problem_history.list_for_problem(conn, problem_id)
        assert len(events) == 1
        assert events[0].event_type == "created"
        assert events[0].metadata["title"] == "A brand new pattern"
        assert events[0].metadata["entity_count"] == 2

    def test_match_writes_an_evidence_added_event(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", "Therapist notes tool", "business",
                             ["e1", "e2", "e3"], "2026-01-01T00:00:00Z")
            conn.commit()
            problem_id, match = canonicalizer.resolve_problem(
                ["e1", "e2"], "Clinical session documentation", "business", "2026-W02", conn,
            )
            conn.commit()
            events = problem_history.list_for_problem(conn, "p1")
        assert len(events) == 1
        assert events[0].event_type == "evidence_added"
        assert events[0].metadata["match_score"] == match["match_score"]
        assert events[0].metadata["title"] == "Clinical session documentation"

    def test_repeated_matches_accumulate_multiple_events(self, fresh_db):
        with database.get_connection() as conn:
            problem_id, _ = canonicalizer.resolve_problem(
                ["e1", "e2"], "Original pattern", "business", "2026-W01", conn,
            )
            conn.commit()
            canonicalizer.resolve_problem(
                ["e1", "e2"], "Same pattern, week 2", "business", "2026-W02", conn,
            )
            conn.commit()
            canonicalizer.resolve_problem(
                ["e1", "e2"], "Same pattern, week 3", "business", "2026-W03", conn,
            )
            conn.commit()
            events = problem_history.list_for_problem(conn, problem_id)
        assert [e.event_type for e in events] == ["created", "evidence_added", "evidence_added"]

    def test_opportunity_id_is_threaded_through_to_the_event(self, fresh_db):
        with database.get_connection() as conn:
            problem_id, _ = canonicalizer.resolve_problem(
                ["e1"], "A pattern", "business", "2026-W01", conn,
                opportunity_id="opp-123",
            )
            conn.commit()
            events = problem_history.list_for_problem(conn, problem_id)
        assert events[0].opportunity_id == "opp-123"

    def test_opportunity_id_defaults_to_empty_string(self, fresh_db):
        """Backward compatibility: existing callers that don't pass
        opportunity_id must keep working, and the event is still recorded."""
        with database.get_connection() as conn:
            problem_id, _ = canonicalizer.resolve_problem(
                ["e1"], "A pattern", "business", "2026-W01", conn,
            )
            conn.commit()
            events = problem_history.list_for_problem(conn, problem_id)
        assert events[0].opportunity_id == ""

    def test_history_event_domain_matches_problem_domain(self, fresh_db):
        with database.get_connection() as conn:
            problem_id, _ = canonicalizer.resolve_problem(
                ["e1"], "A pattern", "cybersecurity", "2026-W01", conn,
            )
            conn.commit()
            events = problem_history.list_for_problem(conn, problem_id)
        assert events[0].domain == "cybersecurity"
