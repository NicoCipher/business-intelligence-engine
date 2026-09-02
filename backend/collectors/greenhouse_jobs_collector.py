"""
collectors/greenhouse_jobs_collector.py — Greenhouse public job boards collector

Data source: Greenhouse Job Board API v1 (https://developers.greenhouse.io/job-board.html)
  Base URL: https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
  Authentication: None. Public read-only endpoint for published job listings.
  Rate limits & throttling:
    - Conservative per-board request delay (GREENHOUSE_REQUEST_DELAY).
    - HTTP 429 (Too Many Requests) raises RateLimitError.
    - HTTP 403 indicating throttling / rate limiting raises RateLimitError.
    - Other HTTP errors (404, 500, etc.) and timeouts log warnings and count
      toward board-level failure; if all configured boards fail, raises CollectorError.
    - No fabricated quota values: Greenhouse does not expose quota headers on
      its public job board endpoints.

Evidence & Domain Relevance:
  - Public job postings from verified industry companies provide factual
    evidence of technical focus areas, organizational hiring, and technology
    stack investments.
  - Collector responsibility: preserve source facts and provenance only.
  - Business conclusions (demand signals, expansion, hiring surges, growth)
    are strictly downstream concerns and are NOT inferred at collection time.

Signal mapping:
  - source: "greenhouse_jobs"
  - source_id: "{job_id}|{board_token}" (cross-company collision prevention)
  - title: job title (unmodified except for whitespace trimming)
  - content: job description, HTML tags stripped, HTML entities unescaped,
    whitespace normalized, text safe-truncated
  - url: absolute_url pointing to the public job posting
  - platform_score: 0 (jobs have no upvotes/scores)
  - comment_count: 0
  - tags: source-derived only:
      "gh:job"
      "company:<normalized-company>"
      "gh:board:<board_token>"
      "gh:location:<location>"
      "gh:remote" (only if explicitly present in location/office strings)
      "gh:department:<department>"
      "gh:office:<office>"
  - raw_metadata: job_id, internal_job_id, requisition_id, company,
    board_token, location, departments, offices, updated_at, first_published,
    absolute_url, language

Privacy:
  - Ingests public job postings only.
  - Does NOT ingest candidate fields, application questions, recruiter names,
    emails, phone numbers, or personal info.

Known limitations & change detection:
  - The Greenhouse API provides an `updated_at` timestamp on each job.
  - BIA's existing (source, source_id, domain) deduplication drops seen signals
    upon subsequent runs without mutating historical rows. If a job is modified
    upstream, the original collected signal remains preserved and the update is
    not reflected. Dedicated change detection / update tracking is deferred to
    future milestones.
"""

from __future__ import annotations

import html
import logging
import re
import time
from typing import Any, Iterator

import requests

from collectors.base import (
    BaseCollector,
    CollectorError,
    RateLimitError,
)
from config import (
    GREENHOUSE_JOBS_LIMIT,
    GREENHOUSE_REQUEST_DELAY,
    GREENHOUSE_TIMEOUT_S,
)
from domains.base import GreenhouseBoard
from models import Signal

logger = logging.getLogger(__name__)

_API_BASE = "https://boards-api.greenhouse.io/v1/boards"
_USER_AGENT = "BIA-OS/1.0 (Job board evidence collector; +https://github.com/NicoCipher/business-intelligence-engine)"

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r" +([.,;:!?\"'\)\]])")
_COMPANY_NORM_RE = re.compile(r"[^a-z0-9_-]")


