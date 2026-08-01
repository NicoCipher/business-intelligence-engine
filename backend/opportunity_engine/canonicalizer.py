"""
opportunity_engine/canonicalizer.py — Canonical Problem Identity

Resolves a newly-detected opportunity's entity signature and matches it
against existing Problem rows (see models.py's Problem docstring and the
architecture review §4/§5 for why Problem — not Opportunity — is the
thing that should have long-lived identity).

Design, stated plainly:
  - Entity overlap is the primary signal, title-token overlap is a
    secondary support signal. "Avoid brittle keyword mappings" ruled out
    pure title matching as the primary mechanism — "therapist notes" and
    "clinical session notes" barely share title tokens, but if the
    extractor's entity vocabulary captures the shared concept, they'll
    share entity ids.
  - Thresholds are deliberately conservative. A false MERGE (wrongly
    unifying two different problems) corrupts accumulated history and is
    hard to undo cleanly. A false SPLIT (same problem getting a new root)
    just means slower recognition that self-corrects as more evidence
    accumulates. So the bar to merge is set high on purpose.
  - Fully deterministic — no embeddings, no ML. This is a known,
    explicitly-stated limitation (see the review's Future Work section):
    matching only works as well as the keyword-based entity vocabulary
    does. Upgrading to true semantic similarity is a separate, larger
    infrastructure decision, not something to back into silently here.
"""

import json
import logging

import database
from knowledge_graph import decay
from knowledge_graph.extractor import EntityExtractor
from opportunity_engine import problem_history
from opportunity_engine.similarity import title_tokens, jaccard, weighted_jaccard
from models import Signal, Problem

logger = logging.getLogger(__name__)

# Conservative on purpose — see module docstring.
ENTITY_MATCH_THRESHOLD = 0.5   # entity overlap alone is sufficient above this
TITLE_SUPPORT_THRESHOLD = 0.5  # any entity overlap + strong title overlap also counts
ENTITY_WEIGHT = 0.7
TITLE_WEIGHT = 0.3


def resolve_entity_ids(cluster_signals: list[Signal], domain: str) -> list[str]:
    """
    Resolve the persisted, deduplicated entity IDs a cluster's signals
    mention, scoped to this domain (schema v5).

    Reuses EntityExtractor's matching — the same keyword scan already
    used during the pipeline's extraction stage — rather than
    re-implementing keyword matching a second time. Looks up each
    matched (type, name, domain) triple's canonical entities.id, the
    same resolution technique extractor.py's persist_results() uses for
    relationship building.
    """
    if not cluster_signals:
        return []

    extractor = EntityExtractor()
    found: set[tuple[str, str]] = set()
    for sig in cluster_signals:
        result = extractor.extract(sig)
        for entity in result.entities:
            found.add((entity.type, entity.name))

    if not found:
        return []

    ids: list[str] = []
    with database.get_connection() as conn:
        for etype, name in found:
            row = conn.execute(
                "SELECT id FROM entities WHERE type = ? AND name = ? AND domain = ?",
                (etype, name, domain),
            ).fetchone()
            if row:
                ids.append(row["id"])
    return ids


def _week_key_from_iso(ts: str) -> str:
    from datetime import datetime
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"


def find_match(entity_ids: list[str], title: str, domain: str, conn) -> dict | None:
    """
    Find the best-matching existing Problem for a new opportunity's
    entity signature + title, or None if nothing clears the bar.

    Queries every Problem in this domain, unbounded by recency — a
    dormant problem reappearing after months is exactly the kind of
    long-term memory this exists to catch, so recency-limiting the
    candidate set would undermine the point. Flagged in the architecture
    review as a future scaling concern (§6), not addressed here.

    Entity comparison is lifecycle-weighted (schema v8,
    knowledge_graph/decay.py), not plain set overlap: an entity's
    contribution to entity-Jaccard is scaled by decay.match_weight()
    (active=1.0, dormant=reduced, archived=0/excluded). This is the
    "two-layer matching eligibility" decision from the decay RFC review —
    stale knowledge stops creating new matches without being deleted or
    blocking the Problem from being retrieved as historical context.
    Entity ids with no corresponding `entities` row (including every
    existing test that uses bare synthetic ids) default to full weight —
    see decay.match_weight()'s docstring for why that's the correct
    default, not a gap. Title comparison is untouched plain jaccard()
    throughout — titles aren't entities, they have no lifecycle.

    Returns {"problem_id", "matched_title", "match_score"} or None.
    """
    rows = conn.execute(
        "SELECT id, title, entity_ids FROM problems WHERE domain = ?",
        (domain,),
    ).fetchall()
    if not rows:
        return None

    new_entities = set(entity_ids)
    new_title_tokens = title_tokens(title)

    candidate_entity_sets = [set(json.loads(row["entity_ids"] or "[]")) for row in rows]
    all_entity_ids = new_entities.union(*candidate_entity_sets) if candidate_entity_sets else new_entities
    weights = _lifecycle_match_weights(conn, domain, all_entity_ids)
    weight_fn = lambda eid: weights.get(eid, 1.0)  # noqa: E731 — unknown id -> full weight, see decay.match_weight()

    best = None
    best_score = 0.0
    for row, candidate_entities in zip(rows, candidate_entity_sets):
        entity_j = weighted_jaccard(new_entities, candidate_entities, weight_fn)
        title_j = jaccard(new_title_tokens, title_tokens(row["title"]))

        qualifies = entity_j >= ENTITY_MATCH_THRESHOLD or (entity_j > 0 and title_j >= TITLE_SUPPORT_THRESHOLD)
        if not qualifies:
            continue

        combined = entity_j * ENTITY_WEIGHT + title_j * TITLE_WEIGHT
        if combined > best_score:
            best = row
            best_score = combined

    if best is None:
        return None

    return {
        "problem_id": best["id"],
        "matched_title": best["title"],
        "match_score": round(best_score, 3),
    }


