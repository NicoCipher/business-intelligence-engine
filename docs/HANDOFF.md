# BIA Project Handoff (updated through `d865ae8f8f7ccffea78fcb7c22021876d5ff0118`: merged NIC-19 accepted experiment on top of NIC-18, NIC-13, and NIC-14)

Supersedes the schema-v7-era handoff. Full architecture detail now lives
in `docs/ARCHITECTURE.md` (current state) and `docs/SCHEMA.md` (full
version history) — this file is the orientation summary, not the whole
picture.

## Part 0: Phase 1 Operations Console (`079dced`, committed 2026-08-22)

Phase 1 adds a Next.js 16 App Router / TypeScript internal console at the
repository root. Its intentionally narrow route set is:

- `/overview`, `/signals`, `/problems`, `/problems/[problemId]`,
  `/opportunities`, `/opportunities/[opportunityId]`, `/reports`,
  `/reports/[weekKey]`, and `/system`.
- System health now displays live collector operations state (`GET /api/v1/system/collector-operations`,
  added in `903feeb`). Dedicated Pipeline, Change Events browsing, Watchlists, and Alert Rules
  interfaces remain undesigned.

The console calls only existing API contracts. The server-only client in
`src/features/api/client.ts` uses `BIA_API_BASE_URL` and `BIA_API_KEY`; no
browser code receives either value, calls the backend directly, or uses
browser credential storage. Production startup fails closed when either is
missing. Every data-backed page waits for `connection()` so production builds
never call the backend; individual reads retain their explicit fetch policy:
health no-store, stats 30s, lists 60s, details/history 120s, reports 300s,
and the protected opportunity-status mutation no-store.

External Signal and report text is rendered as React text, never HTML.
Evidence links permit only `http:`/`https:` and use `noopener noreferrer`.
`proxy.ts` issues a per-request CSP nonce for framework scripts; the static
headers also set no-sniff, frame denial, no referrer, COOP, and a restrictive
Permissions Policy. The two `use client` files are the required Next error
boundaries; all operational views are Server Components. The only Server
Action validates the opportunity identifier/status and invokes the backend
server-side.

**Deployment gate:** BIA remains a single-operator, private-network service.
There is currently no console session/RBAC layer, and the status Server Action
therefore relies on authenticated private ingress restricting who can reach the
console. Do not publish this console to a public or broadly shared origin until
that ingress/operator-auth boundary is enforced. HSTS/TLS must likewise be set
at the HTTPS reverse proxy, which is outside this repository.

**Validation at this handoff:** `npm run lint`, `npm run typecheck`, and
`npm test` pass (15 Vitest tests); production `npm run build` passes with
server-only validation credentials; `npm run check:performance` reports
126.2 KiB gzip against a 150 KiB root-client budget. Production response
inspection confirmed a fresh CSP nonce appears in both the header and
framework markup, and static client assets contain neither the validation key
nor the BIA environment-variable names.

**E2E / visual-verification limitation:** the two existing unchanged
Playwright tests start the mock API and Next server but cannot launch because
`/Users/mac/Library/Caches/ms-playwright/chromium_headless_shell-1208/`
does not contain `chrome-headless-shell`. The final workspace-local install
attempt (`PLAYWRIGHT_BROWSERS_PATH=0 npx playwright install
chromium-headless-shell`) timed out after reaching 30% of its 95.3 MiB download
(`ETIMEDOUT`), then retried with DNS failures (`ENOTFOUND
cdn.playwright.dev`). The installed `/Applications/Google Chrome.app` also
aborts when Playwright launches it headlessly. Browser visual verification is
therefore not available here. Leave the tests intact and rerun `npm run
test:e2e` in an environment with the matching Playwright browser installed.

`AGENTS.md` and `CLAUDE.md` are intentional Next-generated guidance: the
former points agents to the installed version's documentation and the latter
aliases it. They do not override repository architecture documentation and are
kept so `next dev` does not recreate an untracked diff.

