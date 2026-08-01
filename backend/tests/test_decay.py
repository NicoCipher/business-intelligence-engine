"""
tests/test_decay.py — Tests for knowledge_graph/decay.py (schema v8):
lifecycle state decisions, matching-eligibility weights, and the full
run_decay_pass() integration against a real database.

Run with:
    cd backend && pytest tests/test_decay.py -v
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
import database
from knowledge_graph import decay
from models import Problem


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _days_ago(days: float) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(days=days))


# ── Pure decision logic ─────────────────────────────────────────────────

class TestDecideLifecycleState:
    def test_recent_reference_stays_active(self):
        state = decay.decide_lifecycle_state(
            days_since_reference=1, dormant_days=365, archive_days=730,
            strongly_connected=False,
        )
        assert state == "active"

    def test_past_dormant_threshold_becomes_dormant(self):
        state = decay.decide_lifecycle_state(
            days_since_reference=400, dormant_days=365, archive_days=730,
            strongly_connected=False,
        )
        assert state == "dormant"

    def test_past_archive_threshold_becomes_archived(self):
        state = decay.decide_lifecycle_state(
            days_since_reference=800, dormant_days=365, archive_days=730,
            strongly_connected=False,
        )
        assert state == "archived"

    def test_exactly_at_dormant_threshold_is_dormant(self):
        state = decay.decide_lifecycle_state(
            days_since_reference=365, dormant_days=365, archive_days=730,
            strongly_connected=False,
        )
        assert state == "dormant"

    def test_exactly_at_archive_threshold_is_archived(self):
        state = decay.decide_lifecycle_state(
            days_since_reference=730, dormant_days=365, archive_days=730,
            strongly_connected=False,
        )
        assert state == "archived"

    def test_protected_stays_active_regardless_of_elapsed_time(self):
        state = decay.decide_lifecycle_state(
            days_since_reference=10000, dormant_days=365, archive_days=730,
            strongly_connected=False, protected=True,
        )
        assert state == "active"

    def test_strongly_connected_extends_thresholds_not_immune(self):
        # 400 days clears the base dormant threshold (365) but not the
        # multiplied one (365 * 1.5 = 547.5) -- should still be active.
        state = decay.decide_lifecycle_state(
            days_since_reference=400, dormant_days=365, archive_days=730,
            strongly_connected=True,
        )
        assert state == "active"

    def test_strongly_connected_still_eventually_decays(self):
        # Far enough past even the multiplied threshold.
        state = decay.decide_lifecycle_state(
            days_since_reference=100000, dormant_days=365, archive_days=730,
            strongly_connected=True,
        )
        assert state == "archived"

    def test_extension_point_parameters_are_accepted_but_have_no_effect(self):
        """Explicitly verifies these are true no-ops today, not silently
        wired into the decision -- passing a value must not change the
        outcome versus leaving them None."""
        kwargs = dict(days_since_reference=400, dormant_days=365, archive_days=730, strongly_connected=False)
        baseline = decay.decide_lifecycle_state(**kwargs)
        with_extensions = decay.decide_lifecycle_state(
            **kwargs, confidence_score=0.9, evidence_quality=0.1, user_interaction_score=100.0,
        )
        assert baseline == with_extensions == "dormant"


class TestMatchWeight:
    def test_active_gets_full_weight(self):
        assert decay.match_weight("active") == 1.0

    def test_dormant_gets_configured_reduced_weight(self):
        assert decay.match_weight("dormant") == config.DORMANT_MATCH_WEIGHT
        assert 0.0 < decay.match_weight("dormant") < 1.0

    def test_archived_gets_zero_weight(self):
        assert decay.match_weight("archived") == 0.0

    def test_unknown_state_defaults_to_full_weight(self):
        """No lifecycle information available (e.g. entity id with no
        corresponding row) must default to full weight, not a penalty."""
        assert decay.match_weight("some_future_state_not_yet_defined") == 1.0
        assert decay.match_weight("") == 1.0


# ── run_decay_pass() integration ────────────────────────────────────────

@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_decay.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()
    yield db_path


def _insert_entity(conn, id_, domain="business", days_old=0, connections=0):
    updated_at = _days_ago(days_old)
    conn.execute(
        """
        INSERT INTO entities (id, type, name, domain, created_at, updated_at, lifecycle_state, lifecycle_updated_at)
        VALUES (?, 'technology', ?, ?, ?, ?, 'active', ?)
        """,
        (id_, id_, domain, updated_at, updated_at, updated_at),
    )
    for i in range(connections):
        other_id = f"{id_}-peer-{i}"
        conn.execute(
            """
            INSERT INTO entities (id, type, name, domain, created_at, updated_at, lifecycle_state, lifecycle_updated_at)
            VALUES (?, 'technology', ?, ?, ?, ?, 'active', ?)
            """,
            (other_id, other_id, domain, updated_at, updated_at, updated_at),
        )
        conn.execute(
            """
            INSERT INTO relationships (id, from_id, to_id, type, weight, domain, created_at, updated_at, lifecycle_state, lifecycle_updated_at)
            VALUES (?, ?, ?, 'co-occurs', 1.0, ?, ?, ?, 'active', ?)
            """,
            (f"rel-{id_}-{i}", id_, other_id, domain, updated_at, updated_at, updated_at),
        )


def _insert_relationship(conn, id_, from_id="a", to_id="b", domain="business", days_old=0, weight=1.0):
    updated_at = _days_ago(days_old)
    for eid in (from_id, to_id):
        conn.execute(
            """
            INSERT OR IGNORE INTO entities (id, type, name, domain, created_at, updated_at, lifecycle_state, lifecycle_updated_at)
            VALUES (?, 'technology', ?, ?, ?, ?, 'active', ?)
            """,
            (eid, eid, domain, updated_at, updated_at, updated_at),
        )
    conn.execute(
        """
        INSERT INTO relationships (id, from_id, to_id, type, weight, domain, created_at, updated_at, lifecycle_state, lifecycle_updated_at)
        VALUES (?, ?, ?, 'co-occurs', ?, ?, ?, ?, 'active', ?)
        """,
        (id_, from_id, to_id, weight, domain, updated_at, updated_at, updated_at),
    )


class TestRunDecayPassEntities:
    def test_recently_referenced_entity_stays_active(self, fresh_db):
        with database.get_connection() as conn:
            _insert_entity(conn, "e1", days_old=1)
            conn.commit()
            decay.run_decay_pass(conn, domain="business")
            state = conn.execute("SELECT lifecycle_state FROM entities WHERE id = 'e1'").fetchone()["lifecycle_state"]
        assert state == "active"

    def test_stale_unconnected_entity_becomes_dormant(self, fresh_db):
        with database.get_connection() as conn:
            _insert_entity(conn, "e1", days_old=config.ENTITY_DORMANT_DAYS + 10)
            conn.commit()
            decay.run_decay_pass(conn, domain="business")
            state = conn.execute("SELECT lifecycle_state FROM entities WHERE id = 'e1'").fetchone()["lifecycle_state"]
        assert state == "dormant"

    def test_very_stale_unconnected_entity_becomes_archived(self, fresh_db):
        with database.get_connection() as conn:
            _insert_entity(conn, "e1", days_old=config.ENTITY_ARCHIVE_DAYS + 10)
            conn.commit()
            decay.run_decay_pass(conn, domain="business")
            state = conn.execute("SELECT lifecycle_state FROM entities WHERE id = 'e1'").fetchone()["lifecycle_state"]
        assert state == "archived"

    def test_entity_referenced_by_problem_is_protected(self, fresh_db):
        with database.get_connection() as conn:
            _insert_entity(conn, "e1", days_old=config.ENTITY_ARCHIVE_DAYS + 1000)
            problem = Problem(id="p1", title="A problem", domain="business", entity_ids=["e1"])
            row = problem.to_db_row()
            conn.execute(
                """
                INSERT INTO problems (id, domain, title, entity_ids, first_seen, last_seen, weeks_seen, created_at, updated_at)
                VALUES (:id, :domain, :title, :entity_ids, :first_seen, :last_seen, :weeks_seen, :created_at, :updated_at)
                """,
                row,
            )
            conn.commit()
            decay.run_decay_pass(conn, domain="business")
            state = conn.execute("SELECT lifecycle_state FROM entities WHERE id = 'e1'").fetchone()["lifecycle_state"]
        assert state == "active"

    def test_strongly_connected_entity_resists_decay_longer(self, fresh_db):
        """days_old is past the base dormant threshold but not the
        connection-boosted (multiplied) one -- should stay active."""
        days = int(config.ENTITY_DORMANT_DAYS * 1.2)
        assert days < config.ENTITY_DORMANT_DAYS * config.DECAY_PROTECTION_MULTIPLIER
        with database.get_connection() as conn:
            _insert_entity(conn, "e1", days_old=days, connections=config.ENTITY_STRONG_CONNECTION_COUNT)
            conn.commit()
            decay.run_decay_pass(conn, domain="business")
            state = conn.execute("SELECT lifecycle_state FROM entities WHERE id = 'e1'").fetchone()["lifecycle_state"]
        assert state == "active"

    def test_never_deletes_rows(self, fresh_db):
        with database.get_connection() as conn:
            _insert_entity(conn, "e1", days_old=config.ENTITY_ARCHIVE_DAYS + 10)
            conn.commit()
            decay.run_decay_pass(conn, domain="business")
            count = conn.execute("SELECT COUNT(*) c FROM entities WHERE id = 'e1'").fetchone()["c"]
        assert count == 1

    def test_domain_isolation(self, fresh_db):
        """Decay for one domain must not touch another domain's entities,
        even if they'd otherwise qualify."""
        with database.get_connection() as conn:
            _insert_entity(conn, "e1", domain="business", days_old=config.ENTITY_ARCHIVE_DAYS + 10)
            _insert_entity(conn, "e2", domain="cybersecurity", days_old=config.ENTITY_ARCHIVE_DAYS + 10)
            conn.commit()
            decay.run_decay_pass(conn, domain="business")
            biz_state = conn.execute("SELECT lifecycle_state FROM entities WHERE id = 'e1'").fetchone()["lifecycle_state"]
            sec_state = conn.execute("SELECT lifecycle_state FROM entities WHERE id = 'e2'").fetchone()["lifecycle_state"]
        assert biz_state == "archived"
        assert sec_state == "active"

    def test_does_not_move_state_backward(self, fresh_db):
        """A decay pass never reactivates -- an already-archived entity
        stays archived even if run_decay_pass is called again."""
        with database.get_connection() as conn:
            _insert_entity(conn, "e1", days_old=config.ENTITY_ARCHIVE_DAYS + 10)
            conn.commit()
            decay.run_decay_pass(conn, domain="business")
            decay.run_decay_pass(conn, domain="business")  # second call, same state
            state = conn.execute("SELECT lifecycle_state FROM entities WHERE id = 'e1'").fetchone()["lifecycle_state"]
        assert state == "archived"

    def test_returns_accurate_counts(self, fresh_db):
        with database.get_connection() as conn:
            _insert_entity(conn, "e1", days_old=config.ENTITY_ARCHIVE_DAYS + 10)
            _insert_entity(conn, "e2", days_old=config.ENTITY_DORMANT_DAYS + 10)
            _insert_entity(conn, "e3", days_old=1)
            conn.commit()
            counts = decay.run_decay_pass(conn, domain="business")
        assert counts["entities_archived"] >= 1
        assert counts["entities_dormant"] >= 1


