# Observation V1 — Producer Registry and Target-Attempt Boundary

Version: 4.0  
Status: Implemented for BIA-59; pending PR review and merge  
Scope: BIA-59 / BIA-8.4  
Depends on: BIA-58 / BIA-8.3 and BIA-57 canonical Signal identity

## 1. Problem

BIA-58 validates and persists Observation results, but before BIA-59 its supported
application path accepted any caller-supplied producer identity and semantic-contract
version.

BIA-59 adds the producer-neutral trust boundary that answers:

> Is this exact producer profile approved to attempt this exact semantic contract,
> and is the supplied producer invocation the same producer and canonical Signal
> that were authorized?

BIA-59 does not select a producer, discover a target, activate the pipeline, or grant
Observation any downstream authority.

## 2. Authoritative constraints

The boundary preserves the approved Observation V1 rules:

- producer kind, name, revision, and semantic-contract version remain distinct;
- producer name and revision are optional **when defined by the approved profile**;
- `None` is an exact literal identity value, never a wildcard;
- approval is explicit and fail-closed;
- there is no implicit latest/newest producer or contract;
- automatic target discovery and segmentation remain deferred;
- production producer selection remains deferred to BIA-61;
- pipeline integration remains deferred to BIA-60;
- Observation remains unconsumed by downstream intelligence.

## 3. Chosen architecture

The execution seam is:

```
canonical persisted Signal
        +
explicit ObservationRunInput
        |
        v
ObservationProducerRegistry
        |
        | exact identity + exact contract approval
        v
AuthorizedObservationAttempt
        |
        +----------------------+
        |                      |
        v                      v
explicit supplied        operational failure
producer invocation      persistence
        |
        v
ObservationResultInput
        |
        v
BIA-58 persist_produced()
```

The production registry ships empty. BIA-59 builds the mechanism but approves no
real producer.

## 4. Module responsibilities

### `backend/observation_service.py`

BIA-58 remains the persistence owner. BIA-59 adds only the capability that its two
write paths require:

- `AuthorizedObservationAttempt`
- private `_ISSUE_TOKEN`
- private `_issue_authorized_attempt()`

`persist_produced()` and `persist_operational_failure()` now reject a raw
`ObservationRunInput` and require an `AuthorizedObservationAttempt`.

The service imports nothing from `observation_producer_registry.py`. This keeps the
dependency one-way and avoids a circular import.

### `backend/observation_producer_registry.py`

Owns producer authorization policy and the explicit producer invocation contract:

- `ObservationProducer` protocol
- `ApprovedProducerProfile`
- `ObservationProducerRegistry`
- `ObservationProducerNotAuthorized`
- `PRODUCER_REGISTRY`
- `authorize_attempt()`
- `invoke_authorized_producer()`

Dependency direction is:

```
models.py
   ^
   |
observation_service.py
   ^
   |
observation_producer_registry.py
```

## 5. Producer interface

`ObservationProducer` is a producer-neutral protocol.

A producer exposes:

- `producer_kind`
- `producer_name`
- `producer_revision`
- `produce(signal, run) -> ObservationResultInput`

BIA-59 selects no implementation. The caller supplies the producer explicitly.

`invoke_authorized_producer()` verifies:

1. the caller supplied an `AuthorizedObservationAttempt`;
2. the supplied Signal ID equals the authorized attempted Signal ID;
3. that Signal is field-equivalent to the canonical SQLite-backed Signal loaded
   for the attempted ID, preventing a transient/mutated same-ID object from
   becoming interpretation evidence;
4. the supplied producer's exact `(kind, name, revision)` identity equals the
   identity authorized in the run.

Only then is `producer.produce()` invoked, and it receives the canonical
SQLite-backed Signal rather than trusting the caller's object.

The helper does not catch producer failures, choose retry behavior, persist failure
runs, or select a fallback producer. Those concerns remain with a future caller.

## 6. Canonical Signal rule

The producer seam requires the canonical persisted Signal, not merely a
collector-temporary or mutated object that reuses the same ID.

BIA-57 already provides this boundary through
`SignalPersistenceResolution.persisted_signal`, which is hydrated from SQLite.
BIA-59 also re-loads the attempted Signal at invocation and rejects a supplied
Signal that is not field-equivalent to that canonical row, so the producer cannot
interpret transient same-ID text.

The BIA-59 execution test deliberately exercises:

```
collected Signal
  -> persist_signals()
  -> SignalPersistenceResolution.persisted_signal
  -> authorize_attempt()
  -> invoke_authorized_producer()
  -> persist_produced()
```

BIA-59 does not wire this flow into the production pipeline.

Authorization also applies the complete `ObservationRun` structural model
validation before issuing a capability. Empty run IDs, Signal IDs, contract
versions, timestamps, or supplied producer metadata therefore fail before a
producer can execute or incur side effects.

