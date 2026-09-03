# NIC-20 — Condition State evidence review before production design

Status: review only. This document does not select an interpreter, define a
production schema, amend RFC-002, or authorize implementation.

## Scope and evidence reviewed

This review is limited to what NIC-17, NIC-18, and accepted NIC-19 actually
measure: interpretation of a pre-selected literal condition span into a
Condition State. It is not evidence about correlation, Problem identity,
contradiction resolution across Signals, scoring, Findings, Opportunities, or
reporting.

Read inputs:

- NIC-15 shared `InterpreterCase` / `InterpreterResult` contract in
  `backend/tests/condition_state_eval/result.py`, with the scoring contract in
  `evaluate.py`.
- NIC-17 frozen corpus in `dataset.py`: 32 Core and 12 Adversarial cases; 41
  scored and 3 diagnostic. The corpus assigns a literal `target_span` before
  interpretation, including paired spans from one source in `CS-CORE-013a/b`
  and `CS-CORE-014a/b`.
- NIC-18 `rules-v1` reference implementation and standalone result, whose
  frozen interpreter SHA-256 is
  `827e23a3677e831ccddb02d0b5e7d40742575e3e7aeac01a87db0698baaeb905` and
  whose frozen output SHA-256 is
  `db74f39fc68d173de6b6a8e9c90f4c559efd47e83c0b008e9d9264d3e6369404`.
- Accepted NIC-19 contract, original 2.5 availability investigation, accepted
  result review, and both raw accepted Gemini 3.1 files in
  `docs/experiments/nic-19/`.
- ADR-001, ADR-005, canonical Data Model / Pipeline / Invariants / Decision
  Model, RFC-001, proposed RFC-002, and the current HANDOFF.

#### Independent record check

The two accepted raw JSON artifacts were rechecked locally. Each contains 41
unique scored and 3 unique diagnostic records; each records 31 correct scored
cases, zero operational failures, zero critical inversions, and zero `null`
abstentions. The `(label, evidence_span, raw structured output)` tuple is
identical for all 44 case IDs across runs. The ten scored errors are exactly
`CS-CORE-004`, `CS-CORE-009`, `CS-CORE-010`, `CS-CORE-012`, `CS-CORE-028`,
`CS-ADV-001`, `CS-ADV-006`, `CS-ADV-007`, `CS-ADV-008`, and `CS-ADV-009`;
each has expected `unknown` and a predicted `active` or `resolved` label. The
corpus SHA-256 also matched the accepted contract:
`a33660f69461ea77c9025927f736a4055584464afd4643c61ce7da282ec2e147`.

The accepted evidence therefore establishes reproducibility for one frozen
offline model contract, not truth outside the frozen corpus. Gemini 2.5's
model-list/generate-content mismatch remains an operational availability fact,
not semantic evidence. The accepted 3.1 contract's fixed rate-limit protocol
is likewise experimental execution provenance, not an Observation requirement.

### A. Design implications supported by evidence

1. **A condition-level interpretation must be traceable to a literal portion
   of source evidence.** NIC-17 deliberately turns one source into two
   different evaluated conditions in `CS-CORE-013a/b` (homepage resolved;
   search active) and `CS-CORE-014a/b` (invoicing resolved; onboarding active).
   Both accepted runs returned the respective distinct labels and literal spans.
   A future `InterpretedObservation` may therefore describe one condition of a
   Signal, but must preserve a resolvable link to the immutable Signal and its
   literal evidence span. This does **not** demonstrate that an automatic
   segmenter is reliable: the human-authored corpus supplied `target_span`.

2. **`active | resolved | unknown` is sufficient as the outcome vocabulary for
   the tested, pre-segmented task.** Every scored NIC-17 case has one of these
   gold labels, including negation, history, recurrence, hypotheticals,
   questions, hedging, informal language, and adversarial lexical senses.
   Gemini achieved 31/41 with no active/resolved inversion; rules-v1 achieved
   7/41 with one inversion. The conclusion is deliberately narrow: this
   tri-state vocabulary expresses the reviewed corpus, not every future
   semantic claim BIA may ingest.

3. **Current-state interpretation must retain the linguistic context that
   qualifies time and recurrence.** `CS-CORE-003` was correctly resolved from
   “long behind us now”; `CS-CORE-004` was incorrectly resolved from a past
   “used to crash” statement whose gold state is unknown; `CS-CORE-005`,
   `CS-CORE-006`, and `CS-ADV-012` demonstrate recurrence / fix-then-return
   shapes that are active in the corpus. This supports preserving the cited
   text and its source context. It does not justify inventing a normalized
   timestamp, recurrence counter, or state-transition field in V1: those were
   not independently evaluated as data fields.

