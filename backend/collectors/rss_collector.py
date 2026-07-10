"""
collectors/rss_collector.py — RSS feed signal collection

RSS is the oldest and most reliable way to subscribe to public data.
No API keys, no rate limits that matter, no authentication.
Standard XML format parseable with the Python stdlib.

Why RSS as the third source?
  HN (official API) and Reddit (PRAW) are our primary sources.
  RSS extends coverage to sources that don't have APIs:
    - hnrss.org: filtered HN feeds by keyword — extremely high signal
    - Stack Overflow tag feeds: skill demand signals from practitioners
  RSS also serves as a fallback if PRAW credentials are not configured.

Feed selection rationale:
  We include Ask HN and Show HN as separate feeds from the HN collector
  because hnrss.org applies keyword filters that the Firebase API doesn't
  easily support. This surfaces niche Ask HN posts that the top-stories
  endpoint would miss.

Dependencies:
  Uses only Python stdlib (urllib + xml.etree). No feedparser needed.
  This keeps the dependency count minimal and avoids any version conflicts.

Adding feeds:
  Update RSS_FEEDS in config.py to add or remove sources.
  Each entry is a (url, description) tuple. The collector handles all URLs
  the same way — no source-specific logic required.
"""

import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Generator

from .base import BaseCollector, CollectorError, RateLimitError
from models import Signal

# Namespaces used in RSS 2.0 and Atom feeds
_RSS_NS = {
    "atom":    "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc":      "http://purl.org/dc/elements/1.1/",
}

# Default RSS feeds — tunable via config
DEFAULT_RSS_FEEDS: list[tuple[str, str]] = [
    # hnrss.org — free filtered HN feeds, no rate limits
    (
        "https://hnrss.org/ask",
        "Ask HN — direct questions (highest demand signal value)",
    ),
    (
        "https://hnrss.org/show",
        "Show HN — product launches (market entry signals)",
    ),
    (
        "https://hnrss.org/newest?q=freelance+OR+saas+OR+automation+OR+side+project",
        "HN keyword filter — opportunity-adjacent discussions",
    ),
    # Stack Overflow tag feeds — skill and technology demand signals
    (
        "https://stackoverflow.com/feeds/tag/saas",
        "Stack Overflow SaaS tag — technical demand for SaaS tooling",
    ),
    (
        "https://stackoverflow.com/feeds/tag/automation",
        "Stack Overflow automation tag — automation skill demand",
    ),
]

# Demand/complaint/opportunity tag markers — same logic as HN collector
_DEMAND_MARKERS = [
    "how to", "looking for", "any tool", "recommend", "best way",
    "is there a", "does anyone", "help me", "i wish", "need a",
]
_COMPLAINT_MARKERS = [
    "frustrated", "broken", "annoying", "terrible", "doesn't work",
    "missing", "no solution", "can't find", "impossible",
]
_OPPORTUNITY_MARKERS = [
    "launched", "open source", "free alternative", "built this",
    "released", "announcing", "show hn",
]

_TIMEOUT = 12       # seconds per feed request
_DELAY   = 0.5      # seconds between feeds (polite but fast)
_HEADERS = {
    "User-Agent": "BIA-OS/1.0 RSS reader — business intelligence collector",
    "Accept":     "application/rss+xml, application/atom+xml, application/xml, text/xml",
}


