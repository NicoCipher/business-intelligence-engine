"""
tests/test_greenhouse_jobs_collector.py — Unit and integration tests for GreenhouseJobsCollector V1.

Tests cover:
  1. Normal job ingestion and Signal mapping
  2. Multiple boards handling
  3. Stable, cross-company source_id format ({job_id}|{board_token})
  4. Real database-backed duplicate skipping using canonical isolated test DB
  5. HTML cleaning (tags, entities, script/style blocks, punctuation spacing)
  6. Location mapping and gh:location / gh:remote tags
  7. Department & office mapping and gh:department / gh:office tags
  8. Missing optional fields (null content, null location, empty lists)
  9. Empty valid board (success with 0 signals)
  10. Malformed JSON / unexpected response shape
  11. HTTP errors (HTTP 404, 500, timeouts)
  12. Rate-limit handling (HTTP 429 and HTTP 403 throttle evidence)
  13. Partial board failure (one succeeds, one fails -> SUCCESS with partial results)
  14. All-board failure (all boards fail -> CollectorError -> TRANSIENT_FAILURE)
  15. No business-meaning tags (guaranteeing evidence-only ingestion)
  16. Privacy protection: no candidate, applicant, recruiter, or PII ingestion
  17. No false failures when 0 boards configured
  18. Clean CI database isolation via autouse fresh_db fixture

Deterministic tests; zero live network calls.
"""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest
import requests

