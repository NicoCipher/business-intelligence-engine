# Intelligence Principles

Version: 1.0

Status: Canonical

---

# 1. Purpose

This document defines the principles that govern intelligence production within BIA.

These principles apply to every subsystem responsible for collecting, processing, evaluating, storing, or presenting information.

Unlike implementation rules, these principles describe *how intelligence is created* rather than *how software is written*.

---

# 2. Intelligence Lifecycle

Every piece of intelligence progresses through a fixed sequence.

```
Observation
    ↓
Signal
    ↓
Knowledge
    ↓
Problem
    ↓
Opportunity
    ↓
Decision Intelligence
```

No stage may be skipped.

Every stage must preserve traceability to the previous one.

---

# 3. Signals

Signals are immutable observations collected from external sources.

Signals are facts.

Signals are never conclusions.

Examples include:

- Reddit discussions
- Hacker News posts
- RSS articles
- future public data sources

Signals represent what happened.

They do not represent what BIA believes.

---

# 4. Knowledge

Knowledge is structured information extracted from signals.

Knowledge consists of:

- entities
- relationships
- classifications

Knowledge reduces ambiguity without introducing judgment.

---

# 5. Problems

Problems represent persistent market pain.

A Problem is not created because an opportunity exists.

A Problem exists independently of any proposed solution.

Multiple observations may strengthen confidence in the same Problem.

Problems accumulate evidence throughout their lifetime.

---

# 6. Opportunities

An Opportunity is a dated assessment that a Problem may be commercially valuable.

Unlike Problems:

- Opportunities expire.
- Opportunities change.
- Opportunities may disappear.

Problems persist.

---

# 7. Intelligence

Intelligence is not information.

Intelligence is the interpretation of accumulated evidence.

Intelligence requires:

- history
- comparison
- recurrence
- evaluation

Without accumulated evidence, only information exists.

---

# 8. Confidence

Confidence measures evidence quality.

Confidence does not measure certainty.

Increasing confidence requires:

- additional observations
- stronger evidence
- repeated validation
- corroboration across sources

Confidence must never increase solely because time has passed.

---

# 9. Recurrence

Recurrence strengthens intelligence.

Repeated observations of the same Problem increase confidence that the Problem is genuine.

Recurrence alone does not guarantee commercial opportunity.

It increases belief in the existence of the Problem.

---

# 10. Evidence Quality

Not all evidence contributes equally.

Future scoring systems should distinguish between:

- discussion
- complaint
- purchasing intent
- implementation attempts
- revenue signals
- market validation

Evidence quality is expected to become a primary driver of confidence.

---

# 11. Historical Integrity

Historical observations are permanent.

Corrections append new evidence.

They do not rewrite previous evidence.

This preserves:

- auditability
- reproducibility
- intelligence evolution

---

# 12. Decision Intelligence

The objective of BIA is not prediction.

The objective is improved decision making.

Every recommendation should reduce uncertainty for a founder.

Recommendations must communicate:

- supporting evidence
- uncertainty
- assumptions
- limitations

---

# 13. Architectural Consequences

These principles require:

- immutable Signals
- persistent Problems
- historical memory
- explainable scoring
- reproducible recommendations
- evidence-backed confidence

Future implementations must preserve these properties.

---

# 14. Authority

This document defines the intelligence model of BIA.

All future scoring systems, validation systems, memory systems, prediction systems, and autonomous agents inherit these principles.
