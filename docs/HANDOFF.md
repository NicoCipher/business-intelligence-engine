# BIA Project Handoff (updated — schema v7 milestone closed)

Supersedes the schema-v6-era handoff. Full architecture detail now lives
in `docs/ARCHITECTURE.md` (current state) and `docs/SCHEMA.md` (full
version history) — this file is the orientation summary, not the whole
picture.

## Part 1: Current System State

**Architecture:** see `docs/ARCHITECTURE.md` for the full diagram and
reasoning. Summary: `Signal → [extraction] → Entity/Relationship
(knowledge graph, schema v8 decay) → [canonical matching] → Problem
(identity, schema v6; lifecycle_state/trend, schema v9) →
[persistent memory] → problem_history (schema v7) → Opportunity (dated,
immutable observation) → Report`.

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
9. Schema v7: persistent Problem memory (`problem_history` table,
   `opportunity_engine/problem_history.py`).
10. **CI investigation, three separate pushes**: found and fixed the
    same DDL-ordering bug class three times over — `_SCHEMA_DDL` runs
    unconditionally on every `initialize()` call, before any migration,
    so any index referencing a migration-added column crashes any
    database older than that migration. Fixed for
    `idx_entities_domain`/`idx_rel_domain` (v5 boundary), then
    `idx_signals_dedup`/`idx_opp_problem`/`idx_reports_week_domain` (v2
    and v6 boundaries) in one comprehensive audit, which itself
    surfaced a second bug class (index creation nested inside a
    column-existence guard means it silently never runs on a *fresh*
    database) — found by the audit's own new regression tests, not by
    a reported error. Full detail:
    `docs/PROBLEM_MEMORY_VALIDATION.md` and the `d26e891`/`bbf0722`
    commit messages.
11. Schema v8: knowledge-graph decay. `lifecycle_state` on
    `entities`/`relationships` (active → dormant → archived, never
    deleted, reversible on new evidence), lifecycle-weighted canonical
    matching, decay pass wired into the pipeline as Stage 2.5.
12. Merged an externally-authored architecture handbook
    (`docs/architecture/`) that landed on `origin/main` mid-session,
    then reconciled three points of drift between it and the actual
    implementation (a broken filename cross-reference, an
    `Opportunity`-immutability contradiction, and a lifecycle-history
    ambiguity) — see that commit's message for detail.
13. **Schema v9: Problem lifecycle & trend.** Two independent current-state
    axes (`lifecycle_state`: new/active/dormant/archived/reactivated;
    `trend`: unknown/growing/stable/declining) rather than one combined
    state — the first design used a single field and was fully replaced,
    before shipping, once a design review made the state-explosion cost
    concrete. **Just completed, validated, and committed locally** (see
    Part 5).

**Current code state:** `origin/main` at `50c75ac` (schema v8 +
handbook reconciliation, both pushed), plus schema v9 work committed on
top locally (not yet pushed — see Part 5). 467/467 tests passing.
Schema version 9.

**Active problems:** none known/open. Every DDL-ordering-class bug found
during the CI investigation is fixed and has dedicated regression
coverage (`test_migration_v5.py`, `test_migration_v6_upgrade.py`,
`test_migration_v8.py`, `test_migration_v9.py`) that specifically
exercises both failure modes (pre-migration database, and fresh database
with guard-nested index creation) so neither recurs silently for a
future migration.

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

**Decision: knowledge-graph decay is scoped to entities/relationships
only — Signal and Opportunity stay exactly as immutable as before.**
The original decay request bundled in Signal/Opportunity lifecycle
states and Problem lifecycle transitions; both were pushed back on and
descoped before implementation, since Signal/Opportunity immutability
is a load-bearing decision from schema v6/v7, and Problem lifecycle is
already its own separately-gated future item (Part 4, item 5 below) that
needs real `problem_history` data to design against, not to be decided
as a side effect of a knowledge-graph feature.

**Decision: decay never reactivates; only new evidence does.** The decay
pass (`run_decay_pass()`) only ever moves lifecycle state forward or
leaves it alone. Reactivation lives entirely in
`extractor.persist_results()`, on the same code path that already
handles first-insert vs. re-encounter — one reactivation path, not two
places that both need to agree on what "active again" means.

