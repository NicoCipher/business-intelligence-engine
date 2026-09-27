# BIA Project Handoff

Updated 2026-09-27 against current `main` at `09c1a6f37b97f480c1407a5ec39cee5e830374f2`.

This file is the **current orientation handoff**, not a historical diary. When this handoff, an old chat, an older commit, or another document conflicts with the live repository or Linear, verify current `main` and the authoritative Linear issue before acting.

Useful references:

- `docs/ARCHITECTURE.md` — implemented architecture and responsibility boundaries
- `docs/architecture/INTERPRETED_OBSERVATION_V1_FIELD_DISPOSITION_AND_INVARIANTS.md` — approved Observation V1 contract
- `docs/architecture/OBSERVATION_V1_BACKEND_INTEGRATION_PLAN.md` — approved backend integration design
- `docs/adr/` — accepted architectural decisions
- `docs/rfc/` — pipeline-level proposals and decisions
- `docs/experiments/` — semantic experiment evidence
- Linear project `BIA` — current sequencing, blockers, and issue state
- `backend/database.py` — current schema authority when schema docs disagree

> Documentation drift note: `backend/database.py` currently declares **schema v11**, while `docs/SCHEMA.md` still says v9. Treat the code as authoritative until the schema history document is refreshed.

---

## 1. Current Position

BIA is past the basic-backend stage and is now in the **Semantic Understanding Foundation** phase.

The collection, persistence, scheduling, canonical Problem memory, Opportunity generation, change detection, reporting, internal Operations Console, and durable SQLite snapshot foundations already exist.

The central architecture problem is no longer “collect more data.” It is:

> **What is each piece of evidence actually saying, and what is BIA allowed to infer from it?**

The project is therefore moving from:

`raw Signal text → deterministic heuristics → intelligence`

toward:

`Signal → InterpretedObservation → validated reasoning → downstream intelligence`

without turning BIA into an LLM wrapper.

The Greenhouse false-positive incident demonstrated why this boundary matters: source text can contain business-looking vocabulary without proving customer pain, demand, willingness to pay, or an Opportunity.

---

## 2. Authoritative Repository State

Current `main`:

`09c1a6f37b97f480c1407a5ec39cee5e830374f2`

Latest main commit:

`fix(security): patch Next.js AVIF RCE`

Important merged semantic-foundation commits before it include:

- `a5af927bdb0a24e1a6f2d9aa9d94831db9ff68ab` — BIA-56 / BIA-8.1, immutable Observation persistence
- `16269e9560f24308611769365b51912952c6b08b` — BIA-57 / BIA-8.2, canonical persisted Signal identity
- PR #20 — Observation V1 contract corpus / BIA-7

Current schema version in `backend/database.py` is **v11**.

The project remains **single-operator**. Do not introduce users, tenants, RBAC, OAuth, or multi-user ownership into existing state without an explicit architecture decision.

The Python backend and Next.js Operations Console now live in the same repository.

---

## 3. What BIA Can Do Today

### Collection

The canonical backend has collectors for:

- Hacker News
- RSS
- GitHub
- Google Trends
- Stack Exchange
- Greenhouse Jobs
- SEC EDGAR Form 8-K / 8-K/A

Reddit collector code exists, but dependable live Reddit production collection remains an operational gap.

Collectors produce immutable `Signal` evidence. Collection-time metadata must remain factual/source-derived; collectors must not manufacture downstream business meaning.

### Durable operation

BIA has:

- adaptive source/domain scheduling
- failure/backoff/quota handling
- hourly GitHub Actions collection heartbeat
- canonical SQLite snapshot continuity
- pipeline/report locking and snapshot safety
- failure isolation between collectors and stages

### Knowledge and memory

BIA has:

- domain-scoped Entity/Relationship extraction
- knowledge-graph lifecycle decay
- canonical persistent `Problem` identity
- append-only `problem_history`
- Problem lifecycle and trend axes
- deterministic correlation hardening

Problems are the long-lived intelligence memory. Opportunities are dated assessments attached to Problems.

### Change intelligence

BIA produces `change_events` and maintains the operator acknowledgement watermark through `operator_state`.

Existing read-side includes:

- `GET /api/v1/changes`
- `GET /api/v1/changes/unseen`
- `POST /api/v1/operator-state/ack`

### Operations Console

The internal Next.js console includes:

- Overview
- Signals
- Problems
- Opportunities
- Reports
- System

