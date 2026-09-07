# InterpretedObservation V1 — Field Disposition and Invariants

Status: **Design proposal for independent review**

Scope: NIC-5 contract design only. This document does not authorize a
migration, runtime implementation, interpreter, API, pipeline, frontend,
scoring, Problem/Opportunity, or RFC-002 change.

## Purpose and boundary

An InterpretedObservation is a structured interpretation derived from one
immutable BIA Signal. It lets later code consume bounded meaning without
re-guessing raw source text. V1 is deliberately a **Condition State profile**
only: a producer identifies a literal condition target and interprets its state
as active, resolved, or unknown. The target and the literal support for that
state are distinct semantic roles.

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
| 4 | **Each observation links to one immutable Signal, a literal condition target, and literal state support where required.** The target and support may overlap or be identical, but are never assumed identical. | NIC-15/17 distinguish target_span from interpreter-selected evidence_span; in CS-CORE-003 the target is the whole historical sentence while accepted support is “that's long behind us now.” | Losing what condition “that” refers to and forcing downstream code to reinterpret prose. |
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
| target_span / condition text | One literal contiguous condition occurrence being interpreted | CS-CORE-013a/b and 014a/b; distinct from evidence_span in CS-CORE-003 | TRANSFORM | required condition_citation | Preserve what condition the record is about without requiring downstream prose interpretation. |
| expected_label | Gold answer withheld from interpreter | NIC-17 scoring control | REJECT | — | Answer keys are not production semantics. |
| scored, case_set, category, notes, critical_inversion_probe | Corpus/scoring organization | Core, adversarial, diagnostic harness | REJECT | — | Benchmark policy must not enter runtime data. |
| label | active, resolved, unknown; Gemini also allowed null | 41 scored cases; 24 expected unknown | ADOPT | condition_state | Triad is sufficient for the tested pre-segmented task. |
| null / abstention | Model declined a label | Allowed, but neither accepted run emitted it | DEFER | — | Its semantic lifecycle is untested; do not invent a fourth state. |
| evidence_span | One exact contiguous target_span substring selected as state support | CS-CORE-003 accepted support is shorter than target_span; required for active/resolved and optional for unknown in NIC-15 | TRANSFORM | state_evidence_citation | State support is distinct from, but contained by, the condition target. |
| matched_cue | Rules-only matched token | NIC-18 implementation detail | REJECT | — | Rule vocabulary is not semantic meaning. |
| rationale | Model explanation prose | Gemini structured response | REJECT | — | Persuasive model prose is neither stable evidence nor BIA claim. |
| raw_output | Exact provider JSON | Preserved only in experiment artifacts | REJECT | — | Provider schema must not become durable semantic data. |
| interpreter_id | Rules/shadow interpreter name | NIC-18 versus NIC-19 | TRANSFORM | generic run provenance: producer_kind and interpreter_name | Audit derivation without making interpreter identity semantic. |
| interpreter_version | Interpreter revision | rules 1.0.0 and Gemini 3.0.0 | TRANSFORM | interpreter_revision in run provenance | Needed for reproducing production attempts, not semantic identity. |
| prompt_version | Gemini prompt revision | NIC-19 only | REJECT | — | Not usable by human/rule production. |
| model_identity | Provider/model string | NIC-19 only | REJECT | — | No production interpreter is selected; it is not semantic content. |
| provider/API/endpoint/response schema/generation settings | Gemini transport configuration | Frozen for experiment reproducibility | REJECT | — | Fields are provider-specific execution configuration. |
| run_timestamp | Attempt time | NIC-15 result metadata | TRANSFORM | attempted_at (and produced_at if distinct) in run provenance | Audit time must not be confused with source-event time. |
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

