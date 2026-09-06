# InterpretedObservation V1 — Field Disposition and Invariants

Status: **Design proposal for independent review**

Scope: NIC-5 contract design only. This document does not authorize a
migration, runtime implementation, interpreter, API, pipeline, frontend,
scoring, Problem/Opportunity, or RFC-002 change.

## Purpose and boundary

An InterpretedObservation is a structured interpretation derived from one
immutable BIA Signal. It lets later code consume bounded meaning without
re-guessing raw source text. V1 is deliberately a **Condition State profile**
only: a cited condition is active, resolved, or unknown.

It is not source truth, a general claim ontology, a source-authority system,
a confidence score, a Problem, an Opportunity, or a Finding. The evidence base
is NIC-15 through NIC-20: NIC-17's frozen pre-segmented corpus, NIC-18's
reference baseline, accepted NIC-19 shadow results, and the NIC-20 review.

---

## Part 1 — Constitutional invariants

| # | Statement | Why / evidence | Failure prevented |
| --- | --- | --- | --- |
| 1 | **Signal remains immutable raw/source evidence.** Observation never edits Signal text, URL, source metadata, tags, or collection facts. | Signal is append-only architecture; NIC-17 derives readings from supplied source text. | A derived reading silently becomes a falsified source record. |
| 2 | **Observation is derived interpretation, not source truth.** | NIC-19's two runs agree on the same ten expected-unknown errors; NIC-20 rejects agreement as truth. | A label becomes an asserted fact by the source or BIA. |
| 3 | **One Signal may produce zero, one, or multiple observations.** | CS-CORE-013a/b and CS-CORE-014a/b contain distinct conditions in one source. | One-Signal/one-meaning conflation. |
| 4 | **Each observation links to one immutable Signal and literal cited evidence in it.** | NIC-15 requires grounded spans; NIC-17 supplies literal target spans; NIC-19 validates literal citations. | Uninspectable semantic claims. |
| 5 | **Evidence text and interpreted meaning are separate.** | Historical, recurring, hedged, and conflict language changes the reading without changing source facts. | Paraphrase replacing evidence, or citation treated as a label. |
| 6 | **Semantic unknown differs from interpreter operational failure.** | NIC-15 makes label and error exclusive; NIC-19 had semantic over-assertions but zero operational failures. | Retrying an honest unknown or storing a request failure as meaning. |
| 7 | **Model/provider confidence is not BIA confidence.** | Exact 44/44 model agreement repeated the same failures. | Provider probability becoming business confidence. |
| 8 | **Model/provider telemetry is not semantic data.** | Prompt, schema, model, tokens, latency, cost, retry, and endpoint were NIC-19 execution provenance. | Vendor request format becomes BIA's semantic model. |
| 9 | **Observation cannot decide Problem identity, Opportunity qualification, relevance, support/contradiction, scoring, Findings, or recommendations.** | ADR-001 assigns identity to Problem; ADR-002 assigns dated assessment to Opportunity; NIC-20 withheld all downstream authority. | Bypassing Correlation, canonicalization, Investigation, or Analysis. |
| 10 | **Demand-looking text does not grant authority to prove demand.** | Greenhouse hiring/salary/B2B vocabulary resembled demand while evidencing labor investment. | Repeating the raw-text false positive. |
| 11 | **No Greenhouse-specific policy is encoded in the permanent contract.** | NIC-30/31 containment is temporary; NIC-20 rejects a one-source ontology. | General architecture overfit to greenhouse_jobs. |
| 12 | **The contract is interpreter-neutral.** Human, rules, or a future model can produce the same profile. | NIC-18 rules and NIC-19 Gemini are comparison mechanisms; neither is production-selected. | Making an LLM mandatory. |
| 13 | **Every field has a demonstrated semantic or audit purpose.** | NIC-5 forbids vague future-use fields; NIC-20 defers untested normalization. | Optional fields silently becoming policy. |
| 14 | **Corrections preserve history rather than rewrite it.** | Immutable Opportunities and append-only Problem history establish BIA's audit discipline. | Losing prior interpretation and correction provenance. |

