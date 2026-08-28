"""
api/changes.py — Change Events read-side API (Change Detection Read-Side V1)

Routes:
  GET /api/v1/changes           browse/filter the chronological change feed
  GET /api/v1/changes/unseen    the canonical, acknowledgeable "what's new
                                 since I last looked" snapshot

Reviewed design: see the Change Detection Read-Side design milestone
(docs/HANDOFF.md history around 9fa09d0). Two distinct needs, two
distinct endpoints, deliberately NOT unified into one parameterized
route:

  - GET /changes is a general, filterable browse surface over
    change_events, ordered `detected_at DESC` (newest world-event
    first — the "what happened" reading order). It answers "show me
    the feed," with normal domain/significance/event_type/entity
    filters, same conventions as api/opportunities.py and
    api/problems.py.

  - GET /changes/unseen is intentionally NOT just "/changes with a
    since filter." It is global and unfiltered by design — see its
    own docstring below and operator_state's own migration comment
    ("this table's replacement is a new migration's decision, not an
    extension of this one" — i.e. per-domain/per-filter checkpoints
    are explicitly out of scope for this table's current shape).
    Exposing domain/significance/event_type filters on this endpoint
    would misleadingly imply an operator could acknowledge a filtered
    slice independently of the rest — operator_state has exactly one
    global watermark, so that's not actually possible, and the API
    must not pretend otherwise.

Auth: every route here requires auth.get_current_actor (matches
api/problems.py's stricter, more recent convention of protecting GET
routes too, not just mutations — deliberate, not accidental, per that
module's own comment on the same choice).

entity_title resolution: a single query with two conditional LEFT
JOINs (problems / opportunities, each gated on entity_ref_type) rather
than either inlining the full referenced resource or making the
client do a follow-up GET per row. See _CHANGE_EVENT_SELECT below.
"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

import auth
import database
from database import decode_json

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Response models ──────────────────────────────────────────────────────
# Real, enforced models (response_model=...), matching the convention
# already applied throughout api/*.py.

class ChangeEvent(BaseModel):
    id: str
    domain: str
    event_type: str
    entity_ref_type: str          # "problem" | "opportunity"
    entity_ref_id: str
    entity_title: Optional[str]   # resolved via LEFT JOIN — see module docstring
    previous_value: str
    new_value: str
    significance: str             # "normal" | "high"
    detected_at: str
    created_at: str
    metadata: dict


class ChangeEventListResponse(BaseModel):
    changes: list[ChangeEvent]
    total: int
    limit: int
    offset: int
    server_time: str


class UnseenChangesResponse(BaseModel):
    changes: list[ChangeEvent]
    total_unseen: int
    since: Optional[str]     # the last_seen_at this was resolved against; None = never seen
    snapshot_at: str         # THE acknowledgement watermark — see module docstring
    limit: int
    offset: int


# ── Shared query machinery ───────────────────────────────────────────────
# One query shape for both routes: neither GET /changes nor GET
# /unseen should drift into a second, subtly different JOIN/shape over
# time — that would risk the two surfaces disagreeing about what an
# "event" even looks like.

_CHANGE_EVENT_SELECT = """
    SELECT
        c.id, c.domain, c.event_type, c.entity_ref_type, c.entity_ref_id,
        c.previous_value, c.new_value, c.significance,
        c.detected_at, c.created_at, c.metadata,
        p.title AS problem_title,
        o.title AS opportunity_title
    FROM change_events c
    LEFT JOIN problems      p ON (c.entity_ref_type = 'problem'     AND c.entity_ref_id = p.id)
    LEFT JOIN opportunities o ON (c.entity_ref_type = 'opportunity' AND c.entity_ref_id = o.id)