class GreenhouseJobsCollector(BaseCollector):
    """Domain-scoped collector for public Greenhouse job boards."""

    SOURCE_NAME = "greenhouse_jobs"
    DEFAULT_LIMIT = GREENHOUSE_JOBS_LIMIT

    def __init__(
        self,
        boards: list[GreenhouseBoard] | None = None,
        domain: str = "business",
    ) -> None:
        super().__init__(domain=domain)
        self._boards: list[GreenhouseBoard] = list(boards or [])

    def _clean_html(self, raw_html: str | None) -> str:
        """Strip HTML tags and unescape entities into clean plain text."""
        if not raw_html:
            return ""
        text = str(raw_html)
        # Strip script and style blocks entirely
        text = _SCRIPT_STYLE_RE.sub(" ", text)
        # Unescape up to 3 passes for nested/double entity encodings
        for _ in range(3):
            unescaped = html.unescape(text)
            if unescaped == text:
                break
            text = unescaped
        # Strip tags
        text = _TAG_RE.sub(" ", text)
        text = html.unescape(text)
        # Normalize whitespace and trailing spacing before punctuation
        text = _WHITESPACE_RE.sub(" ", text).strip()
        text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
        return text

    def _normalize_company(self, company: str) -> str:
        """Normalize company name for safe source-derived tagging."""
        slug = company.strip().lower().replace(" ", "-")
        return _COMPANY_NORM_RE.sub("", slug)

    def _build_tags(
        self,
        board: GreenhouseBoard,
        location_name: str,
        dept_names: list[str],
        office_names: list[str],
        office_locations: list[str],
    ) -> list[str]:
        """Produce strictly source-derived tags. No business conclusions."""
        tags = ["gh:job"]

        norm_co = self._normalize_company(board.company)
        if norm_co:
            tags.append(f"company:{norm_co}")

        if board.board_token:
            tags.append(f"gh:board:{board.board_token.strip().lower()}")

        if location_name:
            clean_loc = location_name.strip().lower()
            tags.append(f"gh:location:{clean_loc}")
            if "remote" in clean_loc:
                tags.append("gh:remote")

        for dept in dept_names:
            clean_dept = dept.strip().lower()
            if clean_dept:
                tags.append(f"gh:department:{clean_dept}")

        for office in office_names:
            clean_off = office.strip().lower()
            if clean_off:
                tags.append(f"gh:office:{clean_off}")

        for off_loc in office_locations:
            clean_off_loc = off_loc.strip().lower()
            if clean_off_loc:
                tags.append(f"gh:location:{clean_off_loc}")
                if "remote" in clean_off_loc:
                    tags.append("gh:remote")

        # Deduplicate while preserving order
        return list(dict.fromkeys(tags))

    def _job_to_signal(self, job: dict[str, Any], board: GreenhouseBoard) -> Signal | None:
        """Map a public Greenhouse job JSON dictionary to a canonical Signal."""
        if not isinstance(job, dict):
            return None

        job_id = job.get("id")
        if job_id is None:
            return None

        title = str(job.get("title") or "").strip()
        if not title:
            return None

        # Build stable cross-company source_id
        source_id = f"{job_id}|{board.board_token}"

        raw_content = job.get("content")
        content = self._safe_text(self._clean_html(raw_content), max_length=4000)

        # Location extraction
        loc_obj = job.get("location")
        if isinstance(loc_obj, dict):
            location_name = str(loc_obj.get("name") or "").strip()
        elif loc_obj is not None:
            location_name = str(loc_obj).strip()
        else:
            location_name = ""

        # Departments
        raw_depts = job.get("departments") or []
        dept_names: list[str] = []
        if isinstance(raw_depts, list):
            for d in raw_depts:
                if isinstance(d, dict) and d.get("name"):
                    dept_names.append(str(d["name"]).strip())
                elif isinstance(d, str) and d.strip():
                    dept_names.append(d.strip())

        # Offices
        raw_offices = job.get("offices") or []
        office_names: list[str] = []
        office_locations: list[str] = []
        if isinstance(raw_offices, list):
            for o in raw_offices:
                if isinstance(o, dict):
                    if o.get("name"):
                        office_names.append(str(o["name"]).strip())
                    if o.get("location"):
                        office_locations.append(str(o["location"]).strip())
                elif isinstance(o, str) and o.strip():
                    office_names.append(o.strip())

        tags = self._build_tags(
            board=board,
            location_name=location_name,
            dept_names=dept_names,
            office_names=office_names,
            office_locations=office_locations,
        )

        raw_metadata = {
            "job_id": job_id,
            "internal_job_id": job.get("internal_job_id"),
            "requisition_id": job.get("requisition_id"),
            "board_token": board.board_token,
            "company": board.company,
            "location": location_name,
            "departments": dept_names,
            "offices": office_names,
            "office_locations": office_locations,
            "updated_at": job.get("updated_at"),
            "first_published": job.get("first_published"),
            "absolute_url": job.get("absolute_url"),
            "language": job.get("language"),
        }

        return Signal(
            source=self.SOURCE_NAME,
            source_id=source_id,
            title=title,
            content=content,
            url=str(job.get("absolute_url") or ""),
            platform_score=0,
            comment_count=0,
            tags=tags,
            domain=self.domain,
            raw_metadata=raw_metadata,
        )

    def _fetch_board(
        self,
        board: GreenhouseBoard,
        session: requests.Session,
    ) -> list[dict[str, Any]]:
        """Fetch published jobs for a single board token from Greenhouse public API."""
        url = f"{_API_BASE}/{board.board_token}/jobs"
        params = {"content": "true"}
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        }

        try:
            resp = session.get(
                url,
                params=params,
                headers=headers,
                timeout=GREENHOUSE_TIMEOUT_S,
            )
        except requests.Timeout as e:
            raise CollectorError(
                f"Timeout connecting to Greenhouse board '{board.board_token}': {e}"
            ) from e
        except requests.RequestException as e:
            raise CollectorError(
                f"Network error querying Greenhouse board '{board.board_token}': {e}"
            ) from e

        if resp.status_code == 429:
            raise RateLimitError(
                f"Greenhouse rate limit reached for board '{board.board_token}' (HTTP 429)"
            )

        if resp.status_code == 403:
            # Check for throttle / rate limit indicators
            body_lower = resp.text.lower()
            if "rate limit" in body_lower or "throttle" in body_lower or "retry-after" in resp.headers:
                raise RateLimitError(
                    f"Greenhouse rate limit reached for board '{board.board_token}' (HTTP 403): {resp.text[:200]}"
                )
            raise CollectorError(
                f"Greenhouse access forbidden for board '{board.board_token}' (HTTP 403): {resp.text[:200]}"
            )

        if resp.status_code == 404:
            raise CollectorError(
                f"Greenhouse board not found '{board.board_token}' (HTTP 404)"
            )

        if resp.status_code != 200:
            raise CollectorError(
                f"Greenhouse HTTP {resp.status_code} for board '{board.board_token}': {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except Exception as e:
            raise CollectorError(
                f"Greenhouse returned non-JSON response for board '{board.board_token}': {e}"
            ) from e

        if not isinstance(data, dict) or "jobs" not in data or not isinstance(data["jobs"], list):
            raise CollectorError(
                f"Unexpected JSON structure from Greenhouse board '{board.board_token}'"
            )

        return data["jobs"]

    def _fetch(self, limit: int) -> Iterator[Signal]:
        """Fetch signals across all configured Greenhouse job boards.

        Allocation: the global ``limit`` is divided equally across all configured
        boards upfront — ``per_board_cap = max(1, limit // n_boards)`` — so no
        single early board can consume the entire run.  Each board that is reached
        may contribute at most ``per_board_cap`` new signals, regardless of how many
        jobs it publishes.  The global ``total_yielded`` counter enforces the outer
        safety ceiling; once it reaches ``limit`` the loop exits immediately.

        Guarantee (when ``limit >= n_boards``): a large early board cannot starve
        later boards, and every queried board receives a non-zero cap.

        Limitation (when ``limit < n_boards``): the global ceiling is hit before
        every board can be queried.  The first ``limit`` boards each contribute one
        signal (cap is ``max(1, …) = 1``), and boards beyond that position are not
        reached in that run.
        """
        if not self._boards:
            self.logger.info("[%s] No Greenhouse boards configured; skipping", self.domain)
            return

        n_boards = len(self._boards)
        # Equal share per board; at least 1 so cap is never zero.
        # The global limit remains the hard ceiling regardless.
        per_board_cap = max(1, limit // n_boards)

        session = requests.Session()
        successful_boards = 0
        failed_boards = 0
        total_yielded = 0

        for idx, board in enumerate(self._boards):
            if total_yielded >= limit:
                break

            # Delay between boards to be respectful of external service
            if idx > 0 and GREENHOUSE_REQUEST_DELAY > 0:
                time.sleep(GREENHOUSE_REQUEST_DELAY)

            try:
                raw_jobs = self._fetch_board(board, session)
                successful_boards += 1
            except RateLimitError:
                # Re-raise rate-limiting immediately so the scheduler applies backoff
                raise
            except Exception as e:
                failed_boards += 1
                self.logger.warning(
                    "[%s] Failed querying Greenhouse board '%s' (%s): %s",
                    self.domain,
                    board.board_token,
                    board.company,
                    e,
                )
                continue

            board_yielded = 0
            for job in raw_jobs:
                # Stop if this board has consumed its fair share OR the global cap is hit
                if board_yielded >= per_board_cap or total_yielded >= limit:
                    break

                signal = self._job_to_signal(job, board)
                if signal is None:
                    continue

                if self._is_duplicate(signal.source_id, domain=self.domain):
                    continue

                yield signal
                board_yielded += 1
                total_yielded += 1

        # Aggregate failure handling: if every board failed, raise CollectorError
        if successful_boards == 0 and failed_boards > 0:
            raise CollectorError(
                f"All {failed_boards} configured Greenhouse job boards failed"
            )
