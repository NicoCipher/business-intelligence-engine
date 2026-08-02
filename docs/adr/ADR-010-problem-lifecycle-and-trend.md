# ADR-010 — Problem Lifecycle & Trend

Version: 1.0

Status: Accepted

Date: 2026-08-02

Supersedes: None

---

# Context

Not every Problem remains permanently active.

Some go quiet. Some later reappear. Among those still active, some are accelerating, some are steady, some are fading.

ADR-006 attempted to describe this as an extension of knowledge-graph lifecycle decay, using the same Active/Dormant/Archived/Reactivated vocabulary. That framing was corrected by ADR-008 (which restricts that model to Entities and Relationships) — Problem-level lifecycle was never actually given its own accurate architectural decision. This ADR is that decision.

A further design question emerged specifically for Problems, which does not apply at the Entity/Relationship level: should "is this still relevant" and "how is it trending" be the same field, or two independent ones?

---

# Problem

Without Problem-level lifecycle tracking, the intelligence engine cannot distinguish a Problem still under active discussion from one that hasn't produced a real signal in a year, even though both persist forever by design (Problems are never deleted).

Separately, without trend tracking, "this Problem exists and is recurring" carries no information about direction — a Problem seen twice, six months apart, and a Problem seen twice, this week, would look identical.

A first implementation combined both concerns into a single `trajectory_state` field (discovery → validation → growing/mature/declining → archived, plus reactivated). Before that design was ever pushed, it was rejected: a combined enum either explodes combinatorially (every lifecycle stage × every trend) or produces contradictory-reading states — a Problem that just came back from archival but also happens to be declining; a Problem that's growing overall but whose single most recent data point looks quiet.

---

# Decision

Problem carries two INDEPENDENT current-state fields, not one:

**`lifecycle_state`** — "is this Problem operationally relevant right now?"

```
new -> active -> dormant -> archived
                    ^-- reactivated <--'
```

**`trend`** — "how is its evidence cadence changing?", entirely independent of lifecycle:

```
unknown -> growing | stable | declining
```

Confidence remains part of the existing Opportunity scoring model (`OpportunityScores.confidence`) and is not part of either field — a third, already-existing axis, correctly left alone.

One field, one concept: `lifecycle_state` never encodes trend information, and `trend` never encodes operational-relevance information. A `dormant` Problem can still carry a last-known `declining` trend value. A freshly `reactivated` Problem has its `trend` reset to `unknown` independently of the lifecycle transition that triggered it.

---

# Rationale

Lifecycle state answers a binary-ish operational question: should this Problem currently be treated as live. Trend answers a directional question: is the live evidence increasing, steady, or decreasing. These questions have different owners in a founder's mental model when reading a report ("is this still a thing" vs. "is it getting bigger"), and conflating them into one field means every future consumer of this data has to parse a compound state to answer either question independently.

Splitting them also decoupled two pieces of logic that were tangled together in the first (rejected) design: reactivation no longer needs special-case handling for "what trend value should a reactivated Problem show" — it simply resets `trend` to `unknown`, and the next `run_lifecycle_pass()` reclassifies it using the same rules as any other Problem, anchored to the reactivation timestamp rather than `first_seen`.

---

# Alternatives Considered

## Alternative 1 — Single Combined `trajectory_state`

Rejected — this was the first design, fully implemented and tested (23 tests) before being replaced.

Produces contradictory-reading states and requires the state machine to special-case "reactivated" against trend classification, since one field has to represent both concerns at once.

## Alternative 2 — Lifecycle Only, No Trend

Rejected.

Answers "is this still relevant" but discards directional information a founder reading a report would want — recurring-but-flat and recurring-and-accelerating look identical.

## Alternative 3 — Two Independent Axes

Accepted.

One field, one concept. Each axis's transition rules can be reasoned about, tested, and explained independently.

---

# Consequences

Positive consequences include:

- no contradictory-reading combined states
- reactivation logic decoupled from trend classification
- each axis independently testable and explainable
- extensible: a future third axis (e.g., confidence-derived signal, if one is ever built distinct from the scorer) doesn't require redesigning the first two

Trade-offs include:

- two columns instead of one, two `_updated_at` companions
- every transition writes a `status_changed` event tagged by which axis changed, rather than one undifferentiated transition log
- the rework cost of replacing the first (single-field) implementation — accepted because nothing had been pushed yet when the correction was made

---

# Architectural Impact

`lifecycle_state` mirrors the same `active -> dormant -> archived` shape as Entity/Relationship decay (ADR-008), with its own separate thresholds (`PROBLEM_DORMANT_DAYS`, `PROBLEM_ARCHIVE_DAYS`) — a Problem going quiet is a different, higher-level signal than a single entity mention going stale, so the numbers differ, but the shape is intentionally consistent across the platform.

Reactivation is event-driven, mirroring ADR-008's pattern exactly: checked inside `canonicalizer.resolve_problem()` the instant new evidence arrives, not swept periodically. `reactivated` is a one-pass marker — the next `run_lifecycle_pass()` promotes it straight to `active` (the archive check still takes precedence if it immediately goes quiet again).

This decision explicitly does not touch Opportunity or Signal. Both remain exactly as immutable as ADR-002 and the platform's core invariants require. `Opportunity.status` (`new|validated|dismissed|archived`) is a separate, pre-existing, human-curated review field, unrelated to this ADR, discovered during this decision's design — the vocabularies happen to share "new" and "archived," which is coincidental, not conceptual overlap.

---

# Current Implementation

Schema v9 adds to `problems`:

- `lifecycle_state` (new | active | dormant | archived | reactivated)
- `lifecycle_updated_at`
- `trend` (unknown | growing | stable | declining)
- `trend_updated_at`

Transition rules, thresholds, and the full trend-classification formula (recent-window vs. prior-window `problem_history` evidence-count comparison) are documented in `docs/SCHEMA.md`'s v9 entry and `opportunity_engine/lifecycle.py`'s module docstring.

Every transition on either axis writes a `status_changed` `problem_history` event (the event type ADR-005 / schema v7 reserved for exactly this, unused until this decision), tagged `metadata["axis"]` so the two axes never get conflated in the history log even though both underlying columns are current-state fields, overwritten on each transition.

---

# Future Evolution

Future versions may introduce append-only lifecycle/trend history (`problem_lifecycle_history`, structurally distinct from the `status_changed` events already recorded in `problem_history`, which capture transitions but not a queryable timeline shaped for that specific purpose) — not a current requirement, consistent with the same deferred-append-only-history reasoning already applied to Entities/Relationships (ADR-008).

Evidence-quality and confidence-derived signals remain explicit non-goals of this decision (see `opportunity_engine/lifecycle.py`'s extension-point parameters, currently unused) — nothing in the codebase computes either as a distinct value yet, and fabricating inputs would be worse than leaving the hooks unused until they do.

---

# Related Decisions

Depends on:

- ADR-001 — Problem as Canonical Identity
- ADR-005 — Persistent Problem Memory
- ADR-008 — Entity & Relationship Lifecycle Decay (parallel shape, separate thresholds)
- ADR-009 — Weighted Canonical Matching (Corrected) (Problem-level `lifecycle_state` is deliberately NOT read by matching — see that ADR's Future Evolution section)

Distinct from (do not conflate):

- `Opportunity.status` — unrelated, pre-existing, human-curated

Corrects the Problem-level scope error in:

- ADR-006 — Lifecycle Decay (superseded by ADR-008 for its Entity/Relationship content; this ADR is the first accurate documentation of Problem-level lifecycle, which ADR-006 never correctly separated out)

---

# References

Architecture Handbook

- 04_DATA_MODEL.md (Problem section, Current Implementation Note)
- 06_ARCHITECTURAL_INVARIANTS.md
- 08_MEMORY_ARCHITECTURE.md

Implementation Documentation

- docs/ARCHITECTURE.md ("Problem lifecycle & trend" section)
- docs/SCHEMA.md (v9 entry — full transition-rule tables)

---

# Status

Accepted.

Two independent axes — lifecycle_state and trend — are a foundational property of BIA's Problem model and should be preserved by future implementations. Any future addition of a third dimension (e.g., a genuine confidence-trajectory signal) should extend this pattern rather than folding into either existing axis.
