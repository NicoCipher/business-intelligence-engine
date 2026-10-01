"""Tests for BIA-59 producer authorization and supplied target execution."""

import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database
from collectors.base import persist_signals
from models import (
    CitationSourcePart,
    ObservationCitation,
    ObservationConditionState,
    ObservationProducerKind,
    Signal,
)
from observation_producer_registry import (
    PRODUCER_REGISTRY,
    ApprovedProducerProfile,
    ObservationProducer,
    ObservationProducerNotAuthorized,
    ObservationProducerRegistry,
    authorize_attempt,
    invoke_authorized_producer,
)
from observation_service import (
    AuthorizedObservationAttempt,
    ObservationResultInput,
    ObservationRunInput,
    ObservationServiceError,
    persist_produced,
)


CONTRACT_V1 = "condition-state/v1"


def citation(text: str = "condition remains active") -> ObservationCitation:
    return ObservationCitation(CitationSourcePart.CONTENT, text)


def profile(
    kind: ObservationProducerKind = ObservationProducerKind.RULE,
    name: str | None = "reviewed",
    revision: str | None = "r1",
    versions: tuple[str, ...] = (CONTRACT_V1,),
) -> ApprovedProducerProfile:
    return ApprovedProducerProfile(kind, name, revision, frozenset(versions))


def run_input(
    *,
    kind: ObservationProducerKind = ObservationProducerKind.RULE,
    name: str | None = "reviewed",
    revision: str | None = "r1",
    version: str = CONTRACT_V1,
    signal_id: str = "canonical-1",
) -> ObservationRunInput:
    return ObservationRunInput(
        "run-1",
        signal_id,
        citation(),
        version,
        kind,
        "attempted",
        name,
        revision,
    )


def test_production_registry_ships_empty_and_authorizes_nothing():
    assert PRODUCER_REGISTRY.profiles == ()
    assert PRODUCER_REGISTRY.profile_for(
        ObservationProducerKind.RULE, "reviewed", "r1"
    ) is None
    with pytest.raises(ObservationProducerNotAuthorized):
        authorize_attempt(PRODUCER_REGISTRY, run_input())


def test_registry_and_profiles_are_deeply_immutable():
    approved = profile()
    registry = ObservationProducerRegistry((approved,))
    with pytest.raises(FrozenInstanceError):
        registry.profiles = ()
    with pytest.raises(FrozenInstanceError):
        approved.producer_name = "other"
    with pytest.raises(TypeError, match="immutable tuple"):
        ObservationProducerRegistry([approved])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ApprovedProducerProfile"):
        ObservationProducerRegistry((object(),))  # type: ignore[arg-type]


def test_duplicate_identity_is_rejected_even_if_contract_sets_differ():
    with pytest.raises(ValueError, match="duplicate producer profile"):
        ObservationProducerRegistry((
            profile(versions=(CONTRACT_V1,)),
            profile(versions=("condition-state/v2",)),
        ))


def test_optional_name_and_revision_are_exact_values_not_wildcards():
    registry = ObservationProducerRegistry((
        profile(name=None, revision=None),
    ))
    assert registry.profile_for(ObservationProducerKind.RULE, None, None) is not None
    assert registry.profile_for(
        ObservationProducerKind.RULE, "reviewed", None
    ) is None
    assert registry.profile_for(
        ObservationProducerKind.RULE, None, "r1"
    ) is None

    human_with_revision = profile(
        kind=ObservationProducerKind.HUMAN,
        name="operator",
        revision="rev-a",
    )
    assert human_with_revision.producer_revision == "rev-a"


def test_supplied_optional_metadata_must_be_nonempty_when_present():
    with pytest.raises(ValueError):
        profile(name="")
    with pytest.raises(ValueError):
        profile(revision="")
    with pytest.raises(ValueError):
        profile(versions=())


def test_authorization_requires_exact_identity_and_contract_version():
    registry = ObservationProducerRegistry((
        profile(versions=(CONTRACT_V1, "condition-state/v2")),
    ))
    authorized = authorize_attempt(registry, run_input())
    assert isinstance(authorized, AuthorizedObservationAttempt)

    with pytest.raises(ObservationProducerNotAuthorized):
        authorize_attempt(registry, run_input(name="other"))
    with pytest.raises(ObservationProducerNotAuthorized):
        authorize_attempt(registry, run_input(revision="r2"))
    with pytest.raises(ObservationProducerNotAuthorized):
        authorize_attempt(
            registry,
            run_input(kind=ObservationProducerKind.MODEL),
        )
    with pytest.raises(ObservationProducerNotAuthorized):
        authorize_attempt(registry, run_input(version="condition-state/v3"))


