"""
collectors/stackexchange_collector.py — Stack Exchange signal collection

Data source: Stack Exchange REST API v2.3 (https://api.stackexchange.com/docs)
  Endpoint: /2.3/questions
  Authentication: Optional API key via ?key=<key>. Unauthenticated requests
    use a shared IP-based quota. A registered key is recommended for more
    predictable quota allocation; actual quota values (quota_remaining,
    quota_max) are taken from the API response wrapper at runtime.
  Rate limits & throttling:
    - Checked via top-level JSON wrapper:
      - `backoff`: integer seconds; if present, client must pause before the
        next request to this API.
      - `quota_remaining`: integer remaining requests; if 0, collector raises
        RateLimitError.
      - `quota_max`: integer total daily quota.
    - HTTP 429 and HTTP 400 with error_id=502 (throttle violation) map to
      RateLimitError.

Evidence & Domain Relevance:
  - Technical pain points, architectural friction, integration questions,
    unanswered questions, and community interest.
  - Queries are configured per-domain via DomainSources.stackexchange_queries
    (list of StackExchangeQuery objects).

Tagging & Signal Contract:
  - Preserves observable source facts without imposing business conclusions.
  - Tags emitted:
    - site:<site_name> (e.g. site:stackoverflow, site:freelancing)
    - se:tag:<tag_name> (e.g. se:tag:saas, se:tag:multi-tenant)
    - se:no_accepted_answer (when accepted_answer_id is null/absent)
    - se:zero_answers (when answer_count == 0)
    - se:answered (when is_answered == True, meaning >=1 upvoted answer)
  - platform_score: net question votes (score, preserves negative scores)
  - comment_count: maps to answer_count (represents answer/discussion volume
    on Stack Exchange; raw comment_count is also retained in raw_metadata)
  - source_id: "{question_id}|{site}" (provides permanent, cross-site unique IDs)
  - Attribution & licensing metadata (owner display name, user ID, link, and
    content_license) are preserved in raw_metadata.
"""

from __future__ import annotations

import html
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Generator

import requests

from config import (
    STACKEXCHANGE_PAGE_SIZE,
    STACKEXCHANGE_QUESTION_LIMIT,
    STACKEXCHANGE_REQUEST_DELAY,
    STACKEXCHANGE_WINDOW_DAYS,
)
from domains.base import StackExchangeQuery
from models import Signal
from .base import BaseCollector, CollectorError, RateLimitError

_API_BASE = "https://api.stackexchange.com/2.3"
_TIMEOUT = 10  # seconds per HTTP request
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
# Tags replaced with spaces can create "word ." artifacts; strip spaces before punctuation.
_SPACE_BEFORE_PUNCT_RE = re.compile(r" +([.,;:!?\"'\)\]])")


