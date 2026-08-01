# Pipeline Architecture

Version: 1.0

Status: Canonical

---

# 1. Purpose

This document defines the intelligence pipeline of BIA.

The pipeline describes how external observations become decision-grade intelligence.

It specifies the logical execution order.

It does not prescribe implementation details.

---

# 2. Objectives

The pipeline exists to satisfy five objectives.

1. Collect information continuously.

2. Preserve every observation.

3. Transform observations into structured knowledge.

4. Produce explainable intelligence.

5. Improve accumulated understanding over time.

---

# 3. Pipeline Overview

Every execution follows the same logical sequence.

```
Collection

↓

Normalization

↓

Extraction

↓

Knowledge Construction

↓

Canonicalization

↓

Opportunity Detection

↓

Scoring

↓

Explanation

↓

Persistence

↓

Publication
```

Every stage consumes the output of the previous stage.

No stage may be skipped.

---

# 4. Collection

Collection acquires observations from external systems.

Responsibilities include:

- source communication
- acquisition
- timestamping
- source attribution

Collection produces immutable Signals.

Collection performs no reasoning.

---

# 5. Normalization

Normalization converts heterogeneous data into a common internal representation.

Responsibilities include:

- field normalization
- duplicate detection
- source consistency
- validation

Normalization reduces structural differences.

It does not change meaning.

---

# 6. Knowledge Extraction

Knowledge extraction converts Signals into structured knowledge.

Responsibilities include:

- entity extraction
- relationship extraction
- classification

The result is a normalized representation of market knowledge.

---

# 7. Knowledge Construction

Extracted knowledge becomes part of the persistent Knowledge Graph.

Responsibilities include:

- entity resolution
- relationship creation
- evidence attachment
- graph persistence

Knowledge accumulates across executions.

---

# 8. Canonicalization

Canonicalization determines whether newly observed knowledge belongs to an existing Problem.

Responsibilities include:

- similarity evaluation
- identity resolution
- historical linkage

Canonicalization preserves continuity across differently worded observations.

Identity is concept-based rather than title-based.

---

# 9. Opportunity Detection

Opportunity detection evaluates whether accumulated evidence indicates commercial potential.

Responsibilities include:

- problem evaluation
- opportunity creation
- opportunity updates

Detection creates dated commercial assessments.

It does not modify historical observations.

---

# 10. Scoring

Scoring evaluates Opportunities using deterministic criteria.

Scoring produces structured assessments.

Scores must always remain reproducible from available evidence.

Scoring never creates evidence.

---

# 11. Explanation

Explanation converts structured intelligence into human-readable reasoning.

Responsibilities include:

- recommendations
- summaries
- confidence explanation
- evidence narration

Explanation communicates intelligence.

It never creates intelligence.

---

# 12. Persistence

Persistence stores every durable object.

Persistent objects include:

- Signals
- Entities
- Relationships
- Problems
- Opportunities

Persistence preserves historical continuity across executions.

---

# 13. Publication

Publication exposes intelligence to consumers.

Publication mechanisms may include:

- reports
- APIs
- dashboards
- future agent interfaces

Publication owns presentation only.

---

# 14. Pipeline Properties

Every pipeline execution must satisfy the following properties.

## Deterministic

Given identical inputs, equivalent intelligence should be produced.

---

## Incremental

Each execution builds upon previous executions.

The pipeline never starts from zero.

---

## Traceable

Every recommendation must remain traceable to supporting Signals.

---

## Idempotent

Reprocessing identical observations should not create duplicate intelligence.

---

## Recoverable

Failures should affect only incomplete executions.

Previously accumulated intelligence must remain valid.

---

# 15. Future Evolution

Future pipeline stages may include:

- validation intelligence
- prediction
- evidence weighting
- indicator generation
- autonomous planning

These extend the pipeline.

They do not replace its existing stages.

---

# 16. Authority

This document defines the canonical intelligence pipeline of BIA.

Every collector, extractor, intelligence engine, scheduler, report generator, and future autonomous execution engine must preserve the execution model defined here.