---

## Part 2 — Experimental field disposition matrix

The rows enumerate temporary inputs, corpus metadata, interpreter output, and
provider metadata used across NIC-15 through NIC-19. Concepts not actually
present as fields are identified rather than invented retroactively.

| Experimental field / concept | Experimental meaning | Evidence | V1 decision | Production concept if transformed | Reason / consequence if wrong |
| --- | --- | --- | --- | --- | --- |
| case_id | Evaluation-record ID | Required to score frozen corpus | REJECT | — | Test identity is not source evidence; adopting it couples production to a benchmark. |
| source_text | Whole evaluator input | NIC-17 fixture input | TRANSFORM | signal_id reference | Signal already owns canonical raw evidence; copying text risks divergence. |
| target_span / condition text | Human-selected literal condition | CS-CORE-013a/b and 014a/b | TRANSFORM | evidence_citation | Preserve cited source evidence, not an evaluator-only input field. |
| expected_label | Gold answer withheld from interpreter | NIC-17 scoring control | REJECT | — | Answer keys are not production semantics. |
| scored, case_set, category, notes, critical_inversion_probe | Corpus/scoring organization | Core, adversarial, diagnostic harness | REJECT | — | Benchmark policy must not enter runtime data. |
| label | active, resolved, unknown; Gemini also allowed null | 41 scored cases; 24 expected unknown | ADOPT | condition_state | Triad is sufficient for the tested pre-segmented task. |
| null / abstention | Model declined a label | Allowed, but neither accepted run emitted it | DEFER | — | Its semantic lifecycle is untested; do not invent a fourth state. |
| evidence_span | Exact contiguous citation | Required for non-null model label; validated in accepted runs | ADOPT | evidence_citation.literal_text | Literal grounding is the demonstrated audit requirement. |
| matched_cue | Rules-only matched token | NIC-18 implementation detail | REJECT | — | Rule vocabulary is not semantic meaning. |
| rationale | Model explanation prose | Gemini structured response | REJECT | — | Persuasive model prose is neither stable evidence nor BIA claim. |
| raw_output | Exact provider JSON | Preserved only in experiment artifacts | REJECT | — | Provider schema must not become durable semantic data. |
| interpreter_id | Rules/shadow interpreter name | NIC-18 versus NIC-19 | TRANSFORM | generic run provenance: producer_kind and interpreter_name | Audit derivation without making interpreter identity semantic. |
| interpreter_version | Interpreter revision | rules 1.0.0 and Gemini 3.0.0 | TRANSFORM | interpreter_revision in run provenance | Needed for reproducing production attempts, not semantic identity. |
| prompt_version | Gemini prompt revision | NIC-19 only | REJECT | — | Not usable by human/rule production. |
| model_identity | Provider/model string | NIC-19 only | REJECT | — | No production interpreter is selected; it is not semantic content. |
| provider/API/endpoint/response schema/generation settings | Gemini transport configuration | Frozen for experiment reproducibility | REJECT | — | Fields are provider-specific execution configuration. |
| run_timestamp | Attempt time | NIC-15 result metadata | TRANSFORM | produced_at in run provenance | Audit time must not be confused with source-event time. |
| latency_ms | Request duration | Reported per accepted NIC-19 record | REJECT | — | Performance telemetry is not meaning. |
| token_usage | Provider usage metadata | Present for Gemini and absent for rules | REJECT | — | Provider billing telemetry would make an LLM-shaped contract. |
| cost_usd | Provider cost estimate | Unavailable in accepted results | REJECT | — | Cost is neither returned reliably nor semantic. |
| execution_parameters | Provider-specific execution metadata | Gemini adapter only | REJECT | — | A generic semantic record must not store an API configuration blob. |
| retry count/rate-limit protocol | Experiment execution behavior | Frozen protocol; accepted runs had zero retries | REJECT | — | Retry policy is not semantic data. |
| operational error | Request/interpreter failure | Separate axis in NIC-15; zero NIC-19 failures | TRANSFORM | separate run outcome | Preserve distinction without storing transient error prose as semantic data. |
| topic_key | Not an experiment field | NIC-5 asks for a decision | DEFER | — | No topic/matching evaluation; it would decide Correlation by convenience. |
| generic fact/assertion classification | Not an experiment field | Diagnostics expose ambiguity but no stable taxonomy | DEFER | — | No tested vocabulary or consumer. |
| temporal context | Linguistic qualification, not normalized field | CS-CORE-003 through 006 and ADV-012 | DEFER | cited text only | No validated timestamp/transition/counter model. |
| attribution | Linguistic form, not field | CS-CORE-007/008 diagnostics | DEFER | cited text only | Claimant and authority policy are open. |
| recurrence | Linguistic form, not field | CS-CORE-005/006 and ADV-012 | DEFER | cited text only | One sentence is not a longitudinal count. |
| geography | Not an experiment field | No geographic cases | DEFER | — | No demonstrated V1 need. |
| entity references | Signal already carries extracted IDs; absent from interpreter contract | Condition experiment never evaluates linkage | DEFER | — | Must not redefine extraction or Problem identity. |
| source capability/authority | Source exists on Signal; no capability field | Greenhouse demonstrates risk, not general vocabulary | DEFER | — | A permanent source policy needs its own evidence and design. |

