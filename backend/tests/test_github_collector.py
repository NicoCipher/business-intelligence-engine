"""
tests/test_github_collector.py — Regression tests for collectors/github_collector.py

Covers:
  1. Credential gating: no GITHUB_TOKEN -> CollectorError, not a crash.
  2. No queries configured -> clean skip, same pattern as RedditCollector
     with no subreddits.
  3. Issue vs. repository parsing into Signal, using hand-built dicts
     shaped like real GitHub Search API responses (see conftest fixtures
     below) -- no real network calls.
  4. source_id prefixing (issue- / repo-) keeps the two item types from
     colliding in the (source, source_id, domain) dedup key, since
     GitHub's issue and repo numeric ids are separate namespaces.
  5. Tagging: demand_signal/complaint_signal/opportunity_signal for
     issues, competitor_signal (+ language:) for repositories.
  6. _search()'s HTTP error handling: 403 rate-limit -> RateLimitError,
     403 other -> CollectorError, 422 -> CollectorError.

Run with:
    cd backend && pytest tests/test_github_collector.py -v
"""

from unittest.mock import Mock

import pytest

from collectors.base import CollectorError, RateLimitError
from collectors.github_collector import GitHubCollector


@pytest.fixture
def collector():
    return GitHubCollector(queries=["looking for a tool"], domain="business")


def _issue_item(**overrides) -> dict:
    item = {
        "id": 1234,
        "title": "Feature request: export to CSV",
        "body": "Would be nice to have a CSV export option.",
        "html_url": "https://github.com/acme/widget/issues/42",
        "repository_url": "https://api.github.com/repos/acme/widget",
        "reactions": {"total_count": 5},
        "comments": 3,
        "labels": [{"name": "enhancement"}],
        "state": "open",
        "user": {"login": "someuser"},
        "created_at": "2026-08-01T00:00:00Z",
    }
    item.update(overrides)
    return item


def _repo_item(**overrides) -> dict:
    item = {
        "id": 5678,
        "full_name": "acme/widget-exporter",
        "description": "A tool that exports things to CSV",
        "html_url": "https://github.com/acme/widget-exporter",
        "stargazers_count": 340,
        "forks_count": 12,
        "language": "Python",
        "topics": ["csv", "export"],
        "created_at": "2025-01-01T00:00:00Z",
    }
    item.update(overrides)
    return item


# ── Credential gating ────────────────────────────────────────────────────