class RSSCollector(BaseCollector):
    """
    Collects signals from a configurable list of RSS/Atom feeds.

    Handles both RSS 2.0 and Atom 1.0 formats transparently.
    Errors on individual feeds are logged and skipped — one broken
    feed does not stop the others.
    """

    SOURCE_NAME  = "rss"
    DEFAULT_LIMIT = 40

    def __init__(self, feeds: list[tuple[str, str]] | None = None):
        super().__init__()
        self._feeds = feeds or DEFAULT_RSS_FEEDS

    def _fetch(self, limit: int) -> Generator[Signal, None, None]:
        per_feed = max(1, limit // len(self._feeds))
        count    = 0

        for url, description in self._feeds:
            if count >= limit:
                break

            self.logger.debug(f"Fetching feed: {url}")
            try:
                items  = self._fetch_feed(url)
                for item in items[:per_feed]:
                    if count >= limit:
                        break
                    sig = self._item_to_signal(item, url)
                    if sig and not self._is_duplicate(sig.source_id):
                        yield sig
                        count += 1
            except RateLimitError:
                raise
            except CollectorError as e:
                self.logger.warning(f"Skipping feed {url}: {e}")
            except Exception as e:
                self.logger.warning(f"Unexpected error for feed {url}: {e}")

            time.sleep(_DELAY)

    def _fetch_feed(self, url: str) -> list[dict]:
        """
        Download and parse one RSS or Atom feed.
        Returns a list of item dicts with normalised fields.
        """
        try:
            req  = urllib.request.Request(url, headers=_HEADERS)
            resp = urllib.request.urlopen(req, timeout=_TIMEOUT)
            raw  = resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise RateLimitError(f"RSS 429 from {url}")
            raise CollectorError(f"HTTP {e.code} fetching {url}")
        except urllib.error.URLError as e:
            raise CollectorError(f"URL error for {url}: {e.reason}")
        except TimeoutError:
            raise CollectorError(f"Timeout fetching {url}")

        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise CollectorError(f"XML parse error for {url}: {e}")

        # Detect format: Atom uses {http://www.w3.org/2005/Atom} prefix
        if root.tag == "{http://www.w3.org/2005/Atom}feed":
            return self._parse_atom(root)
        return self._parse_rss(root)

    def _parse_rss(self, root: ET.Element) -> list[dict]:
        """Parse RSS 2.0 <item> elements."""
        items = []
        channel = root.find("channel")
        if channel is None:
            channel = root

        for item in channel.findall("item"):
            items.append({
                "title":   self._text(item, "title"),
                "link":    self._text(item, "link"),
                "guid":    self._text(item, "guid") or self._text(item, "link"),
                "desc":    self._text(item, "description"),
                "content": self._text(item, f"{{{_RSS_NS['content']}}}encoded"),
                "date":    self._text(item, "pubDate"),
                "score":   0,
                "comments": int(self._text(item, "comments") or 0),
            })
        return items

    def _parse_atom(self, root: ET.Element) -> list[dict]:
        """Parse Atom 1.0 <entry> elements."""
        ns   = _RSS_NS["atom"]
        items = []
        for entry in root.findall(f"{{{ns}}}entry"):
            link_el = entry.find(f"{{{ns}}}link")
            link    = link_el.get("href", "") if link_el is not None else ""
            items.append({
                "title":   self._text(entry, f"{{{ns}}}title"),
                "link":    link,
                "guid":    self._text(entry, f"{{{ns}}}id") or link,
                "desc":    self._text(entry, f"{{{ns}}}summary"),
                "content": self._text(entry, f"{{{ns}}}content"),
                "date":    self._text(entry, f"{{{ns}}}updated"),
                "score":   0,
                "comments": 0,
            })
        return items

    def _item_to_signal(self, item: dict, feed_url: str) -> Signal | None:
        """Convert a parsed feed item to a Signal."""
        title = self._safe_text(item.get("title", ""))
        if not title:
            return None

        guid = self._safe_text(item.get("guid") or item.get("link") or "")
        if not guid:
            return None

        content = self._safe_text(
            item.get("content") or item.get("desc") or "",
            max_length=2000,
        )
        url  = item.get("link", "") or feed_url
        tags = self._extract_tags(title, content, feed_url)

        try:
            return Signal(
                source=self.SOURCE_NAME,
                source_id=guid,
                title=title,
                content=content,
                url=url,
                platform_score=item.get("score", 0),
                comment_count=item.get("comments", 0),
                tags=tags,
                raw_metadata={
                    "feed_url":    feed_url,
                    "pubdate":     item.get("date", ""),
                },
            )
        except ValueError as e:
            self.logger.debug(f"Skipping item '{title[:40]}': {e}")
            return None

    @staticmethod
    def _text(el: ET.Element, tag: str) -> str:
        """Safely extract text from an XML element."""
        child = el.find(tag)
        if child is None:
            return ""
        return (child.text or "").strip()

    @staticmethod
    def _extract_tags(title: str, content: str, feed_url: str) -> list[str]:
        combined = f"{title} {content}".lower()
        tags = []

        if "hnrss.org" in feed_url:
            tags.append("hn")
        elif "stackoverflow.com" in feed_url:
            tags.append("stackoverflow")

        if any(m in combined for m in _DEMAND_MARKERS):
            tags.append("demand_signal")
        if any(m in combined for m in _COMPLAINT_MARKERS):
            tags.append("complaint_signal")
        if any(m in combined for m in _OPPORTUNITY_MARKERS):
            tags.append("opportunity_signal")

        return list(dict.fromkeys(tags))
