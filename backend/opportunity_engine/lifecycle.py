"""
opportunity_engine/lifecycle.py — Problem lifecycle & trend (schema v9)

    lifecycle_state:  new -> active -> dormant -> archived
                                          ^-- reactivated <--'
    trend:            unknown -> {growing | stable | declining}

Two INDEPENDENT axes, not one combined state. This module's first
design used a single `trajectory_state` field spanning both "is this
operationally relevant" and "how is it trending" — it was deliberately
unwound in favor of this before anything shipped, once the cost became
concrete: a combined enum either explodes combinatorially (every
lifecycle stage x every trend = far more states than are meaningful) or
produces contradictory-reading values (a Problem that just came back
from archival but also happens to be declining; a Problem that's
growing but whose most recent single data point looks quiet). One field
should represent one concept:

  - lifecycle_state answers "is this operationally relevant right now" —
    derived from recency (Problem.last_seen) and recurrence
    (Problem.weeks_seen).
  - trend answers "how is its evidence cadence changing" — derived from
    comparing problem_history evidence counts across two time windows.
  - confidence lives entirely in the existing opportunity scorer model
    (OpportunityScores.confidence) and is untouched by this module.

Keeping them separate means a dormant Problem can still carry a
last-known "declining" trend, a freshly reactivated Problem's trend
resets to 'unknown' independently of lifecycle_state also changing, and
neither axis needs special-casing to account for the other's value.

Deliberately distinct from Opportunity.status (new|validated|dismissed|
archived — a pre-existing, human-curated review field set via
PATCH /opportunities/{id}/status, explicitly unenforced, unrelated to
this module entirely). The vocabularies happen to share "new" and
"archived"; they are not the same concept. See
docs/architecture/core/04_DATA_MODEL.md's Historical Evolution section
for the underlying distinction (Opportunity is an immutable historical
observation; Problem is a mutable canonical identity).

Two different mechanisms move lifecycle_state, mirroring exactly how
schema v8's decay module splits decay from reactivation:

  - FORWARD progression (new -> active -> dormant -> archived, and all
    trend classification) happens in run_lifecycle_pass() below, run
    once per domain per pipeline execution (pipeline.py Stage 3.5, after
    detection so this run's problem_history events already exist).
  - REACTIVATION (archived -> reactivated) is immediate and event-driven,
    not swept periodically: opportunity_engine/canonicalizer.py's
    resolve_problem() checks the matched Problem's current
    lifecycle_state right when new evidence arrives, and flips it to
    'reactivated' (resetting trend to 'unknown') in the same transaction
    as the evidence_added event. 'reactivated' is a one-pass marker —
    the next run_lifecycle_pass() promotes it straight to 'active'
    (unless it would otherwise re-archive, which the archive check
    still takes precedence over defensively).

Every transition on either axis writes a "status_changed" problem_history
event (reserved by schema v7, unused until now), tagged with which axis
changed via metadata["axis"].
"""

import logging
from datetime import datetime

import config
from opportunity_engine import problem_history

logger = logging.getLogger(__name__)


# ── Time helpers ─────────────────────────────────────────────────────────

def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _days_between(earlier: str, later: str) -> float:
    return (_parse_iso(later) - _parse_iso(earlier)).total_seconds() / 86400.0


def _iso_minus_days(ts: str, days: float) -> str:
    from datetime import timedelta
    return (_parse_iso(ts) - timedelta(days=days)).isoformat().replace("+00:00", "Z")


# ── Trend classification (pure) ─────────────────────────────────────────

def classify_trend(recent_count: int, prior_count: int) -> str:
    """
    Pure function: given how much problem_history evidence landed in the
    most recent window vs. the window before it, classify the trend.

    recent_count / prior_count >= PROBLEM_GROWTH_RATIO  -> growing
    recent_count / prior_count <= PROBLEM_DECLINE_RATIO -> declining
    otherwise                                           -> stable

    prior_count == 0 is handled explicitly rather than dividing by zero:
    any recent evidence where there was previously none is unambiguous
    growth; no evidence in either window is treated as stable rather
    than guessed at — a Problem with genuinely no recent evidence in
    either window should be caught by the independent lifecycle-state
    archive check instead, which runs regardless of trend.
    """
    if prior_count == 0:
        return "growing" if recent_count > 0 else "stable"
    ratio = recent_count / prior_count
    if ratio >= config.PROBLEM_GROWTH_RATIO:
        return "growing"
    if ratio <= config.PROBLEM_DECLINE_RATIO:
        return "declining"
    return "stable"


