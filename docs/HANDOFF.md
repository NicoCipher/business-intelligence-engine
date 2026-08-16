# BIA Project Handoff (updated — through this commit, schema v10: Continuous Intelligence Engine foundation)

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

**Known gaps, explicitly out of scope of recent work (not bugs):**
`GET /reports` has no `domain` filter despite `ReportDetail` already
carrying the field (Problem REST endpoint is done as of item 25 above
— this is the one remaining API-surface gap of this shape); RFC-001's
eleven-stage pipeline is accepted but the codebase still runs the
six-layer model — no migration plan exists yet for that transition.
From the domain/plugin audit that produced ADR-011, now mostly
addressed by item 24 above: `explainer/opportunity.py`, `historical.py`,
and `trends.py`'s narrative logic remain deliberately Business-hardcoded
(confirmed by inspection to be real editorial/semantic judgment, not
vocabulary lookups — see item 24's own detail, and each file's own
docstring), as does `extractor.py`'s `_infer_relationship()` (entity-
type-pair semantics, same reasoning). Extraction, detection, and
canonicalization themselves are domain-generic now; only the narrative
layer is still Business-specific.
Operationally: Reddit credentials are not configured in the only
environment that's touched this project so far, so the Reddit collector
has never been live-validated, only unit-tested; Google Trends has been
unit-tested against fixtures built from `pytrends`' own source, never
against a live response, since `trends.google.com` wasn't reachable
from that environment either. Schema v10's five new tables are
currently inert — `collector_state` exists and is seeded but nothing
reads or writes it yet (no scheduler); `change_events` exists but
nothing writes to it yet (no change detector); `watchlists`/
`alert_rules`/`operator_state` exist with no consumer at all yet. This
is the deliberate, explicit scope of a "foundation" migration, not an
oversight — see item 26.

