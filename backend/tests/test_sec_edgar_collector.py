"""
tests/test_sec_edgar_collector.py — Unit and integration tests for SECEdgarCollector V1.

Tests cover:
  1. Successful 8-K ingestion and canonical Signal mapping
  2. Non-8-K filings (10-K, 10-Q, Form 4) excluded from collection
  3. Deterministic, collision-proof source_id ({accession_number}|{cik_10_digits})
  4. Real database-backed deduplication skipping already persisted signals
  5. Factual provenance and metadata preservation
  6. Official SEC URL construction (primary document and index URLs)
  7. 8-K items metadata parsing and sec:item:<item> tags
  8. Strict absence of semantic or business conclusion tags
  9. Lookback window filtering (skipping filings older than cutoff date)
  10. Multiple configured companies handling
  11. Fairness per-company cap (preventing starvation by high-volume companies)
  12. Partial company failure (one fails, one succeeds -> SUCCESS outcome)
  13. All-company failure (all companies fail -> TRANSIENT_FAILURE outcome)
  14. Rate-limit mapping (HTTP 429 and HTTP 403 throttle indicators -> RATE_LIMITED)
  15. Malformed JSON / unexpected response shape -> TRANSIENT_FAILURE
  16. Missing / invalid User-Agent configuration -> CONFIGURATION_FAILURE
  17. Privacy: no applicant, candidate, recruiter, or personal PII data ingested
  18. Empty company list -> SUCCESS with 0 signals
  19. Clean CI database isolation via autouse fresh_db fixture

Deterministic tests; zero live network calls.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
import requests

import database
from collectors.base import (
    CollectorError,
    CollectorOutcomeKind,
    ConfigurationError,
    RateLimitError,
    persist_signals,
)
from collectors.sec_edgar_collector import (
    SECEdgarCollector,
    _cik_to_int_str,
    _normalize_cik,
)
from domains.base import SECCompany
from models import Signal

_TEST_USER_AGENT = "BIA-OS Research AdminContact@bia-os.local"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Ensure a clean, isolated SQLite database with full schema for each test."""
    db_path = tmp_path / "test_sec_edgar.db"
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


def _sample_submissions(
    cik: str = "0001561550",
    name: str = "Datadog, Inc.",
    filings_recent: dict | None = None,
) -> dict:
    """Build a realistic SEC submissions JSON payload."""
    if filings_recent is None:
        filings_recent = {
            "accessionNumber": ["0001628280-26-053829"],
            "filingDate": [datetime.now(timezone.utc).strftime("%Y-%m-%d")],
            "reportDate": [datetime.now(timezone.utc).strftime("%Y-%m-%d")],
            "acceptanceDateTime": ["2026-08-06T11:07:37.000Z"],
            "act": ["34"],
            "form": ["8-K"],
            "fileNumber": ["001-39051"],
            "filmNumber": ["261245928"],
            "items": ["2.02,9.01"],
            "size": [637678],
            "isXBRL": [1],
            "isInlineXBRL": [1],
            "primaryDocument": ["ddog-20260806.htm"],
            "primaryDocDescription": ["8-K"],
        }

    return {
        "cik": str(int(cik)),
        "name": name,
        "sic": "7372",
        "sicDescription": "Services-Prepackaged Software",
        "filings": {
            "recent": filings_recent,
        },
    }


# ── 1. Initialization and Configuration ─────────────────────────────────────

class TestSECConfiguration:
    def test_missing_user_agent_raises_configuration_error(self, monkeypatch):
        monkeypatch.setattr("collectors.sec_edgar_collector.SEC_EDGAR_USER_AGENT", "")
        company = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        collector = SECEdgarCollector(companies=[company], user_agent="")

        outcome = collector.collect_with_outcome()
        assert outcome.kind is CollectorOutcomeKind.CONFIGURATION_FAILURE
        assert "SEC_EDGAR_USER_AGENT" in outcome.detail

    def test_valid_user_agent_configured(self):
        company = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        collector = SECEdgarCollector(companies=[company], user_agent=_TEST_USER_AGENT)
        assert collector._user_agent == _TEST_USER_AGENT
        assert collector.SOURCE_NAME == "sec_edgar"

    def test_no_companies_returns_empty_and_success(self):
        collector = SECEdgarCollector(companies=[], user_agent=_TEST_USER_AGENT)
        outcome = collector.collect_with_outcome()
        assert outcome.kind is CollectorOutcomeKind.SUCCESS
        assert outcome.signals == []


