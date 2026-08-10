"""
tests/test_api_security.py — API-layer security tests.

Closes a real gap identified in the V1 security review: 502 backend
tests existed below the API boundary, none exercised FastAPI itself.
Covers auth enforcement (auth.py's get_current_actor), security headers
and body size limits (middleware.py), and that response models are
actually enforced now that response_model=dict has been replaced
throughout api/*.py.

Uses FastAPI's TestClient (sync, wraps httpx) against a fresh, isolated
database per test, matching the isolation pattern already used
throughout tests/ (monkeypatch database.DB_PATH before initialize()).

Run with:
    cd backend && pytest tests/test_api_security.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient against a fresh, isolated database, with auth
    disabled (BIA_API_KEY unset) unless a test explicitly sets it."""
    db_path = tmp_path / "test_api.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.delenv("BIA_API_KEY", raising=False)
    database.initialize()

    # auth.API_KEY is read once at import time; re-read it here so a
    # monkeypatched env var actually takes effect for this test.
    import auth
    monkeypatch.setattr(auth, "API_KEY", "")

    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def authed_client(tmp_path, monkeypatch):
    """A TestClient with a real API key configured, for testing that
    protected routes actually enforce it."""
    db_path = tmp_path / "test_api_authed.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()

    import auth
    monkeypatch.setattr(auth, "API_KEY", "test-secret-key")

    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        yield c


class TestHealthEndpointIsUnauthenticated:
    """Health must stay open even when auth is configured elsewhere --
    monitoring tooling needs it to work unconditionally."""

    def test_health_returns_200_without_auth(self, authed_client):
        response = authed_client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestAuthEnforcement:
    def test_patch_status_rejected_without_key_when_configured(self, authed_client):
        response = authed_client.patch(
            "/api/v1/opportunities/does-not-exist/status",
            json={"status": "validated"},
        )
        assert response.status_code == 401

    def test_patch_status_rejected_with_wrong_key(self, authed_client):
        response = authed_client.patch(
            "/api/v1/opportunities/does-not-exist/status",
            json={"status": "validated"},
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert response.status_code == 401

    def test_patch_status_with_correct_key_passes_auth(self, authed_client):
        """Correct key should get past auth -- 404 (not found) proves
        auth succeeded and the request reached the handler, vs. 401
        which would mean auth rejected it first."""
        response = authed_client.patch(
            "/api/v1/opportunities/does-not-exist/status",
            json={"status": "validated"},
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert response.status_code == 404

    def test_pipeline_run_rejected_without_key_when_configured(self, authed_client):
        response = authed_client.post("/api/v1/pipeline/run")
        assert response.status_code == 401

    def test_reports_generate_rejected_without_key_when_configured(self, authed_client):
        response = authed_client.post("/api/v1/reports/generate")
        assert response.status_code == 401

    def test_get_routes_remain_open_regardless_of_auth_config(self, authed_client):
        """Read-only routes were never in scope for auth -- only
        mutating/expensive endpoints are protected."""
        response = authed_client.get("/api/v1/opportunities")
        assert response.status_code == 200

    def test_auth_disabled_by_default_preserves_existing_behavior(self, client):
        """With BIA_API_KEY unset (the default), protected routes must
        behave exactly as they did before auth existed -- no header
        required at all."""
        response = client.patch(
            "/api/v1/opportunities/does-not-exist/status",
            json={"status": "validated"},
        )
        assert response.status_code == 404  # not 401 -- auth is a no-op here


class TestSecurityHeaders:
    def test_security_headers_present_on_every_response(self, client):
        response = client.get("/api/v1/health")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert "Content-Security-Policy" in response.headers

    def test_security_headers_present_on_error_responses_too(self, client):
        response = client.get("/api/v1/reports/does-not-exist")
        assert response.status_code == 404
        assert response.headers["X-Content-Type-Options"] == "nosniff"


class TestBodySizeLimit:
    def test_oversized_body_rejected_with_413(self, client):
        huge_status = "validated" + ("x" * 2_000_000)
        response = client.patch(
            "/api/v1/opportunities/does-not-exist/status",
            content=f'{{"status": "{huge_status}"}}'.encode(),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413

    def test_normal_sized_body_not_rejected_by_size_limit(self, client):
        """A legitimately-sized request must not be caught by the size
        limit -- confirms the limit is generous enough for real use,
        not just that it rejects huge payloads."""
        response = client.patch(
            "/api/v1/opportunities/does-not-exist/status",
            json={"status": "validated"},
        )
        assert response.status_code != 413


class TestResponseModelsAreEnforced:
    """response_model=dict was replaced throughout api/*.py -- these
    confirm real shapes are returned, not just that routes don't crash."""

    def test_opportunity_list_response_shape(self, client):
        response = client.get("/api/v1/opportunities")
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"opportunities", "total", "limit", "offset"}

    def test_signal_list_response_shape(self, client):
        response = client.get("/api/v1/signals")
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"signals", "total", "limit", "offset"}

    def test_signal_stats_response_shape(self, client):
        response = client.get("/api/v1/signals/stats")
        assert response.status_code == 200
        body = response.json()
        assert "total_signals" in body
        assert "by_source" in body
        assert "top_tags" in body

    def test_report_list_response_shape(self, client):
        response = client.get("/api/v1/reports")
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"reports", "total"}

    def test_opportunity_not_found_returns_404_not_500(self, client):
        response = client.get("/api/v1/opportunities/does-not-exist")
        assert response.status_code == 404


class TestPipelineLockPreventsDuplicateRuns:
    def test_pipeline_run_returns_409_when_already_locked(self, client, tmp_path, monkeypatch):
        import config
        import locking
        monkeypatch.setattr(config, "DATA_DIR", tmp_path)
        lock_path = tmp_path / "pipeline.lock"

        import main
        monkeypatch.setattr(main, "PIPELINE_LOCK_PATH", lock_path)

        with locking.exclusive_lock(lock_path):
            response = client.post("/api/v1/pipeline/run")
            assert response.status_code == 409

    def test_report_generate_returns_409_when_already_locked(self, client, tmp_path, monkeypatch):
        import locking
        from api import reports
        lock_path = tmp_path / "report.lock"
        monkeypatch.setattr(reports, "REPORT_LOCK_PATH", lock_path)

        with locking.exclusive_lock(lock_path):
            response = client.post("/api/v1/reports/generate")
            assert response.status_code == 409


class TestCORSConfiguration:
    def test_only_configured_methods_allowed(self, client):
        response = client.options(
            "/api/v1/opportunities",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "DELETE",
            },
        )
        # DELETE is not in the configured allow_methods list
        allow_methods = response.headers.get("access-control-allow-methods", "")
        assert "DELETE" not in allow_methods
