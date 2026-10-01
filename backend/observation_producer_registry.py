"""BIA-59 — Producer-neutral registry and supplied target-attempt boundary.

This module answers exactly one question: is this specific producer,
at this specific revision, approved to attempt this specific semantic
contract? It does not decide which producer should run and does not wire itself into
anything downstream. It defines the producer-neutral callable contract and an
explicit invocation helper for a caller-supplied, already-authorized producer;
it never selects or discovers a producer on its own.

The production registry (PRODUCER_REGISTRY below) ships empty. BIA-59
builds the authorization mechanism; it does not approve a producer.
Adding the first approved producer is BIA-61's job, done by editing
this file through the same review discipline as any other change here.

Identity: producer_name and producer_revision are optional fields
whose allowed values are determined by the exact approved producer
profile -- not a blanket rule keyed on producer_kind. BIA-6
(docs/architecture/OBSERVATION_V1_BACKEND_INTEGRATION_PLAN.md) states
"name/revision when defined by the approved profile"; this module does
not add a requirement the authoritative contract doesn't impose. A
profile may declare producer_name=None, producer_revision=None, or
specific non-empty values for any producer_kind -- what matters is
that authorize_attempt() exact-matches (kind, name, revision) against
a registered profile, treating None as a literal value to match, never
as a wildcard meaning "any". An unmatched combination -- including one
that only fails to match because of a None where a profile expects a
value, or vice versa -- is rejected the same way any other unlisted
identity is.

Every profile also carries an explicit, finite set of contract
versions it is approved to emit — never "any version this producer
happens to emit" — so a revision cannot silently gain authorization
for a contract version it was never evaluated against.

See docs/architecture/OBSERVATION_V1_PRODUCER_REGISTRY_AND_TARGET_ATTEMPT_BOUNDARY.md
for the full design rationale, including why this registry is a frozen
dataclass over a tuple (not a dict-backed structure) and why the
capability type it issues (AuthorizedObservationAttempt) is owned by
observation_service.py rather than by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from models import (
    ObservationProducerKind,
    ObservationRun,
    ObservationRunOutcome,
    Signal,
)
from observation_service import (
    AuthorizedObservationAttempt,
    ObservationResultInput,
    ObservationRunInput,
    ObservationServiceError,
    _issue_authorized_attempt,
    load_canonical_persisted_signal,
)


class ObservationProducer(Protocol):
    """Producer-neutral callable contract for one supplied target attempt.

    The producer identity is explicit and must exactly match the authorized
    ObservationRunInput before produce() is invoked. BIA-59 defines this seam
    without selecting any concrete production producer.
    """

    producer_kind: ObservationProducerKind
    producer_name: str | None
    producer_revision: str | None

    def produce(
        self, signal: Signal, run: ObservationRunInput
    ) -> ObservationResultInput:
        """Interpret exactly the supplied target attempt for one Signal."""
        ...


class ObservationProducerNotAuthorized(ObservationServiceError):
    """A run attempt's producer identity or contract version is not approved."""


def _required_text(value: str | None, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")


@dataclass(frozen=True)
class ApprovedProducerProfile:
    """One approved (kind, name, revision) identity and the contract
    versions it may emit.

    producer_name and producer_revision are optional, matching
    ObservationRunInput and the observation_runs schema exactly: BIA-6
    (docs/architecture/OBSERVATION_V1_BACKEND_INTEGRATION_PLAN.md)
    specifies "name/revision when defined by the approved profile" --
    not a per-kind requirement. This module does not impose a blanket
    "RULE/MODEL always need a revision" or "HUMAN never has one" rule;
    whether a given profile uses None or a specific value is exactly
    what that profile declares, and the registry matches it exactly,
    None included as a literal value, not a wildcard. If a future
    concrete need arises to require identity for a specific kind, that
    is a property of the specific profiles registered, not of this
    type.
    """

    producer_kind: ObservationProducerKind
    producer_name: str | None
    producer_revision: str | None
    approved_contract_versions: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.producer_kind, ObservationProducerKind):
            raise TypeError(
                "ApprovedProducerProfile.producer_kind must be an ObservationProducerKind"
            )
        for field_name, value in (
            ("ApprovedProducerProfile.producer_name", self.producer_name),
            ("ApprovedProducerProfile.producer_revision", self.producer_revision),
        ):
            if value is not None:
                _required_text(value, field_name)
        if not isinstance(self.approved_contract_versions, frozenset) or not self.approved_contract_versions:
            raise ValueError(
                "ApprovedProducerProfile.approved_contract_versions must be a "
                "non-empty frozenset"
            )
        for version in self.approved_contract_versions:
            _required_text(
                version, "ApprovedProducerProfile.approved_contract_versions entry"
            )