# ── 2. CIK Normalization and URL Construction ───────────────────────────────

class TestIdentifiersAndUrls:
    def test_cik_normalization(self):
        assert _normalize_cik(1561550) == "0001561550"
        assert _normalize_cik("1561550") == "0001561550"
        assert _normalize_cik("0001561550") == "0001561550"
        assert _cik_to_int_str("0001561550") == "1561550"
        assert _cik_to_int_str("1561550") == "1561550"

    def test_official_filing_urls_constructed_correctly(self):
        collector = SECEdgarCollector(user_agent=_TEST_USER_AGENT)
        doc_url, index_url = collector._construct_filing_urls(
            cik_int_str="1561550",
            accession_number="0001628280-26-053829",
            primary_document="ddog-20260806.htm",
        )
        assert doc_url == "https://www.sec.gov/Archives/edgar/data/1561550/000162828026053829/ddog-20260806.htm"
        assert index_url == "https://www.sec.gov/Archives/edgar/data/1561550/000162828026053829/0001628280-26-053829-index.htm"

    def test_missing_primary_document_defaults_to_index_url(self):
        collector = SECEdgarCollector(user_agent=_TEST_USER_AGENT)
        doc_url, index_url = collector._construct_filing_urls(
            cik_int_str="1561550",
            accession_number="0001628280-26-053829",
            primary_document="",
        )
        assert doc_url == index_url


# ── 3. Signal Mapping & Provenance Preservation ─────────────────────────────

class TestSignalMapping:
    def test_successful_8k_ingestion_fields_mapped(self):
        company = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        collector = SECEdgarCollector(companies=[company], user_agent=_TEST_USER_AGENT, domain="business")

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filing_data = {
            "accessionNumber": "0001628280-26-053829",
            "filingDate": today,
            "reportDate": today,
            "acceptanceDateTime": "2026-08-06T11:07:37.000Z",
            "act": "34",
            "form": "8-K",
            "fileNumber": "001-39051",
            "filmNumber": "261245928",
            "items": "2.02,9.01",
            "size": 637678,
            "isXBRL": 1,
            "isInlineXBRL": 1,
            "primaryDocument": "ddog-20260806.htm",
            "primaryDocDescription": "8-K",
        }

        mock_resp = _make_response(200, _sample_submissions(
            cik="0001561550",
            name="Datadog, Inc.",
            filings_recent={k: [v] for k, v in filing_data.items()},
        ))

        with patch.object(requests.Session, "get", return_value=mock_resp):
            signals = collector.collect()

        assert len(signals) == 1
        sig = signals[0]

        assert sig.source == "sec_edgar"
        assert sig.source_id == "0001628280-26-053829|0001561550"
        assert sig.title == "Datadog, Inc. Form 8-K (Item 2.02, 9.01)"
        assert "SEC Form 8-K filing for Datadog, Inc. (CIK 0001561550)" in sig.content
        assert f"Filing Date: {today}" in sig.content
        assert "Reported Items: 2.02, 9.01" in sig.content
        assert sig.url == "https://www.sec.gov/Archives/edgar/data/1561550/000162828026053829/ddog-20260806.htm"
        assert sig.platform_score == 0
        assert sig.comment_count == 0
        assert sig.domain == "business"

        # Raw metadata preserves full provenance
        meta = sig.raw_metadata
        assert meta["company"] == "Datadog, Inc."
        assert meta["cik"] == "0001561550"
        assert meta["ticker"] == "DDOG"
        assert meta["accession_number"] == "0001628280-26-053829"
        assert meta["form"] == "8-K"
        assert meta["items"] == ["2.02", "9.01"]
        assert meta["primary_document"] == "ddog-20260806.htm"
        assert meta["is_xbrl"] == 1

    def test_deterministic_source_id_across_companies(self):
        co_a = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        co_b = SECCompany(cik="0001477333", ticker="NET", name="Cloudflare, Inc.")
        collector = SECEdgarCollector(user_agent=_TEST_USER_AGENT)

        filing = {
            "accessionNumber": "0001193125-26-000001",
            "form": "8-K",
            "filingDate": "2026-08-01",
        }
        sig_a = collector._filing_to_signal(co_a, filing)
        sig_b = collector._filing_to_signal(co_b, filing)

        assert sig_a.source_id == "0001193125-26-000001|0001561550"
        assert sig_b.source_id == "0001193125-26-000001|0001477333"
        assert sig_a.source_id != sig_b.source_id

    def test_non_8k_filings_excluded(self):
        """Only 8-K and 8-K/A forms are ingested; 10-K, 10-Q, Form 4 are excluded."""
        company = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        collector = SECEdgarCollector(companies=[company], user_agent=_TEST_USER_AGENT)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filings = {
            "accessionNumber": ["acc-10k", "acc-8k", "acc-10q", "acc-4", "acc-8ka"],
            "filingDate": [today, today, today, today, today],
            "form": ["10-K", "8-K", "10-Q", "4", "8-K/A"],
            "primaryDocument": ["doc1.htm", "doc2.htm", "doc3.htm", "doc4.htm", "doc5.htm"],
            "items": ["", "5.02", "", "", "8.01"],
        }
        mock_resp = _make_response(200, _sample_submissions(filings_recent=filings))

        with patch.object(requests.Session, "get", return_value=mock_resp):
            signals = collector.collect()

        assert len(signals) == 2
        forms = [s.raw_metadata["form"] for s in signals]
        assert forms == ["8-K", "8-K/A"]


