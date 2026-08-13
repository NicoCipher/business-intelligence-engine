# BIA Project Handoff (updated — through `c45e612`, pipeline test network-isolation fix)

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
    are explicitly out of scope for this change (`b616196`).
20. **ADR-011: Domain-Generalized Opportunity Scoring** — designed
    (`a58733a`) then implemented (`665631a`). Followed a domain/plugin
    architecture audit that found `OpportunityScores`, `config.py`'s
    `SCORE_WEIGHTS`/`TIER_GOLD`/`TIER_SILVER`, and a fourth,
    independently-hardcoded tier-threshold check in
    `api/opportunities.py` were all coupled to Business's specific
    seven dimensions, none reachable from `DomainConfig.scoring` (which
    had existed, unused, since the domain architecture was introduced).
    `OpportunityScores.dimensions` is now a dict keyed by domain-
    supplied dimension ids, computed via two tiers — Tier 1
    (data-driven, keyword-presence) and Tier 2 (a registered
    `compute_fn`, for signal-structure logic a keyword list can't
    express). Flat `to_dict()` serialization preserved exactly, zero DB
    migration. `OpportunityScores` ended up a plain class with a
    hand-written `__init__`, not `@dataclass` — an `InitVar`+`@property`
    combination was tried first and reverted: both claim the same class
    attribute at class-definition time, and one silently clobbers the
    other, breaking either construction or reads. Explicitly out of
    scope, per the ADR: `explainer/*`'s narrative logic and
    `detector.py`'s cluster-acceptance gate stay hardcoded to Business's
    seven dimensions — not touched, not generalized. 547/547 passing at
    this commit.
21. **GitHub collector** (`b5afceb`) — `GitHubCollector`, domain-scoped
    like Reddit (not shared/unauthenticated like HN, since GitHub
    search needs a token and is meaningfully domain-specific). Searches
    `/search/issues` (demand signal) and `/search/repositories`
    (competition/opportunity signal — direct, checkable evidence
    whether a similar solution already exists, which no prior source
    gave). `source_id` prefixed `issue-`/`repo-` since GitHub's issue
    and repo numeric ids are separate namespaces. Validated during
    development against live (unauthenticated) GitHub API responses,
    not just synthetic fixtures. 570/570 passing at this commit.
