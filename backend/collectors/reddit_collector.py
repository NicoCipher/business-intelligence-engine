"""
collectors/reddit_collector.py — Reddit signal collection

Data source: reddit.com via PRAW (Python Reddit API Wrapper)
  Official API: https://www.reddit.com/dev/api
  Free tier: 60 requests/minute for non-commercial use (we stay well under)
  Authentication: read-only via script credentials (no user account needed)

Setup (one time, free):
  1. Go to https://www.reddit.com/prefs/apps
  2. Create app → type: "script"
  3. Note client_id and client_secret
  4. Set environment variables:
       REDDIT_CLIENT_ID=your_client_id
       REDDIT_CLIENT_SECRET=your_client_secret

Why Reddit?
  Reddit communities self-organise by interest. r/entrepreneur and r/freelance
  are explicit markets for pain points and opportunity signals. Posts are
  discussion, not advertisements. The upvote system surfaces what resonates.

What we collect:
  - New and hot posts from configured subreddits
  - We read both to capture both recency (new) and quality (hot)

Flair and tags we emit:
  - subreddit name (for clustering by community)
  - demand_signal, complaint_signal, opportunity_signal (same as HN)
  - post_type: text | link (self-posts tend to be higher value for signals)
"""

import os
import time
from typing import Generator

try:
    import praw
    from praw.exceptions import APIException, RedditAPIException
    PRAW_AVAILABLE = True
except ImportError:
    PRAW_AVAILABLE = False

from .base import BaseCollector, CollectorError, RateLimitError
from config import REDDIT_SUBREDDITS, REDDIT_POST_LIMIT, REDDIT_REQUEST_DELAY
from models import Signal

_DEMAND_MARKERS = [
    "how to", "looking for", "recommend", "any tool", "best way",
    "how do i", "is there a", "does anyone", "i wish there was",
    "any alternative", "help me find", "what should i use",
    "how can i", "i'd pay", "would pay for",
]
_COMPLAINT_MARKERS = [
    "frustrated", "annoying", "terrible", "hate", "worst", "broken",
    "doesn't work", "missing feature", "no solution", "can't find",
    "why doesn't", "nobody does", "impossible",
]
_OPPORTUNITY_MARKERS = [
    "built a tool", "launched", "open source", "free alternative",
    "profitable", "bootstrapped", "side project", "i made this",
    "created a service", "started a business",
]


