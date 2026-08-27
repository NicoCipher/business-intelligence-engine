"""
opportunity_engine/change_detection.py — Change Detection V1 (Stage 3.6)

Reviewed design: see the Change Detection design milestone (docs/HANDOFF.md
history, commit around 3d6bcf4). This module is deliberately a PROJECTION
layer, not a second intelligence engine. It does not decide whether a
Problem is dormant, whether a trend is growing, or what an Opportunity's
tier is — lifecycle.py, canonicalizer.py, and the scorer already make
every one of those decisions, exactly once, and write them down
(problem_history for Problems; the immutable opportunities.scores JSON
for Opportunities). This module's only job is translating decisions
already made and already durable elsewhere into change_events — a
differently-shaped, cross-entity (Problem + Opportunity) log meant for
scanning/alerting, not archaeology.

Consequence worth stating explicitly: change_events is RECONSTRUCTIBLE.
If every row were deleted, replaying this module against problem_history
and opportunities would regenerate it exactly (module the Opportunity-tier
comparison's dependency on which rows happen to still exist, which for
immutable, never-deleted Opportunities is not a real risk in practice).
This mirrors the "reports never create intelligence" principle one layer
down — change_events is not a new memory tier, it's an operationally
convenient index over memory that already exists.

Why this queries problem_history/opportunities directly instead of being
handed rows in-memory by canonicalizer.py/lifecycle.py: the reviewed
design explicitly chose NOT to change those modules' return contracts
for this feature alone (they're already tested and reviewed independently
of this milestone). Idempotency therefore cannot rely on "this row was
handed to me exactly once, in-process" — it has to survive an
independent re-query, including a retried pipeline run, a replay, or a
future manual backfill script. See _deterministic_id()'s docstring for
how that's achieved without any schema change.

Two producers, both pure reads until the final write step:
  - detect_problem_changes()     — projects problem_history (`created`,
                                    `status_changed`) rows into
                                    problem_created / problem_lifecycle_changed
                                    / problem_trend_changed events.
                                    `evidence_added` is suppressed
                                    entirely (reviewed decision — it fires
                                    on nearly every recurrence match, every
                                    run, and would dominate the log; see
                                    the design milestone's Risk #1).
  - detect_opportunity_changes() — the one piece of this module that is
                                    NOT a pure relabeling of an
                                    already-recorded decision. Opportunity
                                    is immutable (ADR-002) and has no
                                    history table, so "did the tier
                                    change" is computed here by comparing
                                    each newly-persisted Opportunity's
                                    tier against the immediately preceding
                                    Opportunity (by created_at) for the
                                    same problem_id. The comparison itself
                                    isn't stored anywhere else, but the
                                    raw material to recompute it
                                    (immutable Opportunity rows) is
                                    durable, so this stays reconstructible
                                    too.

Significance is a static, deterministic 'normal'/'high' lookup — no new
scoring dimension, no learned model, no LLM. See _LIFECYCLE_SIGNIFICANCE /
_TREND_SIGNIFICANCE / _tier_crossing_significance() below; every value
reuses thresholds/vocabularies that already exist elsewhere in the
codebase (config.TIER_GOLD, the lifecycle/trend state vocabularies
lifecycle.py already computes).

Explicitly out of scope for this module (see the design milestone for the
full non-goals list): entity/relationship decay events, collector/
scheduler health events (operational, not evidence-about-the-world —
kept out of change_events entirely, not just deprioritized), watchlists/
alert_rules consumption, any delivery mechanism, any new API route,
lifecycle-flapping/hysteresis handling (deferred).
"""

from __future__ import annotations

import json
import logging
import uuid

from models import _now

logger = logging.getLogger(__name__)


# ── Deterministic event identity ────────────────────────────────────────
# Fixed, arbitrary namespace UUID (uuid.uuid5's second argument must be
# stable across runs/processes for the derived ids to be deterministic —
# any fixed UUID works; this one has no other meaning). Do not change
# this constant after this module ships — doing so would silently change
# every future derived id and defeat existing idempotency guarantees
# against already-written rows.
_ID_NAMESPACE = uuid.UUID("6f1b6e4a-6b1a-4b7a-9d1a-3f5c2a7e9b10")


