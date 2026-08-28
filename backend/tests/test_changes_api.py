"""
tests/test_changes_api.py — Tests for api/changes.py (Change Detection
Read-Side V1: GET /changes, GET /changes/unseen).

Uses FastAPI's TestClient against a fresh, isolated database per test,
matching the pattern in tests/test_api_security.py /
tests/test_api_domain_filtering.py.

Run with:
    cd backend && pytest tests/test_changes_api.py -v
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient against a fresh, isolated database, auth disabled
    unless a test explicitly configures a key."""
    db_path = tmp_path / "test_changes_api.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.delenv("BIA_API_KEY", raising=False)
    database.initialize()

    import auth
    monkeypatch.setattr(auth, "API_KEY", "")

    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def authed_client(tmp_path, monkeypatch):
    """A TestClient with a real API key configured."""
    db_path = tmp_path / "test_changes_api_authed.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()

    import auth
    monkeypatch.setattr(auth, "API_KEY", "test-secret-key")

    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        yield c


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _days_ago(days: float) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(days=days))


def _insert_problem(conn, id_, domain="business", title="Solo therapists lack scheduling tools"):
    conn.execute(
        """
        INSERT INTO problems
          (id, domain, title, entity_ids, first_seen, last_seen, weeks_seen, created_at, updated_at,
           lifecycle_state, lifecycle_updated_at, trend, trend_updated_at)
        VALUES (?, ?, ?, '[]', ?, ?, 1, ?, ?, 'new', ?, 'unknown', ?)
        """,
        (id_, domain, title, database._now(), database._now(), database._now(), database._now(),
         database._now(), database._now()),
    )


def _insert_opportunity(conn, id_, problem_id, domain="business", tier="silver", title="Opportunity"):
    scores = json.dumps({"tier": tier, "composite": 7.0, "evidence_count": 2})
    conn.execute(
        """
        INSERT INTO opportunities
            (id, title, description, signal_ids, entity_ids, scores, composite_score,
             status, week_key, created_at, updated_at, domain, problem_id)
        VALUES (?, ?, 'desc', '[]', '[]', ?, 7.0, 'new', '2026-W01', ?, ?, ?, ?)
        """,
        (id_, title, scores, database._now(), database._now(), domain, problem_id),
    )


