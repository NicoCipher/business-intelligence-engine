# BIA Project Handoff (updated — schema v7 milestone closed)

Supersedes the schema-v6-era handoff. Full architecture detail now lives
in `docs/ARCHITECTURE.md` (current state) and `docs/SCHEMA.md` (full
version history) — this file is the orientation summary, not the whole
picture.

## Part 1: Current System State

**Architecture:** see `docs/ARCHITECTURE.md` for the full diagram and
reasoning. Summary: `Signal → [extraction] → Entity/Relationship
(knowledge graph) → [canonical matching] → Problem (identity,
schema v6) → [persistent memory] → problem_history (schema v7) →
Opportunity (dated, immutable observation) → Report`.

**Completed milestones (chronological):**
1. M1–M4a: domain-agnostic pipeline foundation.
2. Reporting layer overhaul: scoring transparency, narrative explanation
   layer, Watch List, Founder Intelligence.
3. Six data-integrity bug fixes (pre-canonicalization era).
4. Intelligence-quality pass: false-positive gate, cross-week recurrence.
5. Full architecture review (Lead Architect framing).
6. Schema v5: domain-scoped knowledge graph.
7. Schema v6: canonical Problem identity (`problems` table,
   `canonicalizer.py`).
8. Three-part architecture RFC review (strategy/positioning, competitive
   analysis, analyst-tradecraft framing) — evaluated against the
   codebase, produced a per-topic Accept/Modify/Postpone/Reject verdict.
   Key outcomes: persistent memory as normalized `problem_history`
   table (not JSON arrays) — accepted with modification; hierarchy and
   embeddings — postponed; agent architecture — postponed until the
   data model proves stable; multi-tenancy schema hook — elevated in
   priority despite being "not urgent."
9. **Schema v7: persistent Problem memory.** `problem_history` table,
   `opportunity_engine/problem_history.py`, wired into
   `canonicalizer.resolve_problem()`. **Just completed, validated, and
   committed locally** (see Part 5).

**Current code state:** committed locally at `7e9a6c1` on top of
`ad95a3b`. **Not yet pushed to origin** — see Part 5 for why. 341/341
tests passing. Schema version 7. Working tree clean at time of commit.

**Active problems:** none known/open. Full validation report:
`docs/PROBLEM_MEMORY_VALIDATION.md` — covers the real end-to-end
pipeline check, migration verification against an authentic v6
database, and transaction-atomicity testing. Three non-blocking pieces
of debt were surfaced (documented there and in
`docs/ARCHITECTURE.md`'s "Matching" section): silent zero-entity
degradation when entity persistence is skipped, the vocabulary-coverage
limitation of deterministic matching (now empirically demonstrated, not
just theorized), and `detect_and_persist()`'s batch-level (not
per-opportunity) commit granularity.

## Part 2: Product Vision

Unchanged from the prior handoff — see the original for the full
target-ecosystem diagram (`Market Intelligence → Opportunity
Intelligence → Founder Intelligence → Writer/Sales/Outreach/Analytics
Agents`). The three-part RFC review reaffirmed this direction while
explicitly postponing the agent-architecture design work until the
Problem/history data model has had time to prove stable under real use
— agent interfaces designed against a schema that's still changing tend
to get thrown away, not reused.

## Part 3: Architecture Decisions (new since the v6 handoff)

**Decision: `problem_history` is a normalized table, not JSON arrays on
`problems`.** This was the one place the RFC review pushed back hardest
on the originally-proposed shape. Arrays-on-row would mean rewriting an
ever-larger blob on every match, no per-event querying, and unbounded
row growth over years of weekly runs. Cost: one extra table, one join.
Benefit: real scalability, indexable, prunable.

**Decision: `Problem` keeps storing only current state; it never grows
history fields.** Discipline decision, not a technical constraint — the
risk flagged during the RFC review was scope creep, where score/evidence
fields slowly migrate onto `Problem` and it becomes a second mutable
record with two names. `resolve_problem()`'s two write paths (create,
match) intentionally touch only `entity_ids`/`last_seen`/`weeks_seen` on
`Problem` itself; everything else about "what happened" goes to
`problem_history`.

**Decision: four of six history event types are reserved, unused.**
`confidence_updated`, `status_changed`, `merged`, `split` are valid
per `models.VALID_HISTORY_EVENT_TYPES` but nothing writes them —
`Problem` has no `status` field and no merge/split logic exists. Defined
now so the event-type column doesn't need another migration when
lifecycle work lands; explicitly not a signal that those features exist.