def test_registry_never_selects_newest_contract_implicitly():
    registry = ObservationProducerRegistry((
        profile(versions=(CONTRACT_V1, "condition-state/v2")),
    ))
    with pytest.raises(ObservationProducerNotAuthorized):
        authorize_attempt(registry, run_input(version="condition-state/v999"))


def test_authorize_attempt_rejects_non_contract_shapes():
    with pytest.raises(TypeError, match="ObservationProducerRegistry"):
        authorize_attempt(object(), run_input())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ObservationRunInput"):
        authorize_attempt(
            ObservationProducerRegistry((profile(),)),
            object(),  # type: ignore[arg-type]
        )


def test_authorized_attempt_cannot_be_constructed_directly_or_leak_issue_token():
    with pytest.raises(TypeError):
        AuthorizedObservationAttempt(run=run_input())
    with pytest.raises(TypeError):
        AuthorizedObservationAttempt(run=run_input(), _token=object())

    authorized = authorize_attempt(
        ObservationProducerRegistry((profile(),)),
        run_input(),
    )
    assert "_token" not in vars(authorized)


class _TestProducer:
    producer_kind = ObservationProducerKind.RULE
    producer_name = "reviewed"
    producer_revision = "r1"

    def produce(
        self,
        signal: Signal,
        run: ObservationRunInput,
    ) -> ObservationResultInput:
        return ObservationResultInput(
            observation_id="producer-observation",
            canonical_signal_id=signal.id,
            condition_citation=run.attempted_condition_citation,
            condition_state=ObservationConditionState.ACTIVE,
            semantic_contract_version=run.attempted_semantic_contract_version,
            recorded_at="recorded",
            state_evidence_citation=ObservationCitation(
                CitationSourcePart.CONTENT, "active"
            ),
        )


def test_test_only_producer_executes_through_authorized_service_boundary(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "bia.db")
    database.initialize()

    stored = Signal(
        source="rss",
        source_id="source-1",
        title="Condition",
        content="The condition remains active today.",
        id="canonical-1",
    )
    first = persist_signals([stored]).resolutions[0]
    assert first.persisted_signal is not None

    duplicate = Signal(
        source="rss",
        source_id="source-1",
        title="Recollected title that must not become provenance",
        content="Recollected content",
        id="collector-temporary-id",
    )
    resolution = persist_signals([duplicate]).resolutions[0]
    signal = resolution.persisted_signal
    assert signal is not None
    assert signal.id == "canonical-1"
    assert signal.content == "The condition remains active today."

    registry = ObservationProducerRegistry((profile(),))
    authorized = authorize_attempt(
        registry,
        run_input(signal_id=signal.id),
    )
    producer: ObservationProducer = _TestProducer()
    result = invoke_authorized_producer(producer, signal, authorized)
    persisted = persist_produced(result, authorized, produced_at="produced")

    assert persisted.created
    assert persisted.observation.signal_id == "canonical-1"
    assert persisted.run.producer_name == "reviewed"


def test_invocation_rejects_actual_producer_identity_mismatch():
    class WrongRevision(_TestProducer):
        producer_revision = "r2"

    registry = ObservationProducerRegistry((profile(),))
    authorized = authorize_attempt(registry, run_input())
    signal = Signal(
        source="rss",
        source_id="source-1",
        title="Condition",
        content="The condition remains active today.",
        id="canonical-1",
    )
    with pytest.raises(ObservationProducerNotAuthorized):
        invoke_authorized_producer(WrongRevision(), signal, authorized)


def test_invocation_rejects_signal_identity_mismatch_before_producer_runs():
    registry = ObservationProducerRegistry((profile(),))
    authorized = authorize_attempt(registry, run_input())
    signal = Signal(
        source="rss",
        source_id="source-2",
        title="Condition",
        content="The condition remains active today.",
        id="not-canonical-1",
    )
    with pytest.raises(ObservationServiceError, match="canonical Signal"):
        invoke_authorized_producer(_TestProducer(), signal, authorized)


def test_invocation_rejects_non_signal_and_non_result_shapes():
    registry = ObservationProducerRegistry((profile(),))
    authorized = authorize_attempt(registry, run_input())

    with pytest.raises(TypeError, match="canonical persisted Signal"):
        invoke_authorized_producer(
            _TestProducer(),
            object(),  # type: ignore[arg-type]
            authorized,
        )

    class WrongResult(_TestProducer):
        def produce(self, signal: Signal, run: ObservationRunInput):
            return object()

    signal = Signal(
        source="rss",
        source_id="source-1",
        title="Condition",
        content="The condition remains active today.",
        id="canonical-1",
    )
    with pytest.raises(ObservationServiceError, match="ObservationResultInput"):
        invoke_authorized_producer(WrongResult(), signal, authorized)