def _deterministic_id(*parts: str) -> str:
    """
    Derive a stable change_events.id from a natural key built out of the
    source fact this event projects (a problem_history row's id, or an
    Opportunity's id plus the projected event_type). Same source fact ->
    same id, always.

    This is the entire idempotency mechanism — the canonical, sole
    mechanism Change Detection V1 relies on for correctness under retry,
    replay, or backfill; there is no secondary guard anywhere else in
    this module. It does not depend on the `since` query bound being
    exact (see detect_problem_changes()'s docstring) — reprocessing the
    same problem_history row or the same Opportunity comparison, whether
    from a retried run, a replay, or a future manual backfill, always
    derives the same primary key, so _write_change_event()'s INSERT OR
    IGNORE silently discards the duplicate. No UNIQUE index beyond the
    existing PRIMARY KEY, no "already processed" flag anywhere, no schema
    change, and — per the reviewed design — no change to
    canonicalizer.py/lifecycle.py's return contracts to hand this module
    rows in-memory instead.
    """
    key = "|".join(parts)
    return str(uuid.uuid5(_ID_NAMESPACE, key))


# ── Significance model (static, deterministic — no LLM) ─────────────────

# status_changed, axis=lifecycle: (from_state, to_state) -> significance.
# Only the one genuinely surprising transition is elevated; everything
# else (including ->archived, ->dormant, ->active, reactivated->active)
# is 'normal' — expected, frequent, not urgent. A Problem coming back
# from archival is the one lifecycle event an operator most wants to know
# about; it isn't in the default vocabulary lifecycle.py's forward pass
# produces (that only ever moves state forward), so this is a real,
# specific signal, not routine housekeeping.
_LIFECYCLE_SIGNIFICANCE: dict[tuple[str, str], str] = {
    ("archived", "reactivated"): "high",
}
_LIFECYCLE_DEFAULT_SIGNIFICANCE = "normal"

# status_changed, axis=trend: to_state -> significance. 'growing' is the
# one trend movement an operator most wants surfaced ("this problem is
# heating up") regardless of what it was previously classified as.
_TREND_SIGNIFICANCE: dict[str, str] = {
    "growing": "high",
}
_TREND_DEFAULT_SIGNIFICANCE = "normal"


def _tier_crossing_significance(previous_tier: str, new_tier: str) -> str:
    """
    Crossing INTO gold is the single most decision-relevant score
    movement — that's what config.TIER_GOLD already exists to mean.
    Every other crossing (bronze->silver, and every downward crossing —
    reviewed decision: downward tier changes are kept, not suppressed,
    since a Problem's evidence quality getting worse is meaningful
    intelligence too, not just noise) is 'normal'. Deliberately keeps
    the model to 'normal'/'high' only — no 'severity of drop' scoring,
    consistent with the schema's own comment calling this "coarse
    triage, not a new score."
    """
    if new_tier == "gold" and previous_tier != "gold":
        return "high"
    return "normal"


# ── Problem-side projection (pure relabeling of existing decisions) ─────

def detect_problem_changes(conn, domain: str, since: str) -> list[dict]:
    """
    Project this run's problem_history writes into change_events rows,
    scoped to `created` and `status_changed` events with
    occurred_at >= `since`.

    `evidence_added` is excluded at the query level, not filtered
    afterward — this IS the suppression mechanism for the reviewed
    "suppress evidence_added entirely" decision. `confidence_updated` /
    `merged` / `split` are schema-reserved problem_history event types
    no code path writes yet (see models.py's VALID_HISTORY_EVENT_TYPES
    docstring) — nothing to project until something writes them.

    `since` bounds the query for efficiency only — it is NOT the
    idempotency mechanism (see _deterministic_id()'s docstring, the
    canonical mechanism). The bound is inclusive (occurred_at >= since),
    so an event landing exactly on `since` is never lost at the
    boundary. Being too early only widens the query to re-check rows a
    prior run may already have projected — harmless, since
    _deterministic_id() makes the resulting INSERT OR IGNORE a no-op for
    anything already written; no possible value of `since` can cause a
    duplicate change_events row. It must not be too late, or a real
    transition could be missed entirely. Callers should pass a
    timestamp captured before this run's Stage 3/3.5 began.
    """
    rows = conn.execute(
        """
        SELECT id, problem_id, domain, event_type, occurred_at, metadata
        FROM problem_history
        WHERE domain = ? AND occurred_at >= ?
          AND event_type IN ('created', 'status_changed')
        ORDER BY occurred_at ASC
        """,
        (domain, since),
    ).fetchall()

    events = []
    for row in rows:
        projected = _project_problem_history_row(row)
        if projected is not None:
            events.append(projected)
    return events


