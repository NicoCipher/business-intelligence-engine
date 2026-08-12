"""
tests/test_trends_collector.py — Regression tests for collectors/trends_collector.py

Note on network access: unlike test_github_collector.py, these tests
cannot be cross-checked against a live API call during development --
trends.google.com is outside this environment's network allowlist.
Fixtures are shaped against pytrends' documented DataFrame formats
(related_queries() -> {keyword: {'top': df, 'rising': df}}, columns
['query', 'value']; interest_over_time() -> DataFrame indexed by date,
one column per keyword plus 'isPartial') and pytrends' own source
(inspected directly during development), not against real responses.

Covers:
  1. Missing pytrends install -> CollectorError, not a crash (the only
     graceful-failure path here; Trends needs no credentials).
  2. No keywords configured -> clean skip, same pattern as the other
     collectors with no sources configured.
  3. Rising-query row parsing into Signal, including the numeric-value
     vs. "Breakout"-string-value cases.
  4. Tagging: demand_signal unconditional, breakout only for the
     Breakout case, trending_up passed through from the direction
     heuristic, keyword: provenance tag always present.
  5. source_id date-scoping: the same rising query on two different
     dates produces two distinct signals (recurrence, not deduplication
     — see module docstring).
  6. _is_trending_up()'s direction heuristic against rising/flat/empty/
     too-short synthetic series.
  7. TooManyRequestsError -> RateLimitError; other ResponseError ->
     CollectorError.

Run with:
    cd backend && pytest tests/test_trends_collector.py -v
"""

from unittest.mock import Mock

import pandas as pd
import pytest

from collectors.base import CollectorError, RateLimitError
from collectors.trends_collector import TrendsCollector, PYTRENDS_AVAILABLE


@pytest.fixture
def collector():
    return TrendsCollector(keywords=["invoicing software"], domain="business")


def _rising_row(query="best invoicing app", value=250):
    return pd.Series({"query": query, "value": value})


# ── Library availability ────────────────────────────────────────────────

class TestLibraryAvailability:
    def test_missing_pytrends_raises_collector_error(self, collector, monkeypatch):
        import collectors.trends_collector as mod
        monkeypatch.setattr(mod, "PYTRENDS_AVAILABLE", False)
        with pytest.raises(CollectorError, match="pytrends"):
            collector._get_client()

    def test_collect_with_missing_pytrends_returns_empty_not_raises(self, collector, monkeypatch):
        import collectors.trends_collector as mod
        monkeypatch.setattr(mod, "PYTRENDS_AVAILABLE", False)
        # BaseCollector.collect() catches CollectorError and returns []
        assert collector.collect() == []


# ── No keywords configured ───────────────────────────────────────────────

def test_no_keywords_skips_cleanly():
    c = TrendsCollector(keywords=[], domain="business")
    assert list(c._fetch(10)) == []


# ── Row -> Signal parsing ─────────────────────────────────────────────────

class TestRowParsing:
    def test_numeric_value_mapped_to_platform_score(self, collector):
        signal = collector._row_to_signal(
            "invoicing software", _rising_row(value=250), "2026-08-12", trending_up=False,
        )
        assert signal.platform_score == 250
        assert "breakout" not in signal.tags

    def test_breakout_string_value_mapped_to_sentinel(self, collector):
        signal = collector._row_to_signal(
            "invoicing software", _rising_row(value="Breakout"), "2026-08-12", trending_up=False,
        )
        assert signal.platform_score == 5000
        assert "breakout" in signal.tags

    def test_breakout_case_insensitive(self, collector):
        signal = collector._row_to_signal(
            "invoicing software", _rising_row(value="breakout"), "2026-08-12", trending_up=False,
        )
        assert "breakout" in signal.tags

    def test_demand_signal_always_applied(self, collector):
        signal = collector._row_to_signal(
            "invoicing software", _rising_row(), "2026-08-12", trending_up=False,
        )
        assert "demand_signal" in signal.tags

    def test_trending_up_tag_reflects_argument(self, collector):
        up = collector._row_to_signal(
            "invoicing software", _rising_row(), "2026-08-12", trending_up=True,
        )
        flat = collector._row_to_signal(
            "invoicing software", _rising_row(), "2026-08-12", trending_up=False,
        )
        assert "trending_up" in up.tags
        assert "trending_up" not in flat.tags

    def test_keyword_provenance_tag_present(self, collector):
        signal = collector._row_to_signal(
            "invoicing software", _rising_row(), "2026-08-12", trending_up=False,
        )
        assert "keyword:invoicing software" in signal.tags

    def test_content_describes_the_increase(self, collector):
        signal = collector._row_to_signal(
            "invoicing software", _rising_row(query="free invoice generator", value=300),
            "2026-08-12", trending_up=False,
        )
        assert "invoicing software" in signal.content
        assert "free invoice generator" in signal.content
        assert "300%" in signal.content

    def test_comment_count_always_zero(self, collector):
        signal = collector._row_to_signal(
            "invoicing software", _rising_row(), "2026-08-12", trending_up=False,
        )
        assert signal.comment_count == 0

    def test_missing_query_text_returns_none(self, collector):
        row = pd.Series({"query": "", "value": 100})
        assert collector._row_to_signal("invoicing software", row, "2026-08-12", False) is None