The V1 semantic core is limited to: Signal link, required condition citation,
state-support citation with the NIC-15 requirement rule, Condition State,
semantic-contract version, and correction lineage. Generic run provenance is
necessary for audit but separate from semantic content.
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
| condition_citation | Yes | Exactly one contiguous literal occurrence identifying the condition target: source_part (title or content), exact case-preserving, non-empty literal_text, and positive occurrence ordinal within that source part. | Preserved immutable Signal title/content | Human/rule/model supplies; validation verifies | Yes | Semantic provenance / target | NIC-17 target_span and multi-condition cases; CS-CORE-003 demonstrates that target differs from support. |
| state_evidence_citation | Required for active/resolved; optional for unknown | Exactly one contiguous literal occurrence in the same source_part and within condition_citation's range. It may equal the target; when present, its literal_text is exact, case-preserving, and non-empty. | Preserved immutable Signal title/content | Human/rule/model supplies; validation verifies | Yes | Semantic provenance / support | NIC-15 evidence_span is one exact substring of target_span; NIC-19 validates literal support. |
| condition_state | Yes | Producer's bounded reading of the condition_citation under V1. Values: active, resolved, unknown. | Interpretation of target and support | Human/rule/model | Yes | Semantic | All scored NIC-17 cases and NIC-20 conclusion. |
| semantic_contract_version | Yes | BIA meaning contract used for the state. Initially condition-state/v1; never a prompt/model/API version. | Approved BIA contract | System selects | Yes | Semantic provenance | Future semantic changes must remain auditable. |
| supersedes_observation_id | Only for correction | Earlier retained interpretation record that this record corrects or replaces. It may differ in Signal, target, support, state, or semantic-contract version; the earlier record remains readable. | Approved correction decision | Approved producer/workflow | Yes | Lineage | Invariant 14 and target-misidentification correction. |

### Explicit non-fields

V1 has no free-form condition name beyond condition_citation, topic key, entity references, claimant,
normalized time, recurrence count, geography, generic fact/assertion type,
confidence, rationale, raw model response, source-capability value, Problem ID,
Opportunity ID, score, recommendation, or opaque metadata blob.

### Producer rule

A human, rule, or model may produce a record. Active and resolved require a
valid condition_citation and state_evidence_citation. Unknown requires a valid
condition_citation; its supporting citation is optional, matching NIC-15's
experimental contract. Unknown is semantic, not a failed request. A failure to
execute creates only an operational run outcome with its attempted input, never
an Observation.

### Unknown, operational failure, and successful abstention

- **Unknown** is a valid condition_state on a retained Observation whose target
  is known but whose state is semantically indeterminate.
- **Operational failure** produces no semantic Observation because no semantic
  result was produced.
- Whether a successfully executed producer may abstain from creating an
  Observation for an already identified target remains **deferred**. NIC-19
  allowed null but the accepted runs contained zero null outcomes; V1 does not
  map successful abstention to unknown or to no record by policy.

Citations resolve only against preserved immutable source text. For the current
Signal shape, title and content are separately named source parts; the lowercased
and concatenated Signal.full_text analysis view is not literal provenance and
must never be a citation target. V1 deliberately permits exactly one contiguous
citation in exactly one source part. Multi-fragment citations and a condition
target spanning title plus content are deferred because NIC-15/17 did not test
them.

### Citation literal invariant

Before occurrence resolution, condition_citation.literal_text must be exact,
case-preserving, and non-empty. Whenever state_evidence_citation exists, its
literal_text has the same requirements. An empty string is never a citation
literal. This preserves NIC-15's non-empty evidence requirement for active and
resolved results while retaining optional support for unknown.

### Citation occurrence resolution

For both condition_citation and state_evidence_citation, the occurrence ordinal
is resolved by enumerating every character start position in the selected,
preserved source_part at which literal_text matches exactly. Overlapping matches
are included and ordered by ascending character start position; occurrence is
the one-based ordinal in that ordered list. This rule resolves an ordinal from
preserved source text without making character offsets V1 fields.

---

## Part 4 — Identity

### A. Observation target identity

The stable target is **which condition occurrence in which Signal is being
interpreted**:

(signal_id, canonical condition_citation)

condition_state is deliberately not part of this target identity. Neither is
semantic_contract_version: a changed meaning contract can reinterpret the same
target without creating a new target. Because V1 condition_citation is one
source part, one contiguous literal occurrence, and one occurrence ordinal,
the same target cannot acquire multiple identities through alternate fragment
decomposition.

### B. Interpretation record identity

