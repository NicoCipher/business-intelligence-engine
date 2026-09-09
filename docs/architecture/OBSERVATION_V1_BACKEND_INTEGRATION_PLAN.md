# Observation V1 — Backend Integration Plan

Status: **NIC-6 design only**. This is an implementation plan, not DDL, runtime code, an interpreter, pipeline wiring, API, or downstream integration.

## 1. Persistence decision

| Object | Decision | Reason |
| --- | --- | --- |
| Immutable InterpretedObservation records | Persisted | Signal provenance, correction lineage, historical replay, audit, NIC-7 tests, and NIC-9 measurement need durable records. |
| Target-level interpreter/run provenance | Persisted | Operational failures create no Observation but must retain the attempted Signal/citation/semantic contract for audit and retry. |

Transient-only storage loses replay and lineage; persisting only semantic results loses failures. Persistence grants no consumer authority: Correlation, Problems, Opportunities, scoring, reports, Findings, APIs, and frontend remain non-consumers.

## 2. Conceptual storage shape

Conceptual structure `interpreted_observations` is append-only. Fields are `observation_id TEXT NOT NULL PRIMARY KEY`; `signal_id` (not-null FK to `signals(id)`, restrict delete); condition citation (`source_part` CHECK title/content, exact case-preserving non-empty `literal_text`, positive overlap-inclusive ordinal); optional state citation of the same shape; `condition_state` CHECK active/resolved/unknown; non-empty `semantic_contract_version`; nullable `supersedes_observation_id` self-FK (not self); and `recorded_at` audit timestamp. Every field is immutable.

SQLite CHECKs enforce enums, non-empty/positive values, state-citation all-or-none, active/resolved support, same source part, foreign keys, and no self-link. Explicit `NOT NULL` primary-key semantics enforce non-null Observation and run identities; primary key alone is not relied upon for this in SQLite rowid tables. A `UNIQUE` constraint/index on non-null `supersedes_observation_id` permits multiple NULL roots while allowing one predecessor at most one direct successor. Local SQLite `BEFORE INSERT` triggers on each append-only table abort if `NEW.observation_id` or `NEW.run_id`, respectively, already exists; this applies before same-key replacement and does not depend on globally enabling `PRAGMA recursive_triggers`. SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers also abort writes on both conceptual tables. Together, a fresh non-null unique insert is allowed, while NULL identity, UPDATE, DELETE, same-key INSERT, `INSERT OR REPLACE`, and `REPLACE INTO` of an existing immutable row are rejected. SQLite `BEFORE UPDATE OF title, content` triggers on `signals` also abort any post-insert change to citation-bearing Signal text, so stored literal citations and overlap ordinals remain resolvable. Application validation against preserved `Signal.title`/`content` enforces literal occurrence, overlapping ordinal, and state-support containment. `Signal.full_text` is never citation provenance. Index Signal ID, supersession ID, and literal-citation lookup.

No uniqueness key claims canonical semantic target identity. Exact-result reuse is a transactionally serialized application lookup over the full approved payload: Signal ID, both citation components including nullness, state, semantic-contract version, and supersession link. It never equates alternate boundaries, normalized text, topics, entities, or inferred meaning.

Conceptual structure `observation_runs` is append-only. Fields are `run_id TEXT NOT NULL PRIMARY KEY`; `attempted_signal_id` not-null FK to `signals(id)` with `ON DELETE RESTRICT`; attempted condition citation in the approved shape; required non-empty `attempted_semantic_contract_version`; `producer_kind` CHECK human/rule/model; name/revision when defined by the approved profile; `attempted_at`; conditional `produced_at`; outcome CHECK produced/operational_failure; and conditional `resulting_observation_id` FK. It has indexes for attempted Signal/time, producer/revision, and result ID. The attempted contract is the contract selected for this target-level attempt before execution; it is retained explicitly, not inferred from producer kind/name/revision, registry configuration, or the newest available contract. This restrictive FK prevents `INSERT OR REPLACE` from using delete-and-reinsert semantics to rewrite citation-bearing Signal text for a retained failure run.

