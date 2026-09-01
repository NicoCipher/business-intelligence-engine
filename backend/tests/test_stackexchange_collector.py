"""
test_stackexchange_collector.py — Unit tests for StackExchangeCollector V1.

Tests cover:
  - Configuration & initialization (anonymous vs. API key, missing queries)
  - Canonical Signal mapping (titles, HTML stripping, scores, discussion counts)
  - Attribution & licensing metadata (owner display name, user id, link, content license)
  - Source-derived state tags (no business conclusions, observable states only)
  - Cross-site source_id isolation
  - Deduplication via _is_duplicate
  - Tag AND query parameter semantics
  - Pagination (pagesize, has_more, limit ceiling)
  - Response-wrapper backoff directive and quota monitoring
  - Error handling (HTTP 429, error_id 502 throttle violation, HTTP 500, timeouts)
  - Aggregate partial success vs. total failure handling

All tests run deterministically against mock HTTP responses; zero live network calls.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from collectors.base import (
    CollectorOutcomeKind,
    CollectorError,
    RateLimitError,
)
from collectors.stackexchange_collector import StackExchangeCollector
from domains.base import StackExchangeQuery
from models import Signal


def _make_response(
    status_code: int = 200,
    json_data: dict | None = None,
    text: str = "",
) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    if json_data is not None:
        resp._content = (
            __import__("json").dumps(json_data).encode("utf-8")
        )
        resp.headers["Content-Type"] = "application/json"
    else:
        resp._content = text.encode("utf-8")
    return resp


def _sample_question(
    question_id: int = 12345,
    title: str = "How to handle multi-tenancy in SaaS?",
    body: str = "<p>What is the best way to handle <code>tenant isolation</code>?</p>",
    score: int = 15,
    answer_count: int = 3,
    is_answered: bool = False,
    accepted_answer_id: int | None = None,
    tags: list[str] | None = None,
    link: str = "https://stackoverflow.com/questions/12345/how-to-handle-multi-tenancy",
    owner_display_name: str = "Alice",
    owner_link: str = "https://stackoverflow.com/users/99/alice",
    owner_user_id: int = 99,
    content_license: str = "CC BY-SA 4.0",
) -> dict:
    return {
        "question_id": question_id,
        "title": title,
        "body": body,
        "score": score,
        "answer_count": answer_count,
        "view_count": 500,
        "is_answered": is_answered,
        "accepted_answer_id": accepted_answer_id,
        "tags": tags or ["saas", "multi-tenant"],
        "link": link,
        "creation_date": 1700000000,
        "last_activity_date": 1700001000,
        "owner": {
            "display_name": owner_display_name,
            "link": owner_link,
            "user_id": owner_user_id,
        },
        "content_license": content_license,
    }


class TestStackExchangeInitialization:
    def test_no_queries_configured_returns_empty_and_success(self):
        collector = StackExchangeCollector(queries=[])
        outcome = collector.collect_with_outcome()
        assert outcome.kind is CollectorOutcomeKind.SUCCESS
        assert outcome.signals == []

    def test_anonymous_access_logs_warning_and_does_not_raise_config_error(self, caplog):
        collector = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])],
            api_key="",
        )
        with caplog.at_level(logging.WARNING):
            with patch.object(collector, "_fetch_query", return_value=iter([])):
                outcome = collector.collect_with_outcome()
        assert outcome.kind is CollectorOutcomeKind.SUCCESS
        assert any("anonymous" in record.message.lower() for record in caplog.records)

    def test_api_key_passed_in_request_params(self):
        collector = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])],
            api_key="test-api-key",
        )
        mock_resp = _make_response(
            200,
            {
                "items": [_sample_question()],
                "has_more": False,
                "quota_remaining": 9990,
                "quota_max": 10000,
            },
        )
        with patch.object(requests.Session, "get", return_value=mock_resp) as mock_get:
            signals = collector.collect()
            assert len(signals) == 1
            call_params = mock_get.call_args[1]["params"]
            assert call_params.get("key") == "test-api-key"


class TestSignalMapping:
    def test_standard_question_mapping(self):
        collector = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])],
            domain="business",
        )
        item = _sample_question(
            question_id=42,
            title="How to &amp; why to use SaaS?",
            body="<p>Here is a question with &lt;b&gt;bold text&lt;/b&gt; and <code>code</code>.</p>",
            score=10,
            answer_count=2,
            is_answered=False,
            accepted_answer_id=None,
            tags=["saas", "architecture"],
            owner_display_name="DevBuilder",
            owner_link="https://stackoverflow.com/u/100",
            owner_user_id=100,
            content_license="CC BY-SA 4.0",
        )
        mock_resp = _make_response(200, {"items": [item], "has_more": False})
        with patch.object(requests.Session, "get", return_value=mock_resp):
            signals = collector.collect()

        assert len(signals) == 1
        sig: Signal = signals[0]
        assert sig.source == "stackexchange"
        assert sig.source_id == "42|stackoverflow"
        assert sig.title == "How to & why to use SaaS?"
        assert sig.content == "Here is a question with <b>bold text</b> and code."
        assert sig.platform_score == 10
        assert sig.comment_count == 2
        assert sig.domain == "business"
        assert sig.url == item["link"]

        # Attribution & metadata
        meta = sig.raw_metadata
        assert meta["site"] == "stackoverflow"
        assert meta["question_id"] == 42
        assert meta["is_answered"] is False
        assert meta["accepted_answer_id"] is None
        assert meta["answer_count"] == 2
        assert meta["owner_display_name"] == "DevBuilder"
        assert meta["owner_link"] == "https://stackoverflow.com/u/100"
        assert meta["owner_user_id"] == 100
        assert meta["content_license"] == "CC BY-SA 4.0"
        assert meta["item_type"] == "question"

    def test_preserves_negative_scores(self):
        collector = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])]
        )
        item = _sample_question(score=-4)
        mock_resp = _make_response(200, {"items": [item], "has_more": False})
        with patch.object(requests.Session, "get", return_value=mock_resp):
            signals = collector.collect()
        assert len(signals) == 1
        assert signals[0].platform_score == -4

    def test_accepted_answer_mapping(self):
        collector = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])]
        )
        item = _sample_question(
            is_answered=True,
            accepted_answer_id=777,
        )
        mock_resp = _make_response(200, {"items": [item], "has_more": False})
        with patch.object(requests.Session, "get", return_value=mock_resp):
            signals = collector.collect()
        sig = signals[0]
        assert sig.raw_metadata["accepted_answer_id"] == 777
        assert sig.raw_metadata["is_answered"] is True
        assert "se:answered" in sig.tags
        assert "se:no_accepted_answer" not in sig.tags


class TestSourceDerivedTags:
    def test_tag_derivations(self):
        collector = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])]
        )
        # Question with no accepted answer and 0 answers
        item_zero = _sample_question(
            answer_count=0,
            is_answered=False,
            accepted_answer_id=None,
            tags=["saas", "api-design"],
        )
        # Question with upvoted answer but no accepted answer
        item_answered_unaccepted = _sample_question(
            answer_count=2,
            is_answered=True,
            accepted_answer_id=None,
            tags=["multi-tenant"],
        )

        mock_resp = _make_response(
            200,
            {"items": [item_zero, item_answered_unaccepted], "has_more": False},
        )
        with patch.object(requests.Session, "get", return_value=mock_resp):
            signals = collector.collect()

        tags_0 = set(signals[0].tags)
        assert "site:stackoverflow" in tags_0
        assert "se:tag:saas" in tags_0
        assert "se:tag:api-design" in tags_0
        assert "se:zero_answers" in tags_0
        assert "se:no_accepted_answer" in tags_0
        assert "se:answered" not in tags_0

        tags_1 = set(signals[1].tags)
        assert "site:stackoverflow" in tags_1
        assert "se:tag:multi-tenant" in tags_1
        assert "se:answered" in tags_1
        assert "se:no_accepted_answer" in tags_1
        assert "se:zero_answers" not in tags_1

        # Must never contain business conclusions
        for sig in signals:
            for forbidden in ("demand_signal", "complaint_signal", "opportunity_signal"):
                assert forbidden not in sig.tags

    def test_cross_site_source_id_isolation(self):
        collector_so = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])]
        )
        collector_freelance = StackExchangeCollector(
            queries=[StackExchangeQuery("freelancing", ["invoicing"])]
        )
        item = _sample_question(question_id=123)

        sig_so = collector_so._question_to_signal(item, "stackoverflow")
        sig_freelance = collector_freelance._question_to_signal(item, "freelancing")

        assert sig_so.source_id == "123|stackoverflow"
        assert sig_freelance.source_id == "123|freelancing"
        assert sig_so.source_id != sig_freelance.source_id


class TestQuerySemanticsAndPagination:
    def test_tag_and_semantics_query_param(self):
        collector = StackExchangeCollector(
            queries=[
                StackExchangeQuery("stackoverflow", ["stripe", "subscriptions"]),
                StackExchangeQuery("freelancing", ["invoicing"]),
            ]
        )
        mock_resp = _make_response(200, {"items": [], "has_more": False})
        with patch.object(requests.Session, "get", return_value=mock_resp) as mock_get:
            collector.collect()
            assert mock_get.call_count == 2
            first_params = mock_get.call_args_list[0][1]["params"]
            second_params = mock_get.call_args_list[1][1]["params"]
            assert first_params["tagged"] == "stripe;subscriptions"
            assert first_params["site"] == "stackoverflow"
            assert second_params["tagged"] == "invoicing"
            assert second_params["site"] == "freelancing"

    def test_pagination_follows_has_more(self):
        collector = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])],
        )
        page1 = _make_response(
            200,
            {"items": [_sample_question(question_id=1)], "has_more": True},
        )
        page2 = _make_response(
            200,
            {"items": [_sample_question(question_id=2)], "has_more": False},
        )

        with patch.object(requests.Session, "get", side_effect=[page1, page2]) as mock_get:
            signals = collector.collect(limit=10)
            assert len(signals) == 2
            assert mock_get.call_count == 2
            assert mock_get.call_args_list[0][1]["params"]["page"] == 1
            assert mock_get.call_args_list[1][1]["params"]["page"] == 2

    def test_deduplication_skips_existing_signals(self):
        collector = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])],
            domain="business",
        )
        item1 = _sample_question(question_id=1)
        item2 = _sample_question(question_id=2)
        mock_resp = _make_response(
            200,
            {"items": [item1, item2], "has_more": False},
        )

        with patch.object(requests.Session, "get", return_value=mock_resp):
            with patch.object(collector, "_is_duplicate", side_effect=lambda sid, domain: sid == "1|stackoverflow"):
                signals = collector.collect()
                assert len(signals) == 1
                assert signals[0].source_id == "2|stackoverflow"


class TestBackoffAndQuotaHandling:
    def test_backoff_directive_triggers_sleep(self):
        collector = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])],
        )
        mock_resp = _make_response(
            200,
            {
                "items": [_sample_question()],
                "has_more": False,
                "backoff": 3,
            },
        )
        with patch.object(requests.Session, "get", return_value=mock_resp):
            with patch("time.sleep") as mock_sleep:
                signals = collector.collect()
                assert len(signals) == 1
                mock_sleep.assert_any_call(3)

    def test_zero_quota_remaining_raises_rate_limit_error(self):
        collector = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])],
        )
        mock_resp = _make_response(
            200,
            {
                "items": [_sample_question()],
                "has_more": False,
                "quota_remaining": 0,
                "quota_max": 300,
            },
        )
        with patch.object(requests.Session, "get", return_value=mock_resp):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.RATE_LIMITED

    def test_missing_quota_metadata_does_not_trigger_rate_limiting(self):
        collector = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])],
        )
        mock_resp = _make_response(
            200,
            {
                "items": [_sample_question()],
                "has_more": False,
                # quota_remaining intentionally missing
            },
        )
        with patch.object(requests.Session, "get", return_value=mock_resp):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.SUCCESS
            assert len(outcome.signals) == 1

    def test_http_429_maps_to_rate_limited(self):
        collector = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])],
        )
        mock_resp = _make_response(429, text="Too Many Requests")
        with patch.object(requests.Session, "get", return_value=mock_resp):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.RATE_LIMITED

    def test_error_id_502_throttle_violation_maps_to_rate_limited(self):
        collector = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])],
        )
        mock_resp = _make_response(
            400,
            {
                "error_id": 502,
                "error_name": "throttle_violation",
                "error_message": "too many requests from this IP",
            },
        )
        with patch.object(requests.Session, "get", return_value=mock_resp):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.RATE_LIMITED

    def test_generic_api_error_maps_to_transient_failure(self):
        collector = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])],
        )
        mock_resp = _make_response(
            400,
            {
                "error_id": 404,
                "error_name": "no_method",
                "error_message": "method not found",
            },
        )
        with patch.object(requests.Session, "get", return_value=mock_resp):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.TRANSIENT_FAILURE

    def test_http_500_maps_to_transient_failure(self):
        collector = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])],
        )
        mock_resp = _make_response(500, text="Internal Server Error")
        with patch.object(requests.Session, "get", return_value=mock_resp):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.TRANSIENT_FAILURE

    def test_network_timeout_maps_to_transient_failure(self):
        collector = StackExchangeCollector(
            queries=[StackExchangeQuery("stackoverflow", ["saas"])],
        )
        with patch.object(requests.Session, "get", side_effect=requests.Timeout("Connection timed out")):
            outcome = collector.collect_with_outcome()
            assert outcome.kind is CollectorOutcomeKind.TRANSIENT_FAILURE


class TestAggregateFailureHandling:
    def test_partial_query_failure_is_success(self, caplog):
        collector = StackExchangeCollector(
            queries=[
                StackExchangeQuery("stackoverflow", ["saas"]),
                StackExchangeQuery("freelancing", ["invoicing"]),
            ]
        )
        resp1 = _make_response(
            200,
            {"items": [_sample_question(question_id=1)], "has_more": False},
        )
        resp2 = _make_response(500, text="Server error on site freelancing")

        with patch.object(requests.Session, "get", side_effect=[resp1, resp2]):
            with caplog.at_level(logging.WARNING):
                outcome = collector.collect_with_outcome()

        assert outcome.kind is CollectorOutcomeKind.SUCCESS
        assert len(outcome.signals) == 1
        assert any("Failed to query Stack Exchange" in record.message for record in caplog.records)

    def test_all_queries_failing_raises_collector_error_and_fails_transiently(self):
        collector = StackExchangeCollector(
            queries=[
                StackExchangeQuery("stackoverflow", ["saas"]),
                StackExchangeQuery("freelancing", ["invoicing"]),
            ]
        )
        resp1 = _make_response(500, text="Server error")
        resp2 = _make_response(500, text="Server error")

        with patch.object(requests.Session, "get", side_effect=[resp1, resp2]):
            outcome = collector.collect_with_outcome()

        assert outcome.kind is CollectorOutcomeKind.TRANSIENT_FAILURE
        assert "All Stack Exchange queries failed" in outcome.detail
