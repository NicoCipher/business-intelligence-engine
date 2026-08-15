"""
api/problems.py — Problem API endpoints

Routes:
  GET /api/v1/problems                list, three named sort orders
  GET /api/v1/problems/{id}           single problem + linked opportunities
  GET /api/v1/problems/{id}/history   full timeline, paginated separately

All three routes require auth (Depends(auth.get_current_actor)) — a
deliberate deviation from opportunities.py/signals.py, whose GET routes
are open and only their PATCH route is protected. Applied here on
request, for consistency/future-proofing rather than because these
specific routes carry elevated risk; auth.get_current_actor no-ops when
BIA_API_KEY is unset, so this costs nothing in an unauthenticated
deployment and simply takes effect whenever a key is configured.

No business logic lives here. These handlers:
  1. Parse and validate request parameters (Pydantic handles this)
  2. Query the database
  3. Shape the response

If a route grows complex, extract a service function in opportunity_engine/
and call it from here. Routes stay thin — same convention as
api/opportunities.py.

Design note on history: problem_history is unbounded, append-only
(schema v7 — see database.py's own comment on why it's a separate table,
not an array on Problem: years of weekly runs can produce arbitrarily
many events). The detail route therefore inlines only a count
(problem_history.count_for_problem(), which exists specifically "for UI
badges" per that module's own docstring) plus linked opportunities
(naturally bounded — one per detection cycle that matched this Problem),
not the full timeline. The full timeline is its own paginated
sub-resource.

Design note on RFC-002 (Investigation Findings, still Proposed, not
Accepted): Problem's own shape is unaffected by whether RFC-002 is ever
implemented — Findings would reference a Problem read-only, as a future,
additive sub-resource (its own doc: "Findings ... reference a Problem
but do not modify it"). Nothing here needs to change if/when that lands.
"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import auth
import database
from database import decode_json
from opportunity_engine import problem_history

logger = logging.getLogger(__name__)
router = APIRouter()


class ProblemSummary(BaseModel):
    id: str
    title: str
    domain: str
    lifecycle_state: str
    trend: str
    weeks_seen: int
    first_seen: str
    last_seen: str


class LinkedOpportunity(BaseModel):
    id: str
    title: str
    composite_score: float
    tier: str
    status: str
    week_key: str


class ProblemDetail(ProblemSummary):
    entity_ids: list[str]
    history_count: int
    linked_opportunities: list[LinkedOpportunity]


class HistoryEvent(BaseModel):
    id: str
    event_type: str
    occurred_at: str
    week_key: str
    opportunity_id: str
    metadata: dict


# Three named sort orders, each answering a genuinely different question
# rather than one default ordering trying to serve all of them:
#   recent      -- "what's happening right now?"      (last_seen DESC)
#   persistent  -- "what keeps happening?"             (weeks_seen DESC)
#   significant -- "what should I care about?"          (best linked
#                  opportunity's composite_score DESC)
#
# "significant" deliberately does not add a score to Problem itself --
# Problem is intentionally unscored by architecture (opportunities are
# the dated commercial assessment, problems are the persistent identity
# underneath them, see 00_ARCHITECTURE_SPECIFICATION.md's Problem/
# Opportunity distinction). A problem's significance is read off the
# best opportunity it has actually produced, via a LEFT JOIN + MAX --
# a problem with zero linked opportunities sorts last under this order,
# not excluded and not erroring.
_SORT_CLAUSES = {
    "recent": "p.last_seen DESC",
    "persistent": "p.weeks_seen DESC",
    # SQLite NULLS LAST needs >= 3.30 (2019) -- "best_score IS NULL, best_score DESC"
    # is the portable equivalent and doesn't depend on the deployment's
    # bundled SQLite version, consistent with this codebase's general
    # care around environment-version assumptions (see database.py's own
    # DDL-ordering guards).
    "significant": "best_score IS NULL, best_score DESC",
}


@router.get("")
def list_problems(
    domain: Optional[str] = Query(None, description="Filter by domain"),
    lifecycle_state: Optional[str] = Query(None, description="Filter by lifecycle_state"),
    trend: Optional[str] = Query(None, description="Filter by trend"),
    sort: Literal["recent", "persistent", "significant"] = Query(
        "recent", description="recent=last_seen DESC, persistent=weeks_seen DESC, "
                              "significant=best linked opportunity's score DESC",
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    actor: auth.Actor = Depends(auth.get_current_actor),
):
    """
    List problems. Filters are unvalidated equality matches (same
    treatment as api/opportunities.py's domain/status/week filters) --
    an unknown value returns an empty list, not an error.
    """
    conditions = ["1=1"]
    params: dict = {}

    if domain:
        conditions.append("p.domain = :domain")
        params["domain"] = domain
    if lifecycle_state:
        conditions.append("p.lifecycle_state = :lifecycle_state")
        params["lifecycle_state"] = lifecycle_state
    if trend:
        conditions.append("p.trend = :trend")
        params["trend"] = trend

    where = " AND ".join(conditions)
    params["limit"] = limit
    params["offset"] = offset

    with database.get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT p.id, p.title, p.domain, p.lifecycle_state, p.trend,
                   p.weeks_seen, p.first_seen, p.last_seen
            FROM   problems p
            LEFT JOIN (
                SELECT problem_id, MAX(composite_score) AS best_score
                FROM   opportunities
                WHERE  problem_id != ''
                GROUP BY problem_id
            ) o ON o.problem_id = p.id
            WHERE  {where}
            ORDER  BY {_SORT_CLAUSES[sort]}
            LIMIT  :limit OFFSET :offset
            """,
            params,
        ).fetchall()

        total = conn.execute(
            f"SELECT COUNT(*) FROM problems p WHERE {where}",
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        ).fetchone()[0]

    items = [_row_to_summary(row) for row in rows]

    return {
        "problems": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{problem_id}")
def get_problem(
    problem_id: str,
    actor: auth.Actor = Depends(auth.get_current_actor),
):
    """Single problem, with linked opportunities inlined (bounded — see
    module docstring) and a history count (not the full timeline — use
    GET /{id}/history for that)."""
    with database.get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, title, domain, lifecycle_state, trend,
                   weeks_seen, first_seen, last_seen, entity_ids
            FROM   problems
            WHERE  id = :id
            """,
            {"id": problem_id},
        ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail=f"Problem '{problem_id}' not found")

        opp_rows = conn.execute(
            """
            SELECT id, title, composite_score, status, week_key, scores
            FROM   opportunities
            WHERE  problem_id = :id
            ORDER  BY composite_score DESC
            """,
            {"id": problem_id},
        ).fetchall()

        history_count = problem_history.count_for_problem(conn, problem_id)

    linked = [
        LinkedOpportunity(
            id=o["id"], title=o["title"],
            composite_score=round(o["composite_score"], 2),
            tier=decode_json(o["scores"], {}).get("tier", "bronze"),
            status=o["status"], week_key=o["week_key"],
        )
        for o in opp_rows
    ]

    return ProblemDetail(
        id=row["id"], title=row["title"], domain=row["domain"],
        lifecycle_state=row["lifecycle_state"], trend=row["trend"],
        weeks_seen=row["weeks_seen"], first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        entity_ids=decode_json(row["entity_ids"], []),
        history_count=history_count,
        linked_opportunities=linked,
    )


@router.get("/{problem_id}/history")
def get_problem_history(
    problem_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor: auth.Actor = Depends(auth.get_current_actor),
):
    """
    Full timeline for one problem, oldest first (chronological reading
    order — see problem_history.list_for_problem()'s own docstring for
    why). Paginated separately from the detail route because this table
    is unbounded (see module docstring).
    """
    with database.get_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM problems WHERE id = :id", {"id": problem_id},
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail=f"Problem '{problem_id}' not found")

        events = problem_history.list_for_problem(conn, problem_id, limit=limit, offset=offset)
        total = problem_history.count_for_problem(conn, problem_id)

    items = [
        HistoryEvent(
            id=e.id, event_type=e.event_type, occurred_at=e.occurred_at,
            week_key=e.week_key, opportunity_id=e.opportunity_id,
            metadata=e.metadata,
        )
        for e in events
    ]

    return {
        "problem_id": problem_id,
        "history": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _row_to_summary(row) -> ProblemSummary:
    return ProblemSummary(
        id=row["id"], title=row["title"], domain=row["domain"],
        lifecycle_state=row["lifecycle_state"], trend=row["trend"],
        weeks_seen=row["weeks_seen"], first_seen=row["first_seen"],
        last_seen=row["last_seen"],
    )
