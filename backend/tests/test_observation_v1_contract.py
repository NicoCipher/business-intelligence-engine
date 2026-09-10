"""Structural and boundary tests for the reviewed Observation V1 corpus.

NIC-7 intentionally does not import an interpreter, create schema objects, or
wire the pipeline. These tests lock the production contract fixtures and the
future enforcement matrix before implementation begins in later issues.
"""

from dataclasses import fields, replace

from tests.condition_state_eval.dataset import CASES as NIC_17_CASES
from tests.observation_v1_contract.corpus import (
    BOUNDARY_CASES,
    CONTRACT_CASES,
    IMPLEMENTATION_MATRIX_CASES,
    LINEAGE_CONTRACT_CASES,
    SEMANTIC_CONTRACT_VERSION,
    STORAGE_CONTRACT_CASES,
    BoundaryCase,
    CitationExpectation,
    Classification,
    ConditionState,
    ContractCase,
    EnforcementLayer,
    MatrixExpectation,
    ObservationExpectation,
    ProducerKind,
    RunExpectation,
    RunOutcome,
    SourcePart,
    StorageExpectation,
    resolve_citation,
    validate_contract_cases,
)
from tests.semantic_eval.corpus import CORPUS as BASELINE_CORPUS
from tests.semantic_eval.corpus import PRESERVE_CASE_IDS

_CASES = {case.case_id: case for case in CONTRACT_CASES}
_BOUNDARIES = {case.case_id: case for case in BOUNDARY_CASES}
_STORAGE = {case.case_id: case for case in STORAGE_CONTRACT_CASES}
_LINEAGE = {case.case_id: case for case in LINEAGE_CONTRACT_CASES}
_MATRIX = {case.case_id: case for case in IMPLEMENTATION_MATRIX_CASES}


def test_contract_corpus_has_no_structural_errors():
    assert validate_contract_cases(CONTRACT_CASES) == []


def test_case_ids_are_unique_across_contract_sections():
    ids = [
        case.case_id
        for case in (
            *CONTRACT_CASES,
            *BOUNDARY_CASES,
            *STORAGE_CONTRACT_CASES,
            *LINEAGE_CONTRACT_CASES,
            *IMPLEMENTATION_MATRIX_CASES,
        )
    ]
    assert len(ids) == len(set(ids))


def test_observation_expectations_keep_approved_semantics_and_lineage():
    assert {field.name for field in fields(ObservationExpectation)} == {
        "condition_citation",
        "condition_state",
        "state_evidence_citation",
        "semantic_contract_version",
        "observation_id",
        "supersedes_observation_id",
    }
    assert {field.name for field in fields(CitationExpectation)} == {
        "source_part",
        "literal_text",
        "occurrence",
    }


def test_no_model_confidence_or_downstream_authority_enters_cases():
    forbidden = {
        "confidence",
        "rationale_output",
        "raw_output",
        "topic_key",
        "problem_id",
        "opportunity_id",
        "source_capability",
    }
    observation_fields = {field.name for field in fields(ObservationExpectation)}
    assert forbidden.isdisjoint(observation_fields)


def test_run_expectations_retain_attempted_input_contract_and_outcome():
    assert {field.name for field in fields(RunExpectation)} == {
        "run_id",
        "attempted_signal_id",
        "attempted_condition_citation",
        "producer_kind",
        "producer_name",
        "producer_revision",
        "attempted_semantic_contract_version",
        "attempted_at",
        "outcome",
        "resulting_observation_index",
        "produced_at",
    }


def test_run_expectations_keep_producer_contract_and_timing_distinct():
    produced = _CASES["OV1-STATE-RESOLVED-SHORT-SUPPORT"].expected_runs[0]
    failure = _CASES["OV1-OPERATIONAL-FAILURE"].expected_runs[0]
    optional_profile = _CASES["OV1-RETRY-PRODUCED-CONFIRMATION"].expected_runs[0]

    assert produced.producer_kind is ProducerKind.RULE
    assert produced.producer_name == "nic-7-reviewed-fixture"
    assert produced.producer_revision == "fixture-r1"
    assert produced.attempted_semantic_contract_version == SEMANTIC_CONTRACT_VERSION
    assert produced.producer_revision != produced.attempted_semantic_contract_version
    assert produced.attempted_at
    assert produced.produced_at
    assert failure.attempted_at
    assert failure.produced_at is None
    assert failure.producer_name is None
    assert failure.producer_revision is None
    assert optional_profile.producer_name is None
    assert optional_profile.producer_revision is None