class TestRunDecayPassRelationships:
    def test_stale_weak_relationship_becomes_dormant(self, fresh_db):
        with database.get_connection() as conn:
            _insert_relationship(conn, "r1", days_old=config.RELATIONSHIP_DORMANT_DAYS + 5, weight=1.0)
            conn.commit()
            decay.run_decay_pass(conn, domain="business")
            state = conn.execute("SELECT lifecycle_state FROM relationships WHERE id = 'r1'").fetchone()["lifecycle_state"]
        assert state == "dormant"

    def test_very_stale_relationship_becomes_archived(self, fresh_db):
        with database.get_connection() as conn:
            _insert_relationship(conn, "r1", days_old=config.RELATIONSHIP_ARCHIVE_DAYS + 5, weight=1.0)
            conn.commit()
            decay.run_decay_pass(conn, domain="business")
            state = conn.execute("SELECT lifecycle_state FROM relationships WHERE id = 'r1'").fetchone()["lifecycle_state"]
        assert state == "archived"

    def test_high_weight_relationship_resists_decay_longer(self, fresh_db):
        days = int(config.RELATIONSHIP_DORMANT_DAYS * 1.2)
        assert days < config.RELATIONSHIP_DORMANT_DAYS * config.DECAY_PROTECTION_MULTIPLIER
        with database.get_connection() as conn:
            _insert_relationship(conn, "r1", days_old=days, weight=config.RELATIONSHIP_STRONG_WEIGHT)
            conn.commit()
            decay.run_decay_pass(conn, domain="business")
            state = conn.execute("SELECT lifecycle_state FROM relationships WHERE id = 'r1'").fetchone()["lifecycle_state"]
        assert state == "active"

    def test_never_deletes_rows(self, fresh_db):
        with database.get_connection() as conn:
            _insert_relationship(conn, "r1", days_old=config.RELATIONSHIP_ARCHIVE_DAYS + 5)
            conn.commit()
            decay.run_decay_pass(conn, domain="business")
            count = conn.execute("SELECT COUNT(*) c FROM relationships WHERE id = 'r1'").fetchone()["c"]
        assert count == 1