### Matrix conclusion

The V1 semantic core is limited to: Signal link, literal evidence citation,
Condition State, semantic-contract version, and correction lineage. Generic
run provenance is necessary for audit but separate from semantic content.
Everything else is rejected or explicitly deferred.

---

## Part 3 — Proposed V1 semantic core

V1 is one fixed profile: **Condition State V1**. Because every V1 record has
that profile, it intentionally has no generic observation_type field merely
to anticipate future types.

| Canonical field | Required | Exact meaning / allowed shape | Source of truth | Producer | Immutable | Class | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| observation_id | Yes | Stable logical record identifier; no database key mechanics selected. | Contract creation | System | Yes | Identity/audit | Historical correction must be traceable. |
| signal_id | Yes | Identifier of the one immutable Signal from which the record derives. | Signal store | Copied by producer | Yes | Semantic provenance | NIC-15/17 grounding and current Signal architecture. |
| evidence_citation | Yes | Object with literal_text and occurrence. Text is an exact substring of canonical Signal text; occurrence is a positive ordinal resolving duplicate identical spans. | Signal text | Human/rule/model selects; validation verifies | Yes | Semantic provenance | Literal spans and multi-condition cases. |
| condition_state | Yes | Producer's bounded reading of cited condition under V1. Values: active, resolved, unknown. | Interpretation of cited evidence | Human/rule/model | Yes | Semantic | All scored NIC-17 cases and NIC-20 conclusion. |
| semantic_contract_version | Yes | BIA meaning contract used for the state. Initially condition-state/v1; never a prompt/model/API version. | Approved BIA contract | System selects | Yes | Semantic provenance | Future semantic changes must remain auditable. |
| supersedes_observation_id | Only for correction | Earlier observation on same cited evidence that this record corrects or replaces. Earlier record remains readable. | Approved correction decision | Approved producer/workflow | Yes | Lineage | Invariant 14 and append-only history. |

### Explicit non-fields

V1 has no free-form condition name, topic key, entity references, claimant,
normalized time, recurrence count, geography, generic fact/assertion type,
confidence, rationale, raw model response, source-capability value, Problem ID,
Opportunity ID, score, recommendation, or opaque metadata blob.

### Producer rule

A human, rule, or model may produce a record. A non-unknown state requires a
valid literal citation. Unknown is semantic, not a failed request. A failure
to execute creates only an operational run outcome, never an Observation.

---

## Part 4 — Identity

**Logical identity.** One logical observation is a Condition State V1 reading
of one cited occurrence in one Signal under one semantic-contract version:

(signal_id, evidence_citation, semantic_contract_version, condition_state)

observation_id names the historical record but is not specified as a UUID,
hash, or database primary key.