**Decision: matching is two-layer weighted (active/dormant/archived), not
binary include/exclude.** `weighted_jaccard()` was added as a strict
generalization of the existing `jaccard()` rather than modifying it in
place — every existing caller (title comparison, and every pre-v8 test)
is provably unaffected, confirmed by the full existing suite passing
unchanged before any new tests were added.

**Decision: two DDL-ordering-bug lessons from the CI investigation were
applied proactively, not just documented.** Schema v8's two new indexes
(`idx_entities_lifecycle`, `idx_rel_lifecycle`) are created unconditionally
in `_migrate_v8()`, outside any column-existence guard, from the start —
rather than writing them the "obvious" way and discovering the same bug
class a fourth time.

**Decision: Problem lifecycle is TWO independent fields
(`lifecycle_state`, `trend`), not one combined state — a correction made
before shipping, not after.** The original design (per this project's own
"explain transition logic before implementing" standing instruction) was
presented as a single `trajectory_state` enum spanning
discovery/validation/growing/mature/declining/archived/reactivated. A
design review rejected that in favor of splitting "is this operationally
relevant" (`lifecycle_state`) from "how is it trending" (`trend`) as
genuinely independent axes — one field, one concept, avoiding both
state-explosion and contradictory-reading combinations. The single-field
version had already been fully implemented, tested (23 passing tests),
and was still fully replaced rather than patched around, once nothing
had been pushed yet made the cost of doing it right effectively zero.
See `docs/SCHEMA.md`'s v9 entry for the complete before/after reasoning.

**Decision: Problem's `lifecycle_state` mirrors the same
`active → dormant → archived` shape as knowledge-graph decay (schema
v8), with its own separate thresholds.** Not initially planned this way
— the original design jumped straight from "recurring" to "archived"
with no intermediate stage. Adding `dormant` as a distinct Problem-level
stage, analogous to entity/relationship decay, was adopted for
consistency once the two-axis split was already being reconsidered.

**Decision: a real, pre-existing exception to Opportunity immutability
was found and had to be reconciled before this work could be named
correctly.** `Opportunity.status` (`new|validated|dismissed|archived`)
is mutated in place via `PATCH /opportunities/{id}/status` — a
human-curated review field, explicitly unenforced, that predates this
whole session's schema work. This wasn't previously surfaced in
`docs/ARCHITECTURE.md`'s characterization of Opportunity as strictly
immutable. Resolution: `Opportunity.status` is real, narrow,
Version-1 API surface, left untouched — but it meant the new
system-derived Problem fields needed distinct names
(`lifecycle_state`/`trend`, not `status`) to avoid confusing two
unrelated vocabularies that happen to share "archived" and "new."

## Part 4: Future Roadmap

Per the RFC review's reprioritization (supersedes the pre-RFC ordering):

1. ~~Domain-scope knowledge graph~~ — done (v5).
2. ~~`problems` table + canonical matching~~ — done (v6).
3. ~~Persistent memory~~ — done (v7).
4. ~~Time-decay on the knowledge graph~~ — **done (v8), this milestone.**
   Scoped to entities/relationships only, per an explicit descope
   decision during design (see Part 3) — Signal/Opportunity lifecycle
   was requested but rejected as out of scope for this item.
5. ~~Problem lifecycle~~ — **done (v9), this milestone.** Shipped as
   two independent axes (`lifecycle_state`, `trend`), not the single
   combined state machine originally sketched — see Part 3's decision
   entry for why. Design was explained and iterated on before
   implementation (per standing instruction): the RFC's proposed field
   shape was itself corrected during that review, before any code
   shipped.
6. **Evidence-quality weighting** — as a separate signal informing
   confidence/verdict, not a rewrite of the scorer's composite formula.
   Schema v8/v9 both added extension-point *shapes* for this
   (`decay.decide_lifecycle_state()`'s `evidence_quality` parameter;
   nothing analogous yet on the Problem lifecycle side) but not the
   signal itself — nothing in the codebase computes evidence quality as
   a distinct value yet.
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
    Problem/canonical data model has had more time to prove stable. Now
    has two more real fields (`lifecycle_state`, `trend`) worth exposing
    once this is built.
12. Market Intelligence, Writer/Sales/Outreach/Analytics agents
    themselves — explicitly out of scope until item 11 exists.