Collector operations are exposed through:

`GET /api/v1/system/collectors`

The console remains a private/single-operator surface, not a public multi-user product.

---

## 4. Semantic Understanding Work Already Completed

The controlled Condition State experiment established evidence for designing a production interpretation layer without granting an external model production authority.

Completed foundation work includes:

- **BIA-15** — Condition State experiment contract
- **BIA-17** — 44-case evaluation corpus
- **BIA-18** — deterministic rules baseline
- **BIA-19** — external-model comparison
- **BIA-20** — evidence review
- **BIA-5** — production Observation V1 data contract
- **BIA-6** — Observation V1 backend integration design
- **BIA-7** — production Observation V1 contract tests
- **BIA-8.1 / BIA-56** — Observation persistence and immutable models
- **BIA-8.2 / BIA-57** — canonical persisted Signal identity

The accepted Gemini experiment remains **offline/shadow evidence only**. It did not select a production model or give model confidence the meaning of BIA confidence.

Core Observation V1 boundaries now established include:

- interpretation derives from immutable Signals
- one Signal may produce zero or more observations
- literal evidence/citations must remain traceable to persisted Signal text
- semantic result and operational failure are different things
- corrections are historical/immutable rather than destructive rewrites
- Entity/Relationship extraction remains a sibling concern, not the Observation layer
- relevance, support/contradiction, Problem identity, scoring, Findings, and Opportunity decisions remain downstream responsibilities
- Observation output must not gain downstream production authority merely because a producer generated it

---

## 5. Current Active Mission — BIA-58 / BIA-8.3

The current active implementation issue is:

**BIA-58 — BIA-8.3: Implement Observation validation and persistence service**

Status in Linear: **In Progress**

Current implementation is in draft PR **#26**:

`feat(bia-58): add observation validation and persistence service`

Branch head recorded in the PR:

`7b49cbf246f29d23ebb4851756b81dd63cfb4e29`

The PR is **not merged into main**.

Its bounded scope is to:

- validate Observation citations against canonical persisted Signal title/content
- enforce exact evidence occurrence/support containment rules
- support exact-result reuse
- preserve immutable correction lineage
- persist Observation result/run state atomically
- keep operational failures separate from semantic results
- remain producer-neutral

Explicitly **out of scope for BIA-58**:

- pipeline activation
- automatic target discovery
- production producer selection
- downstream consumption of Observations
- scoring redesign
- Problem/Opportunity redesign
- LLM promotion

The PR reports:

- 29 focused BIA-58 tests passed
- 302 related tests passed
- 1,127 backend tests passed, 2 skipped
- scoped Ruff passed
- `git diff --check` passed
- schema remains v11

Treat those as PR verification claims until the actual diff/CI is independently reviewed.

---

## 6. Immediate Semantic Sequence

The authoritative active sequence is:

`BIA-58 / 8.3 → BIA-59 / 8.4 → BIA-60 / 8.5 → BIA-61 / 8.6 → BIA-62 / 8.7 → BIA-9`

### BIA-59 / BIA-8.4

Add the producer-neutral registry and supplied target-attempt boundary.

Do not choose a production interpretation model here.

### BIA-60 / BIA-8.5

Integrate Observation as a **shadow pipeline sibling**.

Observations may be generated and stored, but must remain isolated from existing downstream intelligence decisions.

### BIA-61 / BIA-8.6

Select and integrate the production Observation producer only after the producer-neutral infrastructure and shadow boundary exist.

Selection must follow evidence and evaluation, not convenience or vendor preference.

### BIA-62 / BIA-8.7

Verify the complete Observation V1 production path and hand off to BIA-9.

### BIA-9

Validate the real Observation V1 implementation before downstream use.

The trust-gate outcome must be evidence-based. Observation does not become authoritative merely because the pipeline runs successfully.

After BIA-9, the planned semantic sequence is:

`BIA-10 → BIA-11 → BIA-12`

- **BIA-10** — reconcile RFC-002 with the evidence-interpretation boundary
- **BIA-11** — design Investigation → Findings V1
- **BIA-12** — design contradiction-aware Analysis confidence semantics

Do not jump directly from Observation into scoring/recommendations.

---

## 7. Architecture Boundary to Protect

The intended direction remains approximately:

`Signal → [Knowledge Extraction + Evidence Interpretation] → Correlation → Problem → Investigation → Findings → Analysis → Opportunity → Change Detection / Advisory → Report`

