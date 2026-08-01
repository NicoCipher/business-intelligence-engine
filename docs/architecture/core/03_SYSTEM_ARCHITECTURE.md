# System Architecture

Version: 1.0

Status: Canonical

---

# 1. Purpose

This document defines the logical architecture of BIA.

It specifies the responsibilities of each architectural component and the permitted flow of information between them.

Implementation details are intentionally excluded.

---

# 2. Architectural Goal

BIA transforms continuously changing public information into persistent business intelligence.

The architecture is designed to separate:

- observation
- knowledge
- understanding
- decision support

Each stage has a distinct responsibility.

---

# 3. Architectural Layers

The platform consists of six logical layers.

```
External World
        │
        ▼
Collection
        │
        ▼
Knowledge
        │
        ▼
Intelligence
        │
        ▼
Presentation
        │
        ▼
Consumers
```

Information flows downward.

Understanding flows upward.

---

# 4. Layer Responsibilities

## 4.1 Collection Layer

Responsible for acquiring observations.

Inputs include public information sources such as:

- Reddit
- Hacker News
- RSS feeds
- future collectors

Responsibilities:

- collect
- normalize
- deduplicate
- timestamp

Outputs:

Immutable Signals.

---

## 4.2 Knowledge Layer

Responsible for extracting structured information.

Responsibilities:

- entity extraction
- relationship extraction
- classification
- graph construction

Outputs:

Knowledge Graph.

---

## 4.3 Intelligence Layer

Responsible for interpretation.

Responsibilities:

- canonicalization
- problem identification
- opportunity detection
- scoring
- confidence evaluation
- historical accumulation

Outputs:

Decision-grade intelligence.

---

## 4.4 Presentation Layer

Responsible for communication.

Responsibilities:

- reports
- dashboards
- APIs
- future interfaces

This layer owns presentation only.

It never owns intelligence.

---

## 4.5 Consumer Layer

Consumers include:

- founders
- analysts
- autonomous agents
- external systems

Consumers never modify intelligence directly.

They consume published intelligence.

---

# 5. Core Objects

The architecture is centered around five persistent object types.

## Signal

Immutable observation.

Represents something that happened.

---

## Entity

Structured concept extracted from one or more Signals.

---

## Relationship

Connection between Entities.

Represents knowledge.

---

## Problem

Persistent market pain.

Primary long-lived intelligence object.

---

## Opportunity

Time-bound commercial assessment of a Problem.

Derived object.

---

# 6. Information Flow

Information always progresses in the following direction.

```
Signal
    ↓
Entity
    ↓
Relationship
    ↓
Problem
    ↓
Opportunity
    ↓
Report
```

Higher layers may reference lower layers.

Lower layers never depend on higher layers.

---

# 7. Architectural Boundaries

Each layer owns exactly one responsibility.

Collection does not score.

Knowledge does not recommend.

Problems do not generate reports.

Reports do not become memory.

Violating these boundaries introduces architectural debt.

---

# 8. Persistence

The architecture distinguishes between permanent and transient objects.

Permanent:

- Signals
- Entities
- Relationships
- Problems

Transient:

- Opportunities
- Reports

Persistent intelligence accumulates.

Transient artifacts communicate it.

---

# 9. Extensibility

New functionality should be introduced by extending existing layers rather than creating parallel architectures.

Examples include:

- additional collectors
- additional domains
- additional report generators
- future autonomous agents

Extension must preserve architectural boundaries.

---

# 10. Failure Isolation

Failure within one layer must not corrupt another.

Examples:

- a failed collector must not corrupt the Knowledge Graph
- a reporting failure must not modify intelligence
- presentation failures must not affect persistence

Each layer must degrade independently.

---

# 11. Architectural Stability

The logical architecture is expected to remain stable even as implementation evolves.

Individual technologies, algorithms, and storage mechanisms may change.

The architectural responsibilities defined here should not.

---

# 12. Authority

This document defines the structural organization of BIA.

Every subsystem, module, migration, and future service must conform to these architectural boundaries.