"""


def _row_to_change_event(row) -> ChangeEvent:
    entity_title = row["problem_title"] if row["entity_ref_type"] == "problem" else row["opportunity_title"]
    return ChangeEvent(
        id=row["id"],
        domain=row["domain"],
        event_type=row["event_type"],
        entity_ref_type=row["entity_ref_type"],
        entity_ref_id=row["entity_ref_id"],
        entity_title=entity_title,
        previous_value=row["previous_value"],
        new_value=row["new_value"],
        significance=row["significance"],
        detected_at=row["detected_at"],
        created_at=row["created_at"],
        metadata=decode_json(row["metadata"], {}),
    )


def _query_changes(conn, where: str, params: dict, order_by: str, limit: int, offset: int):
    """Shared SELECT + COUNT, used by both routes. `where`/`params` must
    not include `limit`/`offset` — those are bound separately here."""
    query_params = dict(params)
    query_params["limit"] = limit
    query_params["offset"] = offset

    rows = conn.execute(
        f"{_CHANGE_EVENT_SELECT} WHERE {where} ORDER BY {order_by} LIMIT :limit OFFSET :offset",
        query_params,
    ).fetchall()

    total = conn.execute(
        f"SELECT COUNT(*) FROM change_events c WHERE {where}",
        params,
    ).fetchone()[0]

    return [_row_to_change_event(r) for r in rows], total


# ── Routes ────────────────────────────────────────────────────────────────

@router.get("", response_model=ChangeEventListResponse)
def list_changes(
    domain: Optional[str] = Query(
        None, description="Filter by domain id, e.g. business | cybersecurity",
    ),
    significance: Optional[Literal["normal", "high"]] = Query(
        None, description="Filter by significance — a fixed, closed vocabulary by design",
    ),
    event_type: Optional[str] = Query(
        None, description="Filter by event_type, e.g. problem_created, opportunity_tier_crossed",
    ),
    entity_ref_type: Optional[Literal["problem", "opportunity"]] = Query(
        None, description="Filter by the referenced entity's type",
    ),
    entity_ref_id: Optional[str] = Query(
        None, description="Filter by the referenced entity's id",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor: auth.Actor = Depends(auth.get_current_actor),
):
    """
    Browse the change feed, newest world-event first (detected_at DESC).

    All filters are unvalidated equality matches against their columns
    except `significance`/`entity_ref_type`, which are closed
    vocabularies (see the response model) and 422 on an invalid value —
    same distinction api/problems.py/api/opportunities.py already draw
    between open string filters (domain, status) and closed ones
    (StatusUpdate.status). An unknown `domain`/`event_type`/
    `entity_ref_id` value returns an empty list, not an error.
    """
    conditions = ["1=1"]
    params: dict = {}

    if domain:
        conditions.append("c.domain = :domain")
        params["domain"] = domain
    if significance:
        conditions.append("c.significance = :significance")
        params["significance"] = significance
    if event_type:
        conditions.append("c.event_type = :event_type")
        params["event_type"] = event_type
    if entity_ref_type:
        conditions.append("c.entity_ref_type = :entity_ref_type")
        params["entity_ref_type"] = entity_ref_type
    if entity_ref_id:
        conditions.append("c.entity_ref_id = :entity_ref_id")
        params["entity_ref_id"] = entity_ref_id

    where = " AND ".join(conditions)

    with database.get_connection() as conn:
        items, total = _query_changes(conn, where, params, "c.detected_at DESC", limit, offset)
        server_time = database._now()

    return ChangeEventListResponse(
        changes=items, total=total, limit=limit, offset=offset, server_time=server_time,
    )


@router.get("/unseen", response_model=UnseenChangesResponse)
def list_unseen_changes(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor: auth.Actor = Depends(auth.get_current_actor),
):
    """
    The canonical, acknowledgeable "what's new since I last looked"
    snapshot. Deliberately global and unfiltered — see module docstring
    for why no domain/significance/event_type filters are exposed here.

    `snapshot_at` is captured (database._now()) BEFORE querying
    change_events, and is the ONLY timestamp the corresponding
    POST /operator-state/ack call should ever be given — not click
    time, not the browser's clock. Capturing it first, rather than
    reusing the max `created_at` actually found in this query's
    results, means a row that lands in change_events between the
    capture and the SELECT is correctly excluded from THIS response's
    `changes` (it didn't exist yet at snapshot_at) rather than being
    silently included with a mismatched watermark.

    Semantics: `created_at > last_seen_at AND created_at <= snapshot_at`.
    If `last_seen_at` is empty (never acknowledged), the lower bound is
    omitted entirely — "never checked" means everything is unseen, not
    nothing.

    Ordered `detected_at DESC`, same reading order as GET /changes.
    Uses `created_at`, not `detected_at`, for the boundary itself — see
    the design milestone for why (a future backfilled row could carry
    an old `detected_at` but a brand-new `created_at`; filtering on
    `detected_at` could silently exclude a row the operator has
    genuinely never seen).
    """
    with database.get_connection() as conn:
        snapshot_at = database._now()

        since_row = conn.execute(
            "SELECT last_seen_at FROM operator_state WHERE id = 1"
        ).fetchone()
        last_seen_at = since_row["last_seen_at"] if since_row else ""
        since = last_seen_at or None

        conditions = ["c.created_at <= :snapshot_at"]
        params: dict = {"snapshot_at": snapshot_at}
        if last_seen_at:
            conditions.append("c.created_at > :last_seen_at")
            params["last_seen_at"] = last_seen_at
        where = " AND ".join(conditions)

        items, total_unseen = _query_changes(conn, where, params, "c.detected_at DESC", limit, offset)

    return UnseenChangesResponse(
        changes=items, total_unseen=total_unseen, since=since,
        snapshot_at=snapshot_at, limit=limit, offset=offset,
    )