def test_overlap_inclusive_occurrence_is_canonical():
    case = _CASES["OV1-CITATION-OVERLAP-ORDINAL"]
    target = case.attempted_targets[0]
    assert case.signal is not None
    assert resolve_citation(
        case.signal, CitationExpectation(SourcePart.TITLE, "aa", 1)
    ) == (0, 2)
    assert resolve_citation(case.signal, target) == (1, 3)
    assert resolve_citation(
        case.signal, CitationExpectation(SourcePart.TITLE, "aa", 3)
    ) == (2, 4)


def test_citation_matching_is_exact_case_preserving_and_source_part_scoped():
    case = _CASES["OV1-CITATION-SOURCE-PART"]
    assert case.signal is not None
    target = case.attempted_targets[0]
    assert resolve_citation(case.signal, target) == (
        0,
        len("Checkout status is unresolved"),
    )
    assert (
        resolve_citation(
            case.signal,
            CitationExpectation(SourcePart.CONTENT, "checkout status"),
        )
        is None
    )
    assert resolve_citation(
        case.signal,
        CitationExpectation(SourcePart.TITLE, "Checkout status"),
    ) == (0, len("Checkout status"))


def test_active_and_resolved_require_in_target_support():
    for case in CONTRACT_CASES:
        for observation in case.expected_observations or ():
            if observation.condition_state in {
                ConditionState.ACTIVE,
                ConditionState.RESOLVED,
            }:
                assert observation.state_evidence_citation is not None


def test_unknown_support_remains_optional():
    unknown = [
        observation
        for case in CONTRACT_CASES
        for observation in (case.expected_observations or ())
        if observation.condition_state is ConditionState.UNKNOWN
    ]
    assert unknown
    assert any(observation.state_evidence_citation is None for observation in unknown)
    assert any(
        observation.state_evidence_citation is not None for observation in unknown
    )


def test_one_signal_may_have_multiple_observations_from_separate_attempts():
    case = _CASES["OV1-MULTIPLE-TARGETS"]
    assert len(case.attempted_targets) == 2
    assert len(case.expected_observations or ()) == 2
    assert len(case.expected_runs or ()) == 2
    assert {
        observation.condition_state for observation in case.expected_observations or ()
    } == {ConditionState.ACTIVE, ConditionState.RESOLVED}


def test_runs_correspond_to_targets_and_results_without_forbidding_retries():
    case = _CASES["OV1-MULTIPLE-TARGETS"]
    assert case.expected_runs is not None
    assert case.expected_observations is not None

    duplicate_first = replace(
        case,
        expected_runs=(case.expected_runs[0], case.expected_runs[0]),
    )
    assert {
        "OV1-MULTIPLE-TARGETS: duplicate immutable run ID",
        "OV1-MULTIPLE-TARGETS: each supplied target requires at least one run",
        "OV1-MULTIPLE-TARGETS: retained Observation lacks a matching produced run",
    } <= set(validate_contract_cases((duplicate_first,)))

    citation_not_a_target = replace(
        case.expected_runs[0],
        attempted_condition_citation=CitationExpectation(
            SourcePart.CONTENT, "homepage loads fine now"
        ),
    )
    wrong_target = replace(
        case,
        expected_runs=(citation_not_a_target, case.expected_runs[1]),
    )
    assert "OV1-MULTIPLE-TARGETS: run citation was not attempted" in (
        validate_contract_cases((wrong_target,))
    )

    produced_for_other_target = replace(
        case.expected_runs[0],
        resulting_observation_index=1,
    )
    wrong_result = replace(
        case,
        expected_runs=(produced_for_other_target, case.expected_runs[1]),
    )
    assert {
        "OV1-MULTIPLE-TARGETS: produced run does not match attempt",
        "OV1-MULTIPLE-TARGETS: retained Observation lacks a matching produced run",
    } <= set(validate_contract_cases((wrong_result,)))