# ── 4. Tagging & Absence of Business Conclusions ────────────────────────────

class TestSourceDerivedTagging:
    def test_source_derived_tags_emitted(self):
        company = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        collector = SECEdgarCollector(companies=[company], user_agent=_TEST_USER_AGENT)

        filing = {
            "accessionNumber": "0001628280-26-053829",
            "form": "8-K",
            "filingDate": "2026-08-06",
            "items": "1.01, 5.02",
        }
        sig = collector._filing_to_signal(company, filing)
        tags = set(sig.tags)

        assert "sec:8-k" in tags
        assert "sec:cik:0001561550" in tags
        assert "company:datadog-inc" in tags
        assert "sec:ticker:ddog" in tags
        assert "sec:item:1.01" in tags
        assert "sec:item:5.02" in tags

    def test_8ka_amendment_tag(self):
        company = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        collector = SECEdgarCollector(companies=[company], user_agent=_TEST_USER_AGENT)

        filing = {
            "accessionNumber": "0001628280-26-053830",
            "form": "8-K/A",
            "filingDate": "2026-08-07",
            "items": "2.02",
        }
        sig = collector._filing_to_signal(company, filing)
        tags = set(sig.tags)

        assert "sec:8-k" in tags
        assert "sec:8-k/a" in tags

    def test_strictly_no_business_meaning_tags(self):
        """Verify collector never emits downstream interpretations or business conclusions."""
        forbidden_tags = {
            "demand_signal",
            "financial_distress",
            "acquisition",
            "layoffs",
            "growth",
            "competition",
            "opportunity",
            "risk",
            "market_shift",
            "pain_point",
            "bullish",
            "bearish",
            "hiring_surge",
        }

        company = SECCompany(cik="0001108524", ticker="CRM", name="Salesforce, Inc.")
        collector = SECEdgarCollector(companies=[company], user_agent=_TEST_USER_AGENT)

        filing = {
            "accessionNumber": "0001108524-26-000050",
            "form": "8-K",
            "filingDate": "2026-08-10",
            "items": "2.05, 5.02",  # Restructuring, departure of directors
        }
        sig = collector._filing_to_signal(company, filing)
        emitted = set(sig.tags)
        assert not emitted.intersection(forbidden_tags)


# ── 5. Lookback Filtering ───────────────────────────────────────────────────

class TestLookbackFiltering:
    def test_filings_outside_lookback_window_are_skipped(self):
        company = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        collector = SECEdgarCollector(companies=[company], user_agent=_TEST_USER_AGENT, lookback_days=14)

        now = datetime.now(timezone.utc)
        recent_date = (now - timedelta(days=2)).strftime("%Y-%m-%d")
        old_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")

        filings = {
            "accessionNumber": ["acc-recent", "acc-old"],
            "filingDate": [recent_date, old_date],
            "form": ["8-K", "8-K"],
            "primaryDocument": ["recent.htm", "old.htm"],
            "items": ["2.02", "8.01"],
        }
        mock_resp = _make_response(200, _sample_submissions(filings_recent=filings))

        with patch.object(requests.Session, "get", return_value=mock_resp):
            signals = collector.collect()

        assert len(signals) == 1
        assert signals[0].source_id == "acc-recent|0001561550"