An interpretation record is one retained, immutable historical reading of that
target. observation_id names that record; NIC-5 does not choose UUID, hash, or
database-primary-key mechanics. Each record contains its target reference,
state_evidence_citation, condition_state, semantic_contract_version, and any
supersedes_observation_id.

### C. Interpretation value

condition_state is the value asserted by an interpretation record, not the
identity of the condition. A correction from active to unknown therefore
supersedes an earlier record about the same target rather than redefining the
target itself.

### D. Semantic and execution version boundaries

semantic_contract_version belongs to an interpretation record, not stable
target identity, because it describes the BIA meaning definition used for that
reading. interpreter_revision belongs only to run provenance; a new rule/model
revision does not make a new semantic target.

### E. Same target, corrections, and reruns

Two records may point to the same target when they preserve a correction or a
later approved semantic interpretation. A same-target correction can change
active to unknown. A target correction can replace an earlier record whose
Signal, condition target, or state-support citation was misidentified. In both
forms, the later record links to the earlier one through
supersedes_observation_id; equal signal_id, target, support, state, and
semantic-contract version are not required.

Neither record edits the Signal nor deletes the historical reading. A record
explicitly superseded by a retained successor is historical rather than the
current retained interpretation; consumers must traverse lineage to determine
that status. Fan-out/conflicting-successor handling and storage mechanics are
not designed here. A duplicate execution of the same process is a run
deduplication concern, not automatically a new semantic record.

### F. Execution/run identity

Run identity answers which producer attempt created or checked a record, when,
and with what operational outcome. It remains separate from target identity,
interpretation-record identity, and interpretation value.

---

## Part 5 — Provenance

Physical tables and retention are NIC-6 questions. The minimum conceptual
provenance is three structures, not one metadata blob.

### A. Semantic provenance

Required with the observation:

- signal_id
- required condition_citation
- state_evidence_citation when the state rule requires or retains one
- semantic_contract_version
- optional correction link

It answers what was interpreted and under which BIA semantic definition.

### B. Interpreter/run provenance

Separate from the semantic core, every retained production attempt needs:

- attempted_signal_id
- attempted_condition_citation, using the V1 citation shape
- producer_kind: human, rule, or model
- producer name and revision when applicable
- attempted_at, plus produced_at when distinct
- outcome: currently produced or operational_failure; this vocabulary is not
  declared permanently closed
- optional resulting observation_id when a semantic Observation was produced

This lets audit or retry tooling answer what source condition a failed attempt
operated on without relying on an Observation that does not exist. Operational
failure remains a run outcome, not an Observation, and transient error prose
does not enter InterpretedObservation semantic fields. If successful abstention
is later approved, run provenance must add an explicit successful_no_observation
outcome and retain the same attempted input. Until then, V1 does not map
abstention to operational_failure, unknown, or no record.

Provider model IDs, prompt text/version, raw responses, endpoint/API version,
latency, tokens, cost, retries, and generation settings are not Observation
fields. A later execution-log design may decide whether operational retention
needs them.

### C. Raw source provenance

Signal retains source, source ID, URL, title, content, source-derived metadata,
collection time, domain, and immutable identity. Title and content remain
conceptually distinct citation sources. Observation references them and does
not copy, lowercase, concatenate, or otherwise normalize them for provenance.

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
| Hacker News question | Question text and source facts | A reviewed yes/no question may retain unknown under the frozen Condition State contract (CS-CORE-017/018); this is not a rule for all questions | The presupposition is a fact or the audience represents a market |
| Greenhouse job posting | Employer role, salary, location, source facts | A narrow cited condition only if supported | Customer pain, willingness to pay, market gap, or a special source rule |
| SEC filing | Filing text and issuer/filing facts | A cited condition-state statement | Legal truth beyond filing, materiality, or investment advice |
| RSS/product announcement | Published announcement and feed facts | A cited status condition or unknown | Adoption, unmet demand, competitor conclusion, or effectiveness |