def test_retries_can_share_one_target_and_exact_result_observation():
    failure_then_produced = _CASES["OV1-RETRY-FAILURE-THEN-PRODUCED"]
    confirmation = _CASES["OV1-RETRY-PRODUCED-CONFIRMATION"]
    multiple_targets = _CASES["OV1-MULTIPLE-TARGETS-WITH-RETRY"]

    assert (
        validate_contract_cases((failure_then_produced, confirmation, multiple_targets))
        == []
    )
    assert [run.outcome for run in failure_then_produced.expected_runs or ()] == [
        RunOutcome.OPERATIONAL_FAILURE,
        RunOutcome.PRODUCED,
    ]
    assert {
        run.resulting_observation_index
        for run in confirmation.expected_runs or ()
        if run.outcome is RunOutcome.PRODUCED
    } == {0}
    assert {
        run.attempted_condition_citation for run in multiple_targets.expected_runs or ()
    } == set(multiple_targets.attempted_targets)


def test_exact_result_key_includes_supersession_lineage():
    case = _CASES["OV1-RETRY-PRODUCED-CONFIRMATION"]
    assert case.expected_observations is not None
    assert case.expected_runs is not None
    original = replace(
        case.expected_observations[0],
        observation_id="observation-a",
        supersedes_observation_id="predecessor-a",
    )
    duplicate = replace(original, observation_id="observation-b")
    duplicate_result = replace(
        case,
        expected_observations=(original, duplicate),
        expected_runs=(
            replace(case.expected_runs[0], resulting_observation_index=0),
            replace(case.expected_runs[1], resulting_observation_index=1),
        ),
    )
    assert (
        "OV1-RETRY-PRODUCED-CONFIRMATION: duplicate exact-result Observation expectation"
        in validate_contract_cases((duplicate_result,))
    )

    different_predecessor = replace(
        original,
        observation_id="observation-c",
        supersedes_observation_id="predecessor-b",
    )
    different_predecessor_result = replace(
        case,
        expected_observations=(original, different_predecessor),
        expected_runs=(
            replace(case.expected_runs[0], resulting_observation_index=0),
            replace(case.expected_runs[1], resulting_observation_index=1),
        ),
    )
    assert validate_contract_cases((different_predecessor_result,)) == []

    no_predecessor = replace(original, supersedes_observation_id=None)
    no_predecessor_result = replace(
        case,
        expected_observations=(no_predecessor, original),
        expected_runs=(
            replace(case.expected_runs[0], resulting_observation_index=0),
            replace(case.expected_runs[1], resulting_observation_index=1),
        ),
    )
    assert validate_contract_cases((no_predecessor_result,)) == []


def test_retry_reuse_and_other_lineage_invariants_remain_valid():
    reuse = _CASES["OV1-RETRY-PRODUCED-CONFIRMATION"]
    assert {
        run.resulting_observation_index
        for run in reuse.expected_runs or ()
        if run.outcome is RunOutcome.PRODUCED
    } == {0}

    distinct_targets = _CASES["OV1-MULTIPLE-TARGETS"]
    assert validate_contract_cases((distinct_targets,)) == []


def test_zero_target_and_operational_failure_are_distinct():
    no_target = _CASES["OV1-NO-SUPPLIED-TARGET"]
    assert no_target.attempted_targets == ()
    assert no_target.expected_observations == ()
    assert no_target.expected_runs == ()

    failure = _CASES["OV1-OPERATIONAL-FAILURE"]
    assert failure.expected_observations == ()
    assert failure.expected_runs is not None
    assert failure.expected_runs[0].outcome is RunOutcome.OPERATIONAL_FAILURE
    assert failure.expected_runs[0].resulting_observation_index is None
    assert failure.signal is not None
    assert failure.expected_runs[0].attempted_signal_id == failure.signal.signal_id
    assert (
        failure.expected_runs[0].attempted_semantic_contract_version
        == SEMANTIC_CONTRACT_VERSION
    )