For `produced`, SQLite requires exactly one result ID and `produced_at`; for `operational_failure`, both are null. One retained attempt has at most one result reference. A produced run yielded or confirmed that result; it does not prove the attempt created the immutable record. A database INSERT-time trigger (or equivalent database constraint logic) for `produced` additionally requires the referenced Observation to exist and to match exactly: `signal_id == attempted_signal_id`, every condition-citation component (`source_part`, `literal_text`, and occurrence ordinal) == the attempted condition citation, and `semantic_contract_version == attempted_semantic_contract_version`. It aborts a mismatched insert, so direct SQL cannot create a false run/result association. An operational failure retains its attempted Signal, full condition citation, and attempted contract but has no result reference or Observation lookup. No creator-run field, dedup flag, opaque semantic JSON, new outcome, reverse Observation-to-run FK, or batch/multi-output design is added.

When a new Observation is retained, its initial produced run is inserted in the **same SQLite transaction**, after the Observation row exists for the produced-run correspondence check. Failure of that check or the run insert rolls back the Observation insert, so no newly created record is detached from its required initial provenance. Exact-result reuse does not create an Observation; it inserts only a new produced run referencing the existing exact result.

### Enforcement responsibility split

| SQLite enforces | Application enforces |
| --- | --- |
| FK integrity; enum/CHECK/null-cardinality rules; non-null Observation identity and non-null run identity; produced/failure result cardinality; append-only UPDATE/DELETE rejection; prevention of same-primary-key replacement for Observation rows and run rows; single-successor uniqueness; produced-run exact target correspondence; produced-run semantic-contract correspondence; citation-bearing `signals.title`/`content` UPDATE rejection | Citation resolution; overlapping occurrence verification; support containment; cycle detection; exact-result reuse transaction logic; interpreter approval; registry/config selection; semantic-contract compatibility before execution |

## 3. Canonical persisted-Signal identity

Current `persist_signals(domain_signals)` returns only a count. Its `(source, source_id, domain)` deduplication can leave collector-created in-memory IDs unpersisted. Observation cannot reference them.

**Decision:** future persistence returns a resolution per input: dedup key, `canonical_signal_id`, and `inserted|existing`. The persistence boundary owns this mapping. Observation hydrates the canonical stored Signal before interpreting/validating citations, so actual persisted title/content is the evidence. Callers must not recreate IDs.

Dry runs intentionally have no persisted Signal identity. They invoke no retained Observation stage and create no Observation/run. A future labelled simulation is separate and must not persist temporary IDs.

## 4. Pipeline placement

```
Collection → Signal persistence / canonical identity
                         ↓
                    Processing
          ┌──────────────┴──────────────┐
          │                             │
Observation interpretation   Entity/Relationship extraction
          │                             │
          └──────────────┬──────────────┘
                         ↓
 existing raw-Signal detector, scoring, Problem, report stages
```

Observation consumes canonical persisted Signals plus supplied target attempts. Entity extraction is a sibling: neither consumes the other. Manual and scheduled non-dry runs use the same seam. Per-target Observation failure persists only a failure run, logs, and continues extraction and every existing raw-Signal stage. No Signal row is changed.

## 5. Zero-result boundary

| Situation | Handling |
| --- | --- |
| Signal with no supplied target-level attempt | No Observation and no run; not unknown, failure, or abstention. Automatic segmentation remains deferred. |
| Supplied target yields unknown | Persist unknown Observation and produced run; support optional. |
| Supplied target operationally fails | Persist failure run only; no Observation/result reference. |
| Successful no result for supplied target | Deferred; do not map it to a current outcome. |

## 6. Interpreter selection

A later configuration/registry allow-list selects an explicitly approved producer by kind, name, revision, and supported semantic-contract version. It is interpreter-neutral and never “newest wins.” NIC-6 selects none: Gemini and rules-v1 remain experimental evidence. Producer revision is separate from semantic-contract version.

## 7. Reruns, correction lineage, and reads

| Event | Behavior |
| --- | --- |
| Retry after failure | New run for same canonical attempted input; no failure Observation. |
| Same exact semantic payload | Produced run may reuse/reference existing Observation; no authorship inference. |
| Changed state, support, occurrence, boundary, Signal, or contract | New immutable correction, superseding prior record when applicable. |
| Historical backfill | Only supplied target attempts; never mutates Signals, Problems, Opportunities, scores, or reports. |