@dataclass(frozen=True)
class ObservationProducerRegistry:
    """An immutable set of approved producer profiles.

    profiles is a tuple, not a dict: the registry is expected to hold a
    handful of entries at most, so a linear scan in profile_for() needs
    no auxiliary mutable structure that would itself have to be kept
    immutable. Being a frozen dataclass means `profiles` cannot be
    reassigned after construction (dataclasses.FrozenInstanceError),
    and a tuple has no in-place mutation — there is exactly one thing
    here that could vary, and it cannot.
    """

    profiles: tuple[ApprovedProducerProfile, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.profiles, tuple):
            raise TypeError(
                "ObservationProducerRegistry.profiles must be an immutable tuple"
            )
        seen: set[tuple[ObservationProducerKind, str | None, str | None]] = set()
        for profile in self.profiles:
            if not isinstance(profile, ApprovedProducerProfile):
                raise TypeError(
                    "ObservationProducerRegistry.profiles entries must be "
                    "ApprovedProducerProfile values"
                )
            key = (profile.producer_kind, profile.producer_name, profile.producer_revision)
            if key in seen:
                raise ValueError(
                    f"duplicate producer profile: {key!r}"
                )
            seen.add(key)

    def profile_for(
        self,
        producer_kind: ObservationProducerKind,
        producer_name: str | None,
        producer_revision: str | None,
    ) -> ApprovedProducerProfile | None:
        for profile in self.profiles:
            if (
                profile.producer_kind == producer_kind
                and profile.producer_name == producer_name
                and profile.producer_revision == producer_revision
            ):
                return profile
        return None


# The production registry. Ships empty by design: BIA-59 builds the
# authorization mechanism, it does not approve a producer. Every
# attempt against this instance is rejected until a future, reviewed
# change (BIA-61) adds a real entry. Never add a test-only profile
# here — test profiles belong only in test fixtures, as a separately
# constructed ObservationProducerRegistry passed explicitly into
# authorize_attempt(), never assigned to this module-level instance.
PRODUCER_REGISTRY = ObservationProducerRegistry(())


def _validate_run_input(run: ObservationRunInput) -> None:
    """Apply the complete retained-run structural contract before execution.

    ObservationRunInput is intentionally a lightweight transport object. Before
    issuing a capability, reuse ObservationRun's canonical model validation so
    a producer cannot run for an attempt that could never be retained.
    """
    ObservationRun(
        run_id=run.run_id,
        attempted_signal_id=run.attempted_signal_id,
        attempted_condition_citation=run.attempted_condition_citation,
        attempted_semantic_contract_version=run.attempted_semantic_contract_version,
        producer_kind=run.producer_kind,
        producer_name=run.producer_name,
        producer_revision=run.producer_revision,
        attempted_at=run.attempted_at,
        outcome=ObservationRunOutcome.OPERATIONAL_FAILURE,
    )


def authorize_attempt(
    registry: ObservationProducerRegistry, run: ObservationRunInput
) -> AuthorizedObservationAttempt:
    """Check a supplied target attempt against the registry's policy.

    Returns an AuthorizedObservationAttempt on success. Raises
    ObservationProducerNotAuthorized on any mismatch, before anything
    touches the database -- no observation_runs row is written for a
    rejected attempt; retaining one would put an unapproved producer
    identity into the same table this gate exists to keep clean.
    """
    if not isinstance(registry, ObservationProducerRegistry):
        raise TypeError("registry must be an ObservationProducerRegistry")
    if not isinstance(run, ObservationRunInput):
        raise TypeError("run must be an ObservationRunInput")
    _validate_run_input(run)
    profile = registry.profile_for(
        run.producer_kind, run.producer_name, run.producer_revision
    )
    if profile is None:
        raise ObservationProducerNotAuthorized(
            f"producer not authorized: kind={run.producer_kind!r} "
            f"name={run.producer_name!r} revision={run.producer_revision!r}"
        )
    if run.attempted_semantic_contract_version not in profile.approved_contract_versions:
        raise ObservationProducerNotAuthorized(
            f"producer {run.producer_kind!r}/{run.producer_name!r}/{run.producer_revision!r} "
            f"is not approved for contract version "
            f"{run.attempted_semantic_contract_version!r}"
        )
    return _issue_authorized_attempt(run)


def invoke_authorized_producer(
    producer: ObservationProducer,
    signal: Signal,
    authorized: AuthorizedObservationAttempt,
) -> ObservationResultInput:
    """Invoke one explicitly supplied producer for one authorized target.

    This is the BIA-59 producer interface seam, not producer selection. The
    caller supplies the producer, canonical persisted Signal, and capability.
    BIA-60 may later call this seam from the shadow pipeline; BIA-59 itself
    wires it nowhere. Operational-failure handling remains with the future
    caller so this helper does not decide retry/continuation policy.
    """
    if not isinstance(authorized, AuthorizedObservationAttempt):
        raise ObservationServiceError(
            "invoke_authorized_producer requires an AuthorizedObservationAttempt "
            "from authorize_attempt()"
        )
    if not isinstance(signal, Signal):
        raise TypeError("signal must be a canonical persisted Signal")
    run = authorized.run
    if signal.id != run.attempted_signal_id:
        raise ObservationServiceError(
            "authorized producer attempt must receive its canonical Signal"
        )
    producer_identity = (
        producer.producer_kind,
        producer.producer_name,
        producer.producer_revision,
    )
    attempted_identity = (
        run.producer_kind,
        run.producer_name,
        run.producer_revision,
    )
    if producer_identity != attempted_identity:
        raise ObservationProducerNotAuthorized(
            "supplied producer identity does not match the authorized attempt"
        )
    canonical_signal = load_canonical_persisted_signal(run.attempted_signal_id)
    if signal != canonical_signal:
        raise ObservationServiceError(
            "supplied Signal must equal the canonical persisted Signal"
        )
    result = producer.produce(canonical_signal, run)
    if not isinstance(result, ObservationResultInput):
        raise ObservationServiceError(
            "ObservationProducer.produce() must return an ObservationResultInput"
        )
    return result
