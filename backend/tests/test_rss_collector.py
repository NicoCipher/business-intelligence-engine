"""
tests/test_rss_collector.py — Regression tests for collectors/rss_collector.py

Covers two bugs found in production:
  1. RSS 2.0's <comments> element is a URL per spec, not a count —
     hnrss.org correctly follows the spec, and the old code crashed on
     every single hnrss.org item with:
     ValueError: invalid literal for int() with base 10: "https://..."
  2. Stack Overflow's feed endpoint returns 403 (external bot protection,
     not a header/config problem) — this should surface as a clear,
     distinct CollectorError, not a generic "HTTP 403" message, and must
     not crash the collector or take down other feeds.

Run with:
    cd backend && pytest tests/test_rss_collector.py -v
"""

import urllib.error
import xml.etree.ElementTree as ET

import pytest

from collectors.base import CollectorError, RateLimitError
from collectors.rss_collector import RSSCollector


@pytest.fixture
def collector():
    return RSSCollector(feeds=[("https://example.com/feed", "test feed")])


# ── Issue 3: <comments> is a URL, not a count ────────────────────────────

_HNRSS_ITEM_XML = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Ask HN: How do I reconcile invoices?</title>
      <link>https://news.ycombinator.com/item?id=44444444</link>
      <guid>https://news.ycombinator.com/item?id=44444444</guid>
      <description>Some description text</description>
      <pubDate>Tue, 21 Jul 2026 10:00:00 +0000</pubDate>
      <comments>https://news.ycombinator.com/item?id=44444444</comments>
    </item>
  </channel>
</rss>
"""

_NUMERIC_COMMENTS_ITEM_XML = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Some feed with an actual numeric comment count</title>
      <link>https://example.com/post/1</link>
      <guid>https://example.com/post/1</guid>
      <description>desc</description>
      <pubDate>Tue, 21 Jul 2026 10:00:00 +0000</pubDate>
      <comments>42</comments>
    </item>
  </channel>
</rss>
"""

_MISSING_COMMENTS_ITEM_XML = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>A feed item with no comments element at all</title>
      <link>https://example.com/post/2</link>
      <guid>https://example.com/post/2</guid>
      <description>desc</description>
      <pubDate>Tue, 21 Jul 2026 10:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""


class TestCommentsUrlRegression:
    def test_hnrss_style_url_in_comments_does_not_raise(self, collector):
        """This is the exact regression: hnrss.org puts a URL in <comments>,
        per the RSS 2.0 spec. Parsing must not raise ValueError."""
        root = ET.fromstring(_HNRSS_ITEM_XML)
        items = collector._parse_rss(root)
        assert len(items) == 1

    def test_hnrss_style_url_in_comments_defaults_to_zero(self, collector):
        root = ET.fromstring(_HNRSS_ITEM_XML)
        items = collector._parse_rss(root)
        assert items[0]["comments"] == 0

    def test_genuinely_numeric_comments_still_parses_correctly(self, collector):
        """The fix must not break feeds that legitimately provide a number."""
        root = ET.fromstring(_NUMERIC_COMMENTS_ITEM_XML)
        items = collector._parse_rss(root)
        assert items[0]["comments"] == 42

    def test_missing_comments_element_defaults_to_zero(self, collector):
        root = ET.fromstring(_MISSING_COMMENTS_ITEM_XML)
        items = collector._parse_rss(root)
        assert items[0]["comments"] == 0

    def test_item_with_url_comments_converts_to_signal_successfully(self, collector):
        """End-to-end: the full item (not just _parse_rss) must produce a
        usable Signal, proving the fix doesn't just avoid a crash but
        actually restores the intended collection behaviour."""
        root = ET.fromstring(_HNRSS_ITEM_XML)
        items = collector._parse_rss(root)
        sig = collector._item_to_signal(items[0], "https://hnrss.org/ask")
        assert sig is not None
        assert sig.comment_count == 0
        assert sig.title == "Ask HN: How do I reconcile invoices?"


class TestSafeIntHelper:
    def test_valid_integer_string(self, collector):
        assert collector._safe_int("42") == 42

    def test_url_string_defaults(self, collector):
        assert collector._safe_int("https://news.ycombinator.com/item?id=1") == 0

    def test_empty_string_defaults(self, collector):
        assert collector._safe_int("") == 0

    def test_custom_default(self, collector):
        assert collector._safe_int("not a number", default=7) == 7

    def test_none_defaults(self, collector):
        assert collector._safe_int(None) == 0


# ── Issue 6: Stack Overflow 403 handling ──────────────────────────────────

class _FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, code):
        super().__init__(url="https://stackoverflow.com/feeds/tag/saas", code=code,
                          msg="error", hdrs=None, fp=None)