def _project_problem_history_row(row) -> dict | None:
    event_type = row["event_type"]
    metadata = json.loads(row["metadata"] or "{}")

    if event_type == "created":
        change_event_type = "problem_created"
        significance = "high"
        previous_value = ""
        new_value = ""

    elif event_type == "status_changed":
        axis = metadata.get("axis", "")
        from_state = metadata.get("from_state", "")
        to_state = metadata.get("to_state", "")

        if axis == "lifecycle":
            change_event_type = "problem_lifecycle_changed"
            significance = _LIFECYCLE_SIGNIFICANCE.get(
                (from_state, to_state), _LIFECYCLE_DEFAULT_SIGNIFICANCE
            )
        elif axis == "trend":
            change_event_type = "problem_trend_changed"
            significance = _TREND_SIGNIFICANCE.get(to_state, _TREND_DEFAULT_SIGNIFICANCE)
        else:
            # Defensive only — lifecycle.py's own vocabulary is exactly
            # {"lifecycle", "trend"} today (see _transition()'s axis
            # parameter). A change-detection bug must never crash the
            # pipeline (module docstring) — skip rather than guess at an
            # event_type/significance for an axis this module doesn't
            # recognize.
            logger.warning(
                f"[{row['domain']}] Unrecognized status_changed axis "
                f"'{axis}' on problem_history {row['id']}; skipping projection"
            )
            return None

        previous_value = from_state
        new_value = to_state

    else:
        # Unreachable given this module's own query (event_type IN
        # ('created', 'status_changed')) — defensive only, in case a
        # future caller loosens that query without updating this function.
        return None

    return {
        "id": _deterministic_id("problem_history", row["id"]),
        "domain": row["domain"],
        "event_type": change_event_type,
        "entity_ref_type": "problem",
        "entity_ref_id": row["problem_id"],
        "previous_value": previous_value,
        "new_value": new_value,
        "significance": significance,
        "detected_at": row["occurred_at"],
        "metadata": {"source_problem_history_id": row["id"]},
    }


# ── Opportunity-side projection (the one live comparison in this module) ─

def _tier_from_scores_json(scores_json: str) -> str:
    """
    Read the tier BIA already computed and persisted for this Opportunity
    (opportunities.scores JSON, written once at creation — see
    OpportunityScores.to_dict()'s 'tier' key) rather than recomputing it.
    Opportunities are immutable (ADR-002); the persisted tier IS the tier,
    permanently. Falls back to 'bronze' only for the pathological case of
    a scores blob missing the key entirely — every row written by
    OpportunityScores.to_dict() always includes it, so this is a
    parse-safety fallback, not an expected path.
    """
    data = json.loads(scores_json or "{}")
    return data.get("tier", "bronze")