**Frontend note (from the RFC review, worth restating):** the
originally-planned "backend done → build Next.js frontend" ordering was
challenged — Problem Memory is the highest-leverage screen the frontend
will show, and it's only as good as the history data behind it. Frontend
scaffolding/design-system work can start any time, but the Problem
Memory screen specifically should wait until there's real accumulated
history to design against, not be built thin on day one.

## Part 5: Current Session Context

**History across sessions, most recent last:**

1. Schema v7 (persistent Problem memory) was implemented, validated, and
   pushed — `origin/main` reached `a7519cd`. Full validation detail:
   `docs/PROBLEM_MEMORY_VALIDATION.md`.
2. A live CI failure ("Run collection pipeline" erroring) was diagnosed
   and fixed across two more pushes (`d26e891`, then `bbf0722` after a
   second, related error surfaced on the next run) — the DDL-ordering
   bug class described in Part 3 and in full in `docs/SCHEMA.md`'s
   v5/v6 entries. `origin/main` reached `bbf0722`.
3. Schema v8 (knowledge-graph decay) was designed, descoped from a
   larger initial request (see Part 3), implemented, validated, and
   pushed (`89d56d3`).
4. Push was rejected — an externally-authored architecture handbook
   (`docs/architecture/`, 17 files) had landed on `origin/main` directly
   during this session. Fetched, confirmed zero file overlap, merged
   cleanly (`de334a2`), pushed.
5. Reviewed the handbook in full and found three points of drift from
   the actual implementation: a broken filename cross-reference in its
   own reading order, an `Opportunity`-immutability contradiction
   (`04_DATA_MODEL.md` said "Opportunities may expire," which is exactly
   backwards), and an implicit ambiguity about current-state mutation
   vs. rewriting history. All three fixed and pushed (`50c75ac`).
6. This session: Problem lifecycle (RFC roadmap item 5) was designed
   using the "explain transition logic before implementing" standing
   instruction — proposed as a single `trajectory_state` field, fully
   implemented and tested (23 passing tests: schema v9 migration,
   `opportunity_engine/lifecycle.py`, canonicalizer integration, pipeline
   wiring). A design review then rejected the single-field shape in
   favor of two independent axes (`lifecycle_state`, `trend`) — see Part
   3's decision entry. The single-field version was fully replaced, not
   patched around, since nothing had been pushed yet. **Committed
   locally, not yet pushed** — see below.

**Token handling note, still relevant for whoever continues this:**
every GitHub Personal Access Token used in this project's history was
pasted directly into chat and therefore treated as compromised the
moment it appeared, regardless of whether it was used. None were ever
committed or written to any file in this repo. **Before pushing
anything, confirm no stale token is still live at
https://github.com/settings/tokens**, and treat any newly-provided token
the same way — use once, then revoke.

**What's sitting locally, unpushed, right now:** schema v9 — Problem
`lifecycle_state`/`trend` as two independent current-state axes,
`opportunity_engine/lifecycle.py` (trend classification, the periodic
forward-progression pass, event-driven reactivation), canonicalizer
integration, pipeline Stage 3.5. 467/467 tests passing. Verified via
direct calls to `pipeline._run_domain()` with real injected signals,
dry_run=False, across two separate runs specifically to exercise the
full archive → reactivate → promote-to-active cycle through the real
matching code path (not just direct function calls) — confirmed both
axis-tagged `status_changed` events write correctly and Stage 3.5's
one-pass `reactivated → active` promotion fires within the same
pipeline run as the reactivation itself.

**Next steps:** commit and push schema v9, then move to Part 4 item 6
(evidence-quality weighting) or item 7 (relationship hierarchy) — both
still explicitly gated (evidence-quality needs a real signal to weight,
which doesn't exist yet; hierarchy needs real multi-hop data). Given
neither is truly ready, it may be worth spending the next session on
Part 4 items 8–9 (the `explainer.py` split and duplicated
keyword-scanning consolidation) instead — pure code debt with no design
gate, unlike everything else currently at the top of the list. Whoever
picks this up should also note the pattern that's now repeated twice
(schema v8's `idx_opp_problem`-style fresh-database gap, schema v9's
initial single-field design): proposing a design, implementing it fully
with tests, and *then* finding a better shape through review is
apparently how this project's best schema decisions actually get made
here — not a failure mode to avoid, a process to expect and budget for.
