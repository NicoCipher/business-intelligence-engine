"""
collectors/hn_collector.py — Hacker News signal collection

Data source: https://hacker-news.firebaseio.com/v0/ (official public API)
  - No authentication required
  - No documented rate limit; we self-impose 150ms between item fetches
  - Terms of service: public API, no restrictions on use

Why HN?
  Hacker News has unusually high signal quality for this system's purpose.
  Ask HN posts are explicit questions from practitioners who cannot find a
  solution. Show HN posts signal new products entering a market. High comment
  counts indicate the community cares about the topic.

What we collect:
  - Top stories (sorted by community score)
  - We prioritise Ask HN and Show HN by giving them higher base scores
    in the signal's platform_score field

Tags we emit (used by the pattern detector):
  - category: ask | show | tell | story
  - demand_signal   — explicit question about a solution
  - complaint_signal — frustration with existing options
  - opportunity_signal — product launch or market entry
  - tech keywords embedded in title
"""

import time
from typing import Generator

import requests

from .base import BaseCollector, CollectorError, RateLimitError
from config import HN_STORY_LIMIT, HN_REQUEST_DELAY_S
from models import Signal

HN_API = "https://hacker-news.firebaseio.com/v0"
_TIMEOUT = 10  # seconds per request

_DEMAND_MARKERS = [
    "ask hn:", "how do", "looking for", "recommend", "any tool",
    "best way", "how can i", "is there a", "does anyone",
    "what's the best", "any alternative", "help me find",
]
_COMPLAINT_MARKERS = [
    "frustrated", "why doesn't", "annoying", "broken", "terrible",
    "worst", "fails", "problem with", "missing feature", "can't find",
]
_OPPORTUNITY_MARKERS = [
    "show hn:", "launched", "open source", "free alternative",
    "built this because", "profitable", "bootstrapped", "released",
]
_TECH_MARKERS = [
    "ai", "llm", "gpt", "ml", "saas", "api", "rust", "python",
    "react", "database", "cloud", "serverless", "open source",
    "automation", "vector", "embedding", "agent",
]


class HNCollector(BaseCollector):
    """
    Collects signals from Hacker News top stories.

    Fetches 3× the requested limit to allow for filtering out duplicates,
    deleted posts, and irrelevant items.
    """

    SOURCE_NAME = "hn"
    DEFAULT_LIMIT = HN_STORY_LIMIT

    def __init__(self):
        super().__init__()
        self._session = requests.Session()
        self._session.headers["User-Agent"] = (
            "BIA-OS/1.0 signal collector — github.com/your-org/bia-os"
        )

    def _fetch(self, limit: int) -> Generator[Signal, None, None]:
        story_ids = self._get_top_story_ids(limit * 4)
        self.logger.debug(f"Fetched {len(story_ids)} story IDs from HN")

        count = 0
        for story_id in story_ids:
            if count >= limit:
                break

            # Cheap duplicate check before making an HTTP request for the item
            if self._is_duplicate(str(story_id)):
                continue

            item = self._fetch_item(story_id)
            if not item:
                continue

            signal = self._item_to_signal(item)
            if signal:
                yield signal
                count += 1

            time.sleep(HN_REQUEST_DELAY_S)

    def _get_top_story_ids(self, n: int) -> list[int]:
        try:
            resp = self._session.get(f"{HN_API}/topstories.json", timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.json()[:n]
        except requests.Timeout:
            raise CollectorError("Timeout fetching HN top story IDs")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                raise RateLimitError("HN returned 429")
            raise CollectorError(f"HTTP error fetching HN top stories: {e}")
        except requests.RequestException as e:
            raise CollectorError(f"Network error fetching HN top stories: {e}")

    def _fetch_item(self, item_id: int) -> dict | None:
        try:
            resp = self._session.get(
                f"{HN_API}/item/{item_id}.json", timeout=_TIMEOUT
            )
            resp.raise_for_status()
            return resp.json()
        except requests.Timeout:
            self.logger.debug(f"Timeout fetching item {item_id}, skipping")
            return None
        except Exception as e:
            self.logger.debug(f"Failed to fetch item {item_id}: {e}")
            return None

    def _item_to_signal(self, item: dict) -> Signal | None:
        """
        Convert a raw HN API item to a Signal.
        Returns None if the item should be skipped (wrong type, deleted, etc.)
        """
        if not item:
            return None
        if item.get("type") != "story":
            return None
        if item.get("dead") or item.get("deleted"):
            return None

        title = self._safe_text(item.get("title", ""))
        if not title:
            return None

        source_id = str(item["id"])
        url = item.get("url") or f"https://news.ycombinator.com/item?id={source_id}"
        content = self._safe_text(item.get("text", ""))
        raw_score = item.get("score", 0)
        comments = item.get("descendants", 0)

        category = self._classify_category(title)
        tags = self._extract_tags(title, content, category)

        # Ask HN posts have no URL and are self-posts — they're highest value
        # for demand signal detection. Boost their effective score.
        effective_score = raw_score
        if category == "ask":
            effective_score = raw_score + 50   # boost, not fabrication
        elif category == "show":
            effective_score = raw_score + 20

        try:
            return Signal(
                source=self.SOURCE_NAME,
                source_id=source_id,
                title=title,
                content=content,
                url=url,
                platform_score=effective_score,
                comment_count=comments,
                tags=tags,
                raw_metadata={
                    "author":   item.get("by", ""),
                    "unix_time": item.get("time", 0),
                    "category": category,
                    "raw_score": raw_score,
                },
            )
        except ValueError as e:
            self.logger.debug(f"Skipping invalid item {source_id}: {e}")
            return None

    @staticmethod
    def _classify_category(title: str) -> str:
        t = title.lower()
        if t.startswith("ask hn:"):   return "ask"
        if t.startswith("show hn:"):  return "show"
        if t.startswith("tell hn:"):  return "tell"
        return "story"

    @staticmethod
    def _extract_tags(title: str, content: str, category: str) -> list[str]:
        """
        Extract structured tags from title and content.
        Tags feed the pattern detector. Each tag is a dimension of the signal.
        """
        combined = f"{title} {content}".lower()
        tags = [category]

        if any(m in combined for m in _DEMAND_MARKERS):
            tags.append("demand_signal")
        if any(m in combined for m in _COMPLAINT_MARKERS):
            tags.append("complaint_signal")
        if any(m in combined for m in _OPPORTUNITY_MARKERS):
            tags.append("opportunity_signal")

        for tech in _TECH_MARKERS:
            if tech in combined:
                tags.append(tech)

        return list(dict.fromkeys(tags))   # deduplicate preserving order
