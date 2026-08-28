"""
tests/test_operator_state_api.py — Tests for api/operator_state.py
(POST /api/v1/operator-state/ack).

Uses FastAPI's TestClient against a fresh, isolated database per test,
matching the pattern in tests/test_api_security.py.

Run with:
    cd backend && pytest tests/test_operator_state_api.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_operator_state_api.db"
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
    db_path = tmp_path / "test_operator_state_api_authed.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()

    import auth
    monkeypatch.setattr(auth, "API_KEY", "test-secret-key")

    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        yield c


def _last_seen_at() -> str:
    with database.get_connection() as conn:
        return conn.execute("SELECT last_seen_at FROM operator_state WHERE id=1").fetchone()[0]


def _set_last_seen_at(value: str):
    with database.get_connection() as conn:
        conn.execute("UPDATE operator_state SET last_seen_at = ? WHERE id = 1", (value,))
        conn.commit()


# ── Auth ──────────────────────────────────────────────────────────────────

class TestAuthEnforcement:
    def test_ack_rejected_without_key_when_configured(self, authed_client):
        response = authed_client.post(
            "/api/v1/operator-state/ack", json={"as_of": "2026-06-01T00:00:00+00:00"},
        )
        assert response.status_code == 401

    def test_ack_accepted_with_valid_key(self, authed_client):
        response = authed_client.post(
            "/api/v1/operator-state/ack",
            json={"as_of": "2026-06-01T00:00:00+00:00"},
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert response.status_code == 200


# ── Basic semantics ───────────────────────────────────────────────────────

class TestAcknowledgeAdvancesCheckpoint:
    def test_ack_sets_last_seen_at_to_as_of(self, client):
        as_of = "2026-06-01T00:00:00.000000+00:00"
        response = client.post("/api/v1/operator-state/ack", json={"as_of": as_of})
        assert response.status_code == 200
        assert response.json()["last_seen_at"] == as_of
        assert _last_seen_at() == as_of

    def test_ack_from_never_seen_state(self, client):
        assert _last_seen_at() == ""
        as_of = "2026-06-01T00:00:00.000000+00:00"
        client.post("/api/v1/operator-state/ack", json={"as_of": as_of})
        assert _last_seen_at() == as_of

    def test_missing_as_of_is_422(self, client):
        response = client.post("/api/v1/operator-state/ack", json={})
        assert response.status_code == 422


# ── Monotonicity / idempotency ─────────────────────────────────────────────

class TestMonotonicity:
    def test_older_ack_is_a_no_op(self, client):
        later = "2026-06-05T00:00:00.000000+00:00"
        earlier = "2026-06-01T00:00:00.000000+00:00"

        client.post("/api/v1/operator-state/ack", json={"as_of": later})
        response = client.post("/api/v1/operator-state/ack", json={"as_of": earlier})

        assert response.status_code == 200
        assert response.json()["last_seen_at"] == later   # unchanged, not regressed
        assert _last_seen_at() == later

    def test_duplicate_ack_with_same_as_of_is_idempotent(self, client):
        as_of = "2026-06-01T00:00:00.000000+00:00"
        r1 = client.post("/api/v1/operator-state/ack", json={"as_of": as_of})
        r2 = client.post("/api/v1/operator-state/ack", json={"as_of": as_of})

        assert r1.json()["last_seen_at"] == r2.json()["last_seen_at"] == as_of
        assert _last_seen_at() == as_of

    def test_repeated_acks_never_regress_checkpoint(self, client):
        for as_of in [
            "2026-06-01T00:00:00.000000+00:00",
            "2026-06-03T00:00:00.000000+00:00",
            "2026-06-02T00:00:00.000000+00:00",  # older than the previous ack
            "2026-06-04T00:00:00.000000+00:00",
        ]:
            client.post("/api/v1/operator-state/ack", json={"as_of": as_of})

        assert _last_seen_at() == "2026-06-04T00:00:00.000000+00:00"


# ── Future timestamp clamping ───────────────────────────────────────────────

class TestFutureTimestampClamping:
    def test_future_as_of_is_clamped_to_server_now(self, client, monkeypatch):
        frozen_now = "2026-06-01T00:00:00.000000+00:00"
        monkeypatch.setattr(database, "_now", lambda: frozen_now)

        far_future = "2099-01-01T00:00:00.000000+00:00"
        response = client.post("/api/v1/operator-state/ack", json={"as_of": far_future})

        assert response.json()["last_seen_at"] == frozen_now
        assert _last_seen_at() == frozen_now

    def test_as_of_at_exactly_now_is_not_clamped(self, client, monkeypatch):
        frozen_now = "2026-06-01T00:00:00.000000+00:00"
        monkeypatch.setattr(database, "_now", lambda: frozen_now)

        response = client.post("/api/v1/operator-state/ack", json={"as_of": frozen_now})
        assert response.json()["last_seen_at"] == frozen_now


# ── Global acknowledgement semantics ────────────────────────────────────────

class TestGlobalAcknowledgement:
    def test_ack_accepts_no_domain_parameter(self, client):
        """The reviewed design: acknowledgement is global, by design --
        there is no per-domain parameter to even attempt to pass."""
        as_of = "2026-06-01T00:00:00.000000+00:00"
        # Passing an extraneous 'domain' field in the body must not be
        # interpreted as scoping the acknowledgement -- Pydantic simply
        # ignores unknown fields by default; confirm the checkpoint is
        # still set globally regardless.
        response = client.post(
            "/api/v1/operator-state/ack", json={"as_of": as_of, "domain": "business"},
        )
        assert response.status_code == 200
        assert _last_seen_at() == as_of


# ── End-to-end with the unseen endpoint: full acknowledgement flow ─────────

class TestAcknowledgementIntegratesWithUnseenEndpoint:
    def test_acknowledging_a_snapshot_clears_it_from_unseen(self, client):
        import json as _json

        with database.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO problems
                  (id, domain, title, entity_ids, first_seen, last_seen, weeks_seen, created_at, updated_at,
                   lifecycle_state, lifecycle_updated_at, trend, trend_updated_at)
                VALUES ('p1', 'business', 'Test problem', '[]', ?, ?, 1, ?, ?, 'new', ?, 'unknown', ?)
                """,
                (database._now(),) * 6,
            )
            conn.execute(
                """
                INSERT INTO change_events
                    (id, domain, event_type, entity_ref_type, entity_ref_id,
                     previous_value, new_value, significance, detected_at, metadata, created_at)
                VALUES ('e1', 'business', 'problem_created', 'problem', 'p1', '', '', 'high', ?, '{}', ?)
                """,
                (database._now(), database._now()),
            )
            conn.commit()

        unseen_before = client.get("/api/v1/changes/unseen")
        assert unseen_before.json()["total_unseen"] == 1
        snapshot_at = unseen_before.json()["snapshot_at"]

        ack = client.post("/api/v1/operator-state/ack", json={"as_of": snapshot_at})
        assert ack.status_code == 200

        unseen_after = client.get("/api/v1/changes/unseen")
        assert unseen_after.json()["total_unseen"] == 0

    def test_events_created_after_snapshot_remain_unseen_after_acknowledgement(self, client, monkeypatch):
        """The core race scenario: a new event arrives between the
        unseen snapshot and the acknowledgement call. Acknowledging the
        OLD snapshot_at must not swallow the new event."""
        with database.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO problems
                  (id, domain, title, entity_ids, first_seen, last_seen, weeks_seen, created_at, updated_at,
                   lifecycle_state, lifecycle_updated_at, trend, trend_updated_at)
                VALUES ('p1', 'business', 'Test problem', '[]', ?, ?, 1, ?, ?, 'new', ?, 'unknown', ?)
                """,
                (database._now(),) * 6,
            )
            conn.commit()

        # Snapshot taken while the feed is still empty, at a controlled instant.
        t_snapshot = "2026-06-01T00:00:00.000000+00:00"
        monkeypatch.setattr(database, "_now", lambda: t_snapshot)
        unseen_before = client.get("/api/v1/changes/unseen")
        snapshot_at = unseen_before.json()["snapshot_at"]
        assert snapshot_at == t_snapshot
        assert unseen_before.json()["total_unseen"] == 0

        # A new event lands (e.g. a pipeline run) strictly AFTER that snapshot.
        t_race_event = "2026-06-01T00:00:01.000000+00:00"
        with database.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO change_events
                    (id, domain, event_type, entity_ref_type, entity_ref_id,
                     previous_value, new_value, significance, detected_at, metadata, created_at)
                VALUES ('e_race', 'business', 'problem_created', 'problem', 'p1', '', '', 'high', ?, '{}', ?)
                """,
                (t_race_event, t_race_event),
            )
            conn.commit()

        # Server clock has moved on by the time the operator actually
        # clicks acknowledge -- but the Server Action still sends the
        # STALE snapshot_at from before the race event existed.
        t_ack_click = "2026-06-01T00:00:05.000000+00:00"
        monkeypatch.setattr(database, "_now", lambda: t_ack_click)
        client.post("/api/v1/operator-state/ack", json={"as_of": snapshot_at})

        # The race event must still be unseen.
        unseen_after = client.get("/api/v1/changes/unseen")
        assert unseen_after.json()["total_unseen"] == 1
        assert unseen_after.json()["changes"][0]["id"] == "e_race"