class RedditCollector(BaseCollector):
    """
    Collects signals from configured subreddits via the official Reddit API.

    Falls back gracefully if PRAW is not installed or credentials are missing —
    returns an empty list and logs a clear explanation.
    """

    SOURCE_NAME = "reddit"
    DEFAULT_LIMIT = REDDIT_POST_LIMIT

    def __init__(
        self,
        subreddits: list[str] | None = None,
        domain: str = "business",
    ):
        """
        Args:
            subreddits: Subreddits to monitor. Defaults to config.REDDIT_SUBREDDITS
                        for backward compatibility with callers that don't pass
                        domain-specific sources. In the real pipeline, this comes
                        from DomainConfig.sources.reddit_sources — see pipeline.py.
            domain:     The domain these collected signals belong to.
        """
        super().__init__(domain=domain)
        self._subreddits = subreddits if subreddits is not None else REDDIT_SUBREDDITS
        self._reddit: "praw.Reddit | None" = None

    def _get_client(self) -> "praw.Reddit":
        """Lazy-initialise the PRAW client. Raises CollectorError if unavailable."""
        if self._reddit is not None:
            return self._reddit

        if not PRAW_AVAILABLE:
            raise CollectorError(
                "PRAW is not installed. Run: pip install praw"
            )

        client_id = os.getenv("REDDIT_CLIENT_ID", "")
        client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")

        if not client_id or not client_secret:
            raise CollectorError(
                "Reddit credentials not set. "
                "Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET environment variables. "
                "See: https://www.reddit.com/prefs/apps"
            )

        self._reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent="BIA-OS/1.0 signal collector (read-only)",
            # Read-only mode — no user login required
        )
        self._reddit.read_only = True
        return self._reddit

    def _fetch(self, limit: int) -> Generator[Signal, None, None]:
        if not self._subreddits:
            self.logger.info("No subreddits configured for this domain — skipping")
            return

        client = self._get_client()
        per_sub = max(1, limit // len(self._subreddits))

        for sub_name in self._subreddits:
            self.logger.debug(f"Fetching r/{sub_name} (limit={per_sub})")
            try:
                yield from self._fetch_subreddit(client, sub_name, per_sub)
                time.sleep(REDDIT_REQUEST_DELAY)
            except RateLimitError:
                raise   # propagate up to collect() for backoff
            except Exception as e:
                # One subreddit failing must not stop the others
                self.logger.warning(f"Failed to fetch r/{sub_name}: {e}")

    def _fetch_subreddit(
        self,
        client: "praw.Reddit",
        sub_name: str,
        limit: int,
    ) -> Generator[Signal, None, None]:
        """
        Fetch from both 'new' and 'hot' feeds.
        New captures recency; hot captures quality. Combined they cover both.
        """
        try:
            sub = client.subreddit(sub_name)

            # new: recent posts, possibly low engagement but timely
            for submission in sub.new(limit=limit):
                signal = self._submission_to_signal(submission, sub_name)
                if signal and not self._is_duplicate(signal.source_id, domain=self.domain):
                    yield signal

            # hot: community-validated posts, higher engagement
            for submission in sub.hot(limit=limit // 2):
                signal = self._submission_to_signal(submission, sub_name)
                if signal and not self._is_duplicate(signal.source_id, domain=self.domain):
                    yield signal

        except RedditAPIException as e:
            for item in e.items:
                if item.error_type in ("RATELIMIT", "TOO_MANY_REQUESTS"):
                    raise RateLimitError(f"Reddit rate limit: {item.message}")
            raise CollectorError(f"Reddit API error for r/{sub_name}: {e}")
        except APIException as e:
            raise CollectorError(f"Reddit API exception for r/{sub_name}: {e}")

    def _submission_to_signal(
        self,
        submission,
        sub_name: str,
    ) -> Signal | None:
        """Convert a PRAW Submission to a Signal."""
        try:
            title = self._safe_text(getattr(submission, "title", ""))
            if not title:
                return None

            # Deleted or removed
            if submission.selftext in ("[deleted]", "[removed]"):
                return None

            source_id = submission.id
            url = f"https://reddit.com{submission.permalink}"
            content = self._safe_text(getattr(submission, "selftext", ""))
            score = int(getattr(submission, "score", 0))
            comments = int(getattr(submission, "num_comments", 0))
            is_self = bool(getattr(submission, "is_self", True))

            tags = self._extract_tags(title, content, sub_name, is_self)

            return Signal(
                source=self.SOURCE_NAME,
                source_id=source_id,
                title=title,
                content=content,
                url=url,
                platform_score=score,
                comment_count=comments,
                tags=tags,
                raw_metadata={
                    "subreddit":   sub_name,
                    "author":      str(getattr(submission, "author", "") or ""),
                    "flair":       getattr(submission, "link_flair_text", "") or "",
                    "post_type":   "text" if is_self else "link",
                    "upvote_ratio": round(getattr(submission, "upvote_ratio", 0.5), 2),
                    "created_utc": int(getattr(submission, "created_utc", 0)),
                },
                domain=self.domain,
            )
        except Exception as e:
            self.logger.debug(f"Skipping submission {getattr(submission, 'id', '?')}: {e}")
            return None

    @staticmethod
    def _extract_tags(
        title: str,
        content: str,
        sub_name: str,
        is_self: bool,
    ) -> list[str]:
        combined = f"{title} {content}".lower()
        tags = [f"r/{sub_name}"]

        if is_self:
            tags.append("self_post")   # self-posts carry more discussion signal

        if any(m in combined for m in _DEMAND_MARKERS):
            tags.append("demand_signal")
        if any(m in combined for m in _COMPLAINT_MARKERS):
            tags.append("complaint_signal")
        if any(m in combined for m in _OPPORTUNITY_MARKERS):
            tags.append("opportunity_signal")

        return list(dict.fromkeys(tags))