24. **Second-domain data-source generalization** (`ac19d5c`). Addresses
    exactly the gap the paragraph above used to describe as
    unaddressed:
    - `knowledge_graph/extractor.py` — `EntityExtractor` now takes a
      `domain_graph` parameter (defaults to Business's), consuming
      `domain.graph.entity_types`/`.get_display_name()` instead of the
      hardcoded global `knowledge_graph/schema.py` module. Found and
      fixed a real pre-existing gap first: `domains/business/graph.py`
      was missing 6 `display_names` entries schema.py had (chatgpt,
      openai, claude, gemini, anthropic, github) — a prerequisite fix
      before the swap could be behavior-preserving.
    - `domains/registry.py` — new `DomainRegistry.get_or_default()`,
      deliberately non-raising (returns `None`, not an exception, when
      neither the requested nor default domain is registered) — a
      raising version was tried first and doesn't work: plain unit
      tests register no domain at all, not even "business".
    - `opportunity_engine/canonicalizer.py`, `detector.py`,
      `pipeline.py`, `explainer/watch_list.py`, `report/generator.py`
      — all now resolve and use the active domain's real config
      (graph/scoring/keywords) instead of hardcoded globals or hidden
      Business defaults, wherever the real domain object or a
      resolvable domain string was already in scope.
    - `models.py` — a genuine third hardcoding site found by a new
      test *failing*, not by inspection: `Entity.__post_init__`
      validated `type` against a fixed, Business-shaped
      `VALID_ENTITY_TYPES` set. Once extraction was correctly
      domain-scoped, this became actively wrong (would reject any
      second domain's own entity type names), not just redundant.
      Relaxed to a minimal non-empty-string check.
    - 20 new tests (`tests/test_domain_generalization.py`), verified
      by actual mutation testing (not just read-through) to genuinely
      catch a reverted fix rather than passing regardless — one test
      was caught and strengthened mid-review for exactly this reason
      (an `isinstance(ids, list)` assertion that would have passed
      even if the underlying fix were reverted).
    - Deliberately NOT touched, and explicitly documented in each
      file's own docstring (previously this reasoning only existed in
      chat, not in the code): `extractor.py`'s `_infer_relationship()`
      (entity-type-pair semantics with explicit priority ordering, not
      a vocabulary lookup); `explainer/opportunity.py`'s narrative
      logic (verdict language, `_market_gap`, `_time_to_first_revenue`,
      `_DIMENSION_LABELS` — checked whether labels could source from
      `domains.business.scoring.SCORING`'s own fields, confirmed they
      don't match the real hardcoded ones, e.g. `"Competition"` vs.
      `"Market Gap"` for the same dimension id — swapping would have
      silently changed existing report wording); `explainer/
      historical.py` (hardcodes exactly 3 of 7 dimensions as worth
      trend-narrating, an editorial choice); `explainer/trends.py`'s
      narrative templates (`_TREND_NAME_TEMPLATES`/`_WHO_CARES`, keyed
      by Business's entity type names).
    - 614/614 passing at this commit.
25. **Problem REST API** (`a3d0966`) — `GET /api/v1/problems` (list,
    filterable, three named sort orders: `recent`/`persistent`/
    `significant`), `GET /api/v1/problems/{id}` (detail, linked
    opportunities inlined), `GET /api/v1/problems/{id}/history` (full
    timeline, its own paginated sub-resource — `problem_history` is
    unbounded by design, so it's deliberately not inlined into the
    detail response). `significant` sort computed via a `LEFT JOIN`
    against `opportunities.composite_score` — Problem stays
    intentionally unscored by architecture, so "significance" is read
    off the best opportunity a problem has actually produced, not a
    stored column. All three routes require auth
    (`Depends(auth.get_current_actor)`) — a deliberate deviation from
    `opportunities.py`/`signals.py`'s open GETs, applied for
    consistency/future-proofing and clearly documented as intentional.
    Verified against RFC-002 first: Problem's shape is unaffected by
    whether RFC-002 (still Proposed) is ever accepted. 26 new tests.
    640/640 passing at this commit.
26. **Schema v10 — Continuous Intelligence Engine foundation** (this commit,
    current `HEAD`). Five new tables, all additive, zero changes to any
    existing table:
    - `collector_state` — persisted per-`(source, domain)` scheduler
      state (last run/success/failure, consecutive failures, backoff,
      quota), the memory an adaptive scheduler needs that survives
      between GitHub Actions' ephemeral runners (there is no
      long-running process — see `.github/workflows/collect.yml` —
      so nothing else could remember this between runs). Seeded for
      all five known collectors with intervals reflecting each one's
      own already-documented real constraints (Trends most
      conservative at 360min/lowest priority, citing its own module
      docstring's "least reliable source in the system"; GitHub's
      240min citing its Search API's 30 req/min limit), not arbitrary
      numbers. `next_due_at` deliberately NOT a stored column — fully
      derivable from `last_run_at + interval_minutes` clamped by
      `backoff_until`; storing it separately would risk drift, the
      same anti-redundant-derived-state principle already applied to
      `OpportunityScores.composite()` and `Problem.lifecycle_state`.
    - `change_events` — append-only "something meaningful happened"
      log, the intended future source for daily intelligence,
      significance ranking, watchlist updates, and alerts. The actual
      detection logic that writes to it is separate, later work — this
      migration is the table only.
    - `watchlists`, `alert_rules` — foundation only, no delivery
      channel, no UI. Zero FKs on any of the five new tables, verified
      directly via `PRAGMA foreign_key_list`, not assumed — `client_id`
      is deliberately opaque TEXT, preserving a future multi-tenant
      migration path without building one now.
    - `operator_state` — added to this same v10 migration, not deferred
      to v11, after explicit review: `change_events` alone can't answer
      "what's new since I last checked" (its own stated purpose)
      without a persisted "since when" reference point. Minimal
      singleton — `CHECK (id = 1)` enforced at the SQLite level, one
      column (`last_seen_at`) — deliberately not a settings table.
    - Explicit, tested guard-rails for the single-operator constraint
      this was built under: no `users`/`tenants`/`operators` table, no
      `user_id`/`tenant_id` column anywhere, no delivery-channel column
      on `alert_rules` — these are asserted, not just implied by
      absence (`TestSingleOperatorConstraintsHold` in
      `test_migration_v10.py`).
    - One real formatting inconsistency caught during self-review, not
      by inspection: `collector_state`'s column alignment had drifted
      across two edits in this same session — fixed by computing the
      correct padding width programmatically rather than eyeballing it
      a third time, in both `_SCHEMA_DDL` and `_migrate_v10()`.
    - 61 tests in `test_migration_v10.py` (46 for the original four
      tables + 15 for `operator_state`, added after explicit review and
      approval — see this file's own `TestOperatorState` class docstring
      for the decision trail). Verified both directions: a genuine
      pre-v10 database (not a mock) upgraded to v10, and a fresh
      database — both reach identical resulting state. All prior
      migration tests (v5–v9, 74 tests) re-run unchanged. 701/701
      passing at this commit.

**Current code state:** `origin/main` at this commit — everything above
is committed and pushed; working tree is clean, nothing outstanding.
701/701 tests passing. Schema version 10.

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
14. ~~Problem REST endpoint~~ — done (`a3d0966`, item 25). History is a
    separate paginated sub-resource, not inlined; three named sort
    orders instead of one default.
15. `GET /reports` domain filter — `ReportDetail` already carries a
    `domain` field (unlike Opportunities/Signals before `b616196`) but
    the list endpoint has no filter for it. Small, same pattern as
    `b616196`. Still open — the one remaining gap of this exact shape.
16. ~~Domain-generalized opportunity scoring~~ — done, ADR-011
    (`665631a`). See Part 1 item 20. Deliberately scoped to the
    storage/composite-calculation layer only.
17. ~~Second-domain data-source generalization~~ — mostly done,
    uncommitted (see Part 1's uncommitted-work note). `extractor.py`,
    `canonicalizer.py`, `detector.py`'s cluster-acceptance gate,
    `pipeline.py`, and `watch_list.py`'s fallback gate are all
    domain-generic now. What's still genuinely open, not a gap in this
    pass: `extractor.py`'s `_infer_relationship()` and all of
    `explainer/opportunity.py`/`historical.py`/`trends.py`'s narrative
    logic — confirmed by inspection to be real editorial/semantic
    judgment calls, not vocabulary lookups, so deliberately left
    Business-hardcoded (now documented in each file, not just decided
    in conversation). A real second `DomainConfig` would work for
    extraction/detection/scoring today; its reports would still narrate
    in Business's own terms.
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
20. **Continuous Intelligence Engine: the adaptive scheduler** — schema
    v10 (item 26) built the state `collector_state` needs to exist, but
    nothing reads or writes it yet. This is the immediate next
    implementation target: the logic that, on each (now-hourly)
    `collect.py` invocation, checks every collector's persisted state
    and runs only the ones actually due (interval elapsed, not in
    backoff, quota available), then writes `last_run_at`/
    `consecutive_failures`/`backoff_until` back. Explicitly not started.
21. **Change detection, significance ranking, alert delivery, and the
    frontend** — all deliberately deferred past the scheduler. Schema
    v10's `change_events`/`watchlists`/`alert_rules`/`operator_state`
    give these a place to persist to once built, but the logic itself
    (what counts as a meaningful change, how significance is ranked,
    how an alert actually reaches anyone) is undesigned. Do not start
    any of this before the scheduler exists — there's no point
    detecting changes faster than the collectors that would produce
    them can actually run.

**Frontend note (from the RFC review, worth restating):** the
originally-planned "backend done → build Next.js frontend" ordering was
challenged — Problem Memory is the highest-leverage screen the frontend
will show, and it's only as good as the history data behind it. Frontend
scaffolding/design-system work can start any time, but the Problem
Memory screen specifically should wait until there's real accumulated
history to design against, not be built thin on day one. Per the
frontend/backend contract audit that produced schema v10: the frontend
will initially align with BIA's existing single-operator model — no
multi-user auth, no OAuth, no per-user architecture is planned for it
either.

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
   with a stale-count bump (`c45e612`) — see Part 1 item 23.
6. Second-domain data-source generalization — extraction, detection,
   canonicalization made domain-generic; narrative layer deliberately
   left Business-specific and documented as such (`ac19d5c`) — see
   Part 1 item 24.
7. Problem REST API — history as its own paginated sub-resource, three
   named sort orders, auth on all routes as a deliberate deviation from
   the existing open-GET pattern (`a3d0966`) — see Part 1 item 25.
8. Schema v10 — Continuous Intelligence Engine foundation. Reviewed
   against the frontend/backend contract audit's explicit single-operator
   constraint (no multi-user auth, no OAuth, no users table, no tenants)
   before any code was written. `next_due_at` evaluated and deliberately
   not added as a stored column (derivable, avoids drift risk).
   `operator_state` evaluated as its own explicit recommendation
   (belongs in v10 vs. deferred to v11) before being approved and
   implemented in the same migration (this commit) —
   see Part 1 item 26.

**Token handling note, still relevant for whoever continues this:**
every GitHub Personal Access Token used in this project's history was
pasted directly into chat and therefore treated as compromised the
moment it appeared, regardless of whether it was used. None were ever
committed or written to any file in this repo. **Before pushing
anything, confirm no stale token is still live at
https://github.com/settings/tokens**, and treat any newly-provided token
the same way — use once, then revoke.

**Current state:** working tree clean, nothing uncommitted, `origin/main`
and local `main` both at this commit. 701/701 tests passing. Nothing
pending push.

**Next steps — two independent open threads, but one is now explicitly
sequenced ahead of the rest:**

- **The adaptive scheduler (Part 4 item 20) — the immediate next target,
  not a pick-your-priority item like the others below.** `collector_state`
  is seeded and structurally complete but entirely inert — nothing
  reads or writes it yet. This is the piece that makes schema v10
  operational rather than just present. Explicitly not started, per
  standing instruction, alongside change detection, significance
  ranking, alert delivery, APIs, auth, and the frontend (Part 4 item 21)
  — none of those should start before the scheduler exists, since
  there's no point detecting changes faster than the collectors
  producing them can actually run.
- **`explainer/*`'s narrative layer** (Part 4 item 17's remaining
  half) and **RFC-001 implementation** (Part 4 item 13) remain open,
  independent of the scheduler work and of each other — pick either
  once the scheduler lands, same open questions as the prior revision
  (RFC-002's Findings contract still Proposed, not Accepted; the
  narrative work needs its own design discussion before any code).
- **Collector live-validation debt** (Part 4 items 18–19) — still
  unresolved, still worth doing before leaning on Trends/Reddit output
  for anything scheduled to run automatically once the scheduler exists.

Whoever picks this up should keep the pattern noted in the prior
handoff revision in mind: this project's best schema/design decisions
have repeatedly come from proposing a shape, implementing it fully with
tests, and *then* finding a better shape through review (schema v8's
fresh-database DDL gap, schema v9's single-field-to-two-axis
correction, ADR-011's `OpportunityScores` construction mechanism going
through two failed designs before landing on a plain hand-written
`__init__`, the Problem API's `NULLS LAST` → portable-idiom fix caught
before it shipped, schema v10's `collector_state` column-alignment drift
caught and fixed by computing it programmatically rather than
eyeballing it a third time) — not a failure mode to avoid, a process to
expect and budget for. Given that pattern, and the standing "explain
before implementing" instruction, the scheduler itself should get the
same explicit design discussion before any code — it's the next major
piece of new logic, not another additive schema migration, and carries
real judgment calls (how ties between due-but-competing collectors are
actually broken, what a "failed run" means precisely, how backoff
duration scales with `consecutive_failures`) that shouldn't be decided
implicitly while writing code.
