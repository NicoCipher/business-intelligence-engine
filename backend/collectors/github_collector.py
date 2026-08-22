"""
collectors/github_collector.py — GitHub signal collection

Data source: GitHub REST API v3 (https://docs.github.com/en/rest/search)
  Authentication: personal access token, "public_repo" read scope is enough
  Rate limits: 5000 req/hr authenticated in general, but the Search API
    endpoints used here (/search/issues, /search/repositories) have a
    separate, much stricter limit of 30 requests/minute. That's the
    binding constraint for this collector, not the general limit.

Setup (one time, free):
  1. https://github.com/settings/tokens -> Generate new token (fine-grained)
  2. Read-only access to public repositories is sufficient
  3. Set environment variable:
       GITHUB_TOKEN=your_token

Why GitHub?
  Two distinct signal types from one platform:
    - Issue search: feature requests and "is there a tool for X" issues
      filed against public repos -- demand signal, same shape as Reddit
      posts or Ask HN.
    - Repository search: does something matching this query already
      exist, and how much traction does it have (stars)? This is direct,
      checkable evidence for the competition dimension that none of the
      other sources give -- Reddit/HN only ever say a gap *might* exist;
      an absent or low-star repo search result is closer to confirmation.

What we collect:
  - Open issues matching configured search phrases (recency-sorted)
  - Public repositories matching the same phrases (star-sorted, so the
    most established potential competitor surfaces first)

Tags we emit:
  - demand_signal, complaint_signal, opportunity_signal (issues only,
    same convention as reddit_collector.py/hn_collector.py)
  - competitor_signal (repositories only -- a repo search result is by
    definition evidence a similar solution may already exist)
  - language:{lang} (repositories only, when GitHub reports one)
"""

import os
import time
from typing import Generator

import requests

from .base import BaseCollector, CollectorError, ConfigurationError, RateLimitError
from config import GITHUB_SEARCH_LIMIT, GITHUB_REQUEST_DELAY
from models import Signal

_API_BASE = "https://api.github.com"
_TIMEOUT = 10  # seconds per request

_DEMAND_MARKERS = [
    "feature request", "would be nice", "any plans to", "is there a way",
    "looking for", "does this support", "how do i", "is it possible to",
    "would love to see", "any workaround",
]
_COMPLAINT_MARKERS = [
    "doesn't work", "broken", "not working", "fails", "frustrated",
    "no way to", "missing", "can't figure out",
]
_OPPORTUNITY_MARKERS = [
    "open source", "just released", "launched", "new project",
    "free alternative", "built this",
]