**Same Signal/span.** Two records may cite the same Signal and exact evidence
occurrence only if they are distinct historical interpretations, such as an
approved correction or a later semantic-contract version. A duplicate run is
an execution deduplication concern, not a new semantic fact.

**Correction.** Changed interpretation creates a new immutable record pointing
to the earlier record through supersedes_observation_id. It never edits the
Signal or deletes the prior interpretation.

**Interpreter version.** It is not semantic identity. It is generic
interpreter/run provenance.

**Rerun.** Rerunning the same interpreter does not automatically create an
observation. It creates a run record or is deduplicated. An observation is
created only when an approved production process yields a retained semantic
record.

**Run identity.** Logical identity answers what was interpreted; run identity
answers which producer attempt created or checked it, when, and with what
operational outcome. They remain separate.

---

## Part 5 — Provenance

Physical tables and retention are NIC-6 questions. The minimum conceptual
provenance is three structures, not one metadata blob.

### A. Semantic provenance

Required with the observation:

- signal_id
- literal citation text and occurrence selector
- semantic_contract_version
- optional correction link

It answers what was interpreted and under which BIA semantic definition.

### B. Interpreter/run provenance

Separate from the semantic core, a retained production attempt needs:

- producer_kind: human, rule, or model
- producer name and revision when applicable
- produced_at
- outcome: produced or operational failure
- reference to the observation when one was produced

Provider model IDs, prompt text/version, raw responses, endpoint/API version,
latency, tokens, cost, retries, and generation settings are not Observation
fields. A later execution-log design may decide whether operational retention
needs them.

### C. Raw source provenance

Signal retains source, source ID, URL, title/content, source-derived metadata,
collection time, domain, and immutable identity. Observation references it and
does not copy it.

---

## Part 6 — Evidence capability decision

### Decision: no permanent capability field in Observation V1

Do not add capability, authority, source_trust, or proves_customer_demand to
V1.

The Greenhouse incident proves a necessary boundary: semantic interpretation
does not establish evidentiary authority. It does not validate a general
capability vocabulary, assignment authority, granularity (source versus item),
or downstream consumer.

| Alternative | Decision | Reason |
| --- | --- | --- |
| Capability on Observation | Reject for V1 | It would make an individual interpretation appear to confer authority; no vocabulary or evaluator was tested. |
| Capability on interpreter output | Reject for V1 | A model or rule may classify text but cannot authoritatively decide what a source is allowed to prove. |
| Capability supplied by source policy | Defer | This is the plausible future owner, but requires a source-general proposition/capability model and downstream consumer evidence. |
| No capability field in Observation V1; authority deferred downstream | Adopt | It preserves raw evidence and prevents a Condition State label from becoming a demand or Opportunity claim. |

V1 prevents conversion of demand-looking text into source-proves-demand by
design:

1. It records only a narrow cited Condition State.
2. It cannot output relevance, demand, support, contradiction, Problem,
   Opportunity, score, or recommendation claims.
3. A later source-general evidence-policy design may decide what evidence can
   support which proposition, using preserved raw evidence.

This avoids both a global source label pretending every source item has the
same authority and a model-produced capability value pretending interpretation
creates authority.

---

## Part 7 — Signal boundary

| Source example | Signal says / stores | Observation may interpret | Observation must **not** assert |
| --- | --- | --- | --- |
| Reddit complaint | Immutable post text, source/URL/collection facts | A cited complaint condition is active, resolved, or unknown | Representative customer demand, a Problem, or a qualified Opportunity |
| Hacker News question | Question text and source facts | Unknown for a cited question where no state is explicitly asserted | The presupposition is a fact or the audience represents a market |
| Greenhouse job posting | Employer role, salary, location, source facts | A narrow cited condition only if supported | Customer pain, willingness to pay, market gap, or a special source rule |
| SEC filing | Filing text and issuer/filing facts | A cited condition-state statement | Legal truth beyond filing, materiality, or investment advice |
| RSS/product announcement | Published announcement and feed facts | A cited status condition or unknown | Adoption, unmet demand, competitor conclusion, or effectiveness |

Signal owns raw evidence and collection facts. Observation owns bounded
interpretation and citation. Entity extraction remains independent Processing.

