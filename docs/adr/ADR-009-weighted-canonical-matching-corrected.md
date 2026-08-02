# ADR-009 — Weighted Canonical Matching (Corrected)

Version: 1.0

Status: Accepted

Date: 2026-08-02

Supersedes: ADR-007

---

# Context

Canonical matching (`opportunity_engine/canonicalizer.py::find_match()`) determines whether a newly observed Opportunity represents an existing Problem or a genuinely new one, by comparing entity-signature overlap (entity-Jaccard) plus title overlap.

As the knowledge graph accumulated stale Entities and Relationships (ADR-008), those stale graph elements increasingly influenced entity-Jaccard scores with the same strength as current ones, even after they'd been marked dormant or archived.

ADR-007 correctly identified that matching needed to become relevance-aware, but incorrectly described the mechanism as weighting by the *Problem's* own lifecycle state. This ADR corrects that: the weighting operates on Entities, not on Problems.

---

# Problem

Historical graph structure should remain available for matching — an Entity that hasn't been mentioned in months might still be exactly what a new Opportunity is describing.

However, that structure should not always count with the same strength as currently active structure.

Without weighting:

- archived Entities contribute to entity-Jaccard exactly as if they were still active
- a Problem's accumulated `entity_ids` set never "ages" as its individual entities decay
- stale entity structure can incorrectly pull a new Opportunity toward a Problem that hasn't had *real* new evidence in a long time, simply because the raw entity ids still technically overlap

---

# Decision

Canonical matching uses lifecycle-aware weighting, applied per Entity, not per Problem.

Every Problem in the domain remains a fully eligible match candidate regardless of its own `lifecycle_state` (schema v9, ADR-010) — including an `archived` Problem, since archived Problems must remain matchable for reactivation to work at all (see ADR-010).

What varies is how much each individual Entity in the comparison contributes to the entity-Jaccard score, based on that Entity's own `lifecycle_state` (ADR-008):

- active Entities: full weight (1.0)
- dormant Entities: reduced, configurable weight (`config.DORMANT_MATCH_WEIGHT`)
- archived Entities: excluded entirely (weight 0) — filtered from both sides of the comparison rather than distorting the denominator

Entity ids with no corresponding `entities` row default to full weight — this is what keeps matching behavior backward-compatible with contexts that reference entity ids without lifecycle information.

Title comparison (title-Jaccard) is unaffected — titles have no lifecycle.

---

# Rationale

Entity lifecycle state represents current operational relevance of a piece of knowledge-graph structure.

Problem identity represents accumulated historical evidence about a real-world pattern.

These are different layers. Weighting the wrong one (Problem-level, as ADR-007 described) would have meant an archived Problem could never accumulate new evidence at all, since a fully-excluded Problem can't be found by `find_match()` in the first place — directly breaking reactivation. Weighting the right one (Entity-level) means a Problem stays matchable for as long as it exists, while the *specific graph elements* used to justify a match age out independently as they individually go stale.

---

# Alternatives Considered

## Alternative 1 — Equal Matching Weight (No Weighting)

Rejected.

Every historical Entity permanently influences matching regardless of operational relevance, gradually reducing matching precision as the graph grows.

## Alternative 2 — Weight by Problem Lifecycle State

Rejected — this was ADR-007's original (incorrect) design.

Excluding or down-weighting an archived Problem from matching would prevent it from ever being found again by `find_match()`, which is precisely the mechanism reactivation depends on. Weighting must happen at the Entity level, one layer below Problem identity, to avoid this contradiction.

## Alternative 3 — Weight by Entity Lifecycle State

Accepted.

Lets Problems remain permanently matchable while the graph structure justifying any given match ages independently and explainably.

---

# Consequences

Positive consequences include:

- improved canonical matching precision as the graph grows
- Problems remain reachable/reactivatable regardless of their own dormancy
- fully backward compatible — entity ids without lifecycle information default to full weight, so behavior for any pre-existing caller or test is unchanged

Trade-offs include:

- one additional query per `find_match()` call to batch-resolve entity lifecycle weights
- slightly more complex Jaccard computation (`weighted_jaccard()` in `opportunity_engine/similarity.py`, a strict generalization of the original `jaccard()`, which remains untouched and is still used for title comparison)

These costs are accepted; they are small and the correctness gain (Problems staying reachable) is not optional.

---

# Architectural Impact

This decision depends on Entity/Relationship lifecycle state (ADR-008) existing at all, and is a direct consumer of it — not a duplicate of it.

It supports Problem reactivation (ADR-010) by construction: because Problem-level exclusion was rejected, `find_match()`'s candidate query never filters by Problem `lifecycle_state`, which is exactly what allows an archived Problem to be found and reactivated by new evidence.

---

# Current Implementation

`opportunity_engine/similarity.py::weighted_jaccard(a, b, weight_fn)` — a generalization of `jaccard()` that reduces to it exactly when every member has weight 1.0.

`knowledge_graph/decay.py::match_weight(lifecycle_state)` — the active/dormant/archived → weight mapping.

`opportunity_engine/canonicalizer.py::find_match()` — batch-resolves weights for every entity id involved in one call, then applies `weighted_jaccard()` per candidate Problem. Problem-level `lifecycle_state` is never read by this function.

---

# Future Evolution

If a genuine need for Problem-level match eligibility ever arises (for example, deprioritizing but not fully excluding matches against archived Problems), it should be a new, explicitly-reasoned ADR — not a retrofit onto this one, given how directly this decision's correctness depends on Problems staying fully matchable.

---

# Related Decisions

Depends on:

- ADR-001 — Problem as Canonical Identity
- ADR-008 — Entity & Relationship Lifecycle Decay

Supports:

- ADR-010 — Problem Lifecycle & Trend (specifically, reactivation)

Supersedes:

- ADR-007 — Weighted Canonical Matching (corrects mechanism: Entity-level weighting, not Problem-level)

---

# References

Architecture Handbook

- 04_DATA_MODEL.md
- 06_ARCHITECTURAL_INVARIANTS.md

Implementation Documentation

- docs/ARCHITECTURE.md
- docs/SCHEMA.md (v8 entry)

---

# Status

Accepted.

Weighted canonical matching, correctly scoped to Entity-level lifecycle state, is a foundational property of BIA's matching model.
