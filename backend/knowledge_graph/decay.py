"""
knowledge_graph/decay.py — Knowledge-graph lifecycle decay (schema v8)

A graph that only ever grows quietly degrades: match quality and query
performance both suffer once entities/relationships accumulate for years
with no way to distinguish "still relevant" from "mentioned once, three
years ago, never again." This module is the fix — a lifecycle state on
entities and relationships, evaluated by a decay pass that runs once per
domain per pipeline execution (see pipeline.py).

Scope, deliberately narrow: this covers ONLY the knowledge graph
(entities, relationships). Signal stays append-only/immutable. Opportunity
stays immutable, one row per detection. Neither gets a lifecycle here —
that's a separate, future, explicitly-gated decision (Problem/Opportunity
lifecycle is its own roadmap item; see docs/HANDOFF.md). Bundling that in
here would blur the Problem/Opportunity split schema v6/v7 exist to
establish, and would need its own "explain transition logic before
implementing" review against real problem_history data, not this one.

Lifecycle: ACTIVE -> DORMANT -> SOFT_ARCHIVED. Never deleted — decay is
purely a state transition, always reversible. Reactivation happens
elsewhere, not here: knowledge_graph/extractor.py's persist_results()
sets lifecycle_state back to 'active' on every re-encounter, since new
evidence is the only thing that should undo decay. This module only ever
moves state FORWARD (or leaves it alone); it never reactivates anything.

Decision factors available today, all inspectable per-row (nothing
here is a black-box score):
  - last meaningful reference time (`updated_at`, which persist_results()
    now bumps on every re-encounter, not just first insert)
  - connection strength (entity: how many non-archived relationships
    reference it; relationship: its own accumulated `weight`) — more
    connected things are more likely to reflect a real, recurring
    pattern, so they get more time before decaying, not immunity
  - whether an entity is referenced by any current Problem's entity_ids
    in this domain — the best available concrete proxy for "importance"
    today. This PROTECTS (freezes current state, skips further decay)
    rather than reactivates — decay pass never moves state backward.

Extension points, explicitly NOT implemented: confidence score, evidence
quality, user interaction signals. None of those exist anywhere in this
codebase yet (no per-entity confidence field, no evidence-quality
scoring distinct from the opportunity scorer's composite formula, no
user/auth model at all) — wiring them in now would mean fabricating
inputs. `run_decay_pass()` and `decide_lifecycle_state()` both accept
keyword-only parameters for these, currently unused, so a future
implementation can add real signals without changing every call site
again. See each parameter's docstring note.
"""

import json
import logging
from datetime import datetime

import config

logger = logging.getLogger(__name__)


# ── Time helpers ─────────────────────────────────────────────────────────

def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _days_between(earlier: str, later: str) -> float:
    """Days elapsed from `earlier` to `later`, both ISO 8601 strings."""
    return (_parse_iso(later) - _parse_iso(earlier)).total_seconds() / 86400.0


# ── Core decision logic ─────────────────────────────────────────────────

def decide_lifecycle_state(
    *,
    days_since_reference: float,
    dormant_days: float,
    archive_days: float,
    strongly_connected: bool,
    protected: bool = False,
    confidence_score: float | None = None,      # extension point, unused today
    evidence_quality: float | None = None,       # extension point, unused today
    user_interaction_score: float | None = None, # extension point, unused today
) -> str:
    """
    Pure function: given how long it's been since something was last
    meaningfully referenced, decide its lifecycle state. No I/O, fully
    unit-testable, no hidden state — every transition traces to inputs
    that are themselves inspectable on the row.

    `protected` short-circuits to keeping whatever forward progress has
    already happened frozen — this function is only ever called for
    rows the caller has already decided aren't protected (protection is
    checked by the caller before calling this), but the parameter exists
    so the decision logic itself stays fully explainable in one place
    rather than split between caller and callee.

    `strongly_connected` extends both thresholds by
    config.DECAY_PROTECTION_MULTIPLIER — a multiplier, not immunity;
    strongly connected things still eventually decay if genuinely
    unreferenced for long enough.

    The three trailing parameters are extension points for signals that
    don't exist anywhere in this codebase yet (see module docstring).
    They're accepted so future work can add real weighting without
    changing this function's call sites again, but they do nothing right
    now — passing a value here has no effect on the returned state.
    """
    if protected:
        return "active"

    multiplier = config.DECAY_PROTECTION_MULTIPLIER if strongly_connected else 1.0
    effective_dormant_days = dormant_days * multiplier
    effective_archive_days = archive_days * multiplier

    if days_since_reference >= effective_archive_days:
        return "archived"
    if days_since_reference >= effective_dormant_days:
        return "dormant"
    return "active"


# ── Matching-eligibility weights (two-layer, per the RFC decision) ─────