**Console committed and hardened since this handoff was last accurate.**
The console landed as `079dced`, with a CI workflow to validate it
(`83bdad1`, `frontend-ci.yml`: lint, typecheck, Vitest, build, performance
budget) added the same day. Two follow-up fixes: `ac6fc6c` allows the local
Playwright dev origin (`127.0.0.1`) in `next.config.ts`; `42a1312` hardens
console responsiveness and operator-context handling across the overview,
opportunities, problems, reports, and signals views plus shared nav/layout
components, with matching component and E2E test updates. The E2E /
visual-verification limitation described above was specific to the
original development machine (`/Users/mac/...`); it has not been
re-verified since, and no later commit resolves it — Playwright browser
install/launch on whatever machine continues this work still needs its own
check before relying on `npm run test:e2e` output.

## Part 0a: Adaptive Scheduler milestone (`c32d206`, committed 2026-08-22)

Schema v10's `collector_state` is now operational. `backend/scheduler.py`
provides injected-clock, typed state/decision/plan objects; provisions each
known source for newly active domains; gates on enabled state, configuration,
interval, backoff, and quota; resets quotas lazily; and persists each attempt
in its own transaction. A zero-signal collection is success. Attempt outcomes
are success, transient failure, rate limited, or configuration failure;
disabled, unconfigured, not-due, backoff, and quota-gated sources are planner
skips and do not consume quota.

`BaseCollector.collect_with_outcome()` is the non-breaking structured boundary
for scheduled runs; legacy `collect() -> list[Signal]` remains intact. The
canonical pipeline accepts a scheduler source plan. HN is fetched once when it
is due for any active domain, fanned only to HN-due domains, and has its one
physical result persisted independently for every participating `(hn, domain)`
state row. If nothing is due, pipeline stages and report generation do not run.
Manual `/api/v1/pipeline/run` remains a full-run override because it calls the
pipeline without a source plan.

`collect.py` plans and executes scheduled runs through that canonical path and
always snapshots initialized scheduler state in `finally`, including after a
later critical stage failure. `.github/workflows/collect.yml` is now an hourly
heartbeat and supplies its built-in `github.token` as `GITHUB_TOKEN` for the
GitHub collector; it does not globally force HN-only mode when Reddit is
unconfigured. The first real hourly run must confirm that `github.token`
authenticates the collector's GitHub Search requests. No schema-v10 table shape
changed; change detection, watchlists, alerts, delivery, and Admin Console work
remain outside this milestone.

Coverage: `backend/tests/test_scheduler.py` adds deterministic due, isolation,
HN fan-out, outcome, backoff, quota, partial-durability, manual-override, and
workflow tests. `pandas==2.3.3` was added to `backend/requirements.txt` because
the existing Google Trends collector/tests require it.

**Follow-up fix, same day (`4c3bac8`):** the partial-run durability test was
patching `persistence.BACKUP_DIR` for isolation but not `persistence.config.DB_PATH`,
so `collect.py`'s snapshot-on-exit path could still touch the real/shared
database path during that test rather than the fixture's `fresh_db`. One-line
fix, consistent with the project's standing CI-discipline principle that
pipeline tests must not leak outside their fixtures.

## Part 0b: Dependency/security maintenance, public-repo hygiene, and RSS/Trends aggregate-failure correction (2026-08-27)

Three small, independent pieces of work landed after the scheduler and
console milestones above:

**Dependency/security update (`4dfd685`):** `backend/requirements.txt`
bumped `requests` 2.32.3 → 2.33.0, `pytest` 8.3.2 → 9.0.3, and
`pytest-asyncio` 0.23.8 → 1.3.0. No source changes required; full backend
suite passed unchanged after the bump.

**Public README modernization and repository hygiene (`c7ffcfc`,
`2e03e90`):** `README.md` was substantially shortened and modernized for a
public audience (219 → ~96 net lines). `2e03e90` separately reduced the
operational detail exposed in `.env.example` and a console error boundary
(`app/error.tsx`), and added a `.gitignore` entry. Neither commit changes
behavior; both are presentation/disclosure cleanup for a public repository.