## 7. Registry identity

An `ApprovedProducerProfile` contains:

- `producer_kind`
- `producer_name: str | None`
- `producer_revision: str | None`
- non-empty `frozenset[str]` of approved semantic-contract versions

The registry matches `(kind, name, revision)` exactly.

Examples:

- a profile with revision `None` authorizes only attempts whose revision is
  also `None`;
- a profile with revision `"r1"` does not authorize revision `None`;
- a missing name/revision never means "any";
- no producer gains a new contract version merely because it is newer.

BIA-59 intentionally adds no blanket RULE/MODEL/HUMAN identity policy beyond the
approved profile itself.

## 8. Registry immutability

`ObservationProducerRegistry` is a frozen dataclass containing a tuple of frozen
`ApprovedProducerProfile` objects. Each profile contains a `frozenset` of contract
versions.

Runtime construction also rejects:

- a mutable/non-tuple profiles container;
- entries that are not `ApprovedProducerProfile`;
- duplicate `(kind, name, revision)` identities.

No mutable registry state or import-time producer self-registration exists.

This immutability is what makes pre-transaction authorization safe for BIA-59 V1:
the registry cannot change between approval and the BIA-58 transaction.

If approval ever becomes runtime-mutable or DB-backed, authorization must move into
the same transaction as persistence.

## 9. Production lifecycle

The shipped registry is:

```python
PRODUCER_REGISTRY = ObservationProducerRegistry(())
```

It authorizes nothing.

Test producers and test profiles exist only in tests. The first production producer
is a BIA-61 decision and requires a separate reviewed change.

## 10. Capability and bypass model

BIA-59 is an application architecture boundary, not database authorization.

The supported persistence path is structurally fail-closed:

- raw `ObservationRunInput` -> persistence: rejected;
- authorized capability -> persistence: accepted for further BIA-58 validation.

The capability constructor is guarded by a module-private token and is normally
issued only through `authorize_attempt()`.

Python cannot make internal code cryptographically unable to bypass this convention.
Deliberate code could import private symbols or write directly to SQLite. Such bypass
is visibly intentional and greppable; BIA-59 does not claim to prevent hostile
internal code.

## 11. Failure semantics

Authorization failure:

- raises `ObservationProducerNotAuthorized`;
- opens no Observation persistence transaction;
- writes no `observation_runs` row.

Operational producer failure:

- occurs only after an attempt was authorized;
- remains distinct from semantic output;
- may be retained through BIA-58 `persist_operational_failure()` by the future
  caller.

BIA-59 does not decide logging, retries, continuation, or scheduling policy.

## 12. Tests required

BIA-59 tests cover:

- production registry is empty;
- immutable tuple-backed registry and frozen profiles;
- rejection of mutable/non-profile registry contents;
- duplicate profile rejection;
- exact identity lookup;
- optional producer metadata;
- `None` exact-match behavior;
- approved and unapproved producer profiles;
- contract-version compatibility;
- direct capability-construction rejection;
- raw-input persistence bypass rejection through BIA-58 tests;
- test-only producer execution through the authorized boundary;
- canonical Signal identity from BIA-57;
- producer identity mismatch rejection;
- canonical Signal ID mismatch rejection;
- transient/mutated same-ID Signal rejection against the SQLite-backed row;
- malformed run-input rejection before capability issuance.

Existing BIA-58 persistence, exact-reuse, lineage, atomicity, and concurrency behavior
must remain unchanged.

## 13. Explicit non-goals

BIA-59 adds none of the following:

- Gemini, Claude, OpenAI, or any model API call;
- rules-v1 promotion;
- a production producer default;
- producer ranking or fallback;
- newest-version selection;
- automatic target discovery or segmentation;
- pipeline wiring or scheduling;
- downstream Observation consumers;
- changes to Problems, Opportunities, scoring, reports, Findings, or Analysis;
- learning, outcome feedback, or backpropagation;
- DB-backed runtime producer approval;
- mutable global registration or import-time self-registration.

## 14. Future handoff

After BIA-59 is merged and verified:

- BIA-60 may call this seam from the shadow pipeline using supplied target attempts;
- BIA-61 may choose and explicitly add the first approved production producer;
- BIA-62 verifies the complete Observation path;
- BIA-9 remains the trust gate before downstream semantic consumption.

## 15. Acceptance criteria

BIA-59 is complete when:

- the registry, producer protocol, authorization, capability, and invocation seam
  exist as described;
- the production registry is empty;
- no circular dependency exists;
- no pipeline or downstream consumer is added;
- a test-only producer executes end-to-end through canonical Signal resolution,
  authorization, invocation, and BIA-58 persistence;
- focused tests pass;
- full backend regression passes;
- scoped Ruff is clean;
- the final PR diff is independently reviewed against this document and Linear
  BIA-59 before merge.