def test_signal_absence_cannot_carry_observations_or_runs():
    case = _CASES["OV1-STATE-RESOLVED-SHORT-SUPPORT"]
    assert case.expected_observations is not None
    assert case.expected_runs is not None

    observation_without_signal = replace(case, signal=None, expected_runs=())
    assert "OV1-STATE-RESOLVED-SHORT-SUPPORT: Observation exists without Signal" in (
        validate_contract_cases((observation_without_signal,))
    )

    produced_run_without_signal = replace(
        case,
        signal=None,
        expected_observations=(),
    )
    assert "OV1-STATE-RESOLVED-SHORT-SUPPORT: run exists without Signal" in (
        validate_contract_cases((produced_run_without_signal,))
    )

    failure = _CASES["OV1-OPERATIONAL-FAILURE"]
    assert "OV1-OPERATIONAL-FAILURE: run exists without Signal" in (
        validate_contract_cases((replace(failure, signal=None),))
    )

    no_signal_non_result = ContractCase(
        "OV1-NO-SIGNAL-NON-RESULT",
        Classification.UNRESOLVED,
        None,
        (),
        None,
        None,
        "No immutable Signal exists, so this carries no asserted Observation or run.",
    )
    assert validate_contract_cases((no_signal_non_result,)) == []


def test_successful_abstention_remains_unresolved_not_unknown_or_failure():
    case = _CASES["OV1-SUCCESSFUL-NO-OBSERVATION"]
    assert case.classification is Classification.UNRESOLVED
    assert case.expected_observations is None
    assert case.expected_runs is None


def test_question_attribution_and_target_equivalence_remain_unresolved():
    ids = {
        "OV1-WH-QUESTION",
        "OV1-ATTRIBUTED-CLAIM",
        "OV1-ALTERNATE-TARGET-EQUIVALENCE",
    }
    for case_id in ids:
        case = _CASES[case_id]
        assert case.classification is Classification.UNRESOLVED
        assert case.deferred_owner
        assert case.expected_observations is None


def test_lexical_false_positive_controls_are_unknown():
    ids = {
        "OV1-LEXICAL-FIXED-RATE",
        "OV1-LEXICAL-DNS-RESOLVED",
        "OV1-LEXICAL-STILL-WITHIN-TARGET",
    }
    for case_id in ids:
        observations = _CASES[case_id].expected_observations
        assert observations is not None and len(observations) == 1
        assert observations[0].condition_state is ConditionState.UNKNOWN


def test_narrow_greenhouse_state_grants_no_capability_field():
    case = _CASES["OV1-SOURCE-AUTHORITY-BOUNDARY"]
    assert case.signal is not None and case.signal.source == "greenhouse_jobs"
    assert case.expected_observations is not None
    assert case.expected_observations[0].condition_state is ConditionState.ACTIVE
    assert "source_capability" not in {
        field.name for field in fields(ObservationExpectation)
    }


def test_boundary_categories_preserve_existing_ownership():
    expected: dict[str, tuple[Classification, str]] = {
        "OV1-BOUNDARY-C2": (Classification.LIMITATION, "Correlation"),
        "OV1-BOUNDARY-C4": (Classification.LIMITATION, "Correlation"),
        "OV1-BOUNDARY-CONFIDENCE": (Classification.LIMITATION, "Analysis"),
        "OV1-BOUNDARY-CONTESTED": (
            Classification.INEXPRESSIBLE,
            "Correlation/Analysis",
        ),
        "OV1-BOUNDARY-DEMAND-AUTHORITY": (
            Classification.INEXPRESSIBLE,
            "Evidence policy",
        ),
        "OV1-BOUNDARY-P3": (Classification.UNRESOLVED, "Problem identity"),
    }
    assert {
        case_id: (case.classification, case.owner)
        for case_id, case in _BOUNDARIES.items()
    } == expected


def test_boundary_case_shape_cannot_carry_observation_answers():
    assert {field.name for field in fields(BoundaryCase)} == {
        "case_id",
        "classification",
        "evidence_refs",
        "owner",
        "rationale",
    }