Readers traverse `supersedes_observation_id`: predecessor is historical and the terminal record current for that lineage. SQLite rejects a second direct successor through the non-null unique constraint; application validation rejects self-links and cycles. Cross-Signal/target correction remains allowed. Exact reuse does not resolve semantic equivalence across valid alternative boundaries.

## 8. Migration and backfill

Implementation uses the next available schema version, not a hardcoded number, and follows `database.initialize()` ordered idempotent fresh/upgrade migrations. New-table DDL, constraints, and indexes must be tested for both paths; a migration failure rolls back without changing existing intelligence.

No automatic historic-Signal backfill is selected because it requires deferred target discovery. A later explicit backfill must isolate per-attempt failure, resume safely, and never recompute/mutate existing Signals, Entities, Problems, Opportunities, scores, reports, or history.

## 9. NIC-7 test matrix

| Area | Required coverage |
| --- | --- |
| Citation | title/content part; exact case; non-empty; overlap ordinal; support containment; direct-SQL rejection of post-insert `signals.title`/`content` updates and `INSERT OR REPLACE` rewrites when an Observation or failure run references the Signal. |
| State | active/resolved support; optional unknown support; triad only. |
| Records | direct-SQL NULL observation ID rejection (so repeated NULL IDs cannot create rows); UPDATE/DELETE rejection; existing same-key INSERT, `INSERT OR REPLACE`, and `REPLACE INTO` are rejected and leave the original row field-equivalent; fresh non-null unique Observation insert succeeds; one Signal/multiple supplied targets; cross-target/Signal correction; duplicate successor rejection, multiple NULL roots, and cycle validation. |
| Runs | direct-SQL NULL run ID rejection (so repeated NULL IDs cannot create rows); failure retains attempted semantic contract and has no Observation/result; produced has exactly one and its contract matches the referenced Observation; result confirmation is not authorship; valid exact correspondence is accepted; mismatched attempted Signal, citation source part, literal text, occurrence ordinal, or attempted contract are rejected; initial Observation/run atomicity rolls back if run insertion or correspondence validation fails; existing same-key INSERT, `INSERT OR REPLACE`, and `REPLACE INTO` are rejected and leave the original row field-equivalent; fresh non-null unique run insert succeeds; producer revision alone is insufficient contract provenance; no deferred no-result emission. |
| Identity | duplicate collection maps canonical Signal ID; temporary ID rejected; dry run retains nothing. |
| Isolation | one failure continues other attempts, extraction, and raw-Signal stages; sibling independence. |
| Rerun | retry; exact reuse; changed correction/contract; no alternate-boundary equivalence. |
| Migration | fresh/upgrade, constraints/indexes, rollback, no automatic backfill side effect. |
| Non-consumption | detector/scorer/watch list/Correlation/Problem/Opportunity/report/API make no Observation reads. |

## 10. Future backend change map

| Category | Components | Why |
| --- | --- | --- |
| Must change | `backend/database.py`, migration tests | Tables, constraints/indexes, ordered upgrade/fresh behavior. |
| Must change | `backend/models.py` | Immutable Observation/run representations. |
| Must change | `backend/collectors/base.py` | Per-input canonical persisted-Signal resolution. |
| Must change | `backend/pipeline.py` | Sibling stage, canonical handoff, dry-run/failure isolation. |
| Likely | New Observation module and NIC-7 tests | Producer interface, validator, persistence/replay. |
| Likely | Scheduler outcome projection | Only operational visibility, never semantic consumption. |
| Must not change | detector, scorer, Watch List | Raw-Signal non-consumers in V1. |
| Must not change | canonicalizer, Problem/history, reports, APIs, frontend, collector source semantics | No downstream/source-authority rewiring. |

## 11. Deferred questions

Automatic segmentation/target supply; semantic target equivalence/canonical boundaries; multi-fragment/cross-part citations; successful abstention; attribution; question presupposition; temporal, recurrence, geography normalization; entity references and `topic_key`; generic facts; source capability/authority; BIA confidence; cross-source contradiction; production interpreter choice; multi-output execution; semantic downstream consumers; and creator/reuse detail beyond run-result provenance.

## 12. Approval gate

NIC-7 may implement contract tests only after independent review. Later runtime work must implement this plan without deciding deferred semantics by convenience.