**Decision: matching stays deterministic (entity + title Jaccard), no
embeddings.** Reaffirmed by the RFC review, not revisited during v7.
Full reasoning in `docs/ARCHITECTURE.md`'s "Matching" section, including
the now-empirically-confirmed practical consequence: zero shared
extracted entities means zero match, regardless of title similarity.

**Decision: `detect_and_persist()`'s commit granularity is left as-is.**
Considered during v7's atomicity review, not changed. Batch-level commit
(one commit after the whole opportunity loop, not per-opportunity) means
one bad opportunity currently blocks the rest of that batch from
persisting. Real trade-off, not obviously wrong, and changing it is a
separate, larger decision (partial-batch persistence semantics) — not
bundled into this milestone.

## Part 4: Future Roadmap

Per the RFC review's reprioritization (supersedes the pre-RFC ordering):

1. ~~Domain-scope knowledge graph~~ — done (v5).
2. ~~`problems` table + canonical matching~~ — done (v6).
3. ~~Persistent memory~~ — **done (v7), this milestone.**
4. **Time-decay on the knowledge graph** — elevated during the RFC
   review from "not listed" to next priority, ahead of hierarchy. Cheap
   now (a last-referenced timestamp + periodic soft-archive pass); a
   graph that only grows will quietly degrade match quality and query
   performance over years of weekly runs if nothing ages out.
5. **Opportunity lifecycle** state machine (Discovery → Validation →
   Growing → Mature → Declining → Archived) — depends on step 3
   (now real) to derive transitions from actual evidence history, not
   arbitrary thresholds. Explain transition logic before implementing,
   per standing instruction.
6. **Evidence-quality weighting** — as a separate signal informing
   confidence/verdict, not a rewrite of the scorer's composite formula.
7. Relationship hierarchy (multi-level `belongs_to`) — explicitly
   postponed by the RFC review; not enough real multi-hop data yet to
   know what depth is actually useful. Building it now risks a
   premature, likely-wrong abstraction.
8. `explainer.py` split (~60KB, five-plus responsibilities) — code debt,
   grows harder to split the longer it's deferred, still not urgent.
9. Duplicated keyword-scanning logic across `scorer.py`/`extractor.py`/
   `explainer.py` — consolidation candidate.
10. Multi-tenancy schema hook — RFC review flagged this as
    cheap-now/expensive-later even though "not urgent"; worth a small
    decision before Problem/Opportunity/history tables are full of real
    data, not a v10 migration project later.
11. Clean read-only query interface for future agents — design once the
    Problem/canonical data model has had more time to prove stable.
12. Market Intelligence, Writer/Sales/Outreach/Analytics agents
    themselves — explicitly out of scope until item 11 exists.

**Frontend note (from the RFC review, worth restating):** the
originally-planned "backend done → build Next.js frontend" ordering was
challenged — Problem Memory is the highest-leverage screen the frontend
will show, and it's only as good as the history data behind it. Now that
v7 is real, frontend scaffolding/design-system work can start in
parallel with item 4 above, but the Problem Memory screen specifically
should wait until there's real accumulated history to design against,
not be built thin against v7 on day one.

## Part 5: Current Session Context

**What happened this session:** implemented, validated, and locally
committed schema v7 end-to-end. Full validation detail:
`docs/PROBLEM_MEMORY_VALIDATION.md`.

**Not yet pushed to origin, and here's exactly why:** two GitHub
Personal Access Tokens were pasted directly into the chat during this
session. Both were treated as compromised the moment they appeared in
plaintext (regardless of whether they were ever actually used) and were
not committed anywhere or written to any file in this repo. **Whoever
picks this up next should confirm both tokens have been revoked at
https://github.com/settings/tokens before generating a new one and
pushing `7e9a6c1`.** This is a process note, not a code issue — nothing
about it affects the v7 implementation itself.

**Next steps:** once pushed, the next substantive work is Part 4, item
4 (knowledge-graph time-decay) — small, cheap, and ahead of hierarchy
work in the reprioritized order. Recommend starting the next session by
reading `docs/ARCHITECTURE.md` in full (it's the current-state doc now,
not the README) plus `knowledge_graph/extractor.py`'s `persist_results()`
and whatever currently reads `entities`/`relationships` by recency, since
decay will most likely be a last-referenced timestamp plus a periodic
soft-archive query against those two tables.
