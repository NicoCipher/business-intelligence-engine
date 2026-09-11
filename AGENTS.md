<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# BIA Agent Engineering Contract

This file is the repo-wide operating contract for coding agents and contributors. `CLAUDE.md` imports this file; do not create a second, divergent set of Claude-specific engineering rules. Codex and Claude are peers under the same architecture and verification requirements.

## 1. Before changing anything

Do not code from chat memory, an old handoff, or an issue title alone.

1. Inspect the current branch and current `main` before deciding what exists.
2. Read the actual task/Linear issue when one is referenced. Use it for scope, sequencing, acceptance criteria, and blockers; it does not override canonical architecture.
3. Read the smallest relevant authoritative docs before editing code:
   - `docs/architecture/00_ARCHITECTURE_SPECIFICATION.md` and the relevant handbook files for architectural intent and invariants.
   - `docs/ARCHITECTURE.md` for current implementation shape and known implementation constraints.
   - `docs/SCHEMA.md` plus `backend/database.py` for persistence and migration truth.
   - `docs/adr/` for bounded accepted decisions and their supersession history.
   - `docs/rfc/` for larger architecture proposals/decisions; check each document's status before treating it as implemented.
   - `docs/HANDOFF.md` for orientation only. It can lag `main`; verify repository state and the current Linear issue before acting on its "next" instructions.
4. Inspect the implementation and relevant tests. Tests describe expected implementation behavior but do not outrank architecture.

If sources conflict, do not quietly choose the one that makes the requested implementation easiest. Resolve the conflict by authority and freshness, and surface a real architecture contradiction before proceeding.

## 2. Authority and scope

Architectural authority follows the repository's governance model:

`Architecture Specification → Architectural Invariants/Handbook → accepted ADR/RFC decisions → implementation → tests`

Current-state questions require an additional freshness rule: current `main`, current schema code, and the authoritative current task outrank stale handoffs, chats, historical commits, and old implementation notes.

Keep work bounded to the requested mission. Do not expand a bug fix into a redesign, a design task into implementation, or a refactor into semantic behavior changes. If adjacent problems are discovered, report them separately unless they block the task.

## 3. BIA invariants to preserve

These are not convenience preferences.

- **Evidence first.** Every conclusion must remain traceable to observable evidence and provenance.
- **Signals are immutable source evidence.** Do not rewrite source text or collection facts to fit later interpretation.
- **Interpretation is not source truth.** Interpreted Observations are derived records, not claims that the source or BIA has proven the interpretation true.
- **Observation persistence is append-only.** Corrections create new immutable records with explicit lineage; do not update, delete, replace, or bypass the persistence constraints protecting retained Observation/run provenance.
- **Persistence does not grant authority.** Observation records do not automatically become inputs to Correlation, Problems, Opportunities, scoring, Findings, reports, APIs, or frontend merely because they are stored. Downstream consumption requires an explicit approved architecture step.
- **Evidence Interpretation and Knowledge Extraction are sibling responsibilities.** Do not make Entity/Relationship extraction silently depend on Observation semantics or vice versa without an explicit architecture change.
- **Problem is the persistent canonical identity.** Problem current state may evolve through its approved lifecycle/trend mechanisms; its history remains append-only.
- **Opportunity is a dated historical assessment linked to a Problem.** Do not turn Opportunity into the long-lived canonical identity. Preserve the narrow existing human-review status behavior rather than generalizing it into mutable historical evidence.
- **Reports are outputs, never truth.** Do not read generated report prose back into canonical intelligence as authoritative state.
- **Deterministic before intelligent.** Prefer deterministic, inspectable logic when it is sufficient. Models may propose interpretations; model confidence, consistency, or agreement does not make an output authoritative.
- **Explainability is an architectural constraint.** Do not replace inspectable evidence paths with opaque similarity, hidden heuristics, or model-only reasoning as an incidental implementation choice.
- **A source constrains what its evidence can reasonably prove, but source type is not a permanent one-source-one-meaning ontology.** Keep source-specific containment narrow and explicit.
- **The system is currently single-operator.** Do not introduce multi-tenancy, user ownership, RBAC, OAuth, or tenant columns as incidental feature work.
- **No autonomous external-effect actions.** Sending, posting, spending, or acting in external systems requires explicit human approval at the point of action.

## 4. Pipeline and domain boundaries

`backend/pipeline.py::run_full_pipeline()` is the canonical end-to-end orchestration seam. Preserve ordering constraints rather than reconstructing a parallel pipeline in scripts, endpoints, or tests.