def detect_opportunity_changes(conn, domain: str, since: str) -> list[dict]:
    """
    Project this run's newly-persisted Opportunities into change_events.

    For each Opportunity persisted this run (created_at >= `since`) that
    is linked to a Problem (problem_id != ''):
      - if it is the FIRST-EVER Opportunity for that Problem (reviewed
        semantics) -> emit 'new_opportunity'.
      - otherwise, compare its tier against the immediately preceding
        Opportunity (by created_at) for the same problem_id:
          - same tier  -> emit nothing (recurrence suppression — the
                           reviewed decision that a Problem simply
                           getting another same-tier observation is not,
                           by itself, a change worth logging).
          - different tier -> emit 'opportunity_tier_crossed', in EITHER
                           direction (reviewed decision: downward
                           crossings are kept, not suppressed).

    The comparison Opportunity (the "previous" one) is deliberately NOT
    bounded by `since` — it can be from any earlier run; that's the
    entire point of comparing against history. `since` only bounds which
    Opportunities count as "new this run," same efficiency-only role as
    in detect_problem_changes().
    """
    new_opps = conn.execute(
        """
        SELECT id, problem_id, domain, scores, created_at
        FROM opportunities
        WHERE domain = ? AND created_at >= ? AND problem_id != ''
        ORDER BY created_at ASC
        """,
        (domain, since),
    ).fetchall()

    events = []
    for opp in new_opps:
        problem_id = opp["problem_id"]
        tier = _tier_from_scores_json(opp["scores"])

        prior = conn.execute(
            """
            SELECT id, scores FROM opportunities
            WHERE problem_id = ? AND id != ? AND created_at < ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (problem_id, opp["id"], opp["created_at"]),
        ).fetchone()

        if prior is None:
            events.append({
                "id": _deterministic_id("opportunity_first", opp["id"]),
                "domain": opp["domain"],
                "event_type": "new_opportunity",
                "entity_ref_type": "opportunity",
                "entity_ref_id": opp["id"],
                "previous_value": "",
                "new_value": tier,
                "significance": "normal",
                "detected_at": opp["created_at"],
                "metadata": {"problem_id": problem_id},
            })
            continue

        prior_tier = _tier_from_scores_json(prior["scores"])
        if prior_tier != tier:
            events.append({
                "id": _deterministic_id("opportunity_tier", opp["id"]),
                "domain": opp["domain"],
                "event_type": "opportunity_tier_crossed",
                "entity_ref_type": "opportunity",
                "entity_ref_id": opp["id"],
                "previous_value": prior_tier,
                "new_value": tier,
                "significance": _tier_crossing_significance(prior_tier, tier),
                "detected_at": opp["created_at"],
                "metadata": {"problem_id": problem_id, "previous_opportunity_id": prior["id"]},
            })
        # else: same tier as the immediately preceding Opportunity for
        # this Problem -- recurrence, not change. No event.

    return events


# ── Write path ────────────────────────────────────────────────────────

def _write_change_event(conn, event: dict) -> bool:
    """
    INSERT OR IGNORE against change_events' existing PRIMARY KEY. Returns
    True if a new row was written, False if this exact id already existed
    (an idempotent replay, not an error — see _deterministic_id()).
    """
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO change_events
            (id, domain, event_type, entity_ref_type, entity_ref_id,
             previous_value, new_value, significance, detected_at, metadata, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event["id"],
            event["domain"],
            event["event_type"],
            event["entity_ref_type"],
            event["entity_ref_id"],
            event["previous_value"],
            event["new_value"],
            event["significance"],
            event["detected_at"],
            json.dumps(event["metadata"], default=str),
            _now(),
        ),
    )
    return cursor.rowcount > 0


# ── Stage 3.6 entry point ────────────────────────────────────────────

def run_change_detection(conn, domain: str, since: str) -> dict:
    """
    Stage 3.6 entry point — see pipeline.py's own Stage 3.6 comment for
    where this is called from and why it's wrapped in its own
    try/except at that call site.

    Projects this run's problem_history writes and newly-persisted
    Opportunities (both bounded by `since`) into change_events, writes
    them idempotently, and returns counts for pipeline logging. Commits
    once at the end — this stage's writes are independent of, and never
    block, Stage 3/3.5's already-committed intelligence.
    """
    events = detect_problem_changes(conn, domain, since) + detect_opportunity_changes(conn, domain, since)

    counts = {"written": 0, "skipped_duplicate": 0, "high_significance": 0}
    for event in events:
        if _write_change_event(conn, event):
            counts["written"] += 1
            if event["significance"] == "high":
                counts["high_significance"] += 1
        else:
            counts["skipped_duplicate"] += 1

    conn.commit()
    return counts
