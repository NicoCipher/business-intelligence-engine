"""
tests/test_api_problems.py — Problem API endpoints.

Covers GET /api/v1/problems (list, filters, three named sort orders),
GET /api/v1/problems/{id} (detail, linked opportunities, history count),
and GET /api/v1/problems/{id}/history (paginated timeline sub-resource).

Design under test (see api/problems.py's own module docstring for full
rationale): history is a separate paginated sub-resource rather than
inlined in the detail response, since problem_history is unbounded by
design; linked opportunities ARE inlined in the detail response, since
they're naturally bounded. The three sort orders (recent/persistent/
significant) each answer a different question rather than one default
serving all three — "significant" is computed via a LEFT JOIN against
opportunities.composite_score (Problem itself is intentionally
unscored by architecture), not a stored column, so it needs its own
direct coverage.

Uses FastAPI's TestClient against a fresh, isolated database per test,
matching the pattern in tests/test_api_domain_filtering.py.
"""

import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient against a fresh, isolated database with auth disabled."""
    db_path = tmp_path / "test_api_problems.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.delenv("BIA_API_KEY", raising=False)
    database.initialize()

    import auth
    monkeypatch.setattr(auth, "API_KEY", "")

    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        yield c


def _seed_problem(
    problem_id: str, domain: str = "business", title: str = "Test problem",
    weeks_seen: int = 1, lifecycle_state: str = "active", trend: str = "unknown",
    entity_ids: list[str] | None = None,
    first_seen: str = "2026-08-01 00:00:00", last_seen: str = "2026-08-01 00:00:00",
):
    with database.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO problems
                (id, domain, title, entity_ids, first_seen, last_seen,
                 weeks_seen, created_at, updated_at, lifecycle_state, trend)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), ?, ?)
            """,
            (problem_id, domain, title, json.dumps(entity_ids or []),
             first_seen, last_seen, weeks_seen, lifecycle_state, trend),
        )
        conn.commit()


def _seed_opportunity(
    opp_id: str, problem_id: str, domain: str = "business",
    composite_score: float = 5.0, tier: str = "bronze", status: str = "active",
    week_key: str = "2026-W28",
):
    with database.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO opportunities
                (id, title, description, week_key, created_at, updated_at,
                 domain, composite_score, status, problem_id, scores)
            VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), ?, ?, ?, ?, ?)
            """,
            (opp_id, f"Opportunity {opp_id}", "desc", week_key, domain,
             composite_score, status, problem_id, json.dumps({"tier": tier})),
        )
        conn.commit()


def _seed_history_event(
    problem_id: str, event_type: str = "created", domain: str = "business",
    week_key: str = "2026-W28", opportunity_id: str = "", metadata: dict | None = None,
):
    with database.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO problem_history
                (id, problem_id, domain, event_type, occurred_at, week_key,
                 opportunity_id, metadata, created_at)
            VALUES (?, ?, ?, ?, datetime('now'), ?, ?, ?, datetime('now'))
            """,
            (str(uuid.uuid4()), problem_id, domain, event_type, week_key,
             opportunity_id, json.dumps(metadata or {})),
        )
        conn.commit()


