"""
tests/test_lifecycle.py — Tests for opportunity_engine/lifecycle.py
(schema v9): the two independent Problem axes (lifecycle_state, trend)
and the full run_lifecycle_pass() / reactivate_if_archived() integration.

Run with:
    cd backend && pytest tests/test_lifecycle.py -v
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
import database
from opportunity_engine import lifecycle, problem_history
from models import Problem


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _days_ago(days: float) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(days=days))


# ── Pure trend classification ───────────────────────────────────────────

class TestClassifyTrend:
    def test_recent_much_higher_than_prior_is_growing(self):
        assert lifecycle.classify_trend(recent_count=10, prior_count=2) == "growing"

    def test_recent_much_lower_than_prior_is_declining(self):
        assert lifecycle.classify_trend(recent_count=1, prior_count=10) == "declining"

    def test_recent_similar_to_prior_is_stable(self):
        assert lifecycle.classify_trend(recent_count=5, prior_count=5) == "stable"

    def test_exactly_at_growth_ratio_is_growing(self):
        assert lifecycle.classify_trend(recent_count=3, prior_count=2) == "growing"

    def test_exactly_at_decline_ratio_is_declining(self):
        assert lifecycle.classify_trend(recent_count=2, prior_count=4) == "declining"

    def test_zero_prior_with_recent_evidence_is_growing(self):
        assert lifecycle.classify_trend(recent_count=3, prior_count=0) == "growing"

    def test_zero_both_is_stable_not_a_crash(self):
        assert lifecycle.classify_trend(recent_count=0, prior_count=0) == "stable"


# ── run_lifecycle_pass() / reactivate_if_archived() integration ────────

@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_lifecycle.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()
    yield db_path


def _insert_problem(conn, id_, domain="business", weeks_seen=1, first_seen_days_ago=1,
                     last_seen_days_ago=1, lifecycle_state="new", trend="unknown"):
    problem = Problem(
        id=id_, title=f"Problem {id_}", domain=domain, weeks_seen=weeks_seen,
        first_seen=_days_ago(first_seen_days_ago), last_seen=_days_ago(last_seen_days_ago),
        lifecycle_state=lifecycle_state, trend=trend,
    )
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


def _add_evidence_event(conn, problem_id, domain, days_ago, event_type="evidence_added"):
    problem_history.record_event(
        conn, problem_id, domain, event_type, occurred_at=_days_ago(days_ago),
    )


class TestLifecycleStateNewAndActive:
    def test_below_recurrence_threshold_stays_new(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", weeks_seen=1, first_seen_days_ago=1, last_seen_days_ago=1)
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            state = conn.execute("SELECT lifecycle_state FROM problems WHERE id='p1'").fetchone()["lifecycle_state"]
        assert state == "new"

    def test_recurrence_threshold_met_becomes_active(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(
                conn, "p1", weeks_seen=config.PROBLEM_RECURRENCE_WEEKS,
                first_seen_days_ago=5, last_seen_days_ago=1,
            )
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            state = conn.execute("SELECT lifecycle_state FROM problems WHERE id='p1'").fetchone()["lifecycle_state"]
        assert state == "active"

    def test_trend_stays_unknown_without_enough_history(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(
                conn, "p1", weeks_seen=config.PROBLEM_RECURRENCE_WEEKS,
                first_seen_days_ago=5, last_seen_days_ago=1,
            )
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            trend = conn.execute("SELECT trend FROM problems WHERE id='p1'").fetchone()["trend"]
        assert trend == "unknown"


class TestLifecycleStateDormantAndArchived:
    def test_quiet_past_dormant_threshold_becomes_dormant(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(
                conn, "p1", weeks_seen=5, first_seen_days_ago=200,
                last_seen_days_ago=config.PROBLEM_DORMANT_DAYS + 5,
                lifecycle_state="active",
            )
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            state = conn.execute("SELECT lifecycle_state FROM problems WHERE id='p1'").fetchone()["lifecycle_state"]
        assert state == "dormant"

    def test_quiet_past_archive_threshold_becomes_archived_regardless_of_current_state(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(
                conn, "p1", weeks_seen=10, first_seen_days_ago=400,
                last_seen_days_ago=config.PROBLEM_ARCHIVE_DAYS + 5,
                lifecycle_state="dormant",
            )
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            state = conn.execute("SELECT lifecycle_state FROM problems WHERE id='p1'").fetchone()["lifecycle_state"]
        assert state == "archived"

    def test_archival_writes_a_status_changed_event_tagged_lifecycle_axis(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(
                conn, "p1", weeks_seen=1, first_seen_days_ago=200,
                last_seen_days_ago=config.PROBLEM_ARCHIVE_DAYS + 5,
            )
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            events = problem_history.list_for_problem(conn, "p1")
        status_changed = [e for e in events if e.event_type == "status_changed"]
        assert len(status_changed) == 1
        assert status_changed[0].metadata["axis"] == "lifecycle"
        assert status_changed[0].metadata["to_state"] == "archived"

    def test_never_deletes_the_problem_row(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(
                conn, "p1", weeks_seen=1, first_seen_days_ago=200,
                last_seen_days_ago=config.PROBLEM_ARCHIVE_DAYS + 5,
            )
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            count = conn.execute("SELECT COUNT(*) c FROM problems WHERE id='p1'").fetchone()["c"]
        assert count == 1

    def test_already_archived_problem_is_not_re_evaluated(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(
                conn, "p1", weeks_seen=1, first_seen_days_ago=200,
                last_seen_days_ago=1, lifecycle_state="archived",
            )
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            events = problem_history.list_for_problem(conn, "p1")
        assert events == []

    def test_domain_isolation(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(
                conn, "p1", domain="business", weeks_seen=1, first_seen_days_ago=200,
                last_seen_days_ago=config.PROBLEM_ARCHIVE_DAYS + 5,
            )
            _insert_problem(
                conn, "p2", domain="cybersecurity", weeks_seen=1, first_seen_days_ago=200,
                last_seen_days_ago=config.PROBLEM_ARCHIVE_DAYS + 5,
            )
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            biz_state = conn.execute("SELECT lifecycle_state FROM problems WHERE id='p1'").fetchone()["lifecycle_state"]
            sec_state = conn.execute("SELECT lifecycle_state FROM problems WHERE id='p2'").fetchone()["lifecycle_state"]
        assert biz_state == "archived"
        assert sec_state == "new"  # untouched -- different domain

    def test_trend_not_evaluated_for_a_problem_that_archives_this_pass(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(
                conn, "p1", weeks_seen=10, first_seen_days_ago=400,
                last_seen_days_ago=config.PROBLEM_ARCHIVE_DAYS + 5,
                lifecycle_state="mature" if False else "active", trend="growing",
            )
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            problem = conn.execute("SELECT * FROM problems WHERE id='p1'").fetchone()
        assert problem["lifecycle_state"] == "archived"
        assert problem["trend"] == "growing"  # left untouched, not recomputed


class TestTrendClassificationIndependentOfLifecycle:
    def test_growing_problem_classified_correctly(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(
                conn, "p1", weeks_seen=10,
                first_seen_days_ago=config.PROBLEM_TREND_WINDOW_DAYS * 2 + 5,
                last_seen_days_ago=1, lifecycle_state="active",
            )
            conn.commit()
            for _ in range(2):
                _add_evidence_event(conn, "p1", "business", days_ago=config.PROBLEM_TREND_WINDOW_DAYS * 1.5)
            for _ in range(8):
                _add_evidence_event(conn, "p1", "business", days_ago=config.PROBLEM_TREND_WINDOW_DAYS * 0.5)
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            problem = conn.execute("SELECT * FROM problems WHERE id='p1'").fetchone()
        assert problem["trend"] == "growing"
        assert problem["lifecycle_state"] == "active"  # unaffected by trend classification

    def test_declining_problem_classified_correctly(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(
                conn, "p1", weeks_seen=10,
                first_seen_days_ago=config.PROBLEM_TREND_WINDOW_DAYS * 2 + 5,
                last_seen_days_ago=1, lifecycle_state="active",
            )
            conn.commit()
            for _ in range(8):
                _add_evidence_event(conn, "p1", "business", days_ago=config.PROBLEM_TREND_WINDOW_DAYS * 1.5)
            for _ in range(2):
                _add_evidence_event(conn, "p1", "business", days_ago=config.PROBLEM_TREND_WINDOW_DAYS * 0.5)
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            trend = conn.execute("SELECT trend FROM problems WHERE id='p1'").fetchone()["trend"]
        assert trend == "declining"

    def test_stable_cadence_classified_as_stable(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(
                conn, "p1", weeks_seen=10,
                first_seen_days_ago=config.PROBLEM_TREND_WINDOW_DAYS * 2 + 5,
                last_seen_days_ago=1, lifecycle_state="active",
            )
            conn.commit()
            for _ in range(4):
                _add_evidence_event(conn, "p1", "business", days_ago=config.PROBLEM_TREND_WINDOW_DAYS * 1.5)
            for _ in range(4):
                _add_evidence_event(conn, "p1", "business", days_ago=config.PROBLEM_TREND_WINDOW_DAYS * 0.5)
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            trend = conn.execute("SELECT trend FROM problems WHERE id='p1'").fetchone()["trend"]
        assert trend == "stable"

    def test_can_move_between_trend_states_across_passes(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(
                conn, "p1", weeks_seen=10,
                first_seen_days_ago=config.PROBLEM_TREND_WINDOW_DAYS * 2 + 5,
                last_seen_days_ago=1, lifecycle_state="active", trend="growing",
            )
            conn.commit()
            for _ in range(8):
                _add_evidence_event(conn, "p1", "business", days_ago=config.PROBLEM_TREND_WINDOW_DAYS * 1.5)
            for _ in range(1):
                _add_evidence_event(conn, "p1", "business", days_ago=config.PROBLEM_TREND_WINDOW_DAYS * 0.5)
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            trend = conn.execute("SELECT trend FROM problems WHERE id='p1'").fetchone()["trend"]
        assert trend == "declining"

    def test_trend_transition_writes_status_changed_tagged_trend_axis(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(
                conn, "p1", weeks_seen=10,
                first_seen_days_ago=config.PROBLEM_TREND_WINDOW_DAYS * 2 + 5,
                last_seen_days_ago=1, lifecycle_state="active",
            )
            conn.commit()
            for _ in range(2):
                _add_evidence_event(conn, "p1", "business", days_ago=config.PROBLEM_TREND_WINDOW_DAYS * 1.5)
            for _ in range(8):
                _add_evidence_event(conn, "p1", "business", days_ago=config.PROBLEM_TREND_WINDOW_DAYS * 0.5)
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            events = problem_history.list_for_problem(conn, "p1")
        trend_events = [e for e in events if e.event_type == "status_changed" and e.metadata.get("axis") == "trend"]
        assert len(trend_events) == 1
        assert trend_events[0].metadata["to_state"] == "growing"
        assert "recent_count" in trend_events[0].metadata


class TestReactivateIfArchived:
    def test_reactivates_an_archived_problem(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", lifecycle_state="archived")
            conn.commit()
            from models import _now
            result = lifecycle.reactivate_if_archived(conn, "p1", "business", _now())
            conn.commit()
            state = conn.execute("SELECT lifecycle_state FROM problems WHERE id='p1'").fetchone()["lifecycle_state"]
        assert result is True
        assert state == "reactivated"

    def test_resets_trend_to_unknown(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", lifecycle_state="archived", trend="declining")
            conn.commit()
            from models import _now
            lifecycle.reactivate_if_archived(conn, "p1", "business", _now())
            conn.commit()
            trend = conn.execute("SELECT trend FROM problems WHERE id='p1'").fetchone()["trend"]
        assert trend == "unknown"

    def test_writes_one_status_changed_event_per_axis_that_changed(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", lifecycle_state="archived", trend="declining")
            conn.commit()
            from models import _now
            lifecycle.reactivate_if_archived(conn, "p1", "business", _now())
            conn.commit()
            events = problem_history.list_for_problem(conn, "p1")
        axes = sorted(e.metadata["axis"] for e in events if e.event_type == "status_changed")
        assert axes == ["lifecycle", "trend"]

    def test_no_extra_trend_event_if_trend_was_already_unknown(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", lifecycle_state="archived", trend="unknown")
            conn.commit()
            from models import _now
            lifecycle.reactivate_if_archived(conn, "p1", "business", _now())
            conn.commit()
            events = problem_history.list_for_problem(conn, "p1")
        axes = [e.metadata["axis"] for e in events if e.event_type == "status_changed"]
        assert axes == ["lifecycle"]

    def test_no_op_on_a_non_archived_problem(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", lifecycle_state="active")
            conn.commit()
            from models import _now
            result = lifecycle.reactivate_if_archived(conn, "p1", "business", _now())
            conn.commit()
            state = conn.execute("SELECT lifecycle_state FROM problems WHERE id='p1'").fetchone()["lifecycle_state"]
        assert result is False
        assert state == "active"

    def test_no_op_on_unknown_problem_id(self, fresh_db):
        with database.get_connection() as conn:
            from models import _now
            result = lifecycle.reactivate_if_archived(conn, "does-not-exist", "business", _now())
        assert result is False

    def test_reactivated_promotes_to_active_on_next_pass(self, fresh_db):
        with database.get_connection() as conn:
            _insert_problem(
                conn, "p1", weeks_seen=5, first_seen_days_ago=300, last_seen_days_ago=1,
                lifecycle_state="reactivated",
            )
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            state = conn.execute("SELECT lifecycle_state FROM problems WHERE id='p1'").fetchone()["lifecycle_state"]
        assert state == "active"

    def test_reactivated_still_archives_if_it_immediately_goes_quiet_again(self, fresh_db):
        """The archive check takes precedence over the one-pass
        reactivated->active promotion, defensively."""
        with database.get_connection() as conn:
            _insert_problem(
                conn, "p1", weeks_seen=5, first_seen_days_ago=300,
                last_seen_days_ago=config.PROBLEM_ARCHIVE_DAYS + 5,
                lifecycle_state="reactivated",
            )
            conn.commit()
            lifecycle.run_lifecycle_pass(conn, domain="business")
            state = conn.execute("SELECT lifecycle_state FROM problems WHERE id='p1'").fetchone()["lifecycle_state"]
        assert state == "archived"
