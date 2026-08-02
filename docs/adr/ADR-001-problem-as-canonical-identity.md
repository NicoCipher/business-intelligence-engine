# ADR-001 — Problem as Canonical Identity

Version: 1.0

Status: Accepted

Date: 2026-08-01

---

# Context

BIA transforms raw observations into long-term intelligence.

During the initial architecture, several candidate objects were considered as the primary identity of the system.

Candidates included:

- Signal
- Entity
- Opportunity
- Problem

Selecting the wrong canonical identity would affect memory, lifecycle management, prediction, validation, reporting, and future agent behavior.

This decision establishes the permanent intelligence object upon which the rest of the platform is built.

---

# Problem

The platform requires a stable identity capable of representing an underlying real-world issue across multiple observations over time.

That identity must satisfy the following requirements.

- persist across pipeline executions
- accumulate historical evidence
- survive changing market conditions
- support lifecycle transitions
- support prediction
- support validation
- support multiple observations
- support explainable reasoning

No temporary observation should become the permanent identity of the intelligence system.

---

# Decision

**Problem** is the canonical identity of BIA.

Every detected opportunity is interpreted as evidence of an underlying Problem.

Problems persist.

Opportunities do not.

The intelligence engine reasons about Problems rather than individual observations.

---

# Rationale

Problems satisfy every architectural requirement.

A Problem can:

- accumulate evidence
- maintain historical memory
- evolve over time
- reactivate after dormancy
- support lifecycle analysis
- support confidence evolution
- support prediction
- support validation

Problems therefore become the long-lived representation of intelligence.

---

# Alternatives Considered

## Alternative 1 — Signal as Canonical Identity

Rejected.

Signals are immutable observations.

They represent facts rather than intelligence.

Signals cannot accumulate reasoning.

Signals cannot represent persistence.

---

## Alternative 2 — Opportunity as Canonical Identity

Rejected.

An Opportunity represents the engine's assessment at a specific point in time.

Multiple Opportunities may describe the same underlying Problem.

Making Opportunities canonical would duplicate intelligence and fragment historical memory.

---

## Alternative 3 — Entity as Canonical Identity

Rejected.

Entities represent concepts rather than problems.

A market, technology, or regulation is not itself an intelligence conclusion.

Entities provide evidence.

They do not represent decisions.

---

# Consequences

Positive consequences include:

- persistent intelligence
- append-only historical observations
- explainable decision history
- stable lifecycle management
- prediction across time
- validation across time
- reusable intelligence

Trade-offs include:

- canonical matching complexity
- memory management
- lifecycle management
- identity resolution

These complexities are accepted because they preserve long-term intelligence quality.

---

# Architectural Impact

This decision directly enables:

- Persistent Memory
- Lifecycle Decay
- Validation Intelligence
- Prediction Intelligence
- Agent Architecture

Changing this decision would require fundamental redesign of the intelligence engine.

---

# Implementation

The current implementation reflects this decision.

```
Signal

↓

Problem

↓

Opportunity

↓

Report
```

Signals remain immutable.

Problems evolve.

Opportunities are immutable historical observations linked to Problems.

Reports are generated artifacts.

---

# Related Decisions

This ADR establishes the foundation for:

- ADR-002 — Opportunity Immutability
- ADR-005 — Persistent Problem Memory
- ADR-006 — Lifecycle Decay
- ADR-007 — Weighted Canonical Matching

---

# References

Architecture Handbook

- 01_ENGINE_PHILOSOPHY.md
- 02_INTELLIGENCE_PRINCIPLES.md
- 04_DATA_MODEL.md
- 06_ARCHITECTURAL_INVARIANTS.md
- 08_MEMORY_ARCHITECTURE.md

Implementation Documentation

- docs/ARCHITECTURE.md
- docs/SCHEMA.md

---

# Status

Accepted.

This decision forms one of the foundational architectural assumptions of BIA.

Future architectural work should preserve this model unless superseded by a later ADR with explicit justification.
