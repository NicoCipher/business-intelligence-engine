# BIA Project Handoff (updated — through `b616196`, domain-awareness on list endpoints)

Supersedes the schema-v7-era handoff. Full architecture detail now lives
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
    concrete. Pushed as `9a3b3b3`.
14. ADR-006/ADR-007 subject confusion (which two decisions each was
    actually about) corrected via supersession — `ADR-008`, `ADR-009`,
    `ADR-010` added rather than editing the originals in place, to keep
    the record of what was actually decided when intact (`b899793`).
15. **Bug fix: reports were only ever generated on Sundays.**
    `collect.py` gated Stage 4 on `args.report or is_sunday`; on every
    non-Sunday run, no report was produced regardless of opportunity
    count. Root-caused and fixed to run unconditionally; `is_sunday`
    removed, `--report` kept as a harmless no-op flag for backward
    compatibility. Separately investigated the same session: a
    zero-entity/zero-opportunity HN batch, confirmed as correct
    precision-tuned-vocabulary behavior on off-topic input rather than a
    suppression bug — no thresholds changed (`e0a43d7`).
16. Two deferred code-debt items closed: `opportunity_engine/explainer.py`
    (~60KB, five-plus responsibilities) split into a package along its
    own existing section boundaries, zero behavior change, same public
    API (`9524d1e`); duplicated keyword-scanning logic across
    `scorer.py`/`explainer/watch_list.py` consolidated into
    `opportunity_engine/keyword_matching.py`, deliberately *not*
    merged with `extractor.py`'s materially different word-boundary
    algorithm (`dc193cd`).
17. **RFC-001 (Accepted) / RFC-002 (Proposed).** New `docs/rfc/` track,
    distinct from `docs/adr/` (RFCs cover pipeline-level architecture
    spanning multiple stages; ADRs cover one bounded decision). RFC-001
    replaces the six-layer model (Signal → Knowledge → Problem →
    Opportunity → Intelligence → Presentation) with an eleven-stage
    "Constitutional Analyst Pipeline" (Direction → Collection →
    Processing → Correlation → Problem → Investigation → Findings →
    Analysis → Opportunity → Advisory → Presentation → Feedback,
    closing back to Direction) — accepted, **not yet implemented**.
    RFC-002 specifies the data contract for the one new stage with no
    existing implementation home (Investigation/Findings: seven
    evidence-backed facets, immutable and dated like Opportunity) —
    proposed, architecture only. Docs-only commit, no code changed
    (`6895848`).
18. **V1 security and production foundation.** Single-operator API-key
    auth (`auth.py`, no-op when `BIA_API_KEY` unset), atomic
    dependency-free pipeline/report file locking with stale-lock
    recovery (`locking.py` — fixes a real concurrent-trigger SQLite
    race), durable timestamped-snapshot backups (`persistence.py`),
    request body size limits and security headers on every response
    (`middleware.py`). Explicitly no multi-user/RBAC/MFA/BFF — out of
    scope per the resolved threat model (`a90a95a`).
19. **Domain-awareness on list endpoints.** Optional `domain` filter
    added to `GET /opportunities` and `GET /signals` (unvalidated
    equality, same treatment as existing filters; unknown domain →
    empty list, not an error), closing a Domain Architecture (§7)
    isolation gap — both tables have had an indexed `domain` column
    since schema v2. `GET /reports` and a dedicated Problem endpoint
    are explicitly out of scope for this change (`b616196`, current
    `HEAD`).

**Current code state:** `origin/main` at `b616196` — everything above
is committed and pushed; working tree is clean, nothing outstanding.
Per `b616196`'s own commit message, full suite was 533/533 passing
(522 baseline + 11 new) at that commit. Schema version 9.

**Active problems:** none known/open. Every DDL-ordering-class bug found
during the CI investigation is fixed and has dedicated regression
coverage (`test_migration_v5.py`, `test_migration_v6_upgrade.py`,
`test_migration_v8.py`, `test_migration_v9.py`) that specifically
exercises both failure modes (pre-migration database, and fresh database
with guard-nested index creation) so neither recurs silently for a
future migration.