---

## Part 8 — Problem / Opportunity boundary

| Object | Owns | Does not own |
| --- | --- | --- |
| InterpretedObservation | Bounded interpretation of cited Signal evidence | Canonical identity, cross-source support, relevance, score, recommendation |
| Problem | Persistent canonical identity and accumulated history | Raw source rewriting or one-off execution details |
| Opportunity | Dated, scored assessment linked to a Problem | Source truth or permanent Problem identity |

Three failures this prevents:

1. Two invoicing complaints may each be active; calling either one a Problem
   bypasses unresolved P3 actor/context and canonicalization.
2. A Greenhouse posting may carry a narrow interpretation; calling it demand
   bypasses authority, scoring, and containment boundaries.
3. A fixed statement may be resolved; closing a Problem or minting an
   Opportunity from it mistakes a local citation for a scored assessment.

C2/C4 remain Correlation concerns. Problem owns canonical identity. Findings
and judgment remain later Investigation/Analysis work.

---

## Part 9 — Challenge against frozen evidence

| Evidence / case | Result | Contract treatment |
| --- | --- | --- |
| N1 | SUPPORTED | Cited resolved condition can be resolved; Entity extraction remains unchanged. |
| N2 | SUPPORTED | Cited ongoing condition can be active; no score/Problem conclusion follows. |
| S1 | DEFERRED DOWNSTREAM | Relevance-blind risk matching is scoring/Analysis, not Observation. |
| S2 | DEFERRED DOWNSTREAM | Launch announcement versus market gap is authority/scoring, not a Condition State field. |
| C2 | DEFERRED DOWNSTREAM | Paraphrase clustering remains Correlation; no topic_key is added. |
| C4 | DEFERRED DOWNSTREAM | Homonym separation remains Correlation; shared polarity is not shared topic. |
| P3 | DEFERRED DOWNSTREAM | Actor/context in Problem identity remains open; no entity/subject field is smuggled in. |
| CS-CORE-013a/b and 014a/b | SUPPORTED | One Signal can create multiple records with distinct citations and states. |
| CS-CORE-003/004 historical cases | HANDLED AS UNKNOWN | 004 does not establish current state; no normalized time field is invented. |
| CS-CORE-005/006 and CS-ADV-012 recurrence | SUPPORTED | Current state can be active where cited language supports it; recurrence counts/transitions are deferred. |
| CS-CORE-007/008 and CS-ADV-004 attribution/questions | HANDLED AS UNKNOWN | No claimant/presupposition rule is introduced; diagnostics stay open. |
| Expected-unknown cases and ten Gemini errors | SUPPORTED | Unknown is required; model agreement/rationale cannot override it. |
| CS-CORE-009/010 and CS-ADV-001 conflicts | HANDLED AS UNKNOWN | V1 can retain cited indeterminacy; cross-source contradiction remains downstream. |
| Greenhouse false-positive incident | DEFERRED DOWNSTREAM | Narrow interpretation survives; authority and Opportunity qualification remain outside V1. |

**Contract gap check:** none. Every unsolved concern is explicit and excluded
rather than hidden as an optional field.

---

## Part 10 — Deferred questions ledger

