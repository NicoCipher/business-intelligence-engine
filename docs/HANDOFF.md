# BIA Project Handoff

Updated 2026-09-06 through `4e10b8bb299b62e5d6fc28bd14e4a4c8b74f5273` (PR #15 merged).

This file is the **current orientation handoff**, not the full historical diary. The previous long-form handoff remains preserved in git history. For deeper detail, use:

- `docs/ARCHITECTURE.md` — current architecture and boundaries
- `docs/SCHEMA.md` — schema and migration history
- `docs/adr/` — bounded architectural decisions
- `docs/rfc/` — pipeline-level architecture proposals/decisions
- `docs/experiments/` — semantic experiment evidence
- Linear project `BIA` — current sequencing, blockers, and active issue state

When this handoff, an old chat, or a historical commit conflicts with the current repository or Linear, **verify current `main` and the authoritative Linear issue before acting**.

---

## 1. Current Position

BIA is past the basic-backend stage.

The collection, persistence, scheduling, canonical Problem memory, Opportunity generation, change detection, reporting, and internal Operations Console foundations exist and are working. The main architectural gap is now **semantic interpretation of evidence**: BIA still reasons too directly from raw Signal text in important places, which can confuse what a source says with what that source is actually allowed to prove.

The Greenhouse production false positive exposed this clearly. Job-posting boilerplate such as hiring language, salary text, and enterprise/B2B vocabulary can resemble customer demand to the current raw-text Opportunity gate even though a job listing is evidence of employer/labor investment, not direct customer pain or willingness to pay.

The project is therefore at the transition from:

`deterministic evidence pipeline`

into:

`evidence-aware semantic intelligence`

without turning BIA into an LLM wrapper.

---

## 2. Authoritative Repository State

Before this documentation refresh, authoritative `main` is:

`4e10b8bb299b62e5d6fc28bd14e4a4c8b74f5273`

That commit is the merge of PR #15:

`fix(opportunity-engine): temporary Greenhouse origination containment`

PR #15's hosted backend CI run #57 passed on the merge candidate with:

- **989 collected tests**
- **989 passed**
- Python 3.11

Schema is **v10**.

The project remains a **single-operator** system. Do not silently introduce users, tenants, RBAC, OAuth, or multi-user ownership into existing tables without an explicit architecture decision.

---

## 3. What BIA Can Do Today

### Collection

The canonical pipeline has collectors for:

- Hacker News
- RSS
- GitHub
- Google Trends
- Stack Exchange
- Greenhouse Jobs
- SEC EDGAR Form 8-K / 8-K/A
- Reddit collector code exists, but live Reddit validation/usable production collection remains an operational gap

Collectors produce immutable `Signal` evidence. Collection-time tags and metadata must remain factual/source-derived; collectors must not manufacture downstream business meaning.

### Durable operation

BIA has:

- adaptive per-source/per-domain scheduling via `collector_state`
- outcome-aware failure/backoff/quota handling
- hourly GitHub Actions heartbeat
- canonical SQLite snapshot continuity using `bia-database-canonical`
- pipeline/report locking and snapshot safety
- failure isolation so one collector/stage failure does not silently corrupt unrelated state

### Knowledge and memory

BIA has:

- domain-scoped Entity/Relationship extraction
- knowledge-graph lifecycle decay
- canonical persistent `Problem` identity
- append-only `problem_history`
- Problem lifecycle and trend axes
- deterministic correlation hardening

Problems are the persistent intelligence memory. Opportunities remain dated assessments linked to Problems, with the narrow pre-existing human-review `Opportunity.status` mutation as the known exception to otherwise historical Opportunity immutability.

### Change intelligence

BIA produces and exposes `change_events` and tracks the operator's acknowledgement watermark through `operator_state`.

Existing read-side includes:

- `GET /api/v1/changes`
- `GET /api/v1/changes/unseen`
- `POST /api/v1/operator-state/ack`

### Operations Console

The Next.js internal console includes the existing Overview, Signals, Problems, Opportunities, Reports, and System surfaces.

Collector operations are exposed by the actual current endpoint:

`GET /api/v1/system/collectors`

Do **not** use the old stale `/api/v1/system/collector-operations` path that appeared in earlier handoff revisions.

The console remains intended for private/single-operator use. Do not treat it as a public multi-user application without a separate deployment/auth design.

---

## 4. Semantic Understanding Work Completed

The controlled Condition State sequence was intentionally separated from production BIA semantics.

### NIC-15 — experiment contract

Defined the narrow Condition State task and evaluation rules.

### NIC-17 — evaluation corpus

Built the 44-case dataset:

- 32 Core
- 12 Adversarial
- 41 scored
- 3 diagnostic

### NIC-18 — frozen rules baseline

Implemented the deterministic `rules-v1` reference baseline. It is a comparison baseline only, not the production interpreter.

### NIC-19 — external model comparison

Completed and merged at:

`d865ae8f8f7ccffea78fcb7c22021876d5ff0118`

The accepted Gemini experiment remains **offline/shadow evidence only**. Model output did not gain production authority.

Accepted experiment evidence includes two same-configuration runs with 44/44 raw tuple agreement, 41 scored cases, 31 correct, zero critical active/resolved inversions, and ten expected-unknown over-assertions. There is no reproducibly materialized holdout; do not fabricate or reconstruct one.

### NIC-20 — evidence review

Completed and merged via PR #14 at:

`4efaacc152fda0f39b85c963b9c1ffe301a0873e`

Canonical review:

`docs/experiments/nic-20/CONDITION_STATE_EVIDENCE_REVIEW.md`

NIC-20 gives **GO for NIC-5 design only**.

It does **not** select a production model, promote Gemini, grant model confidence the meaning of BIA confidence, or give Condition State authority over Correlation, Problem identity, contradiction reasoning, scoring, Findings, or Opportunities.

Key supported implications include:

- one Signal may need zero or more interpreted observations
- literal evidence traceability is important
- `active | resolved | unknown` is sufficient only for the tested pre-segmented task, not all future semantic claims
- temporal/recurrence language should be preserved before inventing normalized counters or transitions
- semantic `unknown` must remain distinct from operational failure
- attribution/conflicting language must not be collapsed into false certainty

Important unresolved areas include attribution/questions, abstention semantics, automatic segmentation, time/recurrence normalization, cross-source contradiction/source authority, and absent holdout evidence.

---

## 5. Greenhouse False-Positive Containment

### NIC-30 / PR #15 — completed

Production evidence showed Greenhouse job postings could originate Opportunities from job-template vocabulary alone.

PR #15 added a **temporary, Greenhouse-only origination containment**:

- `greenhouse_jobs` cannot independently satisfy the Opportunity business-signal origination gate
- Greenhouse signals remain in clustering
- Greenhouse remains in cluster counts/source structure
- Greenhouse remains in scoring after a legitimate cluster qualifies
- Greenhouse remains in `signal_ids`, persistence, canonicalization, and Problem evidence
- a genuine non-Greenhouse qualifying signal can still originate a mixed cluster containing Greenhouse evidence
- `OpportunityScorer` is intentionally unchanged

This is containment, **not** the permanent evidence semantics architecture.

The unresolved scoring limitation is important: once a mixed cluster legitimately qualifies, Greenhouse text can still influence its score because the scorer continues to read the full cluster.

### Remaining leak: NIC-31 — active

PR #15 also made `build_watch_list()` exclude clusters already diagnosed as:

`no_originating_business_signal`

and added the human-readable rejection label:

`no qualifying originating business evidence`

However, `PatternDetector.diagnose()` still checks diagnostic size/source rules **before** the origination-policy diagnostic gate:

1. `too_small`
2. `single_source`
3. origination eligibility
4. scoring

Therefore a Greenhouse-only cluster with fewer than 5 signals may be labelled `too_small` or `single_source` before it can receive `no_originating_business_signal`. The Watch List can then re-evaluate that rejected raw text through its normal business-keyword fallback and surface it as a founder-facing candidate.

This is tracked in Linear as:

**NIC-31 — Prevent Greenhouse small clusters from re-entering the Opportunity Watch List**

Status: **In Progress**  
Priority: **High**

NIC-31 is the current active mission and blocks NIC-5.

Required bounded fix:

- in `PatternDetector.diagnose()`, clusters with zero origin-eligible signals must receive `no_originating_business_signal` before `too_small` / `single_source`
- this precedence adjustment is diagnostic/reporting coherence only; do not change `detect()` / `detect_and_persist()` persistence semantics
- the Watch List must continue treating `no_originating_business_signal` as a hard admission exclusion
- `watch_list.py` remains source-blind; do not add `greenhouse_jobs` policy there
- preserve genuine non-Greenhouse `too_small` / `single_source` Watch List behavior

Do not expand NIC-31 into scoring redesign, source-capability architecture, schema work, or NIC-5 implementation.

---

## 6. Next Semantic Roadmap

The authoritative immediate sequence is:

`NIC-31 → NIC-5 → NIC-6 → NIC-7 → NIC-8 → NIC-9 → NIC-10 → NIC-11 → NIC-12`

### NIC-5 — Define production Observation V1 data contract

**Design only.** No schema migration or implementation.

Define the smallest permanent `InterpretedObservation` contract justified by evidence.

Existing boundaries to preserve unless evidence demonstrates otherwise:

- interpretation derives from immutable Signals
- interpretation is independent of Entity/Relationship Extraction
- one Signal may produce zero or more observations
- evidence spans preserve traceability
- downstream code must not repeatedly reinterpret raw text
- relevance, support/contradiction, Problem identity, scoring, Findings, and Correlation remain downstream responsibilities
- do not add fields because an external model happened to return them
- C2/C4 remain Correlation problems unless evidence demonstrates otherwise

NIC-5 must explicitly evaluate, not assume, concepts such as condition state, multiple observations, temporal scope, attribution, recurrence, `topic_key`, and generic fact/assertion classification.

### NIC-6 — backend integration design

Design storage/transience, versioning, replay/reprocessing, pipeline position, provenance, failure isolation, migration/backfill behavior, and interpreter approval semantics.

No implementation.

### NIC-7 — production Observation evaluation contract

Add reviewed evaluation cases for only the semantics actually approved in NIC-5/NIC-6. Preserve existing semantic controls and explicitly distinguish supported behavior from known limitations.

### NIC-8 — implementation

Implement the approved production-compatible Observation V1 path.

Observation output must remain isolated from production downstream intelligence decisions until measured.

### NIC-9 — trust gate

Measure the real implementation. Do not tune the implementation merely to improve the reported evaluation result.

Decision must be one of:

- approved for next downstream design stage
- needs correction and re-test
- must remain isolated

### NIC-10 → NIC-12

After Observation V1 is measured:

- NIC-10 reconciles RFC-002 with the evidence-interpretation boundary
- NIC-11 designs Investigation → Findings V1
- NIC-12 designs contradiction-aware Analysis confidence semantics

Do not jump directly from Observation to scoring/recommendations without these gates.

---

## 7. Architecture Boundary to Protect

The intended direction is:

`Signal → sibling Knowledge Extraction + Evidence Interpretation → Correlation → Problem → Investigation → Findings → Analysis → Opportunity → Change Detection / Advisory → Report`

The exact RFC-001 transition is not fully implemented yet, but the responsibility boundaries matter now.

BIA should own:

- evidence
- provenance
- memory
- deterministic state
- evaluation
- architecture boundaries
- downstream decision rules

Models may propose interpretations. They do not become truth merely because they are confident, repeatable, or agree with another model.

A source constrains what evidence may reasonably prove, but individual Signals still require interpretation. Do not hard-wire a permanent one-source-one-meaning ontology.

The central semantic discipline is:

> BIA must control what each piece of evidence is allowed to prove.

---

## 8. Engineering Governance

Canonical operating rule:

> **No agent gets authority merely because it wrote the code, wrote the test, or produced a green report. Evidence passes through independent gates before BIA changes.**

For architecture-sensitive work use:

1. Mission selected from authoritative roadmap/Linear.
2. Authoritative state check: current `main`, relevant ADR/RFC/HANDOFF, schema history, implementation, tests, and issue dependencies.
3. Architecture/spec review: smallest acceptable behavior, explicit non-goals, risks, invariants, acceptance criteria. No implementation during architecture-only phases.
4. Independent challenge: another reviewer/model/session actively tries to break the proposal before coding.
5. Implementation against the approved contract. Tests are part of the contract, not the whole contract.
6. Verification: focused tests, full regression, relevant migration/snapshot/frontend gates, diff-scope check, CI.
7. Independent final review of the actual raw diff and CI output.
8. User merge decision.

Do not trust implementation self-reports in place of inspecting the actual diff and CI.

Mechanical/bounded tasks can use a lighter version of this flow. Semantic architecture such as NIC-5 should use the full challenge/review sequence.

---

## 9. Known Open Work Outside the Immediate Semantic Chain

These remain real but are not the active priority unless explicitly re-prioritized:

- alert delivery and actual `watchlists` / `alert_rules` consumers remain undesigned
- dedicated Change Events browse UI remains optional/deferred; backend read contract already exists
- `GET /reports` still lacks the small domain-filter parity improvement
- Business-specific narrative logic remains in parts of `explainer/*`
- RFC-001 constitutional pipeline transition is not fully implemented
- Reddit live validation remains unresolved
- multi-tenancy remains a future architecture decision, not current implementation scope
- evidence-quality weighting and deeper relationship hierarchy remain gated by demonstrated need/data

Do not add more collectors merely to increase source count while the evidence-semantics boundary is still being established.

---

## 10. Operational Notes

- Canonical persistence authority is the SQLite snapshot artifact path already established by NIC-13.
- SEC EDGAR collection requires `SEC_EDGAR_USER_AGENT`; workflow secret wiring has been fixed. If production behavior is in question, verify a natural scheduled run rather than assuming configuration from code alone.
- Google Trends depends on `pytrends` and has historically been the least reliable external source; do not treat fixture success as proof of provider stability.
- Reddit remains the largest missing direct community/problem-demand source operationally, but source expansion is secondary to semantic correctness right now.
- `watchlists` and `alert_rules` are schema foundations only; do not claim alert delivery exists.

---

## 11. Immediate Handoff Instruction

If continuing the project now:

1. Read **NIC-31** in Linear.
2. Verify current `main` before coding.
3. Fix only the Greenhouse small-cluster diagnostic/reporting precedence leak.
4. Run focused detector/explainer tests and the full backend suite.
5. Review the actual diff independently before merge.
6. Close NIC-31 only after the fix is merged and verified.
7. Then begin **NIC-5 design**, not implementation.

Do not skip NIC-31, and do not start permanent Observation implementation before NIC-5 → NIC-6 → NIC-7 have completed their design/evaluation gates.