Signal owns raw evidence and collection facts. Observation owns bounded
interpretation and citation. Entity extraction remains independent Processing.
WH-question presupposition semantics (CS-ADV-004) remain unresolved, and
successful abstention/no-record behavior remains deferred.

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
| CS-CORE-013a/b and 014a/b | SUPPORTED | One Signal can create multiple records with distinct condition targets, support, and states. |
| CS-CORE-003 historical case | HANDLED AS RESOLVED | Its cited “that's long behind us now” support establishes resolved; no normalized time field is invented. |
| CS-CORE-004 historical case | HANDLED AS UNKNOWN | It does not establish current state; no normalized time field is invented. |
| CS-CORE-005/006 and CS-ADV-012 recurrence | SUPPORTED | Current state can be active where cited language supports it; recurrence counts/transitions are deferred. |
| CS-CORE-007/008 and CS-ADV-004 attribution/questions | DEFERRED | No claimant/presupposition state or successful-abstention/no-record policy is introduced for diagnostics. |
| Expected-unknown cases and ten Gemini errors | SUPPORTED | Unknown is required; model agreement/rationale cannot override it. |
| CS-CORE-009/010 and CS-ADV-001 conflicts | HANDLED AS UNKNOWN | V1 can retain cited indeterminacy; cross-source contradiction remains downstream. |
| Greenhouse false-positive incident | DEFERRED DOWNSTREAM | Narrow interpretation survives; authority and Opportunity qualification remain outside V1. |

### Required target-versus-support recheck

This table separates execution provenance from semantic provenance. Accepted
Gemini evidence is retained only as the evidence the experimental model used;
it is not automatically V1 state support. The V1 state column is the
contract/corpus state, not an endorsement of a model over-assertion. The target
column lets a downstream consumer identify the condition without resolving
pronouns or re-reading the full Signal for that purpose.

| Case | Frozen condition target | Accepted model evidence_span, if relevant | V1 state_evidence_citation | V1 condition_state | Retained record? | Deferred remainder |
| --- | --- | --- | --- | --- | --- | --- |
| CS-CORE-003 | “Last year we struggled with invoicing, but that's long behind us now.” | “that's long behind us now” | “that's long behind us now” | resolved | Yes | Normalized time/transition model |
| CS-CORE-004 | “Back in 2019 the checkout flow used to crash constantly.” | Model error: “used to crash constantly” | Absent; optional for unknown | unknown | Yes, when retained | Historical-current temporal normalization |
| CS-CORE-013a | “The homepage loads fine now” | Same as target | Same as target | resolved | Yes | Automatic target discovery |
| CS-CORE-013b | “the search feature is still broken” | Same as target | Same as target | active | Yes | Automatic target discovery |
| CS-CORE-014a | “We fixed invoicing” | Same as target | Same as target | resolved | Yes | Automatic target discovery |
| CS-CORE-014b | “onboarding is still painful” | Same as target | Same as target | active | Yes | Automatic target discovery |
| CS-CORE-017 | “Is the invoicing bug fixed yet?” | Same as target | Same as target; optional for unknown | unknown | Yes, when retained | Successful-abstention/no-record policy |
| CS-CORE-018 | “Has anyone found a workaround for the export issue?” | Same as target | Same as target; optional for unknown | unknown | Yes, when retained | Successful-abstention/no-record policy |
| CS-ADV-004 | “Why does checkout still fail after the last deploy?” | “checkout still fail” | Absent; diagnostic state is not settled | Not settled; diagnostic | Not decided | Question presupposition and successful-abstention/no-record policy |
| CS-CORE-009 | “Support says it's fixed, but I'm still getting the same error.” | Model error: “I'm still getting the same error” | Absent; optional for unknown | unknown | Yes, when retained | Conflict policy and correction lineage |
| CS-CORE-010 | “I keep hearing it's resolved, but nothing has actually changed on my end.” | Model error: “nothing has actually changed on my end” | Absent; optional for unknown | unknown | Yes, when retained | Attribution/conflict policy and correction lineage |
| CS-CORE-012 | “It's mostly fixed, just a couple of edge cases remain.” | Model error: “a couple of edge cases remain” | Absent; optional for unknown | unknown | Yes, when retained | Partial-resolution normalization |
| CS-CORE-028 | “The report says our churn rate is still within target.” | Model error: “still within target” | Absent; optional for unknown | unknown | Yes, when retained | Domain/relevance semantics |
| CS-ADV-001 | “It's not resolved, despite what the release notes claim.” | Model error: “It's not resolved” | Absent; optional for unknown | unknown | Yes, when retained | Attribution/conflict policy |
| CS-ADV-006 | “This isn't a permanent fix, but it's holding for now.” | Model error: “it's holding for now” | Absent; optional for unknown | unknown | Yes, when retained | Partial-resolution semantics |
| CS-ADV-007 | “The equation was finally solved after three attempts.” | Model error: “The equation was finally solved” | Absent; optional for unknown | unknown | Yes, when retained | Condition/domain applicability |
| CS-ADV-008 | “The DNS record resolved to the wrong IP again.” | Model error: “The DNS record resolved to the wrong IP again.” | Absent; optional for unknown | unknown | Yes, when retained | Condition/domain applicability |
| CS-ADV-009 | “Our margins remain healthy despite rising costs.” | Model error: “Our margins remain healthy” | Absent; optional for unknown | unknown | Yes, when retained | Positive-state/relevance semantics |