The current production system has not completed that full transition yet. Existing downstream components still contain raw-text heuristics that predate Observation V1.

The important invariant is:

> **BIA must control what each piece of evidence is allowed to prove.**

BIA should own:

- evidence
- provenance
- durable memory
- deterministic system state
- evaluation
- architecture boundaries
- downstream decision authority

Models may propose interpretations. They do not become truth because they are confident, repeatable, or agree with another model.

A source constrains what evidence may reasonably prove, but do not hard-wire a permanent one-source-one-meaning ontology.

---

## 8. Machine Learning / LLM Position

No production deep-learning or backpropagation training loop is currently implemented or approved.

That is intentional.

The current priority is to build trustworthy semantic representation and provenance first. A future learned scoring/ranking system would need an explicit feedback/outcome architecture so BIA can distinguish a prediction from whether that prediction was later useful or correct.

Do not add neural-network training simply because PyTorch can be served behind FastAPI.

Likewise, do not make BIA dependent on an LLM before the Observation boundary, evaluation gates, and downstream authority rules are stable.

Current principle:

`strong deterministic/evidence architecture first → measured model assistance second → learned behavior only when outcomes justify it`

---

## 9. Greenhouse Containment Status

The Greenhouse production false-positive work is no longer the active blocker.

Completed:

- **BIA-30** — contain Greenhouse job-posting false-positive Opportunity origination
- **BIA-31** — prevent Greenhouse small clusters from re-entering the Opportunity Watch List

The containment remains intentionally narrow. It is not the permanent evidence-semantics architecture.

Known limitation still worth remembering: once a mixed cluster legitimately qualifies, legacy scoring can still read the full cluster, including Greenhouse text. Do not quietly reinterpret the temporary containment as a complete source-authority solution.

---

## 10. Known Open Work Outside the Immediate Chain

Real but not the current priority unless explicitly re-prioritized:

- Reddit live validation / dependable production collection
- actual `watchlists` / `alert_rules` consumers and alert delivery
- dedicated Change Events browse UI
- small `GET /reports` domain-filter parity gap
- Business-specific narrative logic still present in parts of `explainer/*`
- RFC-001 constitutional pipeline transition is not fully implemented
- multi-tenancy remains a future architecture decision
- evidence-quality weighting remains gated by demonstrated data/need
- deeper relationship hierarchy remains gated by demonstrated multi-hop evidence
- Outcome/feedback architecture for future machine learning has not yet been designed

Do not add more collectors merely to increase source count while the semantic evidence boundary is still being established.

---

## 11. Repository / Documentation Drift to Watch

Current known drift:

- `docs/SCHEMA.md` says v9, but `backend/database.py` is v11
- `docs/HANDOFF.md` was previously frozen at 2026-09-06 and incorrectly listed BIA-31 as active
- PR #23 (`docs: define shared Codex and Claude engineering contract`) is still open; the expanded repo-wide agent contract is therefore not yet part of current `main`

Do not assume an open PR is repository authority.

---

## 12. Engineering Governance

For architecture-sensitive work:

1. Select the mission from current Linear/repository state.
2. Verify current `main`, relevant architecture docs, schema/code, tests, and issue dependencies.
3. Keep the implementation bounded to the accepted contract and explicit non-goals.
4. Challenge architecture separately from implementation.
5. Verify focused tests plus full relevant regression.
6. Inspect the actual diff and CI; do not accept an implementation self-report as proof.
7. Preserve the user's merge decision.

Mechanical fixes can use a lighter process. Semantic architecture and trust-boundary work should use the full review sequence.

---

## 13. Immediate Handoff Instruction

If continuing BIA now:

1. Open **BIA-58** and draft PR **#26**.
2. Compare PR #26 against current `main` and the approved Observation V1 contract/integration plan.
3. Independently review the actual diff, especially citation validation, atomicity, result reuse, correction lineage, and failure semantics.
4. Verify the reported test/CI results.
5. Keep the PR producer-neutral and prevent downstream Observation consumption.
6. Merge only after review.
7. Then continue **BIA-59 / BIA-8.4**, followed by BIA-60, BIA-61, BIA-62, and the BIA-9 trust gate.

Do not begin BIA-10/11/12, model-dependent intelligence, or machine-learning feedback loops before the Observation V1 path is implemented and measured.
