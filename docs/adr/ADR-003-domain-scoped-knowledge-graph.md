# ADR-003 — Domain-Scoped Knowledge Graph

Version: 1.0

Status: Accepted

Date: 2026-08-01

Supersedes: None

---

# Context

BIA is designed as a general intelligence platform rather than a single-domain application.

Early prototypes focused exclusively on business intelligence.

As the platform evolved, additional domains became desirable, including:

- Cybersecurity
- Finance
- Healthcare
- Technology
- Research

The knowledge representation therefore needed to support multiple domains without fragmenting the intelligence engine.

---

# Problem

A single global knowledge graph appears simple but introduces several long-term problems.

Different domains often reuse identical terminology while assigning different meanings.

Examples include:

- Risk
- Exposure
- Asset
- Incident
- Signal

Without domain isolation, unrelated intelligence becomes interconnected, reducing confidence and increasing false relationships.

The platform therefore requires a mechanism for separating domain knowledge while preserving a unified intelligence engine.

---

# Decision

The knowledge graph is partitioned by domain.

Every entity and relationship belongs to exactly one domain.

The intelligence engine remains domain-agnostic.

Domains define:

- collection sources
- extraction rules
- scoring profiles
- entity types
- relationship types
- reporting behavior

The core engine coordinates intelligence across domains without embedding domain-specific logic.

---

# Rationale

Domain partitioning provides:

- semantic isolation
- independent evolution
- reusable intelligence engine
- simplified reasoning
- safer canonicalization
- extensibility through plugins

This allows BIA to expand into new domains without architectural redesign.

---

# Alternatives Considered

## Alternative 1 — Single Global Knowledge Graph

Rejected.

A shared graph increases accidental relationships between unrelated concepts.

Entity resolution becomes increasingly unreliable as domains grow.

---

## Alternative 2 — Separate Intelligence Engines

Rejected.

Duplicating the engine for every domain would fragment development and create unnecessary maintenance burden.

The reasoning process remains identical across domains.

Only domain knowledge differs.

---

## Alternative 3 — Domain-Scoped Knowledge Graph

Accepted.

A shared intelligence engine combined with isolated domain knowledge provides the strongest balance between extensibility and consistency.

---

# Consequences

Positive consequences include:

- independent domain evolution
- reusable intelligence engine
- simplified plugin architecture
- reduced semantic collisions
- safer entity resolution
- improved maintainability

Trade-offs include:

- additional domain metadata
- domain-aware canonicalization
- explicit domain registration

These costs are accepted.

---

# Architectural Impact

This decision directly enables:

- Domain Architecture
- Plugin Architecture
- Domain Registry
- Multi-domain collection
- Domain-specific scoring
- Future cross-domain intelligence

Without domain isolation, future expansion would require substantial architectural redesign.

---

# Implementation

The implementation associates intelligence objects with a domain.

Examples include:

- Entities
- Relationships
- Problems
- Opportunities
- Reports

Collectors operate within a domain.

Canonicalization is performed within the same domain unless future cross-domain reasoning explicitly permits otherwise.

---

# Future Considerations

Future versions of BIA may support controlled cross-domain intelligence.

Examples include:

- cybersecurity affecting finance
- regulation affecting healthcare
- technology affecting business

Cross-domain reasoning should occur through explicit architectural mechanisms rather than implicit graph connections.

Domain isolation remains the default behavior.

---

# Related Decisions

This ADR supports:

- ADR-001 — Problem as Canonical Identity
- ADR-002 — Opportunity Immutability

This ADR enables:

- Plugin Architecture
- Domain Registry
- Multi-domain Intelligence

---

# References

Architecture Handbook

- 03_SYSTEM_ARCHITECTURE.md
- 04_DATA_MODEL.md
- 12_DOMAIN_ARCHITECTURE.md
- 14_PLUGIN_ARCHITECTURE.md

Implementation Documentation

- docs/ARCHITECTURE.md

---

# Status

Accepted.

Domain-scoped knowledge is a foundational architectural property of BIA.

Future domains should extend the platform through published domain contracts rather than modifying the intelligence engine itself.