# ── 6. Database-Backed Deduplication ────────────────────────────────────────

class TestDatabaseDeduplication:
    def test_database_backed_deduplication_skips_persisted_signals(self):
        company = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        collector = SECEdgarCollector(companies=[company], user_agent=_TEST_USER_AGENT, domain="business")

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filing_1 = {
            "accessionNumber": "acc-001",
            "filingDate": today,
            "form": "8-K",
            "primaryDocument": "doc1.htm",
            "items": "2.02",
        }
        filing_2 = {
            "accessionNumber": "acc-002",
            "filingDate": today,
            "form": "8-K",
            "primaryDocument": "doc2.htm",
            "items": "5.02",
        }

        # Pre-populate filing_1 into the database
        sig_1 = collector._filing_to_signal(company, filing_1)
        assert sig_1 is not None
        persist_signals([sig_1])

        filings = {
            "accessionNumber": ["acc-001", "acc-002"],
            "filingDate": [today, today],
            "form": ["8-K", "8-K"],
            "primaryDocument": ["doc1.htm", "doc2.htm"],
            "items": ["2.02", "5.02"],
        }
        mock_resp = _make_response(200, _sample_submissions(filings_recent=filings))

        with patch.object(requests.Session, "get", return_value=mock_resp):
            signals = collector.collect()

        # Unmocked _is_duplicate verifies live SQL query against signals table
        assert len(signals) == 1
        assert signals[0].source_id == "acc-002|0001561550"


# ── 7. Fairness & Multi-Company Allocation ──────────────────────────────────

class TestFairnessAndMultiCompany:
    def test_large_company_does_not_starve_second_company(self):
        co_a = SECCompany(cik="0001108524", ticker="CRM", name="Salesforce, Inc.")
        co_b = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        collector = SECEdgarCollector(companies=[co_a, co_b], user_agent=_TEST_USER_AGENT)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Company A has 50 8-K filings; Company B has 5 8-Ks
        filings_a = {
            "accessionNumber": [f"acc-a-{i}" for i in range(50)],
            "filingDate": [today] * 50,
            "form": ["8-K"] * 50,
            "primaryDocument": [f"doc-a-{i}.htm" for i in range(50)],
            "items": ["2.02"] * 50,
        }
        filings_b = {
            "accessionNumber": [f"acc-b-{i}" for i in range(5)],
            "filingDate": [today] * 5,
            "form": ["8-K"] * 5,
            "primaryDocument": [f"doc-b-{i}.htm" for i in range(5)],
            "items": ["5.02"] * 5,
        }

        def mock_get(url, *args, **kwargs):
            if "0001108524" in url:
                return _make_response(200, _sample_submissions(cik="0001108524", name="Salesforce", filings_recent=filings_a))
            if "0001561550" in url:
                return _make_response(200, _sample_submissions(cik="0001561550", name="Datadog", filings_recent=filings_b))
            return _make_response(404)

        with patch.object(requests.Session, "get", side_effect=mock_get):
            # limit=6 across 2 companies -> per_company_cap = 3
            signals = collector.collect(limit=6)

        from_a = [s for s in signals if "0001108524" in s.source_id]
        from_b = [s for s in signals if "0001561550" in s.source_id]

        assert len(from_a) == 3
        assert len(from_b) == 3
        assert len(signals) == 6

    def test_global_limit_still_respected(self):
        co_a = SECCompany(cik="0001108524", ticker="CRM", name="Salesforce, Inc.")
        co_b = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        collector = SECEdgarCollector(companies=[co_a, co_b], user_agent=_TEST_USER_AGENT)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filings = {
            "accessionNumber": [f"acc-{i}" for i in range(10)],
            "filingDate": [today] * 10,
            "form": ["8-K"] * 10,
            "primaryDocument": [f"doc-{i}.htm" for i in range(10)],
            "items": ["2.02"] * 10,
        }
        mock_resp = _make_response(200, _sample_submissions(filings_recent=filings))

        with patch.object(requests.Session, "get", return_value=mock_resp):
            signals = collector.collect(limit=5)

        assert len(signals) <= 5