**RSS/Trends aggregate-failure correction (`cb38922`):** closes a
scheduler-observability gap that predates the adaptive scheduler itself but
only became consequential once the scheduler started acting on collector
outcomes automatically. RSS and Trends deliberately tolerate individual
feed/keyword failures — one bad source must not kill the whole collector
run — but `_fetch()` previously returned normally with zero signals even
when *every* attempted source failed in a given run, so
`collect_with_outcome()` recorded `SUCCESS`. That's indistinguishable from a
quiet day with no new signals, and would have silently reset
`scheduler.record_outcome()`'s `consecutive_failures`/backoff state on what
was actually a full outage.

Fix: both collectors now track `attempted`/`failed` counts across their
per-source loop; if every attempted source failed, `_fetch()` raises
`CollectorError`, which flows through the existing (unmodified)
`TRANSIENT_FAILURE` path in `collect_with_outcome()` and
`scheduler.record_outcome()`. No new fields, no schema change — this was a
gap in the existing outcome-classification path, not a new mechanism.
Partial success (any source succeeding, even with 0 items), nothing-attempted
(no sources configured, or limit already satisfied by earlier sources), and
`RateLimitError`'s existing immediate-propagation behavior are all
unaffected and covered by new regression tests.

Ten focused tests added across `tests/test_rss_collector.py` and
`tests/test_trends_collector.py` (all-fail, partial-fail, all-succeed-with-
zero-items, nothing-attempted, and rate-limit-still-propagates, for each
collector). Full backend suite: 726 passed in an environment with `pytrends`
installed (716 pre-existing + 10 new); 2 of the pre-existing tests are
`skipif`-gated on `pytrends` being installed and will show as skipped
instead in an environment without it — same pre-existing condition as
before this fix, not a regression.

Files touched: `backend/collectors/rss_collector.py`,
`backend/collectors/trends_collector.py`,
`backend/tests/test_rss_collector.py`, `backend/tests/test_trends_collector.py`.
Nothing else — no schema, scheduler, frontend, or documentation changes in
this commit.

## Part 0c: Change Detection V1, Read-Side V1, and E2E stabilization (2026-08-27 – 2026-08-28)

Two reviewed, approved milestones — each preceded by its own audit/design
step per the project's standing engineering-governance workflow — turned
schema v10's `change_events`/`operator_state` from schema-only foundations
into an actually-produced, actually-queryable, actually-acknowledgeable
contract. A short E2E-stabilization tail followed once hosted CI exercised
the read-side for real.

**Change Detection V1 (`9fa09d0`).** New `backend/opportunity_engine/
change_detection.py`, wired as Stage 3.6 in `pipeline.py` (after lifecycle,
before report generation). Deliberately a *projection* layer, not a second
intelligence engine — it relabels decisions `lifecycle.py`/`canonicalizer.py`
already made and already wrote to `problem_history`, plus one genuinely new
comparison (Opportunity tier movement, since Opportunities have no history
table — ADR-002 immutability). V1 vocabulary: `problem_created`,
`problem_lifecycle_changed`, `problem_trend_changed`, `new_opportunity`
(first-ever Opportunity for a Problem), `opportunity_tier_crossed` (tier
differs from the immediately preceding Opportunity, either direction — a
downward crossing is kept, not suppressed, since deteriorating evidence is
intelligence too). `problem_history.evidence_added` is suppressed entirely
— it fires on nearly every recurrence match, every run, and would dominate
the log. Significance is a static `normal`/`high` lookup table (no LLM, no
learned model): `problem_created` and `archived→reactivated` and
`→growing` and crossing into gold are `high`; everything else is `normal`.
Idempotency is deterministic, not query-window-dependent:
`change_events.id` is derived via `uuid5` from the source `problem_history`
row id (or the Opportunity id + event type), so `INSERT OR IGNORE` makes
retry/replay/backfill naturally safe — this was a deliberate choice to
avoid changing `canonicalizer.py`/`lifecycle.py`'s already-tested return
contracts for this feature alone. 28 new tests. Full backend suite: 754
passed at this commit.