**Contract gap check:** none. Every unsolved concern is explicit and excluded
rather than hidden as an optional field.

---

## Part 10 — Deferred questions ledger

| Deferred question | Why unresolved | Evidence needed | Likely later owner |
| --- | --- | --- | --- |
| Automatic segmentation / producer target supply | NIC-17 supplied target spans | Discovery/overlap/no-safe-target evaluation | NIC-6/NIC-7 Processing |
| Multi-fragment citations / targets spanning title plus content | NIC-15/17 tested one contiguous target_span | Citation-shape evaluation with cross-component targets | Later profile / Processing design |
| Null abstention lifecycle | Allowed but absent in accepted runs | Labeled abstention and operational-policy cases | Interpreter/evaluation design |
| Successful abstention versus no retained record | NIC-20 leaves null/abstention lifecycle open | Cases and policy that distinguish successful abstention from unknown and from operational failure | Interpreter/evaluation design |
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
- **Condition target:** “checkout flow still fails”.
- **State support:** “still fails”.
- **Observation:** condition_state active; semantic_contract_version
  condition-state/v1.
- **Must not assert:** representative demand, Problem identity, or Opportunity.

### 2. Resolved condition

- **Signal says/stores:** “The homepage loads fine now after the cache fix.”
- **Condition target:** “The homepage loads fine now after the cache fix.”
- **State support:** “loads fine now”.
- **Observation:** resolved.
- **Must not assert:** permanence or resolution of related conditions elsewhere.

### 3. Ambiguous/unknown condition

- **Signal says/stores:** “The checkout flow used to crash constantly in
  2019.”
- **Condition target:** “The checkout flow used to crash constantly in 2019.”
- **State support:** “used to crash constantly in 2019” is retained
  optionally for this unknown reading.
- **Observation:** unknown.
- **Must not assert:** current active or resolved state.

### 4. One Signal producing multiple observations

- **Signal says/stores:** “The homepage loads fine now, but search is still
  broken.”
- **Observation A:** target and support “homepage loads fine now”; state
  resolved.
- **Observation B:** target and support “search is still broken”; state active.
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
- **Condition target:** “The company resolved the identified reporting control
  deficiency.”
- **State support:** “resolved the identified reporting control deficiency”.
- **Observation:** resolved for that cited condition.
- **Must not assert:** legal truth beyond the filing, materiality, or advice.

### 7. Question whose presupposition is not asserted fact

- **Signal says/stores:** “Why does checkout still fail after the deploy?”
- **Condition target:** the literal question, if a future producer identifies
  one.
- **State support:** no V1 policy is selected for this diagnostic shape.
- **Observation:** neither unknown nor no record is mandated after successful
  execution; that abstention/no-record policy remains deferred.
- **Must not assert:** that checkout fails. The question policy remains open.

---

## Part 12 — Decision

OBSERVATION V1 CONTRACT READY FOR FINAL APPROVAL

This amended proposal is ready for final independent architectural review:
each retained field has a bounded evidenced purpose, citations use only the
tested canonical single-span shape, target identity is separate from state
support and interpretation value, and unresolved semantics are explicit
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
