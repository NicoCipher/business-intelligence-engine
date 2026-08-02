# ADR-008 — Entity & Relationship Lifecycle Decay

Version: 1.0

Status: Accepted

Date: 2026-08-02

Supersedes: ADR-006

---

# Context

BIA's knowledge graph (Entities and Relationships) grows continuously as the pipeline extracts structure from Signals.

A graph that only ever grows quietly degrades.

Early implementations treated every historical Entity and Relationship equally regardless of recency, in exactly the way ADR-006 originally described — but ADR-006 mistakenly attributed this problem and its fix to Problems. The knowledge graph is where it actually applies.

As the graph grew, stale Entities and Relationships increasingly competed with current ones during canonical matching and opportunity detection.

---

# Problem

Without lifecycle management the intelligence engine cannot distinguish between:

- an Entity mentioned once, years ago, never again
- an Entity referenced weekly, continuously

Treating every Entity and Relationship identically causes:

- reduced canonical matching quality
- degraded query performance as the graph grows without bound
- stale structure competing with current structure

At the same time, deleting historical graph structure violates the platform's append-only philosophy and would destroy the evidence trail underlying every Problem built on it.

The architecture therefore requires forgetting without deletion, scoped to the knowledge graph specifically.

---

# Decision

Entities and Relationships carry a `lifecycle_state`.

Lifecycle transitions describe current operational relevance.

They do not remove historical structure.

The lifecycle model consists of:

- active
- dormant
- archived

There is no separate persisted "reactivated" state at this level — new evidence (a re-encountered Entity or Relationship during extraction) reactivates directly to `active`. This is a deliberate difference from Problem lifecycle (ADR-010), where "reactivated" is a distinct, visible marker state for exactly one pass. At the Entity/Relationship level, that distinction wasn't judged valuable enough to justify a fourth persisted state — reactivation here is a high-frequency, low-ceremony event (any re-extraction of common terms), where at the Problem level it's a rarer, more meaningful moment worth surfacing explicitly.

Entities and Relationships retain their complete row and extraction history regardless of lifecycle state.

---

# Rationale

Lifecycle state represents operational relevance.

The row itself, and the Signals that produced it, represent historical truth.

These are intentionally independent.

An Entity may become archived while its extraction history — which Signals mentioned it, when — remains fully intact and queryable.

Future re-extraction reactivates the same Entity without reconstructing anything.

---

# Alternatives Considered

## Alternative 1 — Delete Stale Entities/Relationships

Rejected.

Deletion permanently removes graph structure that Problems may still reference through their accumulated `entity_ids`.

## Alternative 2 — Ignore Time Completely

Rejected.

Old graph structure gradually dominates canonical matching as the graph grows across years of weekly runs.

## Alternative 3 — Lifecycle State

Accepted.

Preserves historical structure while letting canonical matching reason differently about active and inactive graph elements.

---

# Consequences

Positive consequences include:

- improved canonical matching quality
- reduced stale structure influencing new matches
- preserved historical graph
- cleaner long-term query performance

Trade-offs include:

- lifecycle management overhead
- additional metadata per row
- a periodic decay pass

These costs are accepted because they improve long-term matching quality without sacrificing history.

---

# Architectural Impact

Entity/Relationship lifecycle state directly supports:

- Weighted Canonical Matching (ADR-009)

It does not, by itself, affect Problem-level reasoning — that is governed separately by ADR-010.

---

# Current Implementation

Schema v8 adds to both `entities` and `relationships`:

- `lifecycle_state` (active | dormant | archived)
- `lifecycle_updated_at`

Decay factors: last meaningful reference time (`updated_at`, bumped on every re-encounter, not just first insert — a gap in the original extraction logic that this work also closed), connection strength (relationship count for an Entity, accumulated weight for a Relationship), and whether an Entity is referenced by any current Problem's `entity_ids` (protects without reactivating). Thresholds are configurable (`config.py`: `ENTITY_DORMANT_DAYS`, `ENTITY_ARCHIVE_DAYS`, `RELATIONSHIP_DORMANT_DAYS`, `RELATIONSHIP_ARCHIVE_DAYS`, and a connection-strength protection multiplier).

The decay pass runs once per domain per pipeline execution (`pipeline.py` Stage 2.5, after extraction/persistence, before detection). See `knowledge_graph/decay.py`.

---

# Future Evolution

Future versions may introduce append-only lifecycle history (`entity_lifecycle_history`, `relationship_lifecycle_history`), preserving every transition rather than only the current state plus its last-changed timestamp. Not a current requirement — see `docs/architecture/core/08_MEMORY_ARCHITECTURE.md`'s Current Implementation Note for the full reasoning on why this is deliberately deferred rather than missing.

---

# Related Decisions

Depends on:

- ADR-003 — Domain-Scoped Knowledge Graph

Supports:

- ADR-009 — Weighted Canonical Matching (Corrected)

Distinct from (do not conflate):

- ADR-010 — Problem Lifecycle & Trend

Supersedes:

- ADR-006 — Lifecycle Decay (corrects subject: Entities/Relationships, not Problems)

---

# References

Architecture Handbook

- 04_DATA_MODEL.md
- 08_MEMORY_ARCHITECTURE.md

Implementation Documentation

- docs/ARCHITECTURE.md
- docs/SCHEMA.md (v8 entry)

---

# Status

Accepted.

Entity/Relationship lifecycle decay is a foundational property of the knowledge graph and should be preserved by future implementations.