**Change Detection Read-Side V1 (`9126d8f`).** New `GET /api/v1/changes`
(filterable browse, `detected_at DESC`, `entity_title` resolved via a
single query with two conditional `LEFT JOIN`s — no N+1), `GET /api/v1/
changes/unseen` (the canonical acknowledgeable snapshot — deliberately
global and unfiltered, no domain/significance/event_type params at all,
since `operator_state` has exactly one checkpoint and exposing filters
here would misleadingly imply a filtered slice could be acknowledged
independently), and `POST /api/v1/operator-state/ack` (the only route
that may ever write `operator_state.last_seen_at`). All three require
`auth.get_current_actor`, matching `problems.py`'s stricter, more recent
convention of protecting GETs too.

Unseen semantics: `snapshot_at` is captured (`database._now()`) *before*
querying `change_events`, and is the only value the console should ever
send back as an acknowledgement watermark — never click time, never the
browser's clock. The boundary is `created_at > last_seen_at AND
created_at <= snapshot_at` — deliberately `created_at` (row-insertion
time), not `detected_at` (the underlying fact's timestamp), so a future
backfilled row with an old `detected_at` but a brand-new `created_at`
is still correctly treated as unseen. An empty `last_seen_at` (never
acknowledged) omits the lower bound entirely — "never checked" means
everything is unseen, not nothing.

Acknowledgement: `last_seen_at = MAX(current, MIN(as_of, now))` in one
atomic `UPDATE` — monotonic (never regresses), idempotent (a duplicate
or older `as_of` is a no-op), clamped to server time (defends against a
skewed or malicious client's future timestamp), and global by design —
no domain parameter exists on the route at all. GET routes never mutate
`operator_state` under any circumstance, tested explicitly. The race
this was built to survive: an event arriving between when the operator's
view was fetched and when they click acknowledge must not be silently
swallowed — proven by a test that inserts a new event strictly after a
captured `snapshot_at`, then acknowledges with that stale `snapshot_at`,
and asserts the new event is still unseen afterward.

Console: Overview's "What changed since last looked — Unavailable"
placeholder is replaced with a real panel — unseen count, up to 5
recent/high-significance changes each linked to their Problem or
Opportunity, and an explicit `acknowledgeCurrentChanges` Server Action
(mirroring the existing `reviewOpportunityStatus` action's shape) that
only ever fires on a real form submit, carrying the `snapshot_at` a
prior `GET /changes/unseen` returned. No dedicated `/changes` browsing
page was built — deliberately deferred until this contract had a proven
consumer; see Part 4 for current status. 40 new backend tests, 2 new
frontend unit tests, 1 new E2E test. Full backend suite: 794 passed;
frontend: lint/typecheck clean, vitest 19/19, build succeeds,
performance budget 126.2 KiB gzip (150 KiB budget) — all at this commit.

**E2E stabilization (`d57f135` reverted, `8d45601`, `b13782c`).** Hosted
Frontend CI failed on `9126d8f`'s Playwright run — diagnosed from actual
CI logs, not inferred from a screenshot, across three iterations:

1. First hypothesis (cold Next.js dev-compile timing) was wrong —
   `d57f135` bumped Playwright's default `expect()` timeout to 10s: on
   the next hosted run, the *same* assertion still failed at exactly
   the new 10s limit, proving it was never a timing issue. Reverted in
   `8d45601`.
2. Real cause #1: `tests/e2e/start.mjs` hardcoded its `now` timestamp as
   a frozen calendar literal (`"2026-08-21T12:00:00+00:00"`).
   `isStale()` compares mock freshness timestamps against real
   `Date.now()` with a 36-hour window; once real time passed that
   window, "API + evidence fresh" could never render again, forever —
   deterministic, not flaky. Fixed in `8d45601` by computing `now` at
   server-start time instead.
3. Real cause #2, surfaced only once cause #1 was fixed (the suite
   could now progress far enough to expose it): the mock's `/changes/
   unseen` handler still hardcoded `snapshot_at` to a frozen literal a
   week earlier than the (now-dynamic) `changeEvent.created_at` —
   acknowledging with it could never actually clear the unseen count.
   Fixed in `b13782c` by computing `snapshot_at` per-request inside the
   handler, matching the real backend's own `snapshot_at =
   database._now()` pattern.

No application or backend code was touched by any of these three
commits, and no assertion was weakened at any point — both real fixes
were in the E2E mock fixture only. Hosted Frontend CI on `b13782c`:
green, all steps including "Run end-to-end tests" passing at the step
level (confirmed via the GitHub Actions API, not just the job rollup).
This sandbox still cannot run Playwright locally (`cdn.playwright.dev`
blocked by network egress here) — every iteration above was verified
against real hosted CI logs, not a local run.

## Part 0d: Operations Visibility, Multi-Source Expansion, Canonical Persistence, and Condition State Evaluation

**Collector Operations Visibility:** `GET /api/v1/system/collector-operations` exposes current collector run status, intervals, backoff, and quota consumption from `collector_state`. The Operations Console `/system` page renders live collector operational visibility.

**NIC-14 Deterministic Correlation Safety:** Strengthened topic-matching in `opportunity_engine/detector.py`. Entity-cluster correlation requires verified topical evidence to join a problem cluster, and non-topical effort-expression spans are filtered to prevent false-positive joins.

**Multi-Source Collector Expansion:**
- **StackExchangeCollector:** Ingests developer questions and pain points via the official Stack Exchange `/questions` API across 7 curated technical tags (`saas`, `automation`, `api-design`, `stripe`, `multitenancy`, `subscription`, `pricing`).
- **GreenhouseJobsCollector:** Ingests public job postings across configured SaaS company boards as hiring demand signals with deterministic per-board fairness allocation preventing starvation, and a 30-day lookback window.
- **SECEdgarCollector:** Ingests material corporate change signals from official SEC EDGAR Form 8-K and 8-K/A filings across enterprise SaaS companies, enforcing strict parallel required-array length validation (`form`, `accessionNumber`, `filingDate`) to surface malformed SEC submissions.

**NIC-13 Canonical SQLite Snapshot Continuity:** Single-file canonical artifact authority (`bia-database-canonical` carrying `bia-latest.db`) generated using SQLite's backup API. The hourly workflow restores only the newest non-expired canonical artifact; a one-time migration path handles legacy backups. Strict `set -o pipefail` guards ensure that listing or download failures halt execution rather than falling back to unverified cache copies. A subsequent hotfix decoupled `gh api --paginate --slurp` from external `jq -r` for runner compatibility.
*Operational Status:* Done. Production verification completed successfully on hosted GitHub Actions run `33685932034` (manually triggered on commit `6e1c684`), confirming the full end-to-end cycle: authority discovery succeeded, newest legacy snapshot migrated, canonical database installed, collection pipeline executed, SQLite backup snapshot created, and canonical artifact `bia-database-canonical` published. Steady-state runs now restore directly from this canonical artifact.

**NIC-17 & NIC-18 Condition State Semantics:**
- **NIC-17 Evaluation Corpus:** 44-case Condition State evaluation dataset (`backend/tests/condition_state_eval/dataset.py`) using the NIC-15 EvidenceCase contract (32 Core, 12 Adversarial; 41 scored, 3 diagnostic) with literal target spans.
- **NIC-18 Frozen Rules Baseline:** Deterministic `rules-v1` reference baseline interpreter (`backend/tests/condition_state_eval/rules_interpreter.py`), metric evaluation harness (`evaluate.py`), and runner (`run_rules_baseline.py`), freezing deterministic reference performance prior to model evaluation.

**NIC-19 Condition State External-Model Experiment:**
- Completed and merged to `main` at `d865ae8f8f7ccffea78fcb7c22021876d5ff0118`. The accepted Gemini shadow-evaluation artifacts remain experimental evidence, not a production interpreter selection.

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
from that environment either. Schema v10's `collector_state` is now
consumed by the adaptive scheduler (see Part 0a); `change_events` is now
produced (Stage 3.6) and queryable (`GET /api/v1/changes`), and
`operator_state` is now actively read/written through explicit
acknowledgement (`POST /api/v1/operator-state/ack`) — see Part 0c for
both. `watchlists`/`alert_rules` still have no consumer — that remains
deliberately deferred.

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
17. ~~Second-domain data-source generalization~~ — done (`ac19d5c`).
    `extractor.py`, `canonicalizer.py`, `detector.py`'s cluster-acceptance
    gate, `pipeline.py`, and `watch_list.py`'s fallback gate are all
    domain-generic now. What's still genuinely open, not a gap in this
    pass: `extractor.py`'s `_infer_relationship()` and all of
    `explainer/opportunity.py`/`historical.py`/`trends.py`'s narrative
    logic — confirmed by inspection to be real editorial/semantic
    judgment calls, not vocabulary lookups, so deliberately left
    Business-hardcoded (now documented in each file, not just decided
    in conversation). A real second `DomainConfig` would work for
    extraction/detection/scoring today; its reports would still narrate
    in Business's own terms.
18. ~~Add GitHub, Google Trends, Stack Exchange, Greenhouse Jobs, and SEC EDGAR collectors~~ — done
    (`b5afceb`, `cfa8624`, `9b35708`, `9d5408d`, `a0bcf4c`). All five added collectors are integrated into
    the canonical pipeline, domain sources, and adaptive scheduler.
19. Reddit live validation — credentials were never configured in the
    environment this project has been developed in so far; the
    collector has only ever been exercised via its unit tests (canned
    fixtures) and its graceful-failure path (missing credentials),
    never against the real Reddit API.
20. ~~Continuous Intelligence Engine: the adaptive scheduler~~ — done
    (`c32d206`, hardened by `4c3bac8`; see Part 0a). `collector_state`
    gates the hourly outer heartbeat and records per-source/domain
    outcomes.
20a. ~~RSS/Trends aggregate-failure outcome correctness~~ — done
    (`cb38922`; see Part 0b). Closes the gap where a fully-failed
    RSS/Trends run was indistinguishable from a quiet no-op run at the
    scheduler-outcome level.
20b. ~~Collector operations visibility~~ — done (see Part 0d).
    `GET /api/v1/system/collector-operations` and Console `/system` page render live status.
20c. ~~SQLite snapshot continuity (NIC-13 Phase 1)~~ — done (see Part 0d).
    Production-verified on hosted CI via manual run 33685932034.
20d. ~~Deterministic correlation safety (NIC-14)~~ — done (see Part 0d).
    Topic-matching hardened in `detector.py`.
20e. ~~Condition State evaluation dataset and rules baseline (NIC-17 & NIC-18)~~ — done (see Part 0d).
    44-case dataset and frozen rules-v1 baseline interpreter.
21. ~~The frontend~~ — done for its originally-scoped surface (`079dced`,
    hardened `42a1312`; see Part 0), with the Overview "what changed"
    panel added on top (`9126d8f`; see Part 0c) and System health collector operations
    visibility added on top (see Part 0d). Still no dedicated
    Collectors, Pipeline, or Change Events browsing UI, and no
    Watchlists/Alert Rules UI — the latter two's operational contracts
    still don't exist (see item 22a). A dedicated `/changes` browse
    page was deliberately deferred even though its backend contract now
    exists, per the reviewed read-side design.
22. ~~Change detection~~ — done. Write side (`9fa09d0`) and read side
    (`9126d8f`), both reviewed/approved before implementation; see
    Part 0c for full detail. `change_events` is produced and queryable;
    `operator_state.last_seen_at` is actively used through explicit,
    global, monotonic, idempotent acknowledgement. Significance
    ranking is the static `normal`/`high` model shipped with V1 — see
    Part 0c; no separate ranking system was built, and none is
    currently planned beyond that static table.
22a. **Alert delivery, and watchlists/alert_rules consumption** — still
    undesigned and unimplemented. `watchlists`/`alert_rules` remain
    schema-only, with no consumer anywhere in `backend/` (confirmed by
    inspection, unchanged since v10 was written) and no delivery
    channel by design. This was and remains explicitly out of scope for
    both Change Detection milestones — building it requires its own
    design proposal, not an extension of the read-side's `GET /changes`
    contract.
23. **Semantic evaluation progression:**
    The established semantic sequence is:
    `NIC-19 → NIC-20 → NIC-5 → NIC-6 → NIC-7 → NIC-8 → NIC-9`.
    NIC-19 is complete. NIC-20's evidence review is complete in PR #14 and recommends
    **GO for NIC-5 permanent `InterpretedObservation` design only**. NIC-5 is next;
    no production interpreter has been selected. The unresolved evidence questions
    identified by the review remain open and must not be pre-decided in the design.

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
9. Adaptive scheduler implemented and committed (`c32d206`) — see
   Part 0a.
10. BIA Operations Console Phase 1 added (`079dced`), with a frontend CI
    workflow (`83bdad1`), a local-dev Playwright origin fix (`ac6fc6c`),
    and a responsiveness/operator-context hardening pass (`42a1312`) —
    see Part 0.
11. Scheduler durability test isolation fix — the partial-run durability
    test wasn't isolating `persistence.config.DB_PATH`, only
    `persistence.BACKUP_DIR` (`4c3bac8`) — see Part 0a.
12. Backend dependency/security maintenance: `requests`, `pytest`,
    `pytest-asyncio` bumped (`4dfd685`) — see Part 0b.
13. Public README modernization (`c7ffcfc`) and operational-detail
    minimization in `.env.example`/console error boundary (`2e03e90`) —
    see Part 0b.
14. RSS/Trends aggregate-failure outcome correction (`cb38922`) — see
    Part 0b and Part 4 item 20a.
15. Change Detection V1 (`9fa09d0`) — see Part 0c and Part 4 item 22.
16. Change Detection Read-Side V1 (`9126d8f`) — see Part 0c and Part 4
    item 22.
17. E2E stabilization for the read-side's hosted CI run — `d57f135`
    (reverted), `8d45601`, `b13782c` — see Part 0c.
18. Operations visibility, correlation safety hardening, multi-source expansion (Stack Exchange, Greenhouse, SEC EDGAR), canonical SQLite persistence, and Condition State frozen rules baseline — see Part 0d.

**Token handling note, still relevant for whoever continues this:**
every GitHub Personal Access Token used in this project's history was
pasted directly into chat and therefore treated as compromised the
moment it appeared, regardless of whether it was used. None were ever
committed or written to any file in this repo. **Before pushing
anything, confirm no stale token is still live at
https://github.com/settings/tokens**, and treat any newly-provided token
the same way — use once, then revoke.

**Current state:** authoritative `main` is `d865ae8f8f7ccffea78fcb7c22021876d5ff0118` (merged NIC-19 accepted experiment). NIC-20's documentation-only evidence review is pending in PR #14; it does not change production semantics. The backend suite passes in the project environment. Two Google Trends exception-mapping tests are conditionally skipped when pytrends is unavailable outside the project environment. Frontend: `npm run lint`/`typecheck` clean, `npm test` (Vitest) passing, production `npm run build` succeeds, `npm run check:performance` within budget. Hosted CI collection workflow is operational on canonical snapshot continuity (verified via manual run 33685932034). The next scheduled collection run should exercise steady-state restoration from bia-database-canonical; this is observational follow-up and does not block NIC-13 completion.

**Open items, current as of this revision (see Part 4 for full detail on each):**

- **NIC-20 review / NIC-5 handoff:** the [canonical NIC-20 evidence review](experiments/nic-20/CONDITION_STATE_EVIDENCE_REVIEW.md) is complete in PR #14 and recommends GO for permanent `InterpretedObservation` **design only**. NIC-5 is next, but future work must first read the authoritative NIC-5 issue in Linear. No production interpreter has been selected; unresolved questions about attribution and question diagnostics, abstention, condition segmentation, temporal/recurrence normalization, cross-source contradiction/source authority, and absent holdout evidence remain open.
- **Alert delivery and watchlists/alert_rules consumption** (item 22a) — still undesigned and unimplemented, schema-only, no delivery channel by design.
- **A dedicated `/changes` Console browsing page** (item 21) — backend contract exists; full dedicated browse/filter page remains open.
- **`explainer/*`'s narrative layer** (item 17's remaining half) and **RFC-001 implementation** (item 13) — unchanged.
- **`GET /reports` domain filter** (item 15) — small, still open.

This handoff makes no recommendation among these for what to do next —
that determination, per the project's standing engineering-governance
workflow, belongs to its own audit/design step, not this refresh.