class TestListProblems:
    def test_empty_database_returns_empty_list(self, client):
        response = client.get("/api/v1/problems")
        assert response.status_code == 200
        body = response.json()
        assert body == {"problems": [], "total": 0, "limit": 20, "offset": 0}

    def test_returns_seeded_problems(self, client):
        _seed_problem("p1", title="Problem one")
        _seed_problem("p2", title="Problem two")
        response = client.get("/api/v1/problems")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert {p["id"] for p in body["problems"]} == {"p1", "p2"}

    def test_domain_filter(self, client):
        _seed_problem("p1", domain="business")
        _seed_problem("p2", domain="other")
        response = client.get("/api/v1/problems", params={"domain": "business"})
        body = response.json()
        assert body["total"] == 1
        assert body["problems"][0]["id"] == "p1"

    def test_unknown_domain_returns_empty_not_error(self, client):
        _seed_problem("p1", domain="business")
        response = client.get("/api/v1/problems", params={"domain": "nonexistent"})
        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_lifecycle_state_filter(self, client):
        _seed_problem("p1", lifecycle_state="active")
        _seed_problem("p2", lifecycle_state="dormant")
        response = client.get("/api/v1/problems", params={"lifecycle_state": "dormant"})
        body = response.json()
        assert body["total"] == 1
        assert body["problems"][0]["id"] == "p2"

    def test_trend_filter(self, client):
        _seed_problem("p1", trend="growing")
        _seed_problem("p2", trend="declining")
        response = client.get("/api/v1/problems", params={"trend": "growing"})
        body = response.json()
        assert body["total"] == 1
        assert body["problems"][0]["id"] == "p1"

    def test_pagination(self, client):
        for i in range(5):
            _seed_problem(f"p{i}")
        response = client.get("/api/v1/problems", params={"limit": 2, "offset": 2})
        body = response.json()
        assert body["total"] == 5
        assert len(body["problems"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 2


class TestListProblemsSorting:
    """The three named sort orders each answer a different question --
    see module docstring."""

    def test_sort_recent_orders_by_last_seen_desc(self, client):
        _seed_problem("old", last_seen="2026-08-01 00:00:00")
        _seed_problem("new", last_seen="2026-08-10 00:00:00")
        response = client.get("/api/v1/problems", params={"sort": "recent"})
        ids = [p["id"] for p in response.json()["problems"]]
        assert ids == ["new", "old"]

    def test_sort_persistent_orders_by_weeks_seen_desc(self, client):
        _seed_problem("brief", weeks_seen=1)
        _seed_problem("long_running", weeks_seen=12)
        response = client.get("/api/v1/problems", params={"sort": "persistent"})
        ids = [p["id"] for p in response.json()["problems"]]
        assert ids == ["long_running", "brief"]

    def test_sort_significant_orders_by_best_linked_opportunity_score(self, client):
        """Problem itself has no score column -- "significant" must be
        computed from the best linked opportunity's composite_score via
        a JOIN, not a stored field."""
        _seed_problem("weak")
        _seed_opportunity("opp-weak", "weak", composite_score=3.0)
        _seed_problem("strong")
        _seed_opportunity("opp-strong", "strong", composite_score=9.0)
        response = client.get("/api/v1/problems", params={"sort": "significant"})
        ids = [p["id"] for p in response.json()["problems"]]
        assert ids == ["strong", "weak"]

    def test_sort_significant_problem_with_no_opportunities_sorts_last(self, client):
        """A problem with zero linked opportunities must not be excluded
        or error under "significant" sort -- it sorts last (NULL last),
        proving the LEFT JOIN doesn't silently drop unscored problems."""
        _seed_problem("scored")
        _seed_opportunity("opp-1", "scored", composite_score=5.0)
        _seed_problem("unscored")  # no linked opportunity at all
        response = client.get("/api/v1/problems", params={"sort": "significant"})
        body = response.json()
        ids = [p["id"] for p in body["problems"]]
        assert body["total"] == 2
        assert ids == ["scored", "unscored"]

    def test_default_sort_is_recent(self, client):
        _seed_problem("old", last_seen="2026-08-01 00:00:00", weeks_seen=10)
        _seed_problem("new", last_seen="2026-08-10 00:00:00", weeks_seen=1)
        response = client.get("/api/v1/problems")
        ids = [p["id"] for p in response.json()["problems"]]
        assert ids == ["new", "old"]


class TestGetProblem:
    def test_404_for_unknown_problem(self, client):
        response = client.get("/api/v1/problems/nonexistent")
        assert response.status_code == 404

    def test_returns_full_detail(self, client):
        _seed_problem("p1", title="Founders need invoicing", entity_ids=["e1", "e2"])
        response = client.get("/api/v1/problems/p1")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == "p1"
        assert body["title"] == "Founders need invoicing"
        assert body["entity_ids"] == ["e1", "e2"]
        assert body["linked_opportunities"] == []
        assert body["history_count"] == 0

    def test_linked_opportunities_inlined(self, client):
        _seed_problem("p1")
        _seed_opportunity("opp-1", "p1", composite_score=8.2, tier="gold")
        _seed_opportunity("opp-2", "p1", composite_score=3.0, tier="bronze")
        response = client.get("/api/v1/problems/p1")
        body = response.json()
        assert len(body["linked_opportunities"]) == 2
        # ordered by composite_score DESC
        assert body["linked_opportunities"][0]["id"] == "opp-1"
        assert body["linked_opportunities"][0]["tier"] == "gold"

    def test_opportunities_from_other_problems_not_included(self, client):
        _seed_problem("p1")
        _seed_problem("p2")
        _seed_opportunity("opp-1", "p1")
        _seed_opportunity("opp-2", "p2")
        response = client.get("/api/v1/problems/p1")
        body = response.json()
        assert [o["id"] for o in body["linked_opportunities"]] == ["opp-1"]

    def test_history_count_not_full_history(self, client):
        """The detail route inlines a count, not the array -- see
        module docstring on why history is a separate sub-resource."""
        _seed_problem("p1")
        for _ in range(3):
            _seed_history_event("p1")
        response = client.get("/api/v1/problems/p1")
        body = response.json()
        assert body["history_count"] == 3
        assert "history" not in body


class TestGetProblemHistory:
    def test_404_for_unknown_problem(self, client):
        response = client.get("/api/v1/problems/nonexistent/history")
        assert response.status_code == 404

    def test_empty_history(self, client):
        _seed_problem("p1")
        response = client.get("/api/v1/problems/p1/history")
        assert response.status_code == 200
        body = response.json()
        assert body == {"problem_id": "p1", "history": [], "total": 0, "limit": 50, "offset": 0}

    def test_returns_events_oldest_first(self, client):
        _seed_problem("p1")
        _seed_history_event("p1", event_type="created")
        _seed_history_event("p1", event_type="evidence_added")
        response = client.get("/api/v1/problems/p1/history")
        body = response.json()
        assert body["total"] == 2
        assert [e["event_type"] for e in body["history"]] == ["created", "evidence_added"]

    def test_pagination(self, client):
        _seed_problem("p1")
        for i in range(5):
            _seed_history_event("p1", metadata={"seq": i})
        response = client.get("/api/v1/problems/p1/history", params={"limit": 2, "offset": 2})
        body = response.json()
        assert body["total"] == 5
        assert len(body["history"]) == 2
        assert body["history"][0]["metadata"]["seq"] == 2

    def test_history_scoped_to_the_right_problem(self, client):
        _seed_problem("p1")
        _seed_problem("p2")
        _seed_history_event("p1", event_type="created")
        _seed_history_event("p2", event_type="created")
        _seed_history_event("p2", event_type="evidence_added")
        response = client.get("/api/v1/problems/p1/history")
        body = response.json()
        assert body["total"] == 1


class TestAuthRequired:
    """Deliberate deviation from opportunities.py/signals.py, whose GET
    routes are open -- all three Problem routes require auth here, on
    request, for consistency/future-proofing."""

    @pytest.fixture
    def authed_client(self, tmp_path, monkeypatch):
        db_path = tmp_path / "test_api_problems_auth.db"
        monkeypatch.setattr(database, "DB_PATH", db_path)
        monkeypatch.setenv("BIA_API_KEY", "test-secret-key")
        database.initialize()

        import auth
        monkeypatch.setattr(auth, "API_KEY", "test-secret-key")

        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app) as c:
            yield c

    def test_list_without_key_rejected(self, authed_client):
        response = authed_client.get("/api/v1/problems")
        assert response.status_code in (401, 403)

    def test_detail_without_key_rejected(self, authed_client):
        response = authed_client.get("/api/v1/problems/anything")
        assert response.status_code in (401, 403)

    def test_history_without_key_rejected(self, authed_client):
        response = authed_client.get("/api/v1/problems/anything/history")
        assert response.status_code in (401, 403)

    def test_list_with_correct_key_succeeds(self, authed_client):
        response = authed_client.get(
            "/api/v1/problems", headers={"Authorization": "Bearer test-secret-key"},
        )
        assert response.status_code == 200