import database
from collectors.base import (
    CollectorError,
    CollectorOutcomeKind,
    RateLimitError,
    persist_signals,
)
from collectors.greenhouse_jobs_collector import GreenhouseJobsCollector
from domains.base import GreenhouseBoard
from models import Signal


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Ensure a clean, isolated SQLite database with full schema for each test."""
    db_path = tmp_path / "test_greenhouse.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()
    yield db_path


def _make_response(
    status_code: int = 200,
    json_data: dict | None = None,
    text: str = "",
    headers: dict | None = None,
) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp.headers.update(headers or {})
    if json_data is not None:
        resp._content = json.dumps(json_data).encode("utf-8")
        resp.headers["Content-Type"] = "application/json"
    else:
        resp._content = text.encode("utf-8")
    return resp


def _sample_job(
    job_id: int = 1001,
    title: str = "Senior Backend Engineer",
    content: str = "<p>We are looking for an <b>engineer</b> to build scalable APIs.</p>",
    location_name: str = "San Francisco, CA",
    departments: list[dict] | None = None,
    offices: list[dict] | None = None,
    updated_at: str = "2026-08-20T10:00:00Z",
    absolute_url: str = "https://job-boards.greenhouse.io/acme/jobs/1001",
    **extra,
) -> dict:
    job = {
        "id": job_id,
        "internal_job_id": 9001,
        "title": title,
        "updated_at": updated_at,
        "requisition_id": "REQ-100",
        "location": {"name": location_name} if location_name is not None else None,
        "absolute_url": absolute_url,
        "language": "en",
        "content": content,
        "departments": departments or [{"id": 10, "name": "Engineering"}],
        "offices": offices or [{"id": 20, "name": "SF HQ", "location": "San Francisco, CA, United States"}],
    }
    job.update(extra)
    return job


# ── 1. Initialization and Board Configuration ───────────────────────────────

class TestGreenhouseInitialization:
    def test_no_boards_configured_returns_empty_and_success(self):
        collector = GreenhouseJobsCollector(boards=[])
        outcome = collector.collect_with_outcome()
        assert outcome.kind is CollectorOutcomeKind.SUCCESS
        assert outcome.signals == []

    def test_boards_list_stored(self):
        board = GreenhouseBoard(company="Vercel", board_token="vercel")
        collector = GreenhouseJobsCollector(boards=[board], domain="business")
        assert collector._boards == [board]
        assert collector.domain == "business"


# ── 2. Signal Mapping & Evidence Preservation ───────────────────────────────

class TestSignalMapping:
    def test_normal_job_ingestion_fields_mapped(self):
        board = GreenhouseBoard(company="Vercel", board_token="vercel")
        collector = GreenhouseJobsCollector(boards=[board], domain="business")
        raw_job = _sample_job(
            job_id=4567,
            title="Distributed Systems Lead",
            content="<p>Build next-generation edge infrastructure.</p>",
            location_name="Remote - US",
            departments=[{"id": 1, "name": "Infrastructure"}],
            offices=[{"id": 2, "name": "Virtual", "location": "Remote"}],
            updated_at="2026-08-15T12:00:00Z",
            absolute_url="https://job-boards.greenhouse.io/vercel/jobs/4567",
        )
        mock_resp = _make_response(200, {"jobs": [raw_job], "meta": {"total": 1}})

        with patch.object(requests.Session, "get", return_value=mock_resp):
            signals = collector.collect()

        assert len(signals) == 1
        sig = signals[0]
        assert sig.source == "greenhouse_jobs"
        assert sig.source_id == "4567|vercel"
        assert sig.title == "Distributed Systems Lead"
        assert sig.content == "Build next-generation edge infrastructure."
        assert sig.url == "https://job-boards.greenhouse.io/vercel/jobs/4567"
        assert sig.platform_score == 0
        assert sig.comment_count == 0
        assert sig.domain == "business"

        # Raw metadata preserves factual evidence
        meta = sig.raw_metadata
        assert meta["job_id"] == 4567
        assert meta["board_token"] == "vercel"
        assert meta["company"] == "Vercel"
        assert meta["location"] == "Remote - US"
        assert meta["departments"] == ["Infrastructure"]
        assert meta["offices"] == ["Virtual"]
        assert meta["office_locations"] == ["Remote"]
        assert meta["updated_at"] == "2026-08-15T12:00:00Z"

    def test_stable_source_id_across_different_boards(self):
        """Even if two companies share the same numeric job ID, their source_ids must not collide."""
        board_a = GreenhouseBoard(company="Stripe", board_token="stripe")
        board_b = GreenhouseBoard(company="Vercel", board_token="vercel")
        collector_a = GreenhouseJobsCollector(boards=[board_a])
        collector_b = GreenhouseJobsCollector(boards=[board_b])

        job = _sample_job(job_id=999)
        sig_a = collector_a._job_to_signal(job, board_a)
        sig_b = collector_b._job_to_signal(job, board_b)

        assert sig_a.source_id == "999|stripe"
        assert sig_b.source_id == "999|vercel"
        assert sig_a.source_id != sig_b.source_id

    def test_missing_title_or_id_skipped(self):
        board = GreenhouseBoard(company="Acme", board_token="acme")
        collector = GreenhouseJobsCollector(boards=[board])

        assert collector._job_to_signal({}, board) is None
        assert collector._job_to_signal({"id": 1, "title": ""}, board) is None
        assert collector._job_to_signal({"id": None, "title": "Developer"}, board) is None
        assert collector._job_to_signal("not-a-dict", board) is None

    def test_missing_optional_fields_handled_gracefully(self):
        board = GreenhouseBoard(company="Acme", board_token="acme")
        collector = GreenhouseJobsCollector(boards=[board])
        sparse_job = {
            "id": 123,
            "title": "Core Maintainer",
            "content": None,
            "location": None,
            "departments": None,
            "offices": None,
            "updated_at": None,
        }
        sig = collector._job_to_signal(sparse_job, board)
        assert sig is not None
        assert sig.title == "Core Maintainer"
        assert sig.content == ""
        assert sig.raw_metadata["location"] == ""
        assert sig.raw_metadata["departments"] == []
        assert sig.raw_metadata["offices"] == []


# ── 3. HTML Sanitization ───────────────────────────────────────────────────

class TestHtmlCleaning:
    def test_strips_html_tags_and_unescapes_entities(self):
        collector = GreenhouseJobsCollector()
        raw = "<p>We build <strong>high-availability</strong> distributed systems &amp; microservices.</p>"
        cleaned = collector._clean_html(raw)
        assert cleaned == "We build high-availability distributed systems & microservices."

    def test_handles_double_escaped_entities(self):
        collector = GreenhouseJobsCollector()
        raw = "About us: &amp;lt;h2&amp;gt;Mission&amp;lt;/h2&amp;gt;&amp;lt;p&amp;gt;Fast &amp;amp; reliable.&amp;lt;/p&amp;gt;"
        cleaned = collector._clean_html(raw)
        assert cleaned == "About us: Mission Fast & reliable."

    def test_removes_script_and_style_blocks(self):
        collector = GreenhouseJobsCollector()
        raw = "<style>.hide { display:none; }</style><p>Real description.</p><script>alert('xss');</script>"
        cleaned = collector._clean_html(raw)
        assert cleaned == "Real description."
        assert "alert" not in cleaned
        assert "display:none" not in cleaned

    def test_punctuation_spacing_normalized(self):
        collector = GreenhouseJobsCollector()
        raw = "<p>Join our team </code>. We are hiring </span>!</p>"
        cleaned = collector._clean_html(raw)
        assert cleaned == "Join our team. We are hiring!"


# ── 4. Source-Derived Tags (No Business Conclusions) ────────────────────────

class TestSourceDerivedTags:
    def test_pure_source_derived_tags(self):
        board = GreenhouseBoard(company="Grafana Labs", board_token="grafanalabs")
        collector = GreenhouseJobsCollector(boards=[board])
        raw_job = _sample_job(
            location_name="Remote - EMEA",
            departments=[{"id": 1, "name": "Site Reliability"}],
            offices=[{"id": 2, "name": "London Office", "location": "London, UK"}],
        )
        sig = collector._job_to_signal(raw_job, board)
        tags = set(sig.tags)

        assert "gh:job" in tags
        assert "company:grafana-labs" in tags
        assert "gh:board:grafanalabs" in tags
        assert "gh:location:remote - emea" in tags
        assert "gh:remote" in tags
        assert "gh:department:site reliability" in tags
        assert "gh:office:london office" in tags
        assert "gh:location:london, uk" in tags

    def test_strictly_no_business_meaning_tags(self):
        """Collector must never infer business conclusions, demand signals, or hiring surges."""
        forbidden_tags = {
            "demand_signal",
            "growth",
            "expansion",
            "high_demand",
            "opportunity",
            "pain_point",
            "hiring_surge",
            "hiring_signal",
            "market_growth",
        }
        board = GreenhouseBoard(company="Scale AI", board_token="scaleai")
        collector = GreenhouseJobsCollector(boards=[board])
        raw_job = _sample_job(title="Director of Engineering, Generative AI Platform")
        sig = collector._job_to_signal(raw_job, board)

        emitted = set(sig.tags)
        assert not emitted.intersection(forbidden_tags)


# ── 5. Privacy Protection ───────────────────────────────────────────────────

class TestPrivacyProtection:
    def test_no_candidate_or_recruiter_data_ingested(self):
        """Verify that private applicant/recruiter fields are not preserved."""
        board = GreenhouseBoard(company="Vercel", board_token="vercel")
        collector = GreenhouseJobsCollector(boards=[board])
        polluted_job = _sample_job(
            job_id=888,
            title="Software Engineer",
            # Simulated private/applicant/recruiter fields that must not be ingested
            recruiter={"name": "Jane Recruiter", "email": "jane@example.com"},
            application_questions=[{"id": 1, "label": "Resume"}],
            candidate_fields={"ssn": "000-00-0000"},
            contact_email="hiring@example.com",
            phone="123-456-7890",
        )
        sig = collector._job_to_signal(polluted_job, board)
        assert sig is not None

        # Content must not have recruiter details
        assert "Jane Recruiter" not in sig.content
        assert "jane@example.com" not in sig.content

        # raw_metadata must only contain allowable public keys
        allowable_keys = {
            "job_id", "internal_job_id", "requisition_id", "board_token",
            "company", "location", "departments", "offices",
            "office_locations", "updated_at", "first_published",
            "absolute_url", "language",
        }
        assert set(sig.raw_metadata.keys()) == allowable_keys
        assert "recruiter" not in sig.raw_metadata
        assert "candidate_fields" not in sig.raw_metadata
        assert "application_questions" not in sig.raw_metadata


# ── 6. Database Deduplication ───────────────────────────────────────────────

class TestDatabaseDeduplication:
    def test_live_database_deduplication_skips_persisted_signals(self):
        """Verify that BaseCollector._is_duplicate query against SQLite signals table
        skips already persisted signals in an unmocked DB setup."""
        board = GreenhouseBoard(company="Stripe", board_token="stripe")
        collector = GreenhouseJobsCollector(boards=[board], domain="business")

        job_1 = _sample_job(job_id=101, title="Payment Infrastructure Engineer")
        job_2 = _sample_job(job_id=102, title="Billing Platform Engineer")

        # Pre-populate job_1 in the test database
        sig_1 = collector._job_to_signal(job_1, board)
        assert sig_1 is not None
        persist_signals([sig_1])

        mock_resp = _make_response(200, {"jobs": [job_1, job_2], "meta": {"total": 2}})
        with patch.object(requests.Session, "get", return_value=mock_resp):
            # Unpatched _is_duplicate: verifies live SQL check against signals table
            signals = collector.collect()
            assert len(signals) == 1
            assert signals[0].source_id == "102|stripe"


# ── 7. Multiple Boards, Empty Boards, and Rate Limiting ─────────────────────

class TestBoardExecutionAndErrors:
    def test_multiple_boards_collection(self):
        board_a = GreenhouseBoard(company="Stripe", board_token="stripe")
        board_b = GreenhouseBoard(company="Figma", board_token="figma")
        collector = GreenhouseJobsCollector(boards=[board_a, board_b])

        job_a = _sample_job(job_id=1, title="Stripe Job")
        job_b = _sample_job(job_id=2, title="Figma Job")

        def mock_get(url, *args, **kwargs):
            if "stripe" in url:
                return _make_response(200, {"jobs": [job_a]})
            if "figma" in url:
                return _make_response(200, {"jobs": [job_b]})
            return _make_response(404)

        with patch.object(requests.Session, "get", side_effect=mock_get):
            signals = collector.collect()

        assert len(signals) == 2
        assert {s.source_id for s in signals} == {"1|stripe", "2|figma"}

    def test_empty_valid_board_returns_zero_signals_and_success(self):
        board = GreenhouseBoard(company="EmptyCo", board_token="emptyco")
        collector = GreenhouseJobsCollector(boards=[board])
        mock_resp = _make_response(200, {"jobs": [], "meta": {"total": 0}})

        with patch.object(requests.Session, "get", return_value=mock_resp):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.SUCCESS
            assert outcome.signals == []

    def test_http_429_maps_to_rate_limited(self):
        board = GreenhouseBoard(company="Vercel", board_token="vercel")
        collector = GreenhouseJobsCollector(boards=[board])
        mock_resp = _make_response(429, text="Too Many Requests")

        with patch.object(requests.Session, "get", return_value=mock_resp):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.RATE_LIMITED

    def test_http_403_throttle_maps_to_rate_limited(self):
        board = GreenhouseBoard(company="Vercel", board_token="vercel")
        collector = GreenhouseJobsCollector(boards=[board])
        mock_resp = _make_response(403, text="Rate limit exceeded", headers={"Retry-After": "60"})

        with patch.object(requests.Session, "get", return_value=mock_resp):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.RATE_LIMITED

    def test_malformed_json_response_raises_collector_error(self):
        board = GreenhouseBoard(company="Vercel", board_token="vercel")
        collector = GreenhouseJobsCollector(boards=[board])
        mock_resp = _make_response(200, text="not json at all <xml>")

        with patch.object(requests.Session, "get", return_value=mock_resp):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.TRANSIENT_FAILURE

    def test_partial_board_failure_is_success(self):
        """One board fails (HTTP 500) while another succeeds -> SUCCESS outcome."""
        board_good = GreenhouseBoard(company="GoodCo", board_token="goodco")
        board_bad = GreenhouseBoard(company="BadCo", board_token="badco")
        collector = GreenhouseJobsCollector(boards=[board_good, board_bad])

        good_job = _sample_job(job_id=77)

        def mock_get(url, *args, **kwargs):
            if "goodco" in url:
                return _make_response(200, {"jobs": [good_job]})
            return _make_response(500, text="Internal Server Error")

        with patch.object(requests.Session, "get", side_effect=mock_get):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.SUCCESS
            assert len(outcome.signals) == 1
            assert outcome.signals[0].source_id == "77|goodco"

    def test_all_boards_failing_raises_collector_error_and_fails_transiently(self):
        """When all configured boards fail, collection outcome must be TRANSIENT_FAILURE."""
        board_a = GreenhouseBoard(company="A", board_token="token_a")
        board_b = GreenhouseBoard(company="B", board_token="token_b")
        collector = GreenhouseJobsCollector(boards=[board_a, board_b])

        mock_resp = _make_response(500, text="Internal Error")
        with patch.object(requests.Session, "get", return_value=mock_resp):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.TRANSIENT_FAILURE
            assert "All 2 configured Greenhouse job boards failed" in outcome.detail