**Known gaps, explicitly out of scope of recent work (not bugs):** no
Problem REST endpoint exists yet (`api/` has `opportunities.py`,
`reports.py`, `signals.py` only); `GET /reports` has no `domain` filter
despite `ReportDetail` already carrying the field; RFC-001's eleven-stage
pipeline is accepted but the codebase still runs the six-layer model —
no migration plan exists yet for that transition.

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

Per the RFC review's reprioritization (supersedes the pre-RFC ordering).
**Superseding note (RFC-001, `6895848`):** RFC-001 was accepted after
this list was last ordered and replaces the six-layer architectural
model this roadmap was framed against with an eleven-stage
"Constitutional Analyst Pipeline." No implementation of that transition
has started. Until a migration plan exists, treat RFC-001/RFC-002 as
the dominant open architectural question — items below are still valid
work, but a Problem-endpoint or pipeline-stage change made now should
be checked against RFC-001's stage boundaries first, not just the
six-layer model this list still describes.

1. ~~Domain-scope knowledge graph~~ — done (v5).
2. ~~`problems` table + canonical matching~~ — done (v6).
3. ~~Persistent memory~~ — done (v7).
4. ~~Time-decay on the knowledge graph~~ — done (v8). Scoped to
   entities/relationships only, per an explicit descope decision during
   design (see Part 3) — Signal/Opportunity lifecycle was requested but
   rejected as out of scope for this item.
5. ~~Problem lifecycle~~ — done (v9). Shipped as two independent axes
   (`lifecycle_state`, `trend`), not the single combined state machine
   originally sketched — see Part 3's decision entry for why. Design
   was explained and iterated on before implementation (per standing
   instruction): the RFC's proposed field shape was itself corrected
   during that review, before any code shipped.
6. **Evidence-quality weighting** — as a separate signal informing
   confidence/verdict, not a rewrite of the scorer's composite formula.
   Schema v8/v9 both added extension-point *shapes* for this
   (`decay.decide_lifecycle_state()`'s `evidence_quality` parameter;
   nothing analogous yet on the Problem lifecycle side) but not the
   signal itself — nothing in the codebase computes evidence quality as
   a distinct value yet. Still open.
7. Relationship hierarchy (multi-level `belongs_to`) — explicitly
   postponed by the RFC review; not enough real multi-hop data yet to
   know what depth is actually useful. Still open.
8. ~~`explainer.py` split~~ — done (`9524d1e`).
9. ~~Duplicated keyword-scanning consolidation~~ — done, scoped to
   `scorer.py`/`explainer/watch_list.py` only, deliberately excluding
   `extractor.py`'s different algorithm (`dc193cd`).
10. Multi-tenancy schema hook — RFC review flagged this as
    cheap-now/expensive-later even though "not urgent"; still not
    started. Worth a small decision before Problem/Opportunity/history
    tables are full of real data, not a later migration project.
11. Clean read-only query interface for future agents — design once the
    Problem/canonical data model has had more time to prove stable. Has
    two more real fields (`lifecycle_state`, `trend`) worth exposing
    once this is built. Still gated on RFC-001's Investigation/Findings
    contract (item 13 below) if pipeline restructuring happens first.
12. Market Intelligence, Writer/Sales/Outreach/Analytics agents
    themselves — explicitly out of scope until item 11 exists.
13. **RFC-001 implementation** — no code yet. Migration plan from the
    current six-layer pipeline to the eleven-stage constitutional
    pipeline is undesigned. RFC-002's Findings data contract (Proposed,
    not Accepted) needs resolution first, since Analysis's stage
    contract can't be specified until what it consumes is defined.
14. **Problem REST endpoint** — does not exist. `api/` currently
    exposes `opportunities.py`, `reports.py`, `signals.py` only.
    Explicitly flagged as a separate future item in `b616196`'s commit
    message. No design work done yet on response shape, whether
    `problem_history` is inlined or a sub-resource, filtering, or
    pagination.