def _evidence_count_in_window(conn, problem_id: str, window_start: str, window_end: str) -> int:
    """Count problem_history events (created + evidence_added — both
    represent a real observation landing on this Problem) with
    occurred_at in [window_start, window_end)."""
    row = conn.execute(
        """
        SELECT COUNT(*) c FROM problem_history
        WHERE problem_id = ?
          AND event_type IN ('created', 'evidence_added')
          AND occurred_at >= ? AND occurred_at < ?
        """,
        (problem_id, window_start, window_end),
    ).fetchone()
    return row["c"]


def _most_recent_reactivation_timestamp(conn, problem_id: str) -> str | None:
    """The occurred_at of the most recent status_changed event
    transitioning this Problem's lifecycle_state TO 'reactivated', or
    None if it's never been reactivated. Used to anchor trend
    classification to "how long has fresh activity been going" after a
    Problem comes back from archival, rather than counting the dormant
    gap or the ancient pre-archival history against it."""
    import json
    rows = conn.execute(
        """
        SELECT occurred_at, metadata FROM problem_history
        WHERE problem_id = ? AND event_type = 'status_changed'
        ORDER BY occurred_at DESC
        """,
        (problem_id,),
    ).fetchall()
    for r in rows:
        meta = json.loads(r["metadata"] or "{}")
        if meta.get("axis") == "lifecycle" and meta.get("to_state") == "reactivated":
            return r["occurred_at"]
    return None


# ── Reactivation (called from canonicalizer.resolve_problem(), not here) ──

def reactivate_if_archived(
    conn, problem_id: str, domain: str, now: str, *, week_key: str = "", opportunity_id: str = "",
) -> bool:
    """
    If the given Problem's current lifecycle_state is 'archived', flip
    it to 'reactivated' and reset trend to 'unknown' (the old trend
    predates the dormancy and is no longer meaningful), recording one
    status_changed event per axis that actually changed. No-op (returns
    False) otherwise. Called from resolve_problem()'s match branch, in
    the same transaction as that call's evidence_added event — this is
    the system's only reactivation path, exactly mirroring how
    entity/relationship reactivation works in knowledge_graph/decay.py.
    """
    row = conn.execute(
        "SELECT lifecycle_state, trend FROM problems WHERE id = ?", (problem_id,)
    ).fetchone()
    if row is None or row["lifecycle_state"] != "archived":
        return False

    conn.execute(
        "UPDATE problems SET lifecycle_state = 'reactivated', lifecycle_updated_at = ? WHERE id = ?",
        (now, problem_id),
    )
    problem_history.record_event(
        conn, problem_id, domain, "status_changed",
        week_key=week_key, opportunity_id=opportunity_id,
        metadata={"axis": "lifecycle", "from_state": "archived", "to_state": "reactivated", "reason": "new_evidence"},
        occurred_at=now,
    )

    if row["trend"] != "unknown":
        conn.execute(
            "UPDATE problems SET trend = 'unknown', trend_updated_at = ? WHERE id = ?",
            (now, problem_id),
        )
        problem_history.record_event(
            conn, problem_id, domain, "status_changed",
            week_key=week_key, opportunity_id=opportunity_id,
            metadata={"axis": "trend", "from_state": row["trend"], "to_state": "unknown", "reason": "reactivated"},
            occurred_at=now,
        )

    logger.info(f"[{domain}] Problem {problem_id[:8]}... reactivated (new evidence after archival)")
    return True


# ── The periodic forward-progression pass ───────────────────────────────