class StackExchangeCollector(BaseCollector):
    """
    Collects questions from the Stack Exchange API (/2.3/questions).
    """

    SOURCE_NAME = "stackexchange"
    DEFAULT_LIMIT = STACKEXCHANGE_QUESTION_LIMIT

    def __init__(
        self,
        queries: list[StackExchangeQuery] | None = None,
        domain: str = "business",
        window_days: int = STACKEXCHANGE_WINDOW_DAYS,
        api_key: str | None = None,
    ):
        """
        Args:
            queries: Configured StackExchangeQuery(site, tags) entries.
            domain: Domain ID for scoping.
            window_days: Number of days in the lookback window.
            api_key: Optional Stack Exchange API key. If not provided, reads
                     STACKEXCHANGE_API_KEY environment variable.
        """
        super().__init__(domain=domain)
        self._queries: list[StackExchangeQuery] = queries or []
        self._window_days = window_days
        self._api_key = (
            api_key if api_key is not None else os.getenv("STACKEXCHANGE_API_KEY", "")
        )
        self._session: requests.Session | None = None

    def _get_session(self) -> requests.Session:
        if self._session is not None:
            return self._session

        session = requests.Session()
        session.headers.update({
            "User-Agent": "BIA-OS/1.0 signal collector (read-only)",
            "Accept": "application/json",
        })
        self._session = session
        return session

    def _fetch(self, limit: int) -> Generator[Signal, None, None]:
        if not self._queries:
            self.logger.info(
                "No Stack Exchange queries configured for this domain — skipping"
            )
            return

        if not self._api_key:
            self.logger.warning(
                "STACKEXCHANGE_API_KEY not set; running with anonymous API quota. "
                "A registered key is recommended for predictable quota allocation."
            )

        session = self._get_session()
        fromdate = int(
            (
                datetime.now(timezone.utc) - timedelta(days=self._window_days)
            ).timestamp()
        )

        total_yielded = 0
        failed_queries = 0

        for query in self._queries:
            if total_yielded >= limit:
                break

            remaining_for_run = limit - total_yielded
            query_success = False
            try:
                for signal in self._fetch_query(
                    session=session,
                    query=query,
                    fromdate=fromdate,
                    limit=remaining_for_run,
                ):
                    yield signal
                    total_yielded += 1
                    if total_yielded >= limit:
                        break
                query_success = True
            except RateLimitError:
                # Rate limiting affects the entire IP / key, must propagate immediately
                raise
            except CollectorError as e:
                self.logger.warning(
                    f"Failed to query Stack Exchange for {query.site} tags={query.tags}: {e}"
                )
                failed_queries += 1
            except Exception as e:
                self.logger.warning(
                    f"Unexpected error querying Stack Exchange for {query.site} tags={query.tags}: {e}"
                )
                failed_queries += 1

            # Courtesy delay between independent queries
            time.sleep(STACKEXCHANGE_REQUEST_DELAY)

        # Aggregate failure rule: if every configured query failed, raise CollectorError
        if failed_queries == len(self._queries):
            raise CollectorError("All Stack Exchange queries failed")

    def _fetch_query(
        self,
        session: requests.Session,
        query: StackExchangeQuery,
        fromdate: int,
        limit: int,
    ) -> Generator[Signal, None, None]:
        """Fetch questions for a single StackExchangeQuery with pagination."""
        page = 1
        yielded_for_query = 0

        while yielded_for_query < limit:
            params: dict[str, Any] = {
                "site": query.site,
                "sort": "activity",
                "order": "desc",
                "fromdate": fromdate,
                "pagesize": min(100, STACKEXCHANGE_PAGE_SIZE),
                "page": page,
                "filter": "withbody",
            }
            if query.tags:
                params["tagged"] = ";".join(query.tags)
            if self._api_key:
                params["key"] = self._api_key

            wrapper = self._request(session, params)
            items = wrapper.get("items", [])
            if not items:
                break

            for item in items:
                signal = self._question_to_signal(item, site=query.site)
                if signal and not self._is_duplicate(
                    signal.source_id, domain=self.domain
                ):
                    yield signal
                    yielded_for_query += 1
                    if yielded_for_query >= limit:
                        break

            if not wrapper.get("has_more", False):
                break

            page += 1
            time.sleep(STACKEXCHANGE_REQUEST_DELAY)

    def _request(self, session: requests.Session, params: dict[str, Any]) -> dict[str, Any]:
        """Execute GET /2.3/questions, validate HTTP & wrapper status, and respect backoff."""
        try:
            resp = session.get(f"{_API_BASE}/questions", params=params, timeout=_TIMEOUT)
        except requests.RequestException as e:
            raise CollectorError(f"Stack Exchange request failed: {e}") from e

        if resp.status_code == 429:
            raise RateLimitError("Stack Exchange rate limit hit (HTTP 429)")

        try:
            wrapper: dict[str, Any] = resp.json()
        except Exception as e:
            raise CollectorError(
                f"Stack Exchange returned non-JSON response (HTTP {resp.status_code}): {e}"
            ) from e

        if not isinstance(wrapper, dict):
            raise CollectorError("Stack Exchange returned unexpected JSON payload structure")

        # Check for error fields in response envelope
        if "error_id" in wrapper:
            error_id = wrapper.get("error_id")
            error_name = wrapper.get("error_name", "UnknownError")
            error_msg = wrapper.get("error_message", "")
            if error_id == 502 or "throttle" in error_name.lower():
                raise RateLimitError(
                    f"Stack Exchange throttle violation (error_id={error_id}, {error_name}): {error_msg}"
                )
            raise CollectorError(
                f"Stack Exchange API error (error_id={error_id}, {error_name}): {error_msg}"
            )

        if resp.status_code != 200:
            raise CollectorError(
                f"Stack Exchange HTTP {resp.status_code}: {resp.text[:200]}"
            )

        # Mandatory backoff protocol
        if "backoff" in wrapper:
            backoff_s = int(wrapper["backoff"])
            self.logger.warning(
                f"Stack Exchange response included backoff directive: {backoff_s}s"
            )
            time.sleep(backoff_s)

        # Quota monitoring: quota_remaining drives exhaustion detection.
        # quota_max is telemetry only and must not gate exhaustion detection.
        quota_remaining = wrapper.get("quota_remaining")
        quota_max = wrapper.get("quota_max")
        if quota_remaining is not None:
            if quota_max is not None:
                self.logger.debug(
                    f"Stack Exchange API quota: {quota_remaining}/{quota_max} remaining"
                )
            else:
                self.logger.debug(
                    f"Stack Exchange API quota: {quota_remaining} remaining (quota_max not in response)"
                )
            if quota_remaining == 0:
                raise RateLimitError(
                    "Stack Exchange daily request quota exhausted (quota_remaining=0)"
                )

        return wrapper

    def _clean_html(self, raw_html: str) -> str:
        """Strip HTML tags and unescape HTML entities into plain text."""
        if not raw_html:
            return ""
        text = _TAG_RE.sub(" ", raw_html)
        text = html.unescape(text)
        text = _WHITESPACE_RE.sub(" ", text).strip()
        text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
        return text

    def _question_to_signal(self, item: dict[str, Any], site: str) -> Signal | None:
        """Transform a Stack Exchange question JSON object into a canonical Signal."""
        try:
            raw_title = item.get("title", "")
            title = self._safe_text(html.unescape(raw_title))
            if not title:
                return None

            raw_body = item.get("body", "")
            content = self._safe_text(self._clean_html(raw_body))

            question_id = item.get("question_id")
            if question_id is None:
                return None

            source_id = f"{question_id}|{site}"
            url = item.get("link", "")
            score = int(item.get("score", 0))
            answer_count = int(item.get("answer_count", 0))
            is_answered = bool(item.get("is_answered", False))
            accepted_answer_id = item.get("accepted_answer_id")

            # Extract source-derived tags
            tags: list[str] = [f"site:{site}"]
            for t in item.get("tags", []):
                clean_tag = str(t).strip().lower()
                if clean_tag:
                    tags.append(f"se:tag:{clean_tag}")

            if accepted_answer_id is None:
                tags.append("se:no_accepted_answer")
            if answer_count == 0:
                tags.append("se:zero_answers")
            if is_answered:
                tags.append("se:answered")

            # Deduplicate tags preserving insertion order
            tags = list(dict.fromkeys(tags))

            owner = item.get("owner") or {}
            raw_metadata: dict[str, Any] = {
                "site": site,
                "question_id": question_id,
                "is_answered": is_answered,
                "accepted_answer_id": accepted_answer_id,
                "answer_count": answer_count,
                "view_count": int(item.get("view_count", 0)),
                "score": score,
                "tags": item.get("tags", []),
                "creation_date": item.get("creation_date"),
                "last_activity_date": item.get("last_activity_date"),
                "owner_display_name": owner.get("display_name", ""),
                "owner_link": owner.get("link", ""),
                "owner_user_id": owner.get("user_id"),
                "content_license": item.get("content_license", ""),
                "item_type": "question",
            }

            return Signal(
                source=self.SOURCE_NAME,
                source_id=source_id,
                title=title,
                content=content,
                url=url,
                platform_score=score,
                comment_count=answer_count,
                tags=tags,
                raw_metadata=raw_metadata,
                domain=self.domain,
            )
        except Exception as e:
            self.logger.debug(
                f"Skipping malformed question {item.get('question_id', '?')}: {e}"
            )
            return None
