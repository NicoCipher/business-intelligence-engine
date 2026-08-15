"""
opportunity_engine/problem_history.py — Persistent Problem Memory (schema v7)

Records and reads the append-only event timeline for a Problem. Problem
itself (models.py) stores only current canonical state — this module is
the write/read path for problem_history, the normalized child table that
stores the complete evidence and change timeline (one row per event,
never rewritten).

Kept as its own small module rather than folded into canonicalizer.py:
canonicalizer.py's job is matching (deciding *which* Problem an
observation belongs to); this module's job is recording (writing down
*that it happened*). Same separation-of-responsibility reasoning that's
already flagged explainer.py's ~60KB, five-responsibility shape as debt
worth not repeating elsewhere.

Design:
  - record_event() is the only write path. Every event type is written
    through the same function so there is exactly one place that builds
    the row shape — no per-event-type INSERT statements scattered
    elsewhere.
  - Callers pass a domain explicitly rather than this module looking it
    up — keeps it a pure recorder with no extra query per call.
  - metadata is a plain dict; each caller decides what's worth recording
    for that event type. This module does not validate metadata shape
    beyond what ProblemHistoryEvent's constructor already enforces
    (a valid event_type).
"""

import logging

from models import ProblemHistoryEvent

logger = logging.getLogger(__name__)


def record_event(
    conn,
    problem_id: str,
    domain: str,
    event_type: str,
    *,
    week_key: str = "",
    opportunity_id: str = "",
    metadata: dict | None = None,
    occurred_at: str | None = None,
) -> str:
    """
    Append one event to a Problem's history. Returns the new event's id.

    This never updates or deletes an existing row — history is
    append-only by construction, not just by convention. Callers that
    need "the current state" read it from the problems table itself
    (still the source of truth for current state); this table answers
    "what happened, and when."
    """
    event = ProblemHistoryEvent(
        problem_id=problem_id,
        domain=domain,
        event_type=event_type,
        week_key=week_key,
        opportunity_id=opportunity_id,
        metadata=metadata or {},
    )
    if occurred_at:
        event.occurred_at = occurred_at

    row = event.to_db_row()
    conn.execute(
        """
        INSERT INTO problem_history
          (id, problem_id, domain, event_type, occurred_at, week_key, opportunity_id, metadata, created_at)
        VALUES
          (:id, :problem_id, :domain, :event_type, :occurred_at, :week_key, :opportunity_id, :metadata, :created_at)
        """,
        row,
    )
    logger.debug(f"[{domain}] Problem history: {event_type} recorded for {problem_id[:8]}...")
    return event.id


def list_for_problem(
    conn, problem_id: str, limit: int | None = None, offset: int = 0,
) -> list[ProblemHistoryEvent]:
    """
    Return a Problem's full timeline, oldest first (chronological reading
    order — a founder or future frontend screen reads a history top to
    bottom as "what happened, in order," not most-recent-first).

    `limit`, when given, still returns the oldest `limit` events rather
    than the most recent — callers that specifically want "recent
    activity" should query occurred_at DESC themselves; this default
    matches the "read a timeline" use case, not a "recent activity feed"
    use case.

    `offset` added for api/problems.py's history sub-resource endpoint —
    default 0 keeps every existing call site's behavior unchanged.
    """
    query = "SELECT * FROM problem_history WHERE problem_id = ? ORDER BY occurred_at ASC"
    params: tuple = (problem_id,)
    if limit is not None:
        query += " LIMIT ? OFFSET ?"
        params = (problem_id, limit, offset)
    elif offset:
        query += " LIMIT -1 OFFSET ?"  # SQLite: OFFSET without LIMIT needs LIMIT -1 (unbounded)
        params = (problem_id, offset)

    rows = conn.execute(query, params).fetchall()
    return [ProblemHistoryEvent.from_db_row(row) for row in rows]


def count_for_problem(conn, problem_id: str) -> int:
    """Cheap count without materializing every event — for UI badges etc."""
    row = conn.execute(
        "SELECT COUNT(*) c FROM problem_history WHERE problem_id = ?", (problem_id,)
    ).fetchone()
    return row["c"]