def run_lifecycle_pass(conn, domain: str, now: str | None = None) -> dict:
    """
    Evaluate every Problem in `domain` not already terminally archived
    and independently update its lifecycle_state and trend if either
    qualifies for a transition. Never reactivates on this path (that's
    reactivate_if_archived()'s job, called elsewhere, immediately, on
    new evidence).

    lifecycle_state, evaluated fresh every pass:
      1. Time-based check, unconditional and takes precedence over
         everything else — a Problem in ANY active state can go quiet
         and archive/go dormant, regardless of how it got there.
         days_quiet >= PROBLEM_ARCHIVE_DAYS -> archived
         days_quiet >= PROBLEM_DORMANT_DAYS -> dormant
      2. Otherwise, currently 'reactivated' -> promoted straight to
         'active' (one-pass marker, per the module docstring).
      3. Otherwise, weeks_seen < PROBLEM_RECURRENCE_WEEKS -> 'new'.
      4. Otherwise -> 'active'.

    trend, evaluated independently (skipped entirely if lifecycle_state
    is 'archived' this pass — no point classifying a trend for something
    that just went fully quiet):
      - Anchor = the most recent reactivation timestamp if later than
        first_seen, else first_seen.
      - Elapsed time since anchor < 2x PROBLEM_TREND_WINDOW_DAYS ->
        'unknown' (not enough data to say anything).
      - Otherwise -> classify_trend() on this-window vs. prior-window
        problem_history evidence counts.

    Returns counts of Problems ending this pass in each lifecycle_state,
    for pipeline logging.
    """
    from models import _now as _default_now
    now = now or _default_now()

    counts = {"new": 0, "active": 0, "dormant": 0, "archived": 0}

    rows = conn.execute(
        "SELECT id, lifecycle_state, trend, weeks_seen, first_seen, last_seen FROM problems "
        "WHERE domain = ? AND lifecycle_state != 'archived'",
        (domain,),
    ).fetchall()

    for row in rows:
        problem_id = row["id"]
        current_lifecycle = row["lifecycle_state"]
        current_trend = row["trend"]

        # ── lifecycle_state ──
        days_quiet = _days_between(row["last_seen"], now)
        if days_quiet >= config.PROBLEM_ARCHIVE_DAYS:
            new_lifecycle = "archived"
        elif days_quiet >= config.PROBLEM_DORMANT_DAYS:
            new_lifecycle = "dormant"
        elif current_lifecycle == "reactivated":
            new_lifecycle = "active"
        elif row["weeks_seen"] < config.PROBLEM_RECURRENCE_WEEKS:
            new_lifecycle = "new"
        else:
            new_lifecycle = "active"

        if new_lifecycle != current_lifecycle:
            _transition(conn, problem_id, domain, "lifecycle", current_lifecycle, new_lifecycle, now,
                        reason="time_and_recurrence", days_quiet=round(days_quiet, 1))
        counts[new_lifecycle] += 1

        if new_lifecycle == "archived":
            continue  # trend is moot for a Problem that just went fully quiet

        # ── trend ──
        reactivated_at = _most_recent_reactivation_timestamp(conn, problem_id)
        anchor = reactivated_at if reactivated_at and reactivated_at > row["first_seen"] else row["first_seen"]
        elapsed_days = _days_between(anchor, now)

        if elapsed_days < config.PROBLEM_TREND_WINDOW_DAYS * 2:
            new_trend = "unknown"
        else:
            recent_start = _iso_minus_days(now, config.PROBLEM_TREND_WINDOW_DAYS)
            prior_start = _iso_minus_days(now, config.PROBLEM_TREND_WINDOW_DAYS * 2)
            recent_count = _evidence_count_in_window(conn, problem_id, recent_start, now)
            prior_count = _evidence_count_in_window(conn, problem_id, prior_start, recent_start)
            new_trend = classify_trend(recent_count, prior_count)

        if new_trend != current_trend:
            extra = {}
            if new_trend != "unknown" and elapsed_days >= config.PROBLEM_TREND_WINDOW_DAYS * 2:
                extra = {"recent_count": recent_count, "prior_count": prior_count}
            _transition(conn, problem_id, domain, "trend", current_trend, new_trend, now,
                        reason="trend_classified", **extra)

    conn.commit()
    return counts


def _transition(conn, problem_id: str, domain: str, axis: str, from_state: str, to_state: str, now: str, **metadata) -> None:
    column = "lifecycle_state" if axis == "lifecycle" else "trend"
    updated_at_column = "lifecycle_updated_at" if axis == "lifecycle" else "trend_updated_at"
    conn.execute(
        f"UPDATE problems SET {column} = ?, {updated_at_column} = ? WHERE id = ?",
        (to_state, now, problem_id),
    )
    problem_history.record_event(
        conn, problem_id, domain, "status_changed",
        metadata={"axis": axis, "from_state": from_state, "to_state": to_state, **metadata},
        occurred_at=now,
    )
    logger.info(f"[{domain}] Problem {problem_id[:8]}... {axis}: {from_state} -> {to_state}")