# ── source_id date-scoping (recurrence, not deduplication) ───────────────

def test_same_query_different_dates_produce_distinct_signals(collector):
    row = _rising_row(query="free invoice generator", value=250)
    day1 = collector._row_to_signal("invoicing software", row, "2026-08-12", False)
    day2 = collector._row_to_signal("invoicing software", row, "2026-08-13", False)
    assert day1.source_id != day2.source_id
    assert day1.source_id == "invoicing software|free invoice generator|2026-08-12"
    assert day2.source_id == "invoicing software|free invoice generator|2026-08-13"


def test_same_query_same_date_produces_identical_source_id(collector):
    row = _rising_row(query="free invoice generator", value=250)
    a = collector._row_to_signal("invoicing software", row, "2026-08-12", False)
    b = collector._row_to_signal("invoicing software", row, "2026-08-12", True)
    # source_id is identical regardless of trending_up -- dedup key
    # doesn't depend on the direction tag, only on what was observed.
    assert a.source_id == b.source_id


# ── Trend direction heuristic ─────────────────────────────────────────────

class TestTrendingUpHeuristic:
    def _client_with_series(self, values, has_partial=True):
        client = Mock()
        n = len(values)
        df = pd.DataFrame({"x": values})
        if has_partial:
            df["isPartial"] = [False] * (n - 1) + [True]
        client.interest_over_time.return_value = df
        return client

    def test_clearly_rising_series_detected(self, collector):
        client = self._client_with_series([10, 12, 11, 13, 14, 12, 15, 60, 65, 70, 75, 80])
        assert collector._is_trending_up(client, "x") is True

    def test_flat_series_not_detected_as_rising(self, collector):
        client = self._client_with_series([40, 41, 39, 40, 42, 41, 40, 39, 41, 40, 42, 41])
        assert collector._is_trending_up(client, "x") is False

    def test_declining_series_not_detected_as_rising(self, collector):
        client = self._client_with_series([80, 75, 70, 65, 60, 55, 50, 20, 15, 12, 10, 8])
        assert collector._is_trending_up(client, "x") is False

    def test_empty_dataframe_returns_false(self, collector):
        client = Mock()
        client.interest_over_time.return_value = pd.DataFrame()
        assert collector._is_trending_up(client, "x") is False

    def test_missing_keyword_column_returns_false(self, collector):
        client = Mock()
        client.interest_over_time.return_value = pd.DataFrame({"other": [1, 2, 3]})
        assert collector._is_trending_up(client, "x") is False

    def test_too_short_series_returns_false(self, collector):
        client = self._client_with_series([10, 20], has_partial=False)
        assert collector._is_trending_up(client, "x") is False

    def test_none_returned_by_pytrends_returns_false(self, collector):
        client = Mock()
        client.interest_over_time.return_value = None
        assert collector._is_trending_up(client, "x") is False


# ── pytrends exception mapping ────────────────────────────────────────────

@pytest.mark.skipif(not PYTRENDS_AVAILABLE, reason="pytrends not installed")
class TestExceptionMapping:
    def test_too_many_requests_raises_rate_limit_error(self, collector):
        from pytrends.exceptions import TooManyRequestsError
        client = Mock()
        client.build_payload.side_effect = TooManyRequestsError("rate limited", response=Mock(status_code=429))
        with pytest.raises(RateLimitError):
            list(collector._fetch_keyword(client, "invoicing software", 10, "2026-08-12"))

    def test_other_response_error_raises_collector_error(self, collector):
        from pytrends.exceptions import ResponseError
        client = Mock()
        client.build_payload.side_effect = ResponseError("bad response", response=Mock(status_code=500))
        with pytest.raises(CollectorError):
            list(collector._fetch_keyword(client, "invoicing software", 10, "2026-08-12"))