class GitHubCollector(BaseCollector):
    """
    Collects signals from GitHub's issue and repository search endpoints.

    Falls back gracefully if GITHUB_TOKEN is not set -- raises
    CollectorError with a clear setup message, caught by collect() same
    as every other collector's missing-credential path.
    """

    SOURCE_NAME = "github"
    DEFAULT_LIMIT = GITHUB_SEARCH_LIMIT

    def __init__(
        self,
        queries: list[str] | None = None,
        domain: str = "business",
    ):
        """
        Args:
            queries: Plain search phrases. Defaults to [] (no queries ->
                     _fetch() logs and returns, same pattern as
                     RedditCollector with no subreddits configured). In
                     the real pipeline, this comes from
                     DomainConfig.sources.github_queries -- see
                     pipeline.py.
            domain:  The domain these collected signals belong to.
        """
        super().__init__(domain=domain)
        self._queries = queries or []
        self._session: requests.Session | None = None

    def _get_session(self) -> requests.Session:
        """Lazy-initialise the authenticated session. Raises CollectorError
        if GITHUB_TOKEN is unset."""
        if self._session is not None:
            return self._session

        token = os.getenv("GITHUB_TOKEN", "")
        if not token:
            raise ConfigurationError(
                "GitHub token not set. Set the GITHUB_TOKEN environment "
                "variable. See: https://github.com/settings/tokens"
            )

        session = requests.Session()
        session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "BIA-OS/1.0 signal collector (read-only)",
        })
        self._session = session
        return session

    def _fetch(self, limit: int) -> Generator[Signal, None, None]:
        if not self._queries:
            self.logger.info("No GitHub queries configured for this domain — skipping")
            return

        session = self._get_session()
        # Each query hits two endpoints (issues + repos), so split the
        # overall limit accordingly -- same idea as RedditCollector
        # dividing its limit across subreddits.
        per_query = max(1, limit // (len(self._queries) * 2))

        for query in self._queries:
            self.logger.debug(f"Searching GitHub for '{query}' (limit={per_query})")
            try:
                yield from self._search_issues(session, query, per_query)
                time.sleep(GITHUB_REQUEST_DELAY)
                yield from self._search_repos(session, query, per_query)
                time.sleep(GITHUB_REQUEST_DELAY)
            except RateLimitError:
                raise   # propagate up to collect() for backoff
            except Exception as e:
                # One query failing must not stop the others
                self.logger.warning(f"Failed to search GitHub for '{query}': {e}")

    def _search_issues(
        self, session: requests.Session, query: str, limit: int,
    ) -> Generator[Signal, None, None]:
        """Open issues matching `query`, most recent first."""
        params = {
            "q": f"{query} is:issue is:open",
            "sort": "created",
            "order": "desc",
            "per_page": limit,
        }
        for item in self._search(session, "issues", params):
            signal = self._issue_to_signal(item)
            if signal and not self._is_duplicate(signal.source_id, domain=self.domain):
                yield signal

    def _search_repos(
        self, session: requests.Session, query: str, limit: int,
    ) -> Generator[Signal, None, None]:
        """Public repositories matching `query`, most-starred first --
        surfaces the most established potential competitor, if one exists."""
        params = {
            "q": f"{query} is:public",
            "sort": "stars",
            "order": "desc",
            "per_page": limit,
        }
        for item in self._search(session, "repositories", params):
            signal = self._repo_to_signal(item)
            if signal and not self._is_duplicate(signal.source_id, domain=self.domain):
                yield signal

    def _search(
        self, session: requests.Session, endpoint: str, params: dict,
    ) -> list[dict]:
        try:
            resp = session.get(f"{_API_BASE}/search/{endpoint}", params=params, timeout=_TIMEOUT)
        except requests.RequestException as e:
            raise CollectorError(f"GitHub search request failed: {e}")

        if resp.status_code == 403:
            remaining = resp.headers.get("X-RateLimit-Remaining")
            retry_after = resp.headers.get("Retry-After", "60")
            if remaining == "0" or "rate limit" in resp.text.lower():
                raise RateLimitError(f"GitHub rate limit hit; retry after {retry_after}s")
            raise CollectorError(f"GitHub search forbidden: {resp.text[:200]}")
        if resp.status_code == 422:
            raise CollectorError(f"GitHub rejected search query: {resp.text[:200]}")
        if resp.status_code != 200:
            raise CollectorError(f"GitHub search returned {resp.status_code}: {resp.text[:200]}")

        return resp.json().get("items", [])

    def _issue_to_signal(self, item: dict) -> Signal | None:
        try:
            title = self._safe_text(item.get("title", ""))
            if not title:
                return None

            body = self._safe_text(item.get("body") or "")
            repo_url = item.get("repository_url", "")
            repo_name = repo_url.rsplit("/", 2)[-2:] if repo_url else []
            repo_full_name = "/".join(repo_name) if repo_name else ""

            reactions = item.get("reactions", {}) or {}
            platform_score = int(reactions.get("total_count", 0))
            comment_count = int(item.get("comments", 0))

            tags = self._extract_issue_tags(title, body, repo_full_name)

            return Signal(
                source=self.SOURCE_NAME,
                source_id=f"issue-{item['id']}",
                title=title,
                content=body,
                url=item.get("html_url", ""),
                platform_score=platform_score,
                comment_count=comment_count,
                tags=tags,
                raw_metadata={
                    "repo": repo_full_name,
                    "labels": [l.get("name", "") for l in item.get("labels", [])],
                    "state": item.get("state", ""),
                    "author": (item.get("user") or {}).get("login", ""),
                    "created_at": item.get("created_at", ""),
                    "item_type": "issue",
                },
                domain=self.domain,
            )
        except Exception as e:
            self.logger.debug(f"Skipping issue {item.get('id', '?')}: {e}")
            return None

    def _repo_to_signal(self, item: dict) -> Signal | None:
        try:
            title = self._safe_text(item.get("full_name", ""))
            if not title:
                return None

            description = self._safe_text(item.get("description") or "")
            stars = int(item.get("stargazers_count", 0))
            language = item.get("language") or ""

            tags = ["competitor_signal"]
            if language:
                tags.append(f"language:{language.lower()}")

            return Signal(
                source=self.SOURCE_NAME,
                source_id=f"repo-{item['id']}",
                title=title,
                content=description,
                url=item.get("html_url", ""),
                platform_score=stars,
                comment_count=0,  # not applicable to repositories
                tags=tags,
                raw_metadata={
                    "language":   language,
                    "topics":     item.get("topics", []),
                    "forks":      int(item.get("forks_count", 0)),
                    "created_at": item.get("created_at", ""),
                    "item_type":  "repository",
                },
                domain=self.domain,
            )
        except Exception as e:
            self.logger.debug(f"Skipping repo {item.get('id', '?')}: {e}")
            return None

    @staticmethod
    def _extract_issue_tags(title: str, body: str, repo_full_name: str) -> list[str]:
        combined = f"{title} {body}".lower()
        tags = []
        if repo_full_name:
            tags.append(f"repo:{repo_full_name}")

        if any(m in combined for m in _DEMAND_MARKERS):
            tags.append("demand_signal")
        if any(m in combined for m in _COMPLAINT_MARKERS):
            tags.append("complaint_signal")
        if any(m in combined for m in _OPPORTUNITY_MARKERS):
            tags.append("opportunity_signal")

        return list(dict.fromkeys(tags))
