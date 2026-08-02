# ADR-002 — Opportunity Immutability

Version: 1.0

Status: Accepted

Date: 2026-08-01

Supersedes: None

---

# Context

BIA continuously analyzes evidence over time.

As evidence changes, the intelligence engine produces new assessments.

A fundamental architectural question emerged during the design of the intelligence model:

Should an existing Opportunity be updated as intelligence changes, or should every assessment remain permanently preserved?

This decision directly affects historical analysis, explainability, validation, prediction, and long-term intelligence quality.

---

# Problem

An Opportunity represents the intelligence engine's assessment of a Problem at a specific point in time.

If Opportunities are mutable:

- historical reasoning disappears
- previous assessments are overwritten
- validation becomes unreliable
- prediction loses temporal context
- auditability is weakened

The platform therefore requires a mechanism for preserving historical intelligence while allowing understanding of a Problem to evolve.

---

# Decision

Opportunities are immutable.

Each Opportunity represents a permanent historical observation produced by the intelligence engine.

When intelligence changes, the engine creates a new Opportunity rather than modifying an existing one.

Problems evolve.

Opportunities do not.

---

# Rationale

An immutable Opportunity preserves:

- historical reasoning
- confidence at the time of detection
- supporting evidence
- scoring decisions
- recommendation history

This allows the intelligence engine to reconstruct how its understanding evolved over time.

The immutable model also supports future validation and prediction systems without requiring historical reconstruction.

---

# Alternatives Considered

## Alternative 1 — Mutable Opportunities

Rejected.

Updating Opportunities would overwrite previous intelligence.

Historical reasoning would be lost.

Validation could no longer compare previous assessments against later outcomes.

---

## Alternative 2 — Versioned Opportunities

Partially accepted.

Versioning preserves history but introduces unnecessary complexity.

Creating a new immutable Opportunity for each assessment naturally produces the same historical record while keeping the data model simpler.

---

## Alternative 3 — Replace Previous Opportunity

Rejected.

Deleting or replacing historical intelligence violates the platform's append-only philosophy.

---

# Consequences

Positive consequences include:

- complete historical timeline
- reproducible intelligence
- explainable recommendations
- validation against previous assessments
- prediction using historical evolution
- simplified auditing

Trade-offs include:

- increased storage requirements
- larger Opportunity history
- additional canonical matching work

These trade-offs are accepted.

Storage is significantly less valuable than preserved intelligence.

---

# Relationship to Problems

Problems and Opportunities intentionally have different lifecycles.

Problems are:

- persistent
- canonical
- mutable
- continuously evolving

Opportunities are:

- immutable
- historical
- append-only
- point-in-time assessments

This distinction forms one of the central architectural principles of BIA.

---

# Architectural Impact

This decision enables:

- append-only intelligence history
- longitudinal validation
- prediction over historical assessments
- explainable recommendation evolution
- confidence trend analysis

Changing this decision would require redesign of validation, prediction, and memory subsystems.

---

# Implementation

Current implementation follows this model.

```
Problem

↓

Opportunity A

↓

Opportunity B

↓

Opportunity C
```

Each Opportunity is permanently preserved.

The Problem accumulates history through multiple Opportunities.

No Opportunity is modified after creation.

---

# Related Decisions

This ADR depends on:

- ADR-001 — Problem as Canonical Identity

This ADR enables:

- ADR-005 — Persistent Problem Memory
- ADR-006 — Lifecycle Decay
- ADR-007 — Weighted Canonical Matching

---

# References

Architecture Handbook

- 04_DATA_MODEL.md
- 05_PIPELINE_ARCHITECTURE.md
- 06_ARCHITECTURAL_INVARIANTS.md
- 08_MEMORY_ARCHITECTURE.md

Implementation Documentation

- docs/ARCHITECTURE.md
- docs/SCHEMA.md

---

# Status

Accepted.

Opportunity immutability is a foundational property of BIA's intelligence model and should be preserved by future implementations.
