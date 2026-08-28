"""
api/operator_state.py — Operator checkpoint acknowledgement API

Routes:
  POST /api/v1/operator-state/ack   advance the operator's read checkpoint

operator_state is a distinct resource from change_events (see its own
migration comment in database.py) — change_events just happens to be
its first consumer. This router exists separately from api/changes.py
for that reason, and to leave room for a future second consumer without
changes.py needing to own operator_state's write path.

No GET route here: GET /api/v1/health already exposes
db.operator_last_seen_at read-only (database.get_stats()); a second
endpoint returning the same value would be a redundant contract.

Acknowledgement semantics (reviewed design — see the Change Detection
Read-Side design milestone):
  - Explicit mutation only. This is the ONLY route in this codebase
    that may write operator_state.last_seen_at. No GET, anywhere,
    ever writes it.
  - The request body's `as_of` MUST be the `snapshot_at` value a prior
    GET /api/v1/changes/unseen call returned — never click time, never
    the browser's own clock. This endpoint has no way to enforce that
    server-side (it only receives a timestamp), so the API doc string
    and the eventual console's Server Action are the enforcement
    points — see api/changes.py's /unseen docstring for the full
    reasoning.
  - Monotonic: last_seen_at = max(current last_seen_at, min(as_of, now)).
    A duplicate or older acknowledgement is an idempotent no-op — it
    never regresses the checkpoint. A future-dated `as_of` (clock skew
    or a bad client) is clamped to the server's own "now", so the
    checkpoint can never advance past real time and silently swallow
    events that don't exist yet.
  - "Acknowledge" means "mark everything through this snapshot as
    reviewed" — a single global watermark, not a record of which rows
    were actually rendered on some page. See api/changes.py's module
    docstring for why this endpoint intentionally has no domain/filter
    parameters: operator_state has exactly one checkpoint, so there is
    no such thing as acknowledging a filtered slice independently.
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import auth
import database

logger = logging.getLogger(__name__)
router = APIRouter()


class AckRequest(BaseModel):
    as_of: str   # ISO 8601 timestamp — must be a prior /changes/unseen response's snapshot_at


class AckResponse(BaseModel):
    last_seen_at: str


@router.post("/ack", response_model=AckResponse)
def acknowledge(
    body: AckRequest,
    actor: auth.Actor = Depends(auth.get_current_actor),
):
    """
    Advance operator_state.last_seen_at to `as_of`, monotonically and
    idempotently. See module docstring for full semantics.

    One atomic UPDATE — SQLite's single-writer semantics make this
    naturally race-free against a concurrent acknowledgement (e.g. two
    browser tabs): whichever UPDATE runs last simply computes MAX
    against whatever the other one already wrote.
    """
    now = database._now()
    clamped_as_of = min(body.as_of, now)

    with database.get_connection() as conn:
        conn.execute(
            """
            UPDATE operator_state
               SET last_seen_at = MAX(last_seen_at, :as_of),
                   updated_at   = :now
             WHERE id = 1
            """,
            {"as_of": clamped_as_of, "now": now},
        )
        conn.commit()

        row = conn.execute(
            "SELECT last_seen_at FROM operator_state WHERE id = 1"
        ).fetchone()

    logger.info(f"operator_state acknowledged through {row['last_seen_at']} (by {actor})")
    return AckResponse(last_seen_at=row["last_seen_at"])
