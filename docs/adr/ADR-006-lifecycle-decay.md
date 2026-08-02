# ADR-006 — Lifecycle Decay

Version: 1.0

Status: Accepted

Date: 2026-08-01

Supersedes: None

---

# Context

Not every Problem remains permanently active.

Some Problems disappear.

Some become dormant.

Others later reappear.

Early versions of BIA treated every historical Problem equally regardless of recency.

As the knowledge base grew, stale intelligence increasingly competed with current intelligence during canonical matching and opportunity detection.

The platform therefore required an explicit lifecycle model.

---

# Problem

Without lifecycle management the intelligence engine cannot distinguish between:

- active Problems
- dormant Problems
- archived Problems
- reactivated Problems

Treating every historical Problem identically causes:

- reduced canonical matching quality
- stale intelligence dominating current reasoning
- inflated confidence
- degraded prediction quality

At the same time, deleting historical intelligence violates the platform's append-only philosophy.

The architecture therefore requires forgetting without deletion.

---

# Decision

Problems evolve through lifecycle states.

Lifecycle transitions describe the current state of a Problem.

They do not remove historical knowledge.

The current lifecycle model consists of:

- Active
- Dormant
- Archived
- Reactivated

Problems retain their complete historical memory regardless of lifecycle state.

---

# Rationale

Lifecycle state represents operational relevance.

Memory represents historical truth.

These concepts are intentionally independent.

A Problem may become archived while preserving:

- historical evidence
- Opportunities
- confidence history
- recurrence history
- source history

Future observations may reactivate the same Problem without reconstructing its history.

---

# Alternatives Considered

## Alternative 1 — Delete Stale Problems

Rejected.

Deletion permanently removes intelligence.

Historical reasoning becomes impossible.

Prediction quality decreases.

The architecture explicitly rejects destructive forgetting.

---

## Alternative 2 — Ignore Time Completely

Rejected.

Old intelligence gradually dominates canonical matching.

Historical Problems become indistinguishable from active ones.

Operational relevance is lost.

---

## Alternative 3 — Lifecycle State

Accepted.

Lifecycle state preserves historical memory while allowing the intelligence engine to reason differently about active and inactive Problems.

---

# Consequences

Positive consequences include:

- improved canonical matching
- reduced stale intelligence
- preserved historical memory
- support for reactivation
- cleaner prediction inputs
- improved explainability

Trade-offs include:

- lifecycle management
- additional metadata
- decay processing

These costs are accepted because they improve long-term intelligence quality.

---

# Architectural Impact

Lifecycle state directly supports:

- Persistent Problem Memory
- Weighted Canonical Matching
- Validation Intelligence
- Prediction Intelligence

Lifecycle state represents operational behavior.

Historical memory remains append-only.

---

# Current Implementation

The current implementation stores:

- lifecycle_state
- lifecycle_updated_at

These fields represent the latest known lifecycle condition.

Historical intelligence remains preserved independently.

---

# Future Evolution

Future versions may introduce append-only lifecycle history.

Possible examples include:

- entity_lifecycle_history
- relationship_lifecycle_history

These would preserve every lifecycle transition while leaving the current lifecycle state available for efficient operational reasoning.

Such extensions expand the memory model rather than replacing it.

---

# Related Decisions

Depends on:

- ADR-001 — Problem as Canonical Identity
- ADR-005 — Persistent Problem Memory

Supports:

- ADR-007 — Weighted Canonical Matching
- Validation Intelligence
- Prediction Intelligence

---

# References

Architecture Handbook

- 04_DATA_MODEL.md
- 08_MEMORY_ARCHITECTURE.md
- 09_VALIDATION_INTELLIGENCE.md
- 10_PREDICTION_INTELLIGENCE.md

Implementation Documentation

- docs/ARCHITECTURE.md
- docs/SCHEMA.md

---

# Status

Accepted.

Lifecycle Decay defines how BIA manages operational relevance without sacrificing historical intelligence.

The platform intentionally forgets through lifecycle transitions rather than through deletion.