class TestForbiddenResponseHandling:
    def test_403_raises_collector_error_not_generic_http_error(self, collector, monkeypatch):
        def raise_403(*args, **kwargs):
            raise _FakeHTTPError(403)
        monkeypatch.setattr("urllib.request.urlopen", raise_403)

        with pytest.raises(CollectorError) as exc_info:
            collector._fetch_feed("https://stackoverflow.com/feeds/tag/saas")

        message = str(exc_info.value)
        assert "403" in message
        # Must read as an external condition, not imply our request was malformed.
        assert "bot protection" in message.lower() or "external" in message.lower()

    def test_403_does_not_crash_fetch_or_stop_other_feeds(self, monkeypatch):
        """A 403 on one feed must be caught and logged, not propagate and
        abort collection of the remaining feeds — same contract as any
        other CollectorError raised inside _fetch()."""
        two_feed_collector = RSSCollector(feeds=[
            ("https://stackoverflow.com/feeds/tag/saas", "blocked feed"),
            ("https://example.com/good-feed", "working feed"),
        ])

        call_count = {"n": 0}

        def fake_fetch_feed(self, url):
            call_count["n"] += 1
            if "stackoverflow" in url:
                raise CollectorError(f"{url} returned 403 (likely external bot protection)")
            return []

        monkeypatch.setattr(RSSCollector, "_fetch_feed", fake_fetch_feed)
        # Should not raise — _fetch() catches CollectorError per feed.
        list(two_feed_collector._fetch(limit=10))
        assert call_count["n"] == 2  # both feeds were attempted

    def test_429_still_raises_rate_limit_error(self, collector, monkeypatch):
        """Regression guard: the new 403 branch must not have disturbed the
        existing 429 handling."""
        def raise_429(*args, **kwargs):
            raise _FakeHTTPError(429)
        monkeypatch.setattr("urllib.request.urlopen", raise_429)

        with pytest.raises(RateLimitError):
            collector._fetch_feed("https://example.com/feed")

    def test_other_http_errors_still_generic(self, collector, monkeypatch):
        def raise_500(*args, **kwargs):
            raise _FakeHTTPError(500)
        monkeypatch.setattr("urllib.request.urlopen", raise_500)

        with pytest.raises(CollectorError) as exc_info:
            collector._fetch_feed("https://example.com/feed")
        assert "500" in str(exc_info.value)


class TestAggregateFailureOutcome:
    """
    RSS deliberately tolerates individual feed failures so one bad feed
    doesn't kill the whole collector run. But that tolerance must not
    also hide the case where *every* feed we attempted this run failed —
    that's a real outage and the scheduler needs to see it (via _fetch()
    raising) rather than record a false SUCCESS with zero signals.
    """

    def test_all_feeds_failing_raises_collector_error(self, monkeypatch):
        collector = RSSCollector(feeds=[
            ("https://a.example.com/feed", "feed a"),
            ("https://b.example.com/feed", "feed b"),
            ("https://c.example.com/feed", "feed c"),
        ])

        def always_fail(self, url):
            raise CollectorError(f"{url} returned 500")

        monkeypatch.setattr(RSSCollector, "_fetch_feed", always_fail)

        with pytest.raises(CollectorError) as exc_info:
            list(collector._fetch(limit=10))
        assert "3" in str(exc_info.value)  # all 3 attempted feeds failed

    def test_partial_failure_does_not_raise(self, monkeypatch):
        """Regression: one bad feed among several good ones must remain a
        SUCCESS at the _fetch() level — same case as
        test_403_does_not_crash_fetch_or_stop_other_feeds, asserted here
        directly against the aggregate-failure guard."""
        collector = RSSCollector(feeds=[
            ("https://bad.example.com/feed", "bad feed"),
            ("https://good.example.com/feed", "good feed"),
        ])

        def fake_fetch_feed(self, url):
            if "bad" in url:
                raise CollectorError(f"{url} returned 500")
            return []

        monkeypatch.setattr(RSSCollector, "_fetch_feed", fake_fetch_feed)
        # Should not raise — only one of two attempted feeds failed.
        assert list(collector._fetch(limit=10)) == []

    def test_all_feeds_succeeding_with_zero_items_is_not_a_failure(self, monkeypatch):
        """All feeds reachable, none have new items — a quiet day, not an
        outage. Must not raise."""
        collector = RSSCollector(feeds=[
            ("https://a.example.com/feed", "feed a"),
            ("https://b.example.com/feed", "feed b"),
        ])
        monkeypatch.setattr(RSSCollector, "_fetch_feed", lambda self, url: [])

        assert list(collector._fetch(limit=10)) == []

    def test_no_feeds_attempted_does_not_manufacture_failure(self, monkeypatch):
        """If the limit is already satisfied before every feed is tried,
        the unattempted feeds must not count against us."""
        collector = RSSCollector(feeds=[
            ("https://a.example.com/feed", "feed a"),
            ("https://b.example.com/feed", "feed b"),
        ])

        call_count = {"n": 0}

        def fake_fetch_feed(self, url):
            call_count["n"] += 1
            return [{
                "title": "Something happened",
                "link": f"{url}/1",
                "guid": f"{url}/1",
            }]

        monkeypatch.setattr(RSSCollector, "_fetch_feed", fake_fetch_feed)
        monkeypatch.setattr(RSSCollector, "_is_duplicate", lambda self, *a, **kw: False)
        signals = list(collector._fetch(limit=1))

        assert len(signals) == 1
        assert call_count["n"] == 1  # second feed never attempted, no raise

    def test_rate_limit_error_still_propagates_through_fetch(self, monkeypatch):
        """RateLimitError handling must remain untouched by the aggregate
        failure tracking — it still stops _fetch() immediately."""
        collector = RSSCollector(feeds=[
            ("https://a.example.com/feed", "feed a"),
            ("https://b.example.com/feed", "feed b"),
        ])

        def fake_fetch_feed(self, url):
            raise RateLimitError(f"{url} rate limited")

        monkeypatch.setattr(RSSCollector, "_fetch_feed", fake_fetch_feed)

        with pytest.raises(RateLimitError):
            list(collector._fetch(limit=10))