def test_storage_matrix_covers_nic6_direct_sql_requirements():
    required = {
        "STORAGE-OBS-NULL-ID",
        "STORAGE-RUN-NULL-ID",
        "STORAGE-OBS-REPEATED-NULL",
        "STORAGE-RUN-REPEATED-NULL",
        "STORAGE-OBS-UPDATE",
        "STORAGE-OBS-DELETE",
        "STORAGE-RUN-UPDATE",
        "STORAGE-RUN-DELETE",
        "STORAGE-OBS-SAME-ID-INSERT",
        "STORAGE-RUN-SAME-ID-INSERT",
        "STORAGE-OBS-INSERT-OR-REPLACE",
        "STORAGE-OBS-REPLACE-INTO",
        "STORAGE-RUN-INSERT-OR-REPLACE",
        "STORAGE-RUN-REPLACE-INTO",
        "STORAGE-OBS-FRESH-ID",
        "STORAGE-RUN-FRESH-ID",
        "STORAGE-SIGNAL-TEXT-UPDATE",
        "STORAGE-SIGNAL-REPLACE-OBS",
        "STORAGE-SIGNAL-REPLACE-FAILURE",
    }
    assert required <= _STORAGE.keys()
    for case_id in required:
        assert _STORAGE[case_id].enforcement is EnforcementLayer.SQLITE


def test_rejected_mutations_preserve_original_rows():
    replacement_ids = {
        "STORAGE-OBS-INSERT-OR-REPLACE",
        "STORAGE-OBS-REPLACE-INTO",
        "STORAGE-RUN-INSERT-OR-REPLACE",
        "STORAGE-RUN-REPLACE-INTO",
    }
    for case_id in replacement_ids:
        case = _STORAGE[case_id]
        assert case.expectation is StorageExpectation.REJECT
        assert case.preserves_original is True


def test_storage_matrix_covers_lineage_correspondence_and_atomicity():
    required_expectations = {
        "STORAGE-DUPLICATE-SUCCESSOR": StorageExpectation.REJECT,
        "STORAGE-MULTIPLE-ROOTS": StorageExpectation.ALLOW,
        "STORAGE-SELF-SUPERSESSION": StorageExpectation.REJECT,
        "STORAGE-CYCLE": StorageExpectation.REJECT,
        "STORAGE-PRODUCED-SIGNAL-MISMATCH": StorageExpectation.REJECT,
        "STORAGE-PRODUCED-PART-MISMATCH": StorageExpectation.REJECT,
        "STORAGE-PRODUCED-LITERAL-MISMATCH": StorageExpectation.REJECT,
        "STORAGE-PRODUCED-OCCURRENCE-MISMATCH": StorageExpectation.REJECT,
        "STORAGE-PRODUCED-CONTRACT-MISMATCH": StorageExpectation.REJECT,
        "STORAGE-PRODUCED-EXACT-MATCH": StorageExpectation.ALLOW,
        "STORAGE-FAILURE-NO-RESULT": StorageExpectation.ALLOW,
        "STORAGE-FAILURE-WITH-RESULT": StorageExpectation.REJECT,
        "STORAGE-PRODUCED-NO-RESULT": StorageExpectation.REJECT,
        "STORAGE-ATOMIC-ROLLBACK": StorageExpectation.ROLLBACK,
    }
    assert {
        case_id: _STORAGE[case_id].expectation for case_id in required_expectations
    } == required_expectations


def test_correction_lineage_allows_cross_target_and_cross_signal_successors():
    cross_target = _LINEAGE["LINEAGE-CROSS-TARGET"]
    assert cross_target.expectation is StorageExpectation.ALLOW
    assert cross_target.predecessor_signal_id == cross_target.successor_signal_id
    assert cross_target.predecessor_target != cross_target.successor_target

    cross_signal = _LINEAGE["LINEAGE-CROSS-SIGNAL"]
    assert cross_signal.expectation is StorageExpectation.ALLOW
    assert cross_signal.predecessor_signal_id != cross_signal.successor_signal_id


