"""Read-only collector operations visibility backed by ``collector_state``.

The scheduler remains the sole owner of collection decisions. This endpoint
projects durable state and a transparent next-due timestamp derived from the
documented interval/backoff rule. It does not manufacture a health verdict, a
current running state, configuration status, failure detail, or rate-limit
classification that BIA does not retain.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import auth
import database

router = APIRouter()


class CollectorQuota(BaseModel):
    limit: int
    period_minutes: int
    used: int
    reset_at: Optional[str]


class CollectorStateItem(BaseModel):
    source: str
    domain: str
    enabled: bool
    interval_minutes: int
    priority: int
    quota: CollectorQuota
    last_run_at: Optional[str]
    last_success_at: Optional[str]
    last_failure_at: Optional[str]
    consecutive_failures: int
    backoff_until: Optional[str]
    updated_at: str
    last_attempt_status: Literal["succeeded", "failed", "not_yet_run", "unknown"]
    timing_gate_status: Literal[
        "disabled", "backing_off", "quota_exhausted", "not_yet_run",
        "interval_elapsed", "interval_waiting", "unknown",
    ]
    next_due_at: Optional[str]


class CollectorStateResponse(BaseModel):
    collectors: list[CollectorStateItem]
    server_time: str


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _last_attempt_status(row) -> Literal["succeeded", "failed", "not_yet_run", "unknown"]:
    if not row["last_run_at"]:
        return "not_yet_run"
    if row["last_run_at"] == row["last_success_at"]:
        return "succeeded"
    if row["last_run_at"] == row["last_failure_at"]:
        return "failed"
    return "unknown"


def _next_due_at(row) -> datetime | None:
    last_run_at = _parse_timestamp(row["last_run_at"])
    backoff_until = _parse_timestamp(row["backoff_until"])
    if last_run_at is None:
        return backoff_until

    due_at = last_run_at + timedelta(minutes=row["interval_minutes"])
    if backoff_until is not None:
        due_at = max(due_at, backoff_until)
    return due_at


def _timing_gate_status(row, now: datetime, next_due_at: datetime | None) -> str:
    if not bool(row["enabled"]):
        return "disabled"
    if row["quota_per_period"] and row["quota_used"] >= row["quota_per_period"]:
        reset_at = _parse_timestamp(row["quota_reset_at"])
        if reset_at is None or reset_at > now:
            return "quota_exhausted"
    backoff_until = _parse_timestamp(row["backoff_until"])
    if backoff_until is not None and backoff_until > now:
        return "backing_off"
    if not row["last_run_at"]:
        return "not_yet_run"
    if next_due_at is not None and next_due_at <= now:
        return "interval_elapsed"
    if next_due_at is not None:
        return "interval_waiting"
    return "unknown"


def _row_to_item(row, now: datetime) -> CollectorStateItem:
    next_due_at = _next_due_at(row)
    return CollectorStateItem(
        source=row["source"],
        domain=row["domain"],
        enabled=bool(row["enabled"]),
        interval_minutes=row["interval_minutes"],
        priority=row["priority"],
        quota=CollectorQuota(
            limit=row["quota_per_period"],
            period_minutes=row["quota_period_minutes"],
            used=row["quota_used"],
            reset_at=row["quota_reset_at"] or None,
        ),
        last_run_at=row["last_run_at"] or None,
        last_success_at=row["last_success_at"] or None,
        last_failure_at=row["last_failure_at"] or None,
        consecutive_failures=row["consecutive_failures"],
        backoff_until=row["backoff_until"] or None,
        updated_at=row["updated_at"],
        last_attempt_status=_last_attempt_status(row),
        timing_gate_status=_timing_gate_status(row, now, next_due_at),
        next_due_at=_timestamp(next_due_at) if next_due_at is not None else None,
    )


@router.get("/collectors", response_model=CollectorStateResponse)
def list_collector_state(actor: auth.Actor = Depends(auth.get_current_actor)):
    """Return every known source/domain state without changing scheduler state."""
    now = datetime.now(timezone.utc)
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM collector_state ORDER BY domain ASC, priority ASC, source ASC"
        ).fetchall()

    return CollectorStateResponse(
        collectors=[_row_to_item(row, now) for row in rows],
        server_time=_timestamp(now),
    )