| Deferred question | Why unresolved | Evidence needed | Likely later owner |
| --- | --- | --- | --- |
| Automatic segmentation | NIC-17 supplied spans | Discovery/overlap/no-safe-span evaluation | NIC-6/NIC-7 Processing |
| Null abstention lifecycle | Allowed but absent in accepted runs | Labeled abstention and operational-policy cases | Interpreter/evaluation design |
| Attribution/claimant | Diagnostic cases lack gold labels | Reviewed attributed-source corpus and authority policy | Processing/evidence policy |
| Question presupposition | CS-ADV-004 diagnostic | Question-semantics evaluation | Processing/evaluation |
| Temporal normalization | Only language, not normalized data model, was tested | Relative-time/event-order corpus and consumer | Later profile |
| Recurrence normalization | Textual recurrence is not longitudinal recurrence | Multi-Signal time-series model | Problem/history or later profile |
| Geography | No cases/consumer | Geographic corpus and use case | Later profile/domain |
| Entity references | Not tested in condition experiment | Accurate linkage with a defined consumer | Extraction/Correlation |
| topic_key | No topic/matching evidence | C2/C4-style evidence and consumer | Correlation |
| Generic fact/assertion taxonomy | No stable vocabulary | Cross-domain corpus and use case | Processing/evidence policy |
| Source authority/capabilities | Incident proves risk, not taxonomy | Source-general proposition/capability matrix | Evidence policy |
| Cross-source contradiction | Only within-span conflict tested | Multi-source corroboration/conflict evaluation | Correlation/Analysis |
| BIA confidence | Model agreement is not confidence | Evidence-quality/corroboration semantics | Analysis |
| Storage/replay/backfill/retention | Out of NIC-5 | Approved contract plus operational requirements | NIC-6 |
| Production interpreter | NIC-19 shadow-only; no materialized holdout | Separate reliability/cost/evaluation approval | Later approval issue |

---

## Part 11 — Candidate conceptual examples

These are contract examples, not code or source-policy decisions.

### 1. Genuine user complaint

- **Signal says/stores:** Reddit post: “Our checkout flow still fails for
  returning customers.”
- **Citation:** “checkout flow still fails”.
- **Observation:** condition_state active; semantic_contract_version
  condition-state/v1.
- **Must not assert:** representative demand, Problem identity, or Opportunity.

### 2. Resolved condition

- **Signal says/stores:** “The homepage loads fine now after the cache fix.”
- **Citation:** “homepage loads fine now”.
- **Observation:** resolved.
- **Must not assert:** permanence or resolution of related conditions elsewhere.

### 3. Ambiguous/unknown condition

- **Signal says/stores:** “The checkout flow used to crash constantly in
  2019.”
- **Citation:** “used to crash constantly in 2019”.
- **Observation:** unknown.
- **Must not assert:** current active or resolved state.

### 4. One Signal producing multiple observations

- **Signal says/stores:** “The homepage loads fine now, but search is still
  broken.”
- **Observation A:** citation “homepage loads fine now” and state resolved.
- **Observation B:** citation “search is still broken” and state active.
- **Must not assert:** a single whole-Signal state or one canonical Problem.

### 5. Greenhouse posting

- **Signal says/stores:** employer job-post text, role, location, salary, and
  source facts.
- **Observation may interpret:** only a narrow cited condition when the profile
  applies.
- **Must not assert:** customer demand, willingness to pay, market gap, or a
  source-specific authority value.

### 6. SEC statement

- **Signal says/stores:** filing: “The company resolved the identified
  reporting control deficiency.”
- **Citation:** “resolved the identified reporting control deficiency”.
- **Observation:** resolved for that cited condition.
- **Must not assert:** legal truth beyond the filing, materiality, or advice.

### 7. Question whose presupposition is not asserted fact

- **Signal says/stores:** “Why does checkout still fail after the deploy?”
- **Citation:** the literal question.
- **Observation:** unknown if an approved producer retains one; otherwise no
  observation is also valid when no defensible interpretation is possible.
- **Must not assert:** that checkout fails. The question policy remains open.

---

## Part 12 — Decision

OBSERVATION V1 CONTRACT READY FOR APPROVAL

This proposal is ready for independent architectural review: each retained
field has a bounded evidenced purpose, and unresolved semantics are explicit
deferred constraints. Approval would permit NIC-6 storage/integration design
only—not implementation, production model selection, or downstream semantic
changes.

## Review checklist

- [x] Design artifact only; no runtime, schema, API, pipeline, frontend,
  scoring, Problem, Opportunity, or RFC-002 files changed.
- [x] NIC-15 through NIC-19 fields were dispositioned without adopting provider
  telemetry as semantics.
- [x] Greenhouse is a source-general evidence-boundary lesson, not a permanent
  source-specific rule.
- [x] C2/C4 remain Correlation and P3 remains Problem-identity work.
- [x] No production interpreter is selected.