def test_implementation_neutral_matrix_completes_nic6_scope():
    expected = {
        "MATRIX-IDENTITY-CANONICAL-SIGNAL": MatrixExpectation.ALLOW,
        "MATRIX-IDENTITY-TEMPORARY-SIGNAL": MatrixExpectation.REJECT,
        "MATRIX-ISOLATION-FAILURE-CONTINUES": MatrixExpectation.ALLOW,
        "MATRIX-ISOLATION-SIBLING-EXTRACTION": MatrixExpectation.ALLOW,
        "MATRIX-RERUN-EXACT-REUSE": MatrixExpectation.ALLOW,
        "MATRIX-RETRY-AFTER-OPERATIONAL-FAILURE": MatrixExpectation.ALLOW,
        "MATRIX-RETRY-SUCCESSFUL-SAME-TARGET": MatrixExpectation.ALLOW,
        "MATRIX-RETRY-NO-TARGET-EQUIVALENCE": MatrixExpectation.REJECT,
        "MATRIX-RERUN-CORRECTION-LINEAGE": MatrixExpectation.ALLOW,
        "MATRIX-RERUN-NO-NEWEST-WINS": MatrixExpectation.REJECT,
        "MATRIX-RAW-SIGNAL-ENTITY-EXTRACTION": MatrixExpectation.ALLOW,
        "MATRIX-RAW-SIGNAL-RELATIONSHIP-EXTRACTION": MatrixExpectation.ALLOW,
        "MATRIX-RAW-SIGNAL-DETECTOR-CORRELATION": MatrixExpectation.ALLOW,
        "MATRIX-RAW-SIGNAL-UNRELATED-CONTINUES": MatrixExpectation.ALLOW,
        "MATRIX-TARGET-BOUNDARIES-NON-EQUIVALENT": MatrixExpectation.ALLOW,
        "MATRIX-MIGRATION-NO-AUTOMATIC-BACKFILL": (MatrixExpectation.NON_PRODUCING),
        "MATRIX-MIGRATION-DRY-RUN-NONPRODUCING": (MatrixExpectation.NON_PRODUCING),
        "MATRIX-MIGRATION-FAILED-ROLLBACK": MatrixExpectation.ROLLBACK_PRESERVES,
        "MATRIX-MIGRATION-HISTORICAL-REPLAY": MatrixExpectation.ALLOW,
        "MATRIX-FRESH-INIT-SCHEMA-CONTRACT": (
            MatrixExpectation.ESTABLISHES_SCHEMA_CONTRACT
        ),
        "MATRIX-FRESH-INIT-NONPRODUCING": MatrixExpectation.NON_PRODUCING,
        "MATRIX-UPGRADE-SCHEMA-CONTRACT": (
            MatrixExpectation.ESTABLISHES_SCHEMA_CONTRACT
        ),
        "MATRIX-UPGRADE-PRESERVES-INTELLIGENCE": (
            MatrixExpectation.PRESERVES_EXISTING_STATE
        ),
        "MATRIX-UPGRADE-FAILURE-ROLLBACK": MatrixExpectation.ROLLBACK_PRESERVES,
        "MATRIX-NONCONSUMPTION-CORRELATION": MatrixExpectation.REJECT,
        "MATRIX-NONCONSUMPTION-PATTERN-DETECTOR": MatrixExpectation.REJECT,
        "MATRIX-NONCONSUMPTION-WATCH-LIST": MatrixExpectation.REJECT,
        "MATRIX-NONCONSUMPTION-PROBLEM": MatrixExpectation.REJECT,
        "MATRIX-NONCONSUMPTION-OPPORTUNITY": MatrixExpectation.REJECT,
        "MATRIX-NONCONSUMPTION-SCORING": MatrixExpectation.REJECT,
        "MATRIX-NONCONSUMPTION-CONFIDENCE": MatrixExpectation.REJECT,
        "MATRIX-NONCONSUMPTION-FINDINGS": MatrixExpectation.REJECT,
        "MATRIX-NONCONSUMPTION-REPORTS": MatrixExpectation.REJECT,
        "MATRIX-NONCONSUMPTION-API": MatrixExpectation.REJECT,
    }
    assert {case_id: _MATRIX[case_id].expectation for case_id in expected} == expected


def test_frozen_semantic_baseline_remains_unchanged():
    assert len(BASELINE_CORPUS) == 12
    assert {case.id for case in BASELINE_CORPUS} == {
        "C1",
        "C2",
        "C3",
        "C4",
        "P1",
        "P2",
        "P3",
        "N1_N2",
        "S1",
        "S2",
        "S3",
        "CONFIDENCE_PAIR",
    }
    assert PRESERVE_CASE_IDS == frozenset({"C1", "C3", "P1", "P2", "S3"})


def test_frozen_nic17_corpus_remains_unchanged():
    assert len(NIC_17_CASES) == 44
    assert sum(case.scored for case in NIC_17_CASES) == 41
    assert {case.case_id for case in NIC_17_CASES if not case.scored} == {
        "CS-CORE-007",
        "CS-CORE-008",
        "CS-ADV-004",
    }
