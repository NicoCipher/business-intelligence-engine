"""Focused read-side coverage for Collector Operations Visibility V1."""

from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "collector_state_api.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()

    import auth
    monkeypatch.setattr(auth, "API_KEY", "test-secret-key")

    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as test_client:
        yield test_client


def _headers():
    return {"Authorization": "Bearer test-secret-key"}


def _update(source: str, **values):
    assignments = ", ".join(f"{key} = ?" for key in values)
    with database.get_connection() as conn:
        conn.execute(
            f"UPDATE collector_state SET {assignments} WHERE source = ? AND domain = 'business'",
            (*values.values(), source),
        )
        conn.commit()


def _collector(response, source: str):
    return next(item for item in response.json()["collectors"] if item["source"] == source)


class TestCollectorOperationsReadSide:
    def test_requires_operator_authentication(self, client):
        assert client.get("/api/v1/system/collectors").status_code == 401

    def test_reports_seeded_collectors_as_not_yet_run(self, client):
        response = client.get("/api/v1/system/collectors", headers=_headers())
        assert response.status_code == 200
        body = response.json()
        assert {item["source"] for item in body["collectors"]} == {"hn", "reddit", "rss", "github", "trends"}
        assert all(item["domain"] == "business" for item in body["collectors"])
        assert all(item["last_attempt_status"] == "not_yet_run" for item in body["collectors"])
        assert all(item["timing_gate_status"] == "not_yet_run" for item in body["collectors"])

    def test_projects_failure_backoff_and_quota_without_claiming_rate_limit(self, client):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        backoff = now + timedelta(hours=2)
        reset = now + timedelta(hours=6)
        _update(
            "github",
            last_run_at=now.isoformat(),
            last_success_at=(now - timedelta(days=1)).isoformat(),
            last_failure_at=now.isoformat(),
            consecutive_failures=3,
            backoff_until=backoff.isoformat(),
            quota_per_period=10,
            quota_used=10,
            quota_reset_at=reset.isoformat(),
        )

        response = client.get("/api/v1/system/collectors", headers=_headers())
        item = _collector(response, "github")
        assert item["last_attempt_status"] == "failed"
        assert item["timing_gate_status"] == "quota_exhausted"
        assert item["backoff_until"] == backoff.isoformat()
        assert item["next_due_at"] == reset.isoformat()
        assert item["quota"] == {"limit": 10, "period_minutes": 1440, "used": 10, "reset_at": reset.isoformat()}
        assert "rate_limit" not in item

    def test_disabled_state_takes_precedence_over_due_timing(self, client):
        old_run = datetime.now(timezone.utc) - timedelta(days=1)
        _update("rss", enabled=0, last_run_at=old_run.isoformat())

        response = client.get("/api/v1/system/collectors", headers=_headers())
        assert _collector(response, "rss")["timing_gate_status"] == "disabled"
