"""
tests/test_api_domain_filtering.py — Domain-awareness on list endpoints.

Covers the additive `domain` query parameter added to
GET /api/v1/opportunities and GET /api/v1/signals, per Domain
Architecture (12_DOMAIN_ARCHITECTURE.md §7, Domain Isolation): a client
currently has no way to scope a list to one domain when multiple domains
are active.

Design under test (see api/opportunities.py and api/signals.py
docstrings): `domain` is an unvalidated equality filter, same treatment
as the existing `status`/`week`/`source`/`tag` filters -- an unknown
domain id returns an empty list rather than a 400/422. Omitting it
preserves the exact pre-existing behaviour (all domains, unfiltered),
which is what backward compatibility means here.

Uses FastAPI's TestClient against a fresh, isolated database per test,
matching the pattern in tests/test_api_security.py.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient against a fresh, isolated database with auth disabled."""
    db_path = tmp_path / "test_domain_filtering.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.delenv("BIA_API_KEY", raising=False)
    database.initialize()

    import auth
    monkeypatch.setattr(auth, "API_KEY", "")

    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        yield c


def _seed_opportunity(opp_id: str, domain: str, week_key: str = "2026-W28"):
    with database.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO opportunities
                (id, title, description, week_key, created_at, updated_at, domain)
            VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), ?)
            """,
            (opp_id, f"Opportunity {opp_id}", "desc", week_key, domain),
        )
        conn.commit()


def _seed_signal(sig_id: str, domain: str, source: str = "hn"):
    with database.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO signals
                (id, source, source_id, title, url, collected_at, domain)
            VALUES (?, ?, ?, ?, ?, datetime('now'), ?)
            """,
            (sig_id, source, sig_id, f"Signal {sig_id}", "https://example.com", domain),
        )
        conn.commit()


class TestOpportunitiesDomainFilter:
    def test_no_domain_param_returns_all_domains(self, client):
        """Backward compatibility: omitting `domain` must not change
        existing behaviour -- every opportunity is still returned."""
        _seed_opportunity("opp-biz", "business")
        _seed_opportunity("opp-cyb", "cybersecurity")

        response = client.get("/api/v1/opportunities")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        ids = {o["id"] for o in body["opportunities"]}
        assert ids == {"opp-biz", "opp-cyb"}

    def test_domain_filter_scopes_results(self, client):
        _seed_opportunity("opp-biz", "business")
        _seed_opportunity("opp-cyb", "cybersecurity")

        response = client.get("/api/v1/opportunities", params={"domain": "business"})

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["opportunities"][0]["id"] == "opp-biz"

    def test_unknown_domain_returns_empty_not_error(self, client):
        _seed_opportunity("opp-biz", "business")

        response = client.get("/api/v1/opportunities", params={"domain": "nonexistent"})

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 0
        assert body["opportunities"] == []

    def test_domain_field_present_on_each_item(self, client):
        _seed_opportunity("opp-biz", "business")

        response = client.get("/api/v1/opportunities")

        assert response.status_code == 200
        item = response.json()["opportunities"][0]
        assert item["domain"] == "business"

    def test_domain_filter_combines_with_existing_filters(self, client):
        """domain composes with week_key via AND, same as every other filter."""
        _seed_opportunity("opp-biz-w28", "business", week_key="2026-W28")
        _seed_opportunity("opp-biz-w29", "business", week_key="2026-W29")
        _seed_opportunity("opp-cyb-w28", "cybersecurity", week_key="2026-W28")

        response = client.get(
            "/api/v1/opportunities",
            params={"domain": "business", "week": "2026-W28"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["opportunities"][0]["id"] == "opp-biz-w28"

    def test_single_opportunity_detail_includes_domain(self, client):
        """GET /{id} shares _row_to_summary with the list route -- domain
        should surface there too, since it was already in the row."""
        _seed_opportunity("opp-biz", "business")

        response = client.get("/api/v1/opportunities/opp-biz")

        assert response.status_code == 200
        assert response.json()["domain"] == "business"


class TestSignalsDomainFilter:
    def test_no_domain_param_returns_all_domains(self, client):
        _seed_signal("sig-biz", "business")
        _seed_signal("sig-cyb", "cybersecurity")

        response = client.get("/api/v1/signals")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        ids = {s["id"] for s in body["signals"]}
        assert ids == {"sig-biz", "sig-cyb"}

    def test_domain_filter_scopes_results(self, client):
        _seed_signal("sig-biz", "business")
        _seed_signal("sig-cyb", "cybersecurity")

        response = client.get("/api/v1/signals", params={"domain": "cybersecurity"})

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["signals"][0]["id"] == "sig-cyb"

    def test_unknown_domain_returns_empty_not_error(self, client):
        _seed_signal("sig-biz", "business")

        response = client.get("/api/v1/signals", params={"domain": "nonexistent"})

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 0
        assert body["signals"] == []

    def test_domain_field_present_on_each_item(self, client):
        _seed_signal("sig-biz", "business")

        response = client.get("/api/v1/signals")

        assert response.status_code == 200
        item = response.json()["signals"][0]
        assert item["domain"] == "business"

    def test_domain_filter_combines_with_existing_filters(self, client):
        """domain composes with source via AND, same as every other filter."""
        _seed_signal("sig-biz-hn", "business", source="hn")
        _seed_signal("sig-biz-reddit", "business", source="reddit")
        _seed_signal("sig-cyb-hn", "cybersecurity", source="hn")

        response = client.get(
            "/api/v1/signals",
            params={"domain": "business", "source": "hn"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["signals"][0]["id"] == "sig-biz-hn"