Entity persistence must occur before canonical Problem matching that relies on persisted entity IDs. Calling detection outside the intended pipeline can silently degrade matching rather than fail loudly; do not create new call paths that repeat that footgun.

Domains are registered explicitly through `DomainRegistry`. A domain exports configuration; it must not self-register through import side effects.

Collectors should produce factual/source-derived Signals and metadata. Do not manufacture downstream business meaning inside collectors merely to improve Opportunity or scoring output.

## 5. Database and history rules

Before any schema change, inspect `SCHEMA_VERSION`, current migration ordering, `docs/SCHEMA.md`, migration tests, and snapshot/persistence behavior. Never assume the schema version from a handoff document.

For migrations:

- use the next available version and preserve both fresh-database and upgrade paths;
- make failure rollback behavior explicit and tested;
- preserve foreign-key/provenance constraints and append-only guarantees;
- do not silently backfill semantic meaning into historical rows unless the approved design explicitly requires it;
- do not mutate or discard historical evidence to simplify a migration;
- consider canonical SQLite snapshot continuity when persistence behavior changes.

Never rewrite an accepted ADR to make history look cleaner. If a decision changes, supersede/correct it explicitly so the reasoning trail remains inspectable.

## 6. Working with Codex and Claude

No agent gains authority because it wrote the proposal, implementation, test, or green self-report.

For architecture-sensitive work, separate roles when practical: one agent/session may propose or implement; another should challenge assumptions or review the actual diff. A review must inspect repository state and changed code, not merely accept the implementing agent's summary.

Agents must not:

- weaken tests to make a change pass;
- change architecture documents merely to retroactively justify an implementation;
- hide out-of-scope changes inside a requested fix;
- add dependencies, persistent fields, or new semantic states because they are convenient;
- claim CI, migration safety, or production behavior was verified when it was not;
- put credentials, tokens, secrets, production data, or private values in code, tests, docs, logs, fixtures, or PR text.

Preserve unrelated user changes. Do not clean up files outside the mission just because you noticed style debt.

## 7. Verification expectations

Run the narrowest useful checks while working, then the appropriate regression gate before declaring completion.

### Backend

From the repo root:

- focused test: `cd backend && pytest tests/<relevant_test>.py -q`
- fast regression while iterating: `make test-fast`
- full backend regression before completing meaningful backend behavior changes: `make test`
- backend lint when relevant/available: `make lint`

For schema/persistence changes, run the relevant migration/persistence tests plus the full backend suite. Verify fresh initialization and upgrade behavior when both are affected.

### Frontend / Operations Console

Use the repository scripts rather than inventing alternate commands:

- `npm run lint`
- `npm run typecheck`
- `npm test`
- `npm run build`
- `npm run check:performance`
- `npm run test:e2e` when user-visible flows, routing, integration behavior, or browser contracts change

The frontend is an internal Operations Console, not evidence that BIA is already a public multi-user application.

### Workflows and scheduled collection

Preserve least-privilege GitHub Actions permissions. Do not give a workflow write access unless the task genuinely needs it. Scheduled collection/persistence is operational state, not a CI test fixture; do not make PR verification mutate canonical production intelligence state.

If a check was not run, say so explicitly.

## 8. Git and change hygiene

Use short-lived branches for non-trivial work. When a Linear/BIA issue exists, prefer branch and commit names that carry its identifier, for example `feat/bia-57-...` or `fix/bia-62-...`.

Follow the repository's established Conventional-Commit-like style where practical, e.g. `feat(bia-56): ...`, `fix(...): ...`, `docs(...): ...`.

Do not force-push or rewrite `main`. Do not commit runtime databases, snapshot artifacts, real `.env` files, secrets, caches, or generated local state.

PR/delivery summaries should state what changed, why, architecture impact, database impact, and exactly what was verified. Keep summaries factual; do not substitute a self-report for reviewing the diff.

## 9. Definition of done

A task is complete only when all applicable items are true:

- the requested scope is implemented without unapproved adjacent redesign;
- architectural invariants still hold;
- relevant focused checks pass;
- the appropriate regression suite passes or any unrun gate is explicitly disclosed;
- schema/docs/ADR/RFC updates are included when the approved contract actually changed;
- the final diff has been reviewed for accidental scope expansion, weakened tests, secrets, and historical-data mutation;
- completion claims distinguish what was verified locally, what CI verified, and what remains unverified operationally.
