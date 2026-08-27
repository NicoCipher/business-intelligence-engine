"""
tests/test_change_detection.py — Tests for opportunity_engine/change_detection.py
(Change Detection V1, Stage 3.6).

Run with:
    cd backend && pytest tests/test_change_detection.py -v
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database
import pipeline
from opportunity_engine import change_detection, problem_history
from models import Problem


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_change_detection.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()
    yield db_path


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _days_ago(days: float) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(days=days))


def _far_past() -> str:
    """A `since` bound early enough to sweep up every fixture row below."""
    return _days_ago(3650)


def _insert_problem(conn, id_, domain="business", title="Test problem"):
    problem = Problem(id=id_, title=title, domain=domain)
    row = problem.to_db_row()
    conn.execute(
        """
        INSERT INTO problems
          (id, domain, title, entity_ids, first_seen, last_seen, weeks_seen, created_at, updated_at,
           lifecycle_state, lifecycle_updated_at, trend, trend_updated_at)
        VALUES
          (:id, :domain, :title, :entity_ids, :first_seen, :last_seen, :weeks_seen, :created_at, :updated_at,
           :lifecycle_state, :lifecycle_updated_at, :trend, :trend_updated_at)
        """,
        row,
    )
    return problem


def _record_history(conn, problem_id, domain, event_type, metadata=None, occurred_at=None):
    return problem_history.record_event(
        conn, problem_id, domain, event_type,
        metadata=metadata or {}, occurred_at=occurred_at,
    )


def _insert_opportunity(conn, id_, problem_id, domain="business", tier="bronze", composite=6.0, created_at=None):
    """Minimal direct insert -- mirrors exactly what OpportunityScores.to_dict()
    always includes ('tier', 'composite'), without needing to construct a
    full OpportunityScores object with real dimension weights."""
    scores = json.dumps({"tier": tier, "composite": composite, "evidence_count": 2})
    now = created_at or database._now()
    conn.execute(
        """
        INSERT INTO opportunities
            (id, title, description, signal_ids, entity_ids, scores, composite_score,
             status, week_key, created_at, updated_at, domain, problem_id)
        VALUES (?, ?, ?, '[]', '[]', ?, ?, 'new', '2026-W01', ?, ?, ?, ?)
        """,
        (id_, f"Opportunity {id_}", "desc", scores, composite, now, now, domain, problem_id),
    )


# ── Event mapping + significance ─────────────────────────────────────────

class TestProblemCreatedProjection:
    def test_created_event_maps_to_problem_created_high_significance(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _record_history(conn, "p1", "business", "created", metadata={"title": "x"})
            conn.commit()
            events = change_detection.detect_problem_changes(conn, "business", _far_past())

        assert len(events) == 1
        assert events[0]["event_type"] == "problem_created"
        assert events[0]["significance"] == "high"
        assert events[0]["entity_ref_type"] == "problem"
        assert events[0]["entity_ref_id"] == "p1"


class TestLifecycleProjection:
    def test_archived_to_reactivated_is_high_significance(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _record_history(conn, "p1", "business", "status_changed",
                             metadata={"axis": "lifecycle", "from_state": "archived", "to_state": "reactivated"})
            conn.commit()
            events = change_detection.detect_problem_changes(conn, "business", _far_past())

        assert len(events) == 1
        assert events[0]["event_type"] == "problem_lifecycle_changed"
        assert events[0]["significance"] == "high"
        assert events[0]["previous_value"] == "archived"
        assert events[0]["new_value"] == "reactivated"

    @pytest.mark.parametrize("from_state,to_state", [
        ("new", "active"),
        ("active", "dormant"),
        ("dormant", "archived"),
        ("reactivated", "active"),
    ])
    def test_other_lifecycle_transitions_are_normal_significance(self, fresh_db, from_state, to_state):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _record_history(conn, "p1", "business", "status_changed",
                             metadata={"axis": "lifecycle", "from_state": from_state, "to_state": to_state})
            conn.commit()
            events = change_detection.detect_problem_changes(conn, "business", _far_past())

        assert events[0]["significance"] == "normal"
        assert events[0]["event_type"] == "problem_lifecycle_changed"


class TestTrendProjection:
    def test_growing_trend_is_high_significance(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _record_history(conn, "p1", "business", "status_changed",
                             metadata={"axis": "trend", "from_state": "stable", "to_state": "growing"})
            conn.commit()
            events = change_detection.detect_problem_changes(conn, "business", _far_past())

        assert events[0]["event_type"] == "problem_trend_changed"
        assert events[0]["significance"] == "high"

    @pytest.mark.parametrize("to_state", ["stable", "declining", "unknown"])
    def test_non_growing_trend_is_normal_significance(self, fresh_db, to_state):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _record_history(conn, "p1", "business", "status_changed",
                             metadata={"axis": "trend", "from_state": "growing", "to_state": to_state})
            conn.commit()
            events = change_detection.detect_problem_changes(conn, "business", _far_past())

        assert events[0]["significance"] == "normal"


class TestUnrecognizedAxisIsDefensive:
    def test_unknown_axis_is_skipped_not_crashed(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _record_history(conn, "p1", "business", "status_changed",
                             metadata={"axis": "something_new", "from_state": "a", "to_state": "b"})
            conn.commit()
            events = change_detection.detect_problem_changes(conn, "business", _far_past())

        assert events == []


# ── evidence_added suppression ───────────────────────────────────────────

class TestEvidenceAddedSuppression:
    def test_evidence_added_never_produces_an_event(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _record_history(conn, "p1", "business", "created")
            _record_history(conn, "p1", "business", "evidence_added", metadata={"match_score": 0.9})
            _record_history(conn, "p1", "business", "evidence_added", metadata={"match_score": 0.95})
            conn.commit()
            events = change_detection.detect_problem_changes(conn, "business", _far_past())

        # Only the single 'created' event should be projected.
        assert len(events) == 1
        assert events[0]["event_type"] == "problem_created"


# ── Opportunity: first-ever, recurrence suppression, tier crossing ──────

class TestFirstEverOpportunity:
    def test_first_opportunity_for_a_problem_emits_new_opportunity(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_opportunity(conn, "o1", "p1", tier="silver")
            conn.commit()
            events = change_detection.detect_opportunity_changes(conn, "business", _far_past())

        assert len(events) == 1
        assert events[0]["event_type"] == "new_opportunity"
        assert events[0]["entity_ref_type"] == "opportunity"
        assert events[0]["entity_ref_id"] == "o1"
        assert events[0]["new_value"] == "silver"
        assert events[0]["significance"] == "normal"

    def test_opportunity_with_no_problem_link_is_ignored(self, fresh_db):
        with database.get_connection() as conn:
            _insert_opportunity(conn, "o1", "", tier="gold")
            conn.commit()
            events = change_detection.detect_opportunity_changes(conn, "business", _far_past())

        assert events == []


class TestSameTierRecurrenceSuppression:
    def test_second_opportunity_same_tier_emits_nothing(self, fresh_db):
        t0 = _days_ago(10)
        t1 = _days_ago(1)
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_opportunity(conn, "o1", "p1", tier="silver", created_at=t0)
            conn.commit()
            # First opportunity already "processed" in an earlier run.
            _insert_opportunity(conn, "o2", "p1", tier="silver", created_at=t1)
            conn.commit()
            # Only look at what's new "this run" -- o2.
            events = change_detection.detect_opportunity_changes(conn, "business", since=t1)

        assert events == []


class TestTierCrossing:
    def test_upward_crossing_bronze_to_silver_is_normal(self, fresh_db):
        t0, t1 = _days_ago(10), _days_ago(1)
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_opportunity(conn, "o1", "p1", tier="bronze", created_at=t0)
            conn.commit()
            _insert_opportunity(conn, "o2", "p1", tier="silver", created_at=t1)
            conn.commit()
            events = change_detection.detect_opportunity_changes(conn, "business", since=t1)

        assert len(events) == 1
        assert events[0]["event_type"] == "opportunity_tier_crossed"
        assert events[0]["previous_value"] == "bronze"
        assert events[0]["new_value"] == "silver"
        assert events[0]["significance"] == "normal"

    def test_upward_crossing_into_gold_is_high(self, fresh_db):
        t0, t1 = _days_ago(10), _days_ago(1)
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_opportunity(conn, "o1", "p1", tier="silver", created_at=t0)
            conn.commit()
            _insert_opportunity(conn, "o2", "p1", tier="gold", created_at=t1)
            conn.commit()
            events = change_detection.detect_opportunity_changes(conn, "business", since=t1)

        assert events[0]["event_type"] == "opportunity_tier_crossed"
        assert events[0]["new_value"] == "gold"
        assert events[0]["significance"] == "high"

    def test_downward_crossing_is_kept_and_normal(self, fresh_db):
        t0, t1 = _days_ago(10), _days_ago(1)
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_opportunity(conn, "o1", "p1", tier="gold", created_at=t0)
            conn.commit()
            _insert_opportunity(conn, "o2", "p1", tier="bronze", created_at=t1)
            conn.commit()
            events = change_detection.detect_opportunity_changes(conn, "business", since=t1)

        assert len(events) == 1
        assert events[0]["event_type"] == "opportunity_tier_crossed"
        assert events[0]["previous_value"] == "gold"
        assert events[0]["new_value"] == "bronze"
        assert events[0]["significance"] == "normal"


# ── Idempotency / reprocessing ────────────────────────────────────────────

class TestIdempotency:
    def test_running_detection_twice_does_not_duplicate_events(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _record_history(conn, "p1", "business", "created")
            _record_history(conn, "p1", "business", "status_changed",
                             metadata={"axis": "trend", "from_state": "unknown", "to_state": "growing"})
            _insert_opportunity(conn, "o1", "p1", tier="gold")
            conn.commit()

            first = change_detection.run_change_detection(conn, "business", since=_far_past())
            second = change_detection.run_change_detection(conn, "business", since=_far_past())

            total = conn.execute("SELECT COUNT(*) c FROM change_events").fetchone()["c"]

        assert first["written"] == 3          # created + trend_changed + new_opportunity
        assert second["written"] == 0
        assert second["skipped_duplicate"] == 3
        assert total == 3

    def test_deterministic_id_is_stable_across_separate_calls(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            event_id = _record_history(conn, "p1", "business", "created")
            conn.commit()
            events_a = change_detection.detect_problem_changes(conn, "business", _far_past())
            events_b = change_detection.detect_problem_changes(conn, "business", _far_past())

        assert events_a[0]["id"] == events_b[0]["id"]
        # And it's derived from the source row, not random -- same source
        # event id always yields the same change_events id.
        expected = change_detection._deterministic_id("problem_history", event_id)
        assert events_a[0]["id"] == expected


# ── since boundary: efficiency bound only, never a correctness risk ─────

class TestSinceBoundaryIsEfficiencyOnly:
    def test_event_exactly_on_since_boundary_is_included(self, fresh_db):
        """occurred_at >= since is inclusive -- an event landing exactly
        on the boundary must not be lost."""
        boundary = _days_ago(1)
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _record_history(conn, "p1", "business", "created", occurred_at=boundary)
            conn.commit()
            events = change_detection.detect_problem_changes(conn, "business", since=boundary)

        assert len(events) == 1
        assert events[0]["event_type"] == "problem_created"

    def test_event_just_before_since_is_excluded_by_the_bound(self, fresh_db):
        """Confirms the bound is a real filter, not accidentally
        permissive -- a row strictly before `since` is not swept up."""
        before = _days_ago(2)
        since = _days_ago(1)
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _record_history(conn, "p1", "business", "created", occurred_at=before)
            conn.commit()
            events = change_detection.detect_problem_changes(conn, "business", since=since)

        assert events == []

    def test_an_earlier_since_never_produces_a_duplicate_of_an_already_written_event(self, fresh_db):
        """The `since` bound is efficiency-only: even if a second call
        uses a `since` early enough to re-sweep a row a prior call
        already projected and wrote, the deterministic id makes the
        re-INSERT a no-op -- no possible value of `since` can cause a
        duplicate change_events row. This is the property that lets
        `since` be conservative/early without any correctness cost."""
        early_event_at = _days_ago(10)
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _record_history(conn, "p1", "business", "created", occurred_at=early_event_at)
            conn.commit()

            # First run: since is tight, right at the event's own timestamp.
            first = change_detection.run_change_detection(conn, "business", since=early_event_at)
            # Second run: since is much earlier, re-sweeping the same
            # already-projected row into the query results again.
            second = change_detection.run_change_detection(conn, "business", since=_days_ago(3650))

            total = conn.execute("SELECT COUNT(*) c FROM change_events").fetchone()["c"]

        assert first["written"] == 1
        assert second["written"] == 0
        assert second["skipped_duplicate"] == 1
        assert total == 1


# ── Domain isolation ──────────────────────────────────────────────────────

class TestDomainIsolation:
    def test_events_are_scoped_to_the_requesting_domain(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", domain="business")
            _insert_problem(conn, "p2", domain="other_domain")
            _record_history(conn, "p1", "business", "created")
            _record_history(conn, "p2", "other_domain", "created")
            conn.commit()

            business_events = change_detection.detect_problem_changes(conn, "business", _far_past())
            other_events = change_detection.detect_problem_changes(conn, "other_domain", _far_past())

        assert len(business_events) == 1
        assert business_events[0]["entity_ref_id"] == "p1"
        assert len(other_events) == 1
        assert other_events[0]["entity_ref_id"] == "p2"

    def test_run_change_detection_writes_only_for_its_own_domain(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", domain="business")
            _insert_problem(conn, "p2", domain="other_domain")
            _record_history(conn, "p1", "business", "created")
            _record_history(conn, "p2", "other_domain", "created")
            conn.commit()

            change_detection.run_change_detection(conn, "business", since=_far_past())

            rows = conn.execute("SELECT domain, entity_ref_id FROM change_events").fetchall()

        assert len(rows) == 1
        assert rows[0]["domain"] == "business"
        assert rows[0]["entity_ref_id"] == "p1"


# ── Stage 3.6 pipeline integration: failure isolation + dry-run ─────────

class TestStage36PipelineIntegration:
    def test_change_detection_failure_does_not_crash_pipeline_run(self, fresh_db, monkeypatch):
        from domains.business import DOMAIN_CONFIG as BUSINESS_DOMAIN_CONFIG

        def _boom(conn, domain, since):
            raise RuntimeError("simulated change-detection failure")

        monkeypatch.setattr(pipeline.change_detection, "run_change_detection", _boom)

        # No signals -> Stage 3 (detection) is skipped, but Stage 3.5/3.6
        # still run unconditionally when not dry_run, so this alone is
        # enough to exercise Stage 3.6's failure-isolation branch without
        # needing real collector data.
        result = pipeline._run_domain(
            BUSINESS_DOMAIN_CONFIG,
            shared_hn_signals=[],
            dry_run=False,
            hn_only=False,
            generate_report=False,
            collected_source_signals={"reddit": [], "rss": [], "github": [], "trends": []},
        )

        # The pipeline call itself must not raise, and other stage
        # bookkeeping must still be present (failure isolation).
        assert result.change_events_recorded == 0
        assert result.domain_id == BUSINESS_DOMAIN_CONFIG.id

    def test_dry_run_writes_no_change_events(self, fresh_db, monkeypatch):
        from domains.business import DOMAIN_CONFIG as BUSINESS_DOMAIN_CONFIG

        fixed_now = "2026-01-01T00:00:00.000000+00:00"
        monkeypatch.setattr(database, "_now", lambda: fixed_now)

        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _record_history(conn, "p1", "business", "created", occurred_at=fixed_now)
            conn.commit()

        result = pipeline._run_domain(
            BUSINESS_DOMAIN_CONFIG,
            shared_hn_signals=[],
            dry_run=True,
            hn_only=False,
            generate_report=False,
            collected_source_signals={"reddit": [], "rss": [], "github": [], "trends": []},
        )

        with database.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) c FROM change_events").fetchone()["c"]

        assert count == 0
        assert result.change_events_recorded == 0

    def test_normal_run_records_change_events_via_pipeline(self, fresh_db, monkeypatch):
        from domains.business import DOMAIN_CONFIG as BUSINESS_DOMAIN_CONFIG

        # Stage 3.6 bounds its query at run_started_at = database._now(),
        # captured fresh inside _run_domain -- fixing _now() lets this
        # fixture's occurred_at land exactly on that bound (>=), rather
        # than racing real wall-clock time between the fixture write
        # above and _run_domain's own capture below.
        fixed_now = "2026-01-01T00:00:00.000000+00:00"
        monkeypatch.setattr(database, "_now", lambda: fixed_now)

        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _record_history(conn, "p1", "business", "created", occurred_at=fixed_now)
            conn.commit()

        result = pipeline._run_domain(
            BUSINESS_DOMAIN_CONFIG,
            shared_hn_signals=[],
            dry_run=False,
            hn_only=False,
            generate_report=False,
            collected_source_signals={"reddit": [], "rss": [], "github": [], "trends": []},
        )

        assert result.change_events_recorded == 1
        with database.get_connection() as conn:
            row = conn.execute("SELECT event_type FROM change_events").fetchone()
        assert row["event_type"] == "problem_created"
