"""
collectors/base.py — Abstract interface for all data source collectors

Every collector must:
  1. Define SOURCE_NAME (used for deduplication and logging)
  2. Implement _fetch(limit) → Generator[Signal, ...]
  3. Never raise from collect() — log and return what was collected so far

This contract ensures the pipeline never crashes because one source is down.
A Reddit outage does not stop HN collection.

Error hierarchy:
  CollectorError      — base; unrecoverable, log and skip
  RateLimitError      — subclass; we hit a rate limit, back off and retry
  DuplicateSignal     — subclass; signal already in DB, not an error per se
"""

import logging
import sqlite3
import time
from abc import ABC, abstractmethod
from typing import Generator

from models import Signal
import database


class CollectorError(Exception):
    """Unrecoverable error within a collector. Pipeline should log and continue."""


class RateLimitError(CollectorError):
    """
    The source has rate-limited us. The caller should back off before retrying.
    Include the retry-after seconds in the message if known.
    """


class BaseCollector(ABC):
    """
    Abstract base for all data source collectors.

    Subclasses implement _fetch(). The public collect() method wraps it with:
      - Structured logging
      - Exception isolation (errors in one collector never affect others)
      - Duplicate filtering via the database dedup index
      - Timing and metrics
    """

    SOURCE_NAME: str = ""
    DEFAULT_LIMIT: int = 50

    def __init__(self, domain: str = "business"):
        if not self.SOURCE_NAME:
            raise ValueError(f"{self.__class__.__name__} must define SOURCE_NAME")
        self.domain = domain
        self.logger = logging.getLogger(f"collector.{self.SOURCE_NAME}")

    @abstractmethod
    def _fetch(self, limit: int) -> Generator[Signal, None, None]:
        """
        Fetch at most `limit` new signals from the source.

        Requirements:
          - Must be a generator (yield, not return a list).
          - Must not yield signals already in the database.
            Use source + source_id to check before yielding.
          - Must raise CollectorError (or subclass) on unrecoverable failure.
          - Must never raise on individual item failures — skip and continue.
        """
        ...

    def collect(self, limit: int | None = None) -> list[Signal]:
        """
        Public entry point. Calls _fetch() and handles all errors.

        Returns a list of Signal objects that were successfully collected.
        An empty list is a valid return value — it means nothing new was found
        or the source was temporarily unavailable.
        """
        limit = limit or self.DEFAULT_LIMIT
        signals: list[Signal] = []
        start = time.monotonic()

        self.logger.info(f"Collection started (limit={limit})")

        try:
            for signal in self._fetch(limit):
                signals.append(signal)

        except RateLimitError as e:
            self.logger.warning(f"Rate limited: {e}. Backing off 30 seconds.")
            time.sleep(30)
        except CollectorError as e:
            self.logger.error(f"Collection failed: {e}")
        except Exception:
            self.logger.exception("Unexpected error during collection")

        elapsed = time.monotonic() - start
        self.logger.info(f"Collected {len(signals)} new signals in {elapsed:.2f}s")
        return signals

    def persist(self, signals: list[Signal]) -> int:
        """
        Write this collector's signals to the database. Skips duplicates
        silently. Returns the number of signals actually inserted.

        Delegates to the module-level persist_signals() so there is exactly
        one place that knows how to write a Signal row — pipeline.py calls
        the same function directly when persisting a combined, multi-domain
        batch (e.g. a shared collector's signals fanned out across domains).
        """
        inserted = persist_signals(signals)
        self.logger.info(
            f"Persisted {inserted}/{len(signals)} signals (rest were duplicates)"
        )
        return inserted

    def run(self, limit: int | None = None) -> int:
        """
        Convenience method: collect() then persist(). Returns inserted count.
        This is what the scheduler calls.
        """
        signals = self.collect(limit)
        return self.persist(signals)

    # ── Utilities available to subclasses ─────────────────────────────────

    def _safe_text(self, text: str | None, max_length: int = 4000) -> str:
        """Strip and truncate text. Never raises."""
        if not text:
            return ""
        return str(text).strip()[:max_length]

    def _is_duplicate(self, source_id: str, domain: str | None = None) -> bool:
        """
        Check whether source + source_id already exists in the database.

        If `domain` is given, the check is scoped to that domain — this is
        what domain-specific collectors (Reddit, RSS) should pass, since
        the dedup key is (source, source_id, domain) and each domain keeps
        its own independent copy.

        If `domain` is omitted, the check ignores domain entirely — this is
        the "have I ever fetched this raw item, in any domain" heuristic
        that shared collectors (Hacker News) use purely to avoid a redundant
        HTTP round-trip before the item has been fanned out to domains. It
        intentionally does not gate persistence (which always scopes by
        domain); it only skips re-fetching content that's already been
        seen once.
        """
        query = "SELECT 1 FROM signals WHERE source = ? AND source_id = ?"
        params: list = [self.SOURCE_NAME, str(source_id)]
        if domain is not None:
            query += " AND domain = ?"
            params.append(domain)
        query += " LIMIT 1"

        with database.get_connection() as conn:
            row = conn.execute(query, params).fetchone()
        return row is not None


def persist_signals(signals: list[Signal]) -> int:
    """
    Write a batch of Signal objects to the database. Skips duplicates
    (source, source_id, domain) silently. Returns the number inserted.

    Signals may come from a single collector or be a combined, multi-domain
    batch assembled by pipeline.py — this function doesn't care which.
    It is the single place that knows the signals table's column layout.
    """
    if not signals:
        return 0

    logger = logging.getLogger("collector.persist")
    inserted = 0
    with database.get_connection() as conn:
        for sig in signals:
            try:
                row = sig.to_db_row()
                conn.execute(
                    """
                    INSERT OR IGNORE INTO signals
                      (id, source, source_id, url, title, content,
                       platform_score, comment_count, entity_ids, tags,
                       raw_metadata, collected_at, processed, domain)
                    VALUES
                      (:id, :source, :source_id, :url, :title, :content,
                       :platform_score, :comment_count, :entity_ids, :tags,
                       :raw_metadata, :collected_at, :processed, :domain)
                    """,
                    row
                )
                if conn.execute("SELECT changes()").fetchone()[0] > 0:
                    inserted += 1
            except sqlite3.Error as e:
                logger.error(f"Failed to persist signal {sig.id}: {e}")

        conn.commit()

    return inserted