22. **Google Trends collector, plus GitHub/Reddit credential setup**
    (`cfa8624`) — `TrendsCollector`, via `pytrends` (unofficial,
    reverse-engineered, no documented rate limit — explicitly treated
    in its own module docstring as the least reliable source in the
    system, not a peer of Reddit/GitHub/HN's official APIs). Also
    domain-scoped, a correction from an earlier "shared like HN"
    framing: Trends has no global feed, it's entirely keyword-driven.
    Rising related queries become signals (`demand_signal` applied
    unconditionally — surging search volume is inherently a demand
    signal, unlike the marker-matching the other three collectors use).
    `source_id` is date-scoped, not deduplicated across days — the same
    rising query surging again later is a new, true observation
    (recurrence), not a stale repeat. One real bug caught by the new
    tests, not by inspection: the `trending_up` heuristic returned a
    numpy `bool_` scalar instead of a native Python `bool` — fixed. Also:
    `.env.example` updated with `GITHUB_TOKEN` and an explicit
    "Trends needs no credentials" note; `requirements.txt` gained
    `pytrends==4.9.2` (had been installed manually during development,
    never pinned). Live-validated for GitHub only during that session —
    `trends.google.com` was not reachable from the development sandbox,
    so Trends' parsing is fixture-based, not live-cross-checked. 593/593
    passing at this commit.
23. **CI regression, pipeline test network isolation** (`c45e612`) —
    two tests failed on stale signal counts after GitHub/Trends were
    wired into `pipeline.py`; root cause was worse than a stale count:
    `_patch_collectors()` (test helper) was never updated to patch the
    two new collectors, and three tests register the real
    `domains.business.DOMAIN_CONFIG` (which carries real
    `github_queries`/`trends_keywords`) then call `run_full_pipeline()`
    unpatched — CI logs showed a live Google Trends 429 mid-run, which
    is what surfaced this. Fixed structurally: `_patch_collectors()`
    itself now patches all five collectors, defaulting GitHub/Trends to
    `[]` — the three existing test bodies needed zero argument changes,
    which is why expected counts stayed at their original 6/4, not
    bumped to 9/11. Added one new test proving the positive path
    (GitHub/Trends signals, when present, get the correct domain tag).
    594/594 passing at this commit, current `HEAD`.

**Current code state:** `origin/main` at `c45e612` — everything above
is committed and pushed; working tree is clean, nothing outstanding.
594/594 tests passing. Schema version 9 (unchanged by any of items
20–23 — ADR-011's storage-layer generalization required zero DB
migration).

**Active problems:** none known/open. Every DDL-ordering-class bug found
during the CI investigation is fixed and has dedicated regression
coverage (`test_migration_v5.py`, `test_migration_v6_upgrade.py`,
`test_migration_v8.py`, `test_migration_v9.py`) that specifically
exercises both failure modes (pre-migration database, and fresh database
with guard-nested index creation) so neither recurs silently for a
future migration. The GitHub/Trends network-isolation gap (item 23) is
also fixed and covered — `_patch_collectors()` patching all five
collectors is a structural fix, not a per-test one, so a future new
collector being added without updating that helper is the only way to
reintroduce a similar leak.

**Known gaps, explicitly out of scope of recent work (not bugs):** no
Problem REST endpoint exists yet (`api/` has `opportunities.py`,
`reports.py`, `signals.py` only); `GET /reports` has no `domain` filter
despite `ReportDetail` already carrying the field; RFC-001's eleven-stage
pipeline is accepted but the codebase still runs the six-layer model —
no migration plan exists yet for that transition. From the domain/plugin
audit that produced ADR-011: `knowledge_graph/extractor.py`,
`opportunity_engine/detector.py`, and `opportunity_engine/explainer/*`
still consume `knowledge_graph/schema.py`'s and `config.py`'s hardcoded
Business vocabulary directly, not `domain.graph`/`domain.keywords` —
ADR-011 deliberately scoped only the scoring-storage layer; these three
are separate, not-yet-designed follow-on work, still blocking an actual
second domain from working correctly even with scoring now generalized.
Operationally: Reddit credentials are not configured in the only
environment that's touched this project so far, so the Reddit collector
has never been live-validated, only unit-tested; Google Trends has been
unit-tested against fixtures built from `pytrends`' own source, never
against a live response, since `trends.google.com` wasn't reachable
from that environment either.

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
16. ~~Domain-generalized opportunity scoring~~ — done, ADR-011
    (`665631a`). See Part 1 item 20. Deliberately scoped to the
    storage/composite-calculation layer only.
17. **Second-domain data-source generalization** — the follow-on ADR-011
    deliberately didn't do. `knowledge_graph/extractor.py` still reads
    `knowledge_graph/schema.py`'s hardcoded Business entity vocabulary,
    not `domain.graph`; `opportunity_engine/detector.py`'s
    cluster-acceptance gate and `opportunity_engine/explainer/*`'s
    narrative logic are still hardcoded to Business's specific
    dimensions and keyword sets. Scoring being domain-generic now
    doesn't mean a second domain would actually work end-to-end — these
    three are what would still block it. No design started.
18. ~~Add GitHub and Google Trends collectors~~ — done (`b5afceb`,
    `cfa8624`). Not originally on this list — added by direct request
    mid-session, not from the RFC review's prioritization. Google
    Trends' parsing has never been live-validated (see Part 1's "Known
    gaps"); worth a real validation pass before leaning on its output
    for anything scored/reported.
19. Reddit live validation — credentials were never configured in the
    environment this project has been developed in so far; the
    collector has only ever been exercised via its unit tests (canned
    fixtures) and its graceful-failure path (missing credentials),
    never against the real Reddit API.

**Frontend note (from the RFC review, worth restating):** the
originally-planned "backend done → build Next.js frontend" ordering was
challenged — Problem Memory is the highest-leverage screen the frontend
will show, and it's only as good as the history data behind it. Frontend
scaffolding/design-system work can start any time, but the Problem
Memory screen specifically should wait until there's real accumulated
history to design against, not be built thin on day one.

## Part 5: Recent History

**History, most recent last (extends the log in the prior handoff
revision, which covered through `b616196` — see git log for full detail
on any commit below):**

1. Domain/plugin architecture audit (no commit — analysis only) found
   `OpportunityScores` and three other sites coupled to Business's
   seven hardcoded scoring dimensions, none reachable from
   `DomainConfig.scoring`.
2. ADR-011 designed and locked (`a58733a`), then implemented
   (`665631a`) — see Part 1 item 20 for full detail.
3. GitHub collector added (`b5afceb`) — see Part 1 item 21.
4. Google Trends collector added, plus GitHub/Reddit credential setup
   (`cfa8624`) — see Part 1 item 22.
5. CI regression: two pipeline tests failed on stale signal counts;
   root cause was a test-isolation gap letting live GitHub/Trends
   network calls happen during "unit" tests. Fixed structurally, not
   with a stale-count bump (`c45e612`, current `HEAD`) — see Part 1
   item 23.

**Token handling note, still relevant for whoever continues this:**
every GitHub Personal Access Token used in this project's history was
pasted directly into chat and therefore treated as compromised the
moment it appeared, regardless of whether it was used. None were ever
committed or written to any file in this repo. **Before pushing
anything, confirm no stale token is still live at
https://github.com/settings/tokens**, and treat any newly-provided token
the same way — use once, then revoke.

**Current state:** working tree clean, nothing uncommitted, `origin/main`
and local `main` both at `c45e612`. Nothing pending push.

**Next steps — four independent open threads, pick based on priority:**

- **Second-domain data-source generalization** (Part 4 item 17): the
  most direct follow-on to ADR-011. `extractor.py`, `detector.py`, and
  `explainer/*` are still Business-hardcoded — scoring alone being
  generic doesn't make a second domain work.
- **RFC-001 implementation** (Part 4 item 13): still the largest
  standing open item, unchanged since the last revision. RFC-002's
  Findings contract still needs to move from Proposed to Accepted first.
- **Problem REST endpoint** (Part 4 item 14): still not designed. Should
  be checked against RFC-002's Findings shape and RFC-001's stage
  boundaries before implementation, same caveat as last revision.
- **Collector live-validation debt** (Part 4 items 18–19): Google
  Trends has never been checked against a real response — only
  fixture-based tests, built from reading `pytrends`' own source, not
  from an actual live call. Reddit has never been exercised at all
  beyond its graceful-failure path. Worth resolving before leaning on
  either collector's output for anything that gets scored or reported
  on.

Whoever picks this up should keep the pattern noted in the prior
handoff revision in mind: this project's best schema/design decisions
have repeatedly come from proposing a shape, implementing it fully with
tests, and *then* finding a better shape through review (schema v8's
fresh-database DDL gap, schema v9's single-field-to-two-axis
correction, ADR-011's `OpportunityScores` construction mechanism going
through two failed designs before landing on a plain hand-written
`__init__`) — not a failure mode to avoid, a process to expect and
budget for. Given that pattern, and the standing "explain before
implementing" instruction, the Problem REST endpoint and the
second-domain generalization work in particular should both get an
explicit design discussion before any code is written.