class TestCredentialGating:
    def test_missing_token_raises_collector_error(self, collector, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with pytest.raises(CollectorError, match="GITHUB_TOKEN"):
            collector._get_session()

    def test_collect_with_no_token_returns_empty_not_raises(self, collector, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        # BaseCollector.collect() catches CollectorError and returns []
        assert collector.collect() == []

    def test_session_authenticated_with_bearer_token(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token-123")
        c = GitHubCollector(queries=["x"])
        session = c._get_session()
        assert session.headers["Authorization"] == "Bearer fake-token-123"
        assert session.headers["Accept"] == "application/vnd.github+json"


# ── No queries configured ────────────────────────────────────────────────

def test_no_queries_skips_cleanly(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    c = GitHubCollector(queries=[], domain="business")
    assert list(c._fetch(10)) == []


# ── Issue parsing ─────────────────────────────────────────────────────────

class TestIssueParsing:
    def test_basic_fields_mapped(self, collector):
        signal = collector._issue_to_signal(_issue_item())
        assert signal.source == "github"
        assert signal.source_id == "issue-1234"
        assert signal.title == "Feature request: export to CSV"
        assert signal.content == "Would be nice to have a CSV export option."
        assert signal.url == "https://github.com/acme/widget/issues/42"
        assert signal.platform_score == 5      # reactions.total_count
        assert signal.comment_count == 3
        assert signal.domain == "business"

    def test_repo_full_name_extracted_from_repository_url(self, collector):
        signal = collector._issue_to_signal(_issue_item())
        assert signal.raw_metadata["repo"] == "acme/widget"

    def test_missing_title_returns_none(self, collector):
        assert collector._issue_to_signal(_issue_item(title="")) is None

    def test_demand_tag_applied(self, collector):
        signal = collector._issue_to_signal(
            _issue_item(title="Any workaround for this?", body="")
        )
        assert "demand_signal" in signal.tags

    def test_complaint_tag_applied(self, collector):
        signal = collector._issue_to_signal(
            _issue_item(title="Export is broken", body="doesn't work at all")
        )
        assert "complaint_signal" in signal.tags

    def test_opportunity_tag_applied(self, collector):
        signal = collector._issue_to_signal(
            _issue_item(title="Just released an open source exporter", body="")
        )
        assert "opportunity_signal" in signal.tags

    def test_repo_tag_included(self, collector):
        signal = collector._issue_to_signal(_issue_item())
        assert "repo:acme/widget" in signal.tags

    def test_no_competitor_signal_tag_on_issues(self, collector):
        """competitor_signal is repository-only -- an issue is a demand
        signal, not evidence a competing solution exists."""
        signal = collector._issue_to_signal(_issue_item())
        assert "competitor_signal" not in signal.tags


# ── Repository parsing ────────────────────────────────────────────────────

class TestRepoParsing:
    def test_basic_fields_mapped(self, collector):
        signal = collector._repo_to_signal(_repo_item())
        assert signal.source == "github"
        assert signal.source_id == "repo-5678"
        assert signal.title == "acme/widget-exporter"
        assert signal.content == "A tool that exports things to CSV"
        assert signal.platform_score == 340    # stargazers_count
        assert signal.comment_count == 0        # not applicable to repos

    def test_competitor_signal_tag_always_applied(self, collector):
        signal = collector._repo_to_signal(_repo_item())
        assert "competitor_signal" in signal.tags

    def test_language_tag_applied_when_present(self, collector):
        signal = collector._repo_to_signal(_repo_item(language="Python"))
        assert "language:python" in signal.tags

    def test_no_language_tag_when_absent(self, collector):
        signal = collector._repo_to_signal(_repo_item(language=None))
        assert not any(t.startswith("language:") for t in signal.tags)

    def test_missing_full_name_returns_none(self, collector):
        assert collector._repo_to_signal(_repo_item(full_name="")) is None

    def test_raw_metadata_includes_topics_and_forks(self, collector):
        signal = collector._repo_to_signal(_repo_item())
        assert signal.raw_metadata["topics"] == ["csv", "export"]
        assert signal.raw_metadata["forks"] == 12


# ── source_id namespace separation ────────────────────────────────────────

def test_issue_and_repo_with_same_numeric_id_do_not_collide(collector):
    """GitHub issue ids and repo ids are separate numeric namespaces --
    the issue-/repo- prefix must keep them from colliding in the
    (source, source_id, domain) dedup key."""
    issue_signal = collector._issue_to_signal(_issue_item(id=999))
    repo_signal = collector._repo_to_signal(_repo_item(id=999))
    assert issue_signal.source_id != repo_signal.source_id
    assert issue_signal.source_id == "issue-999"
    assert repo_signal.source_id == "repo-999"


# ── HTTP error handling ────────────────────────────────────────────────────

class TestSearchErrorHandling:
    def _mock_session(self, status_code, headers=None, text=""):
        session = Mock()
        response = Mock()
        response.status_code = status_code
        response.headers = headers or {}
        response.text = text
        response.json.return_value = {"items": []}
        session.get.return_value = response
        return session

    def test_403_with_zero_remaining_raises_rate_limit_error(self, collector):
        session = self._mock_session(
            403, headers={"X-RateLimit-Remaining": "0", "Retry-After": "45"}
        )
        with pytest.raises(RateLimitError, match="45"):
            collector._search(session, "issues", {"q": "x"})

    def test_403_without_rate_limit_indication_raises_collector_error(self, collector):
        session = self._mock_session(403, text="Forbidden for another reason")
        with pytest.raises(CollectorError):
            collector._search(session, "issues", {"q": "x"})

    def test_422_raises_collector_error(self, collector):
        session = self._mock_session(422, text="Validation failed")
        with pytest.raises(CollectorError, match="rejected"):
            collector._search(session, "issues", {"q": "x"})

    def test_200_returns_items(self, collector):
        session = Mock()
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"items": [_issue_item()]}
        session.get.return_value = response
        items = collector._search(session, "issues", {"q": "x"})
        assert len(items) == 1