def match_weight(lifecycle_state: str) -> float:
    """
    How much a single entity should count toward canonical Problem
    matching (opportunity_engine/canonicalizer.py), based on its current
    lifecycle state. Active entities count fully; dormant entities count
    at a reduced, configurable weight; archived entities are excluded
    entirely (weight 0) from new matching, though the rows themselves
    are never deleted and remain queryable as historical context.

    Unknown/unrecognized states default to full weight (1.0) rather than
    raising — callers may pass entity ids with no corresponding row at
    all (e.g. in tests that never insert into `entities`), and treating
    "no lifecycle information available" as "don't penalize" is the
    correct default, not an error.
    """
    if lifecycle_state == "dormant":
        return config.DORMANT_MATCH_WEIGHT
    if lifecycle_state == "archived":
        return 0.0
    return 1.0


# ── The decay pass itself ───────────────────────────────────────────────

def _entities_referenced_by_problems(conn, domain: str) -> set[str]:
    """
    Every entity id currently present in any Problem's accumulated
    entity_ids, for this domain. This is today's protection signal — see
    module docstring for why "referenced by a real Problem" stands in
    for "important" until a richer signal exists.
    """
    rows = conn.execute(
        "SELECT entity_ids FROM problems WHERE domain = ?", (domain,)
    ).fetchall()
    ids: set[str] = set()
    for row in rows:
        ids.update(json.loads(row["entity_ids"] or "[]"))
    return ids


def run_decay_pass(
    conn,
    domain: str,
    now: str | None = None,
    *,
    confidence_scores: dict[str, float] | None = None,       # extension point, unused today
    evidence_quality_scores: dict[str, float] | None = None, # extension point, unused today
    user_interaction_scores: dict[str, float] | None = None, # extension point, unused today
) -> dict:
    """
    Evaluate every non-archived entity and relationship in `domain` and
    move it forward along ACTIVE -> DORMANT -> SOFT_ARCHIVED if enough
    time has passed since it was last meaningfully referenced. Never
    deletes anything, never moves state backward (reactivation is
    persist_results()'s job, on new evidence, not this function's).

    Meant to run once per domain per pipeline execution, after entity
    extraction/persistence (so any entity re-encountered this run has
    already been reactivated before decay evaluates it) and before
    detection (so canonical matching sees this run's current lifecycle
    states, not last run's). See pipeline.py.

    `now` defaults to the real current time; accepting it explicitly
    keeps this testable without monkeypatching a clock.

    The three `*_scores` parameters are extension points for signals
    that don't exist anywhere in this codebase yet — see the module
    docstring. Accepted for forward compatibility; unused today.

    Returns a dict of counts (entities_dormant, entities_archived,
    relationships_dormant, relationships_archived) for pipeline logging.
    """
    from models import _now as _default_now
    now = now or _default_now()

    counts = {
        "entities_dormant": 0, "entities_archived": 0,
        "relationships_dormant": 0, "relationships_archived": 0,
    }

    protected_entity_ids = _entities_referenced_by_problems(conn, domain)

    entities = conn.execute(
        "SELECT id, lifecycle_state, updated_at FROM entities "
        "WHERE domain = ? AND lifecycle_state != 'archived'",
        (domain,),
    ).fetchall()
    for row in entities:
        protected = row["id"] in protected_entity_ids
        connection_count = 0
        if not protected:
            connection_count = conn.execute(
                "SELECT COUNT(*) c FROM relationships "
                "WHERE domain = ? AND lifecycle_state != 'archived' AND (from_id = ? OR to_id = ?)",
                (domain, row["id"], row["id"]),
            ).fetchone()["c"]

        new_state = decide_lifecycle_state(
            days_since_reference=_days_between(row["updated_at"], now),
            dormant_days=config.ENTITY_DORMANT_DAYS,
            archive_days=config.ENTITY_ARCHIVE_DAYS,
            strongly_connected=connection_count >= config.ENTITY_STRONG_CONNECTION_COUNT,
            protected=protected,
        )
        if new_state != row["lifecycle_state"]:
            conn.execute(
                "UPDATE entities SET lifecycle_state = ?, lifecycle_updated_at = ? WHERE id = ?",
                (new_state, now, row["id"]),
            )
            counts[f"entities_{new_state}"] = counts.get(f"entities_{new_state}", 0) + 1
            logger.info(f"[{domain}] entity {row['id'][:8]}... -> {new_state}")

    relationships = conn.execute(
        "SELECT id, lifecycle_state, updated_at, weight FROM relationships "
        "WHERE domain = ? AND lifecycle_state != 'archived'",
        (domain,),
    ).fetchall()
    for row in relationships:
        new_state = decide_lifecycle_state(
            days_since_reference=_days_between(row["updated_at"], now),
            dormant_days=config.RELATIONSHIP_DORMANT_DAYS,
            archive_days=config.RELATIONSHIP_ARCHIVE_DAYS,
            strongly_connected=row["weight"] >= config.RELATIONSHIP_STRONG_WEIGHT,
        )
        if new_state != row["lifecycle_state"]:
            conn.execute(
                "UPDATE relationships SET lifecycle_state = ?, lifecycle_updated_at = ? WHERE id = ?",
                (new_state, now, row["id"]),
            )
            counts[f"relationships_{new_state}"] = counts.get(f"relationships_{new_state}", 0) + 1
            logger.info(f"[{domain}] relationship {row['id'][:8]}... -> {new_state}")

    conn.commit()
    return counts
