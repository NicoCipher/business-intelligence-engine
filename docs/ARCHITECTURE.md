# Architecture (current — schema v7)

`README.md` describes "Version 1" as it was first scoped, and its
"Future modules" section still lists Knowledge Graph as unbuilt. That's
no longer accurate — this document describes what actually exists today.
Treat this file, not that section of the README, as current.

## Data model

```
Signal (immutable event, domain-scoped, dedup on source+source_id+domain)
   │
   ├─ collection: collectors/{hn,reddit,rss}_collector.py → collectors/base.py
   │
   ├─ extraction: knowledge_graph/extractor.py (EntityExtractor)
   │        │
   │        ▼
   │  Entity / Relationship (knowledge graph, domain-scoped — schema v5)
   │        │
   ▼        ▼
   canonical matching: opportunity_engine/canonicalizer.py
        (entity-Jaccard primary, title-Jaccard secondary support)
        │
        ▼
   Problem (stable, long-lived identity — schema v6)
        │
        ├─ persistent memory: problem_history (schema v7, append-only)
        │
        ▼  weekly detection + scoring: opportunity_engine/detector.py + scorer.py
   Opportunity (dated observation, immutable, linked via problem_id)
        │
        ▼  narrative generation: opportunity_engine/explainer.py
   Report (JSON snapshot, persisted to `reports` table)
```

**Problem, not Opportunity, is the canonical identity.** Opportunity
conflated four things — problem identity, customer segment, solution
angle, and dated observation. Problem now owns identity; Opportunity is
a dated, immutable observation that attaches to it via `problem_id`. See
`docs/SCHEMA.md`'s v6 entry and `canonicalizer.py`'s module docstring
for the full reasoning.

**Opportunity is immutable — one row per detection, never edited in
place.** This preserves the evidence trail (every judgment traces to a
specific observation) that's the system's core differentiator. History
of a *Problem* over time lives in `problem_history` (v7), not by
mutating old Opportunity rows.

**Products and Companies are explicitly out of scope.** BIA discovers
and scores opportunities from public discourse; it has never modeled
real companies with independent lifecycle. Kept as narrative-only
callouts (`founder_intelligence.existing_competitors`), not tables.

Orchestrated end-to-end by `pipeline.py::run_full_pipeline()` — the
single source of truth (`collect.py`/`main.py` both call it). Order
matters: `extractor.persist_results()` (populates the knowledge graph)
must run before `detector.detect_and_persist()` (which resolves entity
signatures and Problem matches via `canonicalizer.resolve_entity_ids()`
— that function only *looks up* already-persisted entities, it does not
extract or persist them itself). Calling `detect_and_persist()` without
first running entity persistence doesn't error — it silently degrades
to zero entity matches, so every opportunity looks new and Problems
never merge. This is a real footgun for anything other than the real
pipeline (ad-hoc scripts, future admin tools, tests) calling the
detector directly — see `PROBLEM_MEMORY_VALIDATION.md` for how this
surfaced during v7 validation.

Domain system (`domains/registry.py`) governs which domains are active.
`DomainRegistry` is the sole discovery/registration component — domains
must not self-register on import; each exports `DOMAIN_CONFIG` and
registration happens explicitly at startup. Only `business` has ever had
real data; `cybersecurity` is stubbed with no `DOMAIN_CONFIG`.

## Matching: deterministic, not semantic

Canonical Problem matching (`canonicalizer.find_match()`) uses
entity-Jaccard (primary) + title-Jaccard (secondary support) —
deliberately not embeddings. This was evaluated explicitly (see the
architecture RFC review) and rejected for now: embeddings would catch
paraphrase drift the keyword vocabulary misses, but at the cost of
non-determinism, a new vector-store dependency, and — the real cost — a
worse answer for a product whose differentiator is explainability
("these two share 4 of 6 entities" beats "0.83 cosine-similar"). Revisit
only with concrete evidence that vocabulary expansion can't close the
gap, and even then treat it as an *additional* signal with visible
evidence, never a black-box replacement.

Thresholds (`canonicalizer.py`): entity-Jaccard ≥ 0.5 alone, OR
entity-Jaccard > 0 AND title-Jaccard ≥ 0.5. Deliberately conservative —
a false merge corrupts accumulated history and is hard to undo; a false
split just self-corrects as more evidence accumulates. Practical
consequence, confirmed during v7 validation: two observations with
**zero shared extracted entities** never match, no matter how similar
their titles read to a human — the "or" branch's `entity > 0` condition
can't be satisfied by title overlap alone. Generic titles that don't
happen to contain any of `knowledge_graph/schema.py`'s `ENTITY_TYPES`
keywords will never canonically merge across weeks under the current
vocabulary. This is the known, explicitly-accepted limitation of
choosing deterministic matching over embeddings, not a bug — but it's
worth knowing the vocabulary's coverage is what actually gates
recognition, not title similarity.

## Persistent Problem memory (schema v7)

`Problem` stores only current state. `problem_history` stores the full
timeline as append-only events, written by `canonicalizer.resolve_problem()`
in the same transaction as the Problem row itself, so the two can never
diverge — verified directly (see `PROBLEM_MEMORY_VALIDATION.md`): a
simulated mid-write failure leaves neither a Problem nor a history row
behind, and connection-close semantics discard any uncommitted work even
when the failure isn't a `sqlite3.Error` (the only exception type
`database.get_connection()`'s explicit rollback branch catches).

Full event-type table and backfill details: `docs/SCHEMA.md`'s v7 entry.

## Explainability as an architectural constraint, not a feature

This shows up in multiple decisions above, not just the matching
algorithm: `DimensionExplanation` on the scorer, evidence-linked
Opportunities, human-readable match reasons in `find_match()`'s return
value, and the deterministic-over-semantic matching choice all trade
some capability for the property that every judgment traces to
something inspectable. Future work that would blur that (embeddings,
autonomous agent actions) should be treated as a deliberate, separately
evaluated trade-off — not something to back into as a side effect of an
unrelated feature.

## What's explicitly not built yet

Not a roadmap (see the handoff document for that) — just a list of
things sometimes assumed to exist that don't:
- No opportunity lifecycle state machine (Discovery/Validation/Growing/
  Mature/Declining/Archived) — `Problem` has no `status` field.
- No merge/split logic for Problems (`merged`/`split` event types exist
  in the v7 enum, reserved, unused).
- No evidence-quality weighting distinct from the scorer's composite
  formula.
- No multi-level relationship hierarchy (`belongs_to` is flat, one-hop).
- No multi-tenancy — no schema concept for it at all.
- No clean read-only query interface for future agents (Writer/Sales/
  Outreach/Analytics) — premature before the Problem/history model has
  had time to prove stable under real use.