4. **Semantic indeterminacy is a necessary first-class result for this task;
   it must not be collapsed into an operational failure.** Twenty-four scored
   cases expect `unknown`, and the shared NIC-15 contract keeps `error`
   separate from `label`. The accepted runs had no operational failures, while
   their only semantic errors are ten expected-unknown over-assertions. This
   supports a future design that can represent `unknown` as a semantic outcome
   and preserves execution failure separately when an interpreter is used. It
   does not establish that `null` is a required permanent semantic outcome:
   neither accepted run produced one.

5. **Conflicting and attributed language must remain inspectable rather than
   silently collapsed into a canonical claim.** `CS-CORE-009`, `CS-CORE-010`,
   and `CS-ADV-001` are scored unknown specifically because their same-evidence
   claims conflict; Gemini instead chose active. `CS-CORE-007` and
   `CS-CORE-008` are diagnostic because NIC-15 leaves attribution semantics
   open. The supported design implication is evidence preservation and
   traceability, not a new source-credibility rule or a normalized claimant
   field.

6. **The experiment supports keeping the interpretation layer below
   confidence and recommendation layers.** The Data Model separates
   observations from conclusions, and the Decision Model says confidence is
   earned through evidence, corroboration, recurrence, and history. A single
   model's deterministic agreement on 44 benchmark records cannot supply any
   of those. An interpreted condition can be evidence for later reasoning; it
   is not itself a confidence, score, Finding, or recommendation.

### B. Ideas rejected by evidence or existing architecture

1. **Do not promote Gemini, or any external model, to BIA's production
   interpreter.** The accepted runs are offline/shadow evidence on a fixed
   corpus with no reproducibly materialized holdout. Gemini 2.5 also showed
   provider metadata/generation inconsistency. NIC-19 authorizes no production
   integration, fallback policy, availability claim, or model selection.

2. **Do not treat 44/44 run agreement as ground truth or as BIA confidence.**
   The agreement only demonstrates repeatability of one frozen model contract
   on this corpus. Both runs make the same ten unknown-case errors. It neither
   corroborates a claim across independent external sources nor validates the
   corpus's open diagnostic semantics.

3. **Do not copy Gemini's request/response or telemetry into a permanent
   Observation schema.** Provider/model identifiers, prompt and schema
   versions, endpoint/API version, token usage, latency, raw model rationale,
   retry protocol, and provider errors are experiment/interpreter-execution
   provenance. They are not the semantic meaning of a BIA observation. A
   permanent design may need auditable provenance, but it must not be defined
   by this provider's JSON fields or rationale behavior.

4. **Do not add mandatory normalized time, attribution, recurrence, or
   confidence fields merely because the corpus contains those linguistic
   shapes.** The cases show that these shapes affect interpretation. They do
   not validate a canonical field vocabulary, normalization policy, source
   hierarchy, claim-authority rule, or BIA confidence calculation.

5. **Do not extend Condition State success into authority over correlation,
   Problem identity, contradiction reasoning across Signals, scoring,
   Findings, Opportunities, or reporting.** NIC-17 pre-selects the condition
   span and NIC-19 withholds the answer key; neither evaluates any downstream
   transformation. ADR-001 keeps Problem as the canonical identity, and
   RFC-002 keeps Investigation Findings evidence-only and sourced from Problem
   plus Knowledge rather than raw Signal text.

6. **Do not rewrite RFC-002 or bypass its Investigation/Analysis boundary.**
   The condition experiment concerns Processing-level interpretation of signal
   evidence. It does not redefine the seven Investigation facets, add scoring
   to Findings, or make a model response a Finding. RFC-002 remains proposed
   and outside this review's authority.

### C. Unresolved questions

1. **Attribution and question semantics remain intentionally unresolved.**
   `CS-CORE-007`, `CS-CORE-008`, and `CS-ADV-004` are diagnostics with no gold
   label. NIC-5 must not decide whether an attributed claim is accepted as the
   observation's state, how claimant/source authority works, or whether a
   WH-question's presupposition establishes state.

2. **The meaning and lifecycle of `null` remain unresolved.** The experiment
   contract allowed a null abstention, but the accepted runs produced none. It
   is not evidence for a permanent fourth semantic state, a parser-only
   abstention, or any persistence policy.