15. `GET /reports` domain filter — `ReportDetail` already carries a
    `domain` field (unlike Opportunities/Signals before `b616196`) but
    the list endpoint has no filter for it. Small, same pattern as
    `b616196`.

**Frontend note (from the RFC review, worth restating):** the
originally-planned "backend done → build Next.js frontend" ordering was
challenged — Problem Memory is the highest-leverage screen the frontend
will show, and it's only as good as the history data behind it. Frontend
scaffolding/design-system work can start any time, but the Problem
Memory screen specifically should wait until there's real accumulated
history to design against, not be built thin on day one.

## Part 5: Recent History

**History, most recent last (extends the log in the prior handoff
revision, which covered through schema v7/v8/v9-drafting and the
handbook merge — see git log for full detail on any commit below):**

1. Schema v9 (Problem lifecycle & trend, two independent axes — see
   Part 3) was committed and pushed: `9a3b3b3`.
2. ADR-006/007 subject confusion corrected via supersession
   (ADR-008/009/010, not edits to the originals) — `b899793`.
3. Live bug: reports were only generated on Sundays
   (`args.report or is_sunday` gate in `collect.py`). Root-caused,
   fixed to run unconditionally, `is_sunday` removed — `e0a43d7`.
4. Two previously-deferred code-debt items closed back to back:
   `explainer.py` package split (`9524d1e`), keyword-scanning
   consolidation into `opportunity_engine/keyword_matching.py`
   (`dc193cd`).
5. RFC-001 (Constitutional Analyst Pipeline, Accepted) and RFC-002
   (Investigation Findings contract, Proposed) — a new `docs/rfc/`
   track and a major accepted pipeline redesign (six-layer model →
   eleven-stage pipeline). Docs only, no code — `6895848`.
6. V1 security and production foundation: single-operator API-key auth,
   file locking (fixes a real concurrent-write SQLite race), durable
   backup snapshots, request size limits and security headers —
   `a90a95a`.
7. Domain-awareness filter added to `GET /opportunities` and
   `GET /signals` — `b616196`, current `HEAD`.

**Token handling note, still relevant for whoever continues this:**
every GitHub Personal Access Token used in this project's history was
pasted directly into chat and therefore treated as compromised the
moment it appeared, regardless of whether it was used. None were ever
committed or written to any file in this repo. **Before pushing
anything, confirm no stale token is still live at
https://github.com/settings/tokens**, and treat any newly-provided token
the same way — use once, then revoke.

**Current state:** working tree clean, nothing uncommitted, `origin/main`
and local `main` both at `b616196`. Nothing pending push.

**Next steps — three independent open threads, pick based on priority:**

- **RFC-001 implementation** (Part 4 item 13): the largest open item.
  No migration plan exists yet from the current six-layer pipeline to
  the eleven-stage constitutional pipeline. RFC-002 (Findings contract)
  is still Proposed, not Accepted — likely needs to resolve first,
  since it's on RFC-001's critical path.
- **Problem REST endpoint** (Part 4 item 14): explicitly deferred by
  `b616196`'s own commit message. No design work started — response
  shape, whether `problem_history` is inlined or a sub-resource,
  filtering, and pagination are all open questions. Should be checked
  against RFC-002's Findings shape and RFC-001's stage boundaries
  before implementation, given RFC-001 is now Accepted, to avoid
  building API surface against the six-layer model right as it's
  being superseded.
- **Small, ungated cleanup** (Part 4 item 15): `GET /reports` domain
  filter, same small pattern as `b616196`, no design gate.

Whoever picks this up should keep the pattern noted in the prior
handoff revision in mind: this project's best schema/design decisions
have repeatedly come from proposing a shape, implementing it fully with
tests, and *then* finding a better shape through review (schema v8's
fresh-database DDL gap, schema v9's single-field-to-two-axis
correction) — not a failure mode to avoid, a process to expect and
budget for. Given that pattern, and the standing "explain before
implementing" instruction, the Problem REST endpoint in particular
should get an explicit design discussion — including how it relates to
RFC-002's Findings facets, since both are new API-shaped surfaces
touching Problem-adjacent data — before any code is written.