# ── 8. Error Handling and Outcome Categories ────────────────────────────────

class TestErrorHandling:
    def test_http_429_maps_to_rate_limited(self):
        company = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        collector = SECEdgarCollector(companies=[company], user_agent=_TEST_USER_AGENT)
        mock_resp = _make_response(429, text="Too Many Requests")

        with patch.object(requests.Session, "get", return_value=mock_resp):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.RATE_LIMITED

    def test_http_403_throttle_maps_to_rate_limited(self):
        company = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        collector = SECEdgarCollector(companies=[company], user_agent=_TEST_USER_AGENT)
        mock_resp = _make_response(403, text="Request rate limit reached", headers={"Retry-After": "30"})

        with patch.object(requests.Session, "get", return_value=mock_resp):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.RATE_LIMITED

    def test_partial_company_failure_is_success(self):
        """One company fails (500) while another succeeds -> SUCCESS outcome."""
        co_good = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        co_bad = SECCompany(cik="0001477333", ticker="NET", name="Cloudflare, Inc.")
        collector = SECEdgarCollector(companies=[co_good, co_bad], user_agent=_TEST_USER_AGENT)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filings_good = {
            "accessionNumber": ["acc-good"],
            "filingDate": [today],
            "form": ["8-K"],
            "primaryDocument": ["good.htm"],
            "items": ["2.02"],
        }

        def mock_get(url, *args, **kwargs):
            if "0001561550" in url:
                return _make_response(200, _sample_submissions(cik="0001561550", name="Datadog", filings_recent=filings_good))
            return _make_response(500, text="Internal Server Error")

        with patch.object(requests.Session, "get", side_effect=mock_get):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.SUCCESS
            assert len(outcome.signals) == 1
            assert outcome.signals[0].source_id == "acc-good|0001561550"

    def test_all_companies_failing_raises_collector_error(self):
        """When all configured companies fail, outcome must be TRANSIENT_FAILURE."""
        co_a = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        co_b = SECCompany(cik="0001477333", ticker="NET", name="Cloudflare, Inc.")
        collector = SECEdgarCollector(companies=[co_a, co_b], user_agent=_TEST_USER_AGENT)

        mock_resp = _make_response(500, text="Internal Error")
        with patch.object(requests.Session, "get", return_value=mock_resp):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.TRANSIENT_FAILURE
            assert "All 2 configured SEC EDGAR companies failed" in outcome.detail

    def test_malformed_json_response_fails_transiently(self):
        company = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        collector = SECEdgarCollector(companies=[company], user_agent=_TEST_USER_AGENT)
        mock_resp = _make_response(200, text="<html><body>Non-JSON</body></html>")

        with patch.object(requests.Session, "get", return_value=mock_resp):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.TRANSIENT_FAILURE


# ── 9. Privacy Protection ───────────────────────────────────────────────────

class TestPrivacyProtection:
    def test_no_applicant_or_personal_data_ingested(self):
        company = SECCompany(cik="0001561550", ticker="DDOG", name="Datadog, Inc.")
        collector = SECEdgarCollector(companies=[company], user_agent=_TEST_USER_AGENT)

        filing = {
            "accessionNumber": "0001628280-26-053829",
            "form": "8-K",
            "filingDate": "2026-08-06",
            "primaryDocument": "doc.htm",
            "items": "2.02",
        }
        sig = collector._filing_to_signal(company, filing)
        assert sig is not None

        # raw_metadata must only contain allowable public SEC fields
        allowable_keys = {
            "company", "cik", "ticker", "accession_number", "form",
            "filing_date", "report_date", "acceptance_date_time", "act",
            "file_number", "film_number", "items", "primary_document",
            "primary_doc_description", "size", "is_xbrl", "is_inline_xbrl",
            "filing_url", "filing_detail_url",
        }
        assert set(sig.raw_metadata.keys()) == allowable_keys
        assert "applicant" not in sig.raw_metadata
        assert "candidate" not in sig.raw_metadata
        assert "email" not in sig.raw_metadata
