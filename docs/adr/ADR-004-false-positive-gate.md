# ADR-004 — False Positive Gate

Version: 1.0

Status: Accepted

Date: 2026-08-01

Supersedes: None

---

# Context

The primary objective of BIA is not to maximize the number of detected opportunities.

Its objective is to maximize the quality of intelligence.

Early experimentation demonstrated that increasing sensitivity produced significantly more false positives.

Although recall improved, user trust declined because low-quality intelligence became indistinguishable from high-quality intelligence.

The platform therefore required an explicit architectural decision regarding the balance between precision and recall.

---

# Problem

An intelligence platform continuously receives incomplete, noisy, and ambiguous information.

Without explicit validation, weak evidence may produce convincing but incorrect conclusions.

False positives have several consequences:

- wasted investigation
- reduced confidence
- duplicated intelligence
- misleading reports
- degraded prediction quality
- erosion of user trust

The system therefore requires a mechanism that prevents weak evidence from becoming trusted intelligence.

---

# Decision

BIA prioritizes precision over recall.

Evidence must satisfy validation requirements before it is promoted into trusted intelligence.

The engine intentionally prefers:

- missing a weak opportunity

over

- presenting a false opportunity as credible intelligence.

---

# Rationale

False negatives can often be recovered through future observations.

False positives become part of the intelligence history and influence future reasoning.

Reducing false positives therefore produces higher long-term intelligence quality than maximizing short-term detection volume.

Trust is considered a core architectural asset.

---

# Alternatives Considered

## Alternative 1 — Maximize Recall

Rejected.

Generating every possible opportunity produces excessive noise.

Users must perform manual filtering.

Confidence becomes difficult to interpret.

---

## Alternative 2 — Confidence-Only Ranking

Rejected.

Ranking weak intelligence lower still allows poor-quality observations to enter the intelligence system.

The architecture requires a validation boundary rather than relying solely on ranking.

---

## Alternative 3 — Validation Gate

Accepted.

Evidence must reach a minimum quality threshold before becoming trusted intelligence.

The gate protects downstream systems from unreliable conclusions.

---

# Consequences

Positive consequences include:

- higher intelligence quality
- improved user trust
- cleaner historical memory
- stronger prediction inputs
- more reliable validation

Trade-offs include:

- lower recall
- delayed opportunity detection
- additional validation work

These trade-offs are accepted.

---

# Architectural Impact

This decision directly supports:

- Validation Intelligence
- Prediction Intelligence
- Persistent Memory
- Confidence Evolution
- Explainable Intelligence

Future validation models should strengthen this principle rather than weaken it.

---

# Implementation

Current implementations apply confidence scoring and canonical matching before producing Opportunities.

Future versions may introduce additional validation mechanisms, including:

- evidence quality assessment
- source reliability scoring
- contradiction detection
- temporal consistency validation
- human verification workflows

These mechanisms extend the validation gate rather than replacing it.

---

# Related Decisions

Depends on:

- ADR-001 — Problem as Canonical Identity
- ADR-002 — Opportunity Immutability

Supports:

- ADR-005 — Persistent Problem Memory
- Validation Intelligence
- Prediction Intelligence

---

# References

Architecture Handbook

- 01_ENGINE_PHILOSOPHY.md
- 02_INTELLIGENCE_PRINCIPLES.md
- 06_ARCHITECTURAL_INVARIANTS.md
- 09_VALIDATION_INTELLIGENCE.md

Implementation Documentation

- docs/ARCHITECTURE.md

---

# Status

Accepted.

The False Positive Gate is a permanent architectural principle of BIA.

Future implementations may improve validation mechanisms but should continue to prioritize trustworthy intelligence over maximum detection volume.
