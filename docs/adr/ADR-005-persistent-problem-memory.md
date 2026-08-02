# ADR-005 — Persistent Problem Memory

Version: 1.0

Status: Accepted

Date: 2026-08-01

Supersedes: None

---

# Context

Intelligence improves through accumulated understanding rather than isolated observations.

Early versions of BIA evaluated every collection cycle independently.

Although individual analyses were often correct, the platform repeatedly rediscovered the same underlying Problems because previous intelligence was not retained as first-class knowledge.

This limited trend analysis, confidence evolution, lifecycle reasoning, and prediction.

A persistent memory model was therefore required.

---

# Problem

Without long-term memory the intelligence engine cannot distinguish between:

- a newly emerging Problem
- a recurring Problem
- a continuously evolving Problem

Each pipeline execution becomes an isolated event.

Historical evidence is repeatedly reconstructed rather than accumulated.

This prevents the platform from behaving as a continuously learning intelligence system.

---

# Decision

Persistent memory belongs to the **Problem**.

Problems accumulate intelligence throughout their lifetime.

Memory is append-only.

Historical evidence is preserved rather than replaced.

Every new observation extends the existing intelligence record.

---

# Rationale

The Problem is the only object that represents a continuous real-world issue.

Signals describe observations.

Opportunities describe assessments.

Reports describe outputs.

Only the Problem exists long enough to accumulate institutional knowledge.

Persistent memory therefore naturally belongs to the Problem.

---

# Memory Model

Problem memory accumulates information including:

- first observed
- last observed
- recurrence history
- score evolution
- evidence history
- source history
- confidence evolution
- customer observations
- lifecycle state

Future memory layers may extend this information without replacing existing history.

---

# Alternatives Considered

## Alternative 1 — Stateless Analysis

Rejected.

Each pipeline execution begins from zero.

Historical learning becomes impossible.

Prediction quality remains limited.

---

## Alternative 2 — Opportunity Memory

Rejected.

Opportunities are immutable historical observations.

Attaching evolving memory to Opportunities duplicates intelligence and fragments history.

---

## Alternative 3 — Problem Memory

Accepted.

Problems provide a stable identity capable of accumulating long-term intelligence across multiple observations.

---

# Consequences

Positive consequences include:

- cumulative intelligence
- historical reasoning
- confidence evolution
- lifecycle analysis
- recurring pattern detection
- future prediction
- institutional memory

Trade-offs include:

- additional storage
- memory maintenance
- canonical matching complexity
- migration requirements

These costs are accepted because long-term intelligence is the primary objective of the platform.

---

# Architectural Impact

Persistent Problem Memory directly enables:

- Lifecycle Decay
- Validation Intelligence
- Prediction Intelligence
- Agent reasoning
- Historical explainability

Future capabilities should build upon existing memory rather than introducing parallel memory systems.

---

# Implementation

Current implementations maintain persistent Problem memory through accumulated metadata and historical observations.

Examples include:

- weeks_seen
- first_seen
- last_seen
- entity associations
- historical Opportunities

Future implementations may introduce dedicated append-only memory tables while preserving the same architectural model.

---

# Future Evolution

Persistent memory is expected to expand over time.

Possible future additions include:

- entity lifecycle history
- relationship lifecycle history
- contradiction history
- validation outcomes
- prediction accuracy history
- reasoning lineage

These additions extend memory rather than replacing existing records.

---

# Related Decisions

Depends on:

- ADR-001 — Problem as Canonical Identity
- ADR-002 — Opportunity Immutability

Supports:

- ADR-006 — Lifecycle Decay
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

Persistent Problem Memory is a foundational architectural capability of BIA.

Future intelligence should emerge through the accumulation of memory rather than repeated rediscovery of existing knowledge.
