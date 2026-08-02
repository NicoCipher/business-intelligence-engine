# Architecture Decision Records

Version: 1.0

Status: Canonical

---

# Purpose

Architecture Decision Records (ADRs) document significant engineering decisions made during the evolution of BIA.

The Architecture Handbook defines the principles governing the platform.

ADRs explain why specific architectural decisions were made.

They preserve engineering context that would otherwise be lost over time.

---

# Philosophy

Architecture describes what the platform is.

ADRs describe how it became that way.

Every significant architectural decision should have a permanent historical record.

---

# Relationship to the Architecture Handbook

The Architecture Handbook contains timeless architectural principles.

Architecture Decision Records capture individual decisions made while implementing those principles.

The handbook answers:

> What is the architecture?

ADRs answer:

> Why was this design chosen instead of the alternatives?

---

# When to Create an ADR

An ADR should be created whenever a change significantly affects:

- architecture
- persistence
- intelligence
- memory
- canonicalization
- pipeline behavior
- public interfaces
- extension mechanisms

Routine implementation changes do not require ADRs.

---

# ADR Lifecycle

Every ADR follows the same lifecycle.

```
Proposal

↓

Review

↓

Accepted

↓

Implemented

↓

Referenced

↓

Historical Record
```

Accepted ADRs should never be rewritten.

If architecture changes later, a new ADR supersedes the previous one.

Historical decisions remain preserved.

---

# ADR Structure

Each ADR should include:

1. Title
2. Status
3. Context
4. Problem
5. Decision
6. Alternatives Considered
7. Consequences
8. Implementation Notes
9. References

---

# Numbering

ADRs use sequential numbering.

Example:

```
ADR-001
ADR-002
ADR-003
```

Numbers are never reused.

Withdrawn ADRs remain part of the historical record.

---

# Current ADR Index

| ADR | Title | Status |
|------|-------|--------|
| ADR-001 | Problem as Canonical Identity | Accepted |
| ADR-002 | Opportunity Immutability | Accepted |
| ADR-003 | Domain-Scoped Knowledge Graph | Accepted |
| ADR-004 | False Positive Gate | Accepted |
| ADR-005 | Persistent Problem Memory | Accepted |
| ADR-006 | Lifecycle Decay | Superseded by ADR-008, ADR-010 |
| ADR-007 | Weighted Canonical Matching | Superseded by ADR-009 |
| ADR-008 | Entity & Relationship Lifecycle Decay | Accepted |
| ADR-009 | Weighted Canonical Matching (Corrected) | Accepted |
| ADR-010 | Problem Lifecycle & Trend | Accepted |

ADR-006 and ADR-007 conflated Problem-level and Entity/Relationship-level
lifecycle concepts under the wrong subject. Per this directory's own
rule against rewriting accepted ADRs, both were left unedited (aside from
a superseded-status banner) as the historical record of the original
framing — ADR-008/009/010 are the corrected, accurate versions.

Additional ADRs should be appended sequentially.

---

# Authority

This directory preserves the engineering history of BIA.

Future contributors should consult relevant ADRs before proposing architectural changes that affect existing decisions.