def _lifecycle_match_weights(conn, domain: str, entity_ids: set[str]) -> dict[str, float]:
    """
    Batch-resolve match_weight() for every entity id that might appear in
    this find_match() call, in one query instead of one per comparison.
    Ids with no corresponding row (synthetic test ids, or genuinely
    unknown ids) are simply absent from the returned dict — callers
    default those to full weight via weights.get(id, 1.0).
    """
    if not entity_ids:
        return {}
    placeholders = ",".join("?" for _ in entity_ids)
    rows = conn.execute(
        f"SELECT id, lifecycle_state FROM entities WHERE domain = ? AND id IN ({placeholders})",
        (domain, *entity_ids),
    ).fetchall()
    return {row["id"]: decay.match_weight(row["lifecycle_state"]) for row in rows}


def resolve_problem(
    entity_ids: list[str],
    title: str,
    domain: str,
    week_key: str,
    conn,
    opportunity_id: str = "",
) -> tuple[str, dict | None]:
    """
    Resolve (and update, or create) the canonical Problem for a new
    opportunity. This is the one function detector.py calls.

    Returns (problem_id, match_info | None). match_info is None for a
    genuinely new pattern; otherwise carries the match explanation
    (explainability over black-box matching, per the stated engineering
    principles).

    Idempotency: weeks_seen only increments once per calendar week, even
    if multiple opportunities in the same detection run match the same
    Problem (e.g. two differently-worded clusters both resolving to one
    underlying pain point) — otherwise a single pipeline run could
    inflate weeks_seen by more than one real week.

    `opportunity_id` is optional (defaults to "") and purely additive —
    when supplied it's recorded on the resulting problem_history event so
    the timeline can be traced back to the specific observation that
    produced it (schema v7). Existing callers that don't pass it keep
    working unchanged; the event is still recorded, just without that
    cross-reference.

    Every branch below writes exactly one problem_history event via
    opportunity_engine.problem_history.record_event() — "created" for a
    genuinely new Problem, "evidence_added" for a match — in the same
    transaction as the problems table write, so the two can never
    diverge (a Problem row without a corresponding origin event, or vice
    versa).
    """
    match = find_match(entity_ids, title, domain, conn)

    if match is None:
        problem = Problem(title=title, domain=domain, entity_ids=entity_ids)
        row = problem.to_db_row()
        conn.execute(
            """
            INSERT INTO problems
              (id, domain, title, entity_ids, first_seen, last_seen, weeks_seen, created_at, updated_at)
            VALUES
              (:id, :domain, :title, :entity_ids, :first_seen, :last_seen, :weeks_seen, :created_at, :updated_at)
            """,
            row,
        )
        problem_history.record_event(
            conn,
            problem.id,
            domain,
            "created",
            week_key=week_key,
            opportunity_id=opportunity_id,
            metadata={"title": title, "entity_count": len(entity_ids)},
        )
        logger.info(f"[{domain}] New Problem created: '{title[:60]}'")
        return problem.id, None

    problem_id = match["problem_id"]
    existing = conn.execute(
        "SELECT last_seen, weeks_seen, entity_ids FROM problems WHERE id = ?",
        (problem_id,),
    ).fetchone()

    merged_entity_ids = sorted(set(json.loads(existing["entity_ids"] or "[]")) | set(entity_ids))

    already_counted_this_week = _week_key_from_iso(existing["last_seen"]) == week_key
    new_weeks_seen = existing["weeks_seen"] if already_counted_this_week else existing["weeks_seen"] + 1

    conn.execute(
        """
        UPDATE problems
        SET entity_ids = ?, last_seen = ?, weeks_seen = ?, updated_at = ?
        WHERE id = ?
        """,
        (json.dumps(merged_entity_ids), database._now(), new_weeks_seen, database._now(), problem_id),
    )
    problem_history.record_event(
        conn,
        problem_id,
        domain,
        "evidence_added",
        week_key=week_key,
        opportunity_id=opportunity_id,
        metadata={
            "title": title,
            "matched_title": match["matched_title"],
            "match_score": match["match_score"],
            "new_entity_count": len(entity_ids),
            "weeks_seen": new_weeks_seen,
        },
    )
    logger.info(
        f"[{domain}] '{title[:60]}' matched Problem {problem_id[:8]}... "
        f"(score {match['match_score']}, now seen {new_weeks_seen} week(s))"
    )
    return problem_id, match
