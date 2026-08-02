# ADR-007 — Weighted Canonical Matching

Version: 1.0

Status: Accepted

Date: 2026-08-01

Supersedes: None

---

# Context

Canonical matching determines whether newly observed intelligence represents:

- an existing Problem

or

- a genuinely new Problem.

Early implementations treated every historical Problem equally during matching.

As the knowledge base expanded, long-dormant Problems increasingly competed with active intelligence.

This caused stale historical knowledge to influence present-day identity resolution more strongly than intended.

The platform therefore required canonical matching that considered operational relevance without discarding historical knowledge.

---

# Problem

Historical intelligence should remain available for reasoning.

However, historical intelligence should not always influence identity resolution with the same strength as recently observed intelligence.

Without weighting:

- dormant Problems compete equally with active Problems
- canonical matching becomes less precise
- historical drift increases
- stale intelligence may incorrectly absorb new observations

The architecture therefore requires relevance-aware identity resolution.

---

# Decision

Canonical matching uses lifecycle-aware weighting.

Historical Problems remain eligible for matching.

Their influence varies according to lifecycle state rather than remaining constant.

Operational relevance influences matching.

Historical existence does not guarantee equal matching strength.

---

# Rationale

Lifecycle state represents current operational confidence.

Historical memory represents accumulated intelligence.

These are intentionally independent concepts.

A dormant Problem still exists.

It simply contributes less evidence during canonical resolution than an actively evolving Problem.

If sufficient evidence appears again, the dormant Problem is reactivated rather than recreated.

---

# Alternatives Considered

## Alternative 1 — Equal Matching Weight

Rejected.

Every historical Problem permanently influences matching regardless of operational relevance.

This gradually reduces matching quality as memory grows.

---

## Alternative 2 — Ignore Dormant Problems

Rejected.

Historical intelligence would effectively disappear from canonical reasoning.

Recurring Problems would fragment into duplicate identities.

---

## Alternative 3 — Lifecycle-Weighted Matching

Accepted.

Historical Problems remain available while allowing operational relevance to influence identity resolution.

This balances historical continuity with present-day accuracy.

---

# Consequences

Positive consequences include:

- improved canonical precision
- reduced stale matches
- preserved historical continuity
- natural Problem reactivation
- scalable long-term memory

Trade-offs include:

- additional weighting logic
- lifecycle-aware similarity calculations
- configurable thresholds

These trade-offs are accepted.

---

# Architectural Impact

Weighted canonical matching directly supports:

- Persistent Problem Memory
- Lifecycle Decay
- Validation Intelligence
- Prediction Intelligence

Identity resolution becomes both historically aware and operationally relevant.

---

# Implementation

The implementation combines:

- canonical similarity
- lifecycle state
- operational weighting

Lifecycle weighting modifies matching strength.

It does not modify historical memory.

Unknown identities default to full weighting to preserve backward compatibility.

---

# Future Evolution

Future implementations may incorporate additional weighting signals including:

- source reliability
- evidence quality
- contradiction history
- validation outcomes
- prediction accuracy
- customer feedback

These signals extend weighting.

They do not replace canonical identity.

---

# Related Decisions

Depends on:

- ADR-001 — Problem as Canonical Identity
- ADR-005 — Persistent Problem Memory
- ADR-006 — Lifecycle Decay

Supports:

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

Weighted Canonical Matching preserves one of BIA's central architectural principles:

Historical intelligence should remain available indefinitely, while operational relevance determines how strongly that intelligence participates in present-day reasoning.