3. **Automatic condition discovery and segmentation are untested.** The corpus
   supplies exact target spans, so it does not establish how BIA finds multiple
   conditions, handles overlapping spans, groups clauses, or treats a source
   with no safely segmentable condition.

4. **Temporal and recurrence normalization remain untested.** Relative time,
   event ordering, recurrence counting, and current-vs-historical state need a
   dedicated evidence task before becoming normalized fields or cross-Signal
   reasoning inputs.

5. **Cross-source contradiction, claim provenance, and confidence policy are
   unresolved.** The corpus tests within-span language, not multiple Sources,
   source reliability, corroboration, or longitudinal conflict. Model
   agreement cannot close that gap.

6. **There is no repository-tracked NIC-5 issue contract to refine.** A
   repository issue search returned no NIC-5 issue, and no local contract named
   `InterpretedObservation` exists. NIC-5 must begin from this bounded handoff
   and its own approved issue/design scope, not an inferred backlog.

## NIC-5 handoff

#### NIC-5 may assume

- Condition State is a useful, bounded Processing-layer interpretation task
  when a condition span is already identified.
- V1 needs a condition-level link back to immutable Signal evidence and a
  literal, inspectable evidence span.
- `active`, `resolved`, and `unknown` can represent the scored NIC-17 task.
- Semantic `unknown` and interpreter execution failure must not be conflated.
- The output remains evidence, not confidence, correlation, identity, score,
  Finding, Opportunity, or recommendation.

#### NIC-5 must not assume

- that Gemini is selected, production-ready, or required;
- that a model's confidence, agreement, rationale, token usage, or response
  schema is BIA semantics;
- that a whole Signal has one condition or that segmentation is solved;
- that attribution, question presupposition, `null`, source authority,
  recurrence normalization, or temporal normalization is settled;
- that RFC-002's Findings contract or any downstream stage is being changed.

#### Constraints for canonical `InterpretedObservation` V1 design

1. It must be an additive, traceable interpretation about immutable source
   evidence; it must not mutate Signal content or canonical Problem identity.
2. It must be scoped to a particular condition/evidence span, with enough
   source linkage to reconstruct what was interpreted.
3. It may model the tested Condition State triad, but must not manufacture
   certainty where the evidence is unknown.
4. It must keep semantic content separate from interpreter-specific execution
   provenance and from BIA confidence/scoring.
5. It must leave unresolved semantics explicit rather than encoding a policy
   by convenience. No model response schema may be adopted as the canonical
   schema merely because it was accepted by Gemini.
6. It must stay in the Processing-to-Knowledge portion of the architecture;
   Investigation/Findings, Analysis, Opportunity, and Presentation remain
   separate owners.

#### Evidence gaps NIC-5 must document, not silently solve

- no holdout is available / reproducibly materialized;
- diagnostics leave attribution and WH-question semantics open;
- no automatic segmentation evaluation exists;
- no multi-source contradiction, source-authority, or confidence evaluation
  exists;
- no normalized time or recurrence-field evaluation exists;
- no production interpreter, operational policy, or permanent model-provenance
  decision has been made.

## Recommendation

**GO — evidence is sufficient to begin NIC-5 permanent
`InterpretedObservation` design, not implementation.** The evidence supports a
small, traceable, condition-scoped design with explicit uncertainty and strict
layer boundaries. It does not support selecting a production interpreter or
deciding the unresolved semantics above. No additional experiment is required
before design starts, provided NIC-5 treats those gaps as open constraints
rather than schema requirements.

## Documentation and architecture reconciliation

- `docs/HANDOFF.md` is stale: it still calls NIC-19 active and names
  `6e1c684` as authoritative main, while the accepted NIC-19 merge is
  `d865ae8`. This review records the discrepancy but does not rewrite the
  handoff outside NIC-20's review scope.
- RFC-002 is still marked **Proposed** and states that Investigation consumes
  `Problem` plus connected `Knowledge`, never raw Signal text. A future
  `InterpretedObservation` must therefore be reasoned as Processing/Knowledge
  input, not introduced as an alternate Findings artifact.
- The established roadmap sequence names NIC-20 before NIC-5, but offers no
  locally tracked NIC-5 issue contract. That missing contract is an explicit
  handoff gap, not permission to expand NIC-5.

## Reproducibility checks

- Recomputed accepted-run coverage, metrics, all-case agreement, and the ten
  expected-unknown error pattern from both raw JSON artifacts.
- Verified corpus SHA-256 against the accepted contract.
- Ran focused NIC-17/NIC-18/NIC-19 tests:
  `40 passed`.