def _insert_change_event(
    conn, id_, domain="business", event_type="problem_created",
    entity_ref_type="problem", entity_ref_id="p1",
    previous_value="", new_value="", significance="normal",
    detected_at=None, created_at=None, metadata=None,
):
    now = database._now()
    conn.execute(
        """
        INSERT INTO change_events
            (id, domain, event_type, entity_ref_type, entity_ref_id,
             previous_value, new_value, significance, detected_at, metadata, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (id_, domain, event_type, entity_ref_type, entity_ref_id,
         previous_value, new_value, significance,
         detected_at or now, json.dumps(metadata or {}), created_at or now),
    )


def _set_last_seen_at(conn, value: str):
    conn.execute("UPDATE operator_state SET last_seen_at = ? WHERE id = 1", (value,))


# ── Auth enforcement ──────────────────────────────────────────────────────

class TestAuthEnforcement:
    def test_changes_rejected_without_key_when_configured(self, authed_client):
        response = authed_client.get("/api/v1/changes")
        assert response.status_code == 401

    def test_unseen_rejected_without_key_when_configured(self, authed_client):
        response = authed_client.get("/api/v1/changes/unseen")
        assert response.status_code == 401

    def test_changes_accepted_with_valid_key(self, authed_client):
        response = authed_client.get(
            "/api/v1/changes", headers={"Authorization": "Bearer test-secret-key"},
        )
        assert response.status_code == 200

    def test_changes_open_when_no_key_configured(self, client):
        response = client.get("/api/v1/changes")
        assert response.status_code == 200


# ── Browse: filters, pagination, ordering ─────────────────────────────────

class TestBrowseOrderingAndPagination:
    def test_newest_first_ordering(self, client):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_change_event(conn, "e1", detected_at=_days_ago(5))
            _insert_change_event(conn, "e2", detected_at=_days_ago(1))
            _insert_change_event(conn, "e3", detected_at=_days_ago(3))
            conn.commit()

        response = client.get("/api/v1/changes")
        assert response.status_code == 200
        body = response.json()
        ids = [c["id"] for c in body["changes"]]
        assert ids == ["e2", "e3", "e1"]

    def test_pagination_limit_offset_and_total(self, client):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            for i in range(5):
                _insert_change_event(conn, f"e{i}", detected_at=_days_ago(i))
            conn.commit()

        response = client.get("/api/v1/changes", params={"limit": 2, "offset": 1})
        body = response.json()
        assert body["total"] == 5
        assert body["limit"] == 2
        assert body["offset"] == 1
        assert len(body["changes"]) == 2

    def test_response_includes_server_time(self, client):
        response = client.get("/api/v1/changes")
        assert "server_time" in response.json()
        assert response.json()["server_time"]


class TestBrowseFilters:
    def test_filter_by_domain(self, client):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", domain="business")
            _insert_problem(conn, "p2", domain="other")
            _insert_change_event(conn, "e1", domain="business", entity_ref_id="p1")
            _insert_change_event(conn, "e2", domain="other", entity_ref_id="p2")
            conn.commit()

        response = client.get("/api/v1/changes", params={"domain": "business"})
        body = response.json()
        assert len(body["changes"]) == 1
        assert body["changes"][0]["id"] == "e1"

    def test_filter_by_significance(self, client):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_change_event(conn, "e1", significance="high")
            _insert_change_event(conn, "e2", significance="normal")
            conn.commit()

        response = client.get("/api/v1/changes", params={"significance": "high"})
        body = response.json()
        assert len(body["changes"]) == 1
        assert body["changes"][0]["id"] == "e1"

    def test_invalid_significance_is_422(self, client):
        response = client.get("/api/v1/changes", params={"significance": "critical"})
        assert response.status_code == 422

    def test_filter_by_event_type(self, client):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_change_event(conn, "e1", event_type="problem_created")
            _insert_change_event(conn, "e2", event_type="problem_trend_changed")
            conn.commit()

        response = client.get("/api/v1/changes", params={"event_type": "problem_trend_changed"})
        body = response.json()
        assert len(body["changes"]) == 1
        assert body["changes"][0]["id"] == "e2"

    def test_unknown_event_type_returns_empty_list_not_error(self, client):
        response = client.get("/api/v1/changes", params={"event_type": "not_a_real_type"})
        assert response.status_code == 200
        assert response.json()["changes"] == []

    def test_filter_by_entity_ref_type_and_id(self, client):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_opportunity(conn, "o1", "p1")
            _insert_change_event(conn, "e1", entity_ref_type="problem", entity_ref_id="p1")
            _insert_change_event(conn, "e2", entity_ref_type="opportunity", entity_ref_id="o1")
            conn.commit()

        response = client.get(
            "/api/v1/changes", params={"entity_ref_type": "opportunity", "entity_ref_id": "o1"},
        )
        body = response.json()
        assert len(body["changes"]) == 1
        assert body["changes"][0]["id"] == "e2"

    def test_invalid_entity_ref_type_is_422(self, client):
        response = client.get("/api/v1/changes", params={"entity_ref_type": "signal"})
        assert response.status_code == 422


# ── entity_title resolution ────────────────────────────────────────────────

class TestEntityTitleResolution:
    def test_problem_title_resolved(self, client):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1", title="Freelancers lack invoicing tools")
            _insert_change_event(conn, "e1", entity_ref_type="problem", entity_ref_id="p1")
            conn.commit()

        response = client.get("/api/v1/changes")
        assert response.json()["changes"][0]["entity_title"] == "Freelancers lack invoicing tools"

    def test_opportunity_title_resolved(self, client):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_opportunity(conn, "o1", "p1", title="Invoicing SaaS for freelancers")
            _insert_change_event(conn, "e1", entity_ref_type="opportunity", entity_ref_id="o1")
            conn.commit()

        response = client.get("/api/v1/changes")
        assert response.json()["changes"][0]["entity_title"] == "Invoicing SaaS for freelancers"

    def test_missing_referenced_entity_yields_null_title(self, client):
        with database.get_connection() as conn:
            # No problem row for 'ghost' -- defensive path, should never
            # happen in practice (nothing deletes Problems), but must not crash.
            _insert_change_event(conn, "e1", entity_ref_type="problem", entity_ref_id="ghost")
            conn.commit()

        response = client.get("/api/v1/changes")
        assert response.status_code == 200
        assert response.json()["changes"][0]["entity_title"] is None


# ── metadata exposure ───────────────────────────────────────────────────────

class TestMetadataExposure:
    def test_metadata_exposed_as_decoded_dict(self, client):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_change_event(conn, "e1", metadata={"source_problem_history_id": "h1"})
            conn.commit()

        response = client.get("/api/v1/changes")
        assert response.json()["changes"][0]["metadata"] == {"source_problem_history_id": "h1"}


# ── Empty states ─────────────────────────────────────────────────────────

class TestEmptyStates:
    def test_no_events_returns_empty_list_not_404(self, client):
        response = client.get("/api/v1/changes")
        assert response.status_code == 200
        assert response.json() == {
            "changes": [], "total": 0, "limit": 50, "offset": 0,
            "server_time": response.json()["server_time"],
        }


# ── Unseen: created_at boundary semantics ──────────────────────────────────

class TestUnseenBoundarySemantics:
    def test_never_seen_returns_everything_with_since_none(self, client):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_change_event(conn, "e1", created_at=_days_ago(10))
            conn.commit()

        response = client.get("/api/v1/changes/unseen")
        body = response.json()
        assert body["since"] is None
        assert body["total_unseen"] == 1
        assert body["changes"][0]["id"] == "e1"

    def test_event_at_exact_last_seen_boundary_is_excluded(self, client):
        """created_at > last_seen_at is strict -- an event created
        exactly AT the checkpoint was already accounted for by the
        acknowledgement that set that checkpoint."""
        boundary = _days_ago(5)
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_change_event(conn, "e1", created_at=boundary)
            _set_last_seen_at(conn, boundary)
            conn.commit()

        response = client.get("/api/v1/changes/unseen")
        body = response.json()
        assert body["total_unseen"] == 0
        assert body["since"] == boundary

    def test_event_just_after_last_seen_is_included(self, client):
        boundary = _days_ago(5)
        after = _days_ago(4)
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_change_event(conn, "e1", created_at=after)
            _set_last_seen_at(conn, boundary)
            conn.commit()

        response = client.get("/api/v1/changes/unseen")
        assert response.json()["total_unseen"] == 1

    def test_unseen_uses_created_at_not_detected_at_for_the_boundary(self, client):
        """A row can have an old detected_at (the underlying fact
        happened long ago -- e.g. a future backfill) but a brand-new
        created_at (it just entered the log). Filtering on detected_at
        would wrongly exclude it from 'unseen'; filtering on created_at
        (what this endpoint actually does) correctly includes it."""
        checkpoint = _days_ago(1)
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_change_event(
                conn, "e1",
                detected_at=_days_ago(365),   # old world-event timestamp
                created_at=_days_ago(0.001),  # just written to the log
            )
            _set_last_seen_at(conn, checkpoint)
            conn.commit()

        response = client.get("/api/v1/changes/unseen")
        body = response.json()
        assert body["total_unseen"] == 1
        assert body["changes"][0]["id"] == "e1"

    def test_snapshot_at_excludes_events_created_after_it(self, client, monkeypatch):
        """Events created after snapshot_at must not appear in this
        response -- snapshot_at is captured before the query runs."""
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            conn.commit()

        # Freeze database._now() so we can control exactly what
        # snapshot_at will be, then insert an event with a created_at
        # strictly after it.
        frozen = "2026-06-01T00:00:00.000000+00:00"
        monkeypatch.setattr(database, "_now", lambda: frozen)

        response = client.get("/api/v1/changes/unseen")
        assert response.json()["snapshot_at"] == frozen
        assert response.json()["total_unseen"] == 0

        with database.get_connection() as conn:
            _insert_change_event(conn, "e1", created_at="2026-06-02T00:00:00.000000+00:00")
            conn.commit()

        # Advance the clock past the event's created_at before taking a
        # fresh snapshot -- a change created after the FIRST snapshot_at
        # is correctly absent from that same snapshot's results (it
        # hadn't happened yet), but present once a later snapshot is taken.
        later = "2026-06-03T00:00:00.000000+00:00"
        monkeypatch.setattr(database, "_now", lambda: later)
        response2 = client.get("/api/v1/changes/unseen")
        assert response2.json()["snapshot_at"] == later
        assert response2.json()["total_unseen"] == 1

    def test_unseen_has_no_domain_or_significance_filters(self, client):
        """Reviewed design: /unseen must be global and unfiltered --
        no query params exist to imply an independently-acknowledgeable
        filtered stream."""
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_change_event(conn, "e1", domain="business", significance="normal")
            conn.commit()

        # Unknown query params are silently ignored by FastAPI, not
        # rejected -- confirm no filtering actually occurs even if a
        # caller tries to pass domain/significance.
        response = client.get(
            "/api/v1/changes/unseen", params={"domain": "other", "significance": "high"},
        )
        assert response.json()["total_unseen"] == 1


class TestUnseenGetNeverMutatesOperatorState:
    def test_get_changes_does_not_write_operator_state(self, client):
        with database.get_connection() as conn:
            before = conn.execute("SELECT last_seen_at FROM operator_state WHERE id=1").fetchone()[0]

        client.get("/api/v1/changes")

        with database.get_connection() as conn:
            after = conn.execute("SELECT last_seen_at FROM operator_state WHERE id=1").fetchone()[0]
        assert before == after == ""

    def test_get_unseen_does_not_write_operator_state(self, client):
        with database.get_connection() as conn:
            _insert_problem(conn, "p1")
            _insert_change_event(conn, "e1")
            before = conn.execute("SELECT last_seen_at, updated_at FROM operator_state WHERE id=1").fetchone()
            conn.commit()

        client.get("/api/v1/changes/unseen")
        client.get("/api/v1/changes/unseen")
        client.get("/api/v1/changes/unseen")

        with database.get_connection() as conn:
            after = conn.execute("SELECT last_seen_at, updated_at FROM operator_state WHERE id=1").fetchone()
        assert dict(before) == dict(after)
