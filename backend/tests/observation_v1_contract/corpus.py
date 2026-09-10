"""Production Observation V1 contract cases approved by NIC-5 and NIC-6.

This is a test-first specification, not an interpreter or persistence layer.
Cases classified PRESERVE carry the exact result a future implementation must
produce for a supplied target. LIMITATION, INEXPRESSIBLE, and UNRESOLVED cases
retain the existing semantic-evaluation meanings and are never scored as
Observation failures.

The frozen Semantic Evaluation Baseline V1 and NIC-17 corpus are imported only
for stable references. Neither corpus is copied or modified here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from tests.condition_state_eval.dataset import CASES as NIC_17_CASES

SEMANTIC_CONTRACT_VERSION = "condition-state/v1"


class Classification(str, Enum):
    PRESERVE = "preserve"
    LIMITATION = "limitation"
    INEXPRESSIBLE = "inexpressible"
    UNRESOLVED = "unresolved"


class SourcePart(str, Enum):
    TITLE = "title"
    CONTENT = "content"


class ConditionState(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    UNKNOWN = "unknown"


class RunOutcome(str, Enum):
    PRODUCED = "produced"
    OPERATIONAL_FAILURE = "operational_failure"


class ProducerKind(str, Enum):
    HUMAN = "human"
    RULE = "rule"
    MODEL = "model"


@dataclass(frozen=True)
class SignalFixture:
    signal_id: str
    title: str
    content: str = ""
    source: str = "test_fixture"

    def source_text(self, part: SourcePart) -> str:
        return self.title if part is SourcePart.TITLE else self.content


@dataclass(frozen=True)
class CitationExpectation:
    source_part: SourcePart
    literal_text: str
    occurrence: int = 1


@dataclass(frozen=True)
class ObservationExpectation:
    condition_citation: CitationExpectation
    condition_state: ConditionState
    state_evidence_citation: CitationExpectation | None
    semantic_contract_version: str = SEMANTIC_CONTRACT_VERSION


@dataclass(frozen=True)
class RunExpectation:
    attempted_signal_id: str
    attempted_condition_citation: CitationExpectation
    producer_kind: ProducerKind
    producer_name: str
    producer_revision: str
    attempted_semantic_contract_version: str
    attempted_at: str
    outcome: RunOutcome
    resulting_observation_index: int | None
    produced_at: str | None


@dataclass(frozen=True)
class ContractCase:
    case_id: str
    classification: Classification
    signal: SignalFixture | None
    attempted_targets: tuple[CitationExpectation, ...]
    expected_observations: tuple[ObservationExpectation, ...] | None
    expected_runs: tuple[RunExpectation, ...] | None
    rationale: str
    evidence_refs: tuple[str, ...] = ()
    deferred_owner: str | None = None


@dataclass(frozen=True)
class BoundaryCase:
    case_id: str
    classification: Classification
    evidence_refs: tuple[str, ...]
    owner: str
    rationale: str


class EnforcementLayer(str, Enum):
    SQLITE = "sqlite"
    APPLICATION = "application"
    TRANSACTION = "transaction"


class StorageExpectation(str, Enum):
    ALLOW = "allow"
    REJECT = "reject"
    ROLLBACK = "rollback"


class MatrixExpectation(str, Enum):
    ALLOW = "allow"
    REJECT = "reject"
    NON_PRODUCING = "non_producing"


@dataclass(frozen=True)
class StorageContractCase:
    case_id: str
    operation: str
    expectation: StorageExpectation
    enforcement: EnforcementLayer
    preserves_original: bool = False


@dataclass(frozen=True)
class LineageContractCase:
    case_id: str
    predecessor_signal_id: str
    predecessor_target: CitationExpectation
    successor_signal_id: str
    successor_target: CitationExpectation
    expectation: StorageExpectation


@dataclass(frozen=True)
class ImplementationMatrixCase:
    case_id: str
    section: str
    expectation: MatrixExpectation
    rationale: str


_NIC_17 = {case.case_id: case for case in NIC_17_CASES}

_FIXTURE_PRODUCER_KIND = ProducerKind.RULE
_FIXTURE_PRODUCER_NAME = "nic-7-reviewed-fixture"
_FIXTURE_PRODUCER_REVISION = "fixture-r1"
_FIXTURE_ATTEMPTED_AT = "2026-09-10T00:00:00Z"
_FIXTURE_PRODUCED_AT = "2026-09-10T00:00:01Z"


def _nic17_signal(case_id: str) -> SignalFixture:
    case = _NIC_17[case_id]
    return SignalFixture(
        signal_id=f"signal-{case_id.lower()}",
        title=f"NIC-17 reference {case_id}",
        content=case.source_text,
    )


def _produced(
    attempted_signal_id: str,
    target: CitationExpectation,
    observation_index: int,
) -> RunExpectation:
    return RunExpectation(
        attempted_signal_id=attempted_signal_id,
        attempted_condition_citation=target,
        producer_kind=_FIXTURE_PRODUCER_KIND,
        producer_name=_FIXTURE_PRODUCER_NAME,
        producer_revision=_FIXTURE_PRODUCER_REVISION,
        attempted_semantic_contract_version=SEMANTIC_CONTRACT_VERSION,
        attempted_at=_FIXTURE_ATTEMPTED_AT,
        outcome=RunOutcome.PRODUCED,
        resulting_observation_index=observation_index,
        produced_at=_FIXTURE_PRODUCED_AT,
    )


def _observation(
    target: CitationExpectation,
    state: ConditionState,
    support: CitationExpectation | None,
) -> ObservationExpectation:
    return ObservationExpectation(target, state, support)


_CS003_TARGET = CitationExpectation(
    SourcePart.CONTENT,
    _NIC_17["CS-CORE-003"].target_span,
)
_CS003_SUPPORT = CitationExpectation(SourcePart.CONTENT, "that's long behind us now")

_CS004_TARGET = CitationExpectation(
    SourcePart.CONTENT,
    _NIC_17["CS-CORE-004"].target_span,
)

_CS013A_TARGET = CitationExpectation(
    SourcePart.CONTENT,
    _NIC_17["CS-CORE-013a"].target_span,
)
_CS013B_TARGET = CitationExpectation(
    SourcePart.CONTENT,
    _NIC_17["CS-CORE-013b"].target_span,
)

_CS017_TARGET = CitationExpectation(
    SourcePart.CONTENT,
    _NIC_17["CS-CORE-017"].target_span,
)

_CS005_TARGET = CitationExpectation(
    SourcePart.CONTENT,
    _NIC_17["CS-CORE-005"].target_span,
)

_CS028_TARGET = CitationExpectation(
    SourcePart.CONTENT,
    _NIC_17["CS-CORE-028"].target_span,
)


CONTRACT_CASES: tuple[ContractCase, ...] = (
    ContractCase(
        "OV1-STATE-RESOLVED-SHORT-SUPPORT",
        Classification.PRESERVE,
        _nic17_signal("CS-CORE-003"),
        (_CS003_TARGET,),
        (_observation(_CS003_TARGET, ConditionState.RESOLVED, _CS003_SUPPORT),),
        (_produced("signal-cs-core-003", _CS003_TARGET, 0),),
        "A state-support citation may be shorter than its condition target.",
        ("CS-CORE-003", "NIC-5 Part 9"),
    ),
    ContractCase(
        "OV1-STATE-HISTORICAL-UNKNOWN",
        Classification.PRESERVE,
        _nic17_signal("CS-CORE-004"),
        (_CS004_TARGET,),
        (_observation(_CS004_TARGET, ConditionState.UNKNOWN, None),),
        (_produced("signal-cs-core-004", _CS004_TARGET, 0),),
        "Past activity alone does not establish current state; no normalized time is added.",
        ("CS-CORE-004", "NIC-5 Part 9"),
    ),
    ContractCase(
        "OV1-MULTIPLE-TARGETS",
        Classification.PRESERVE,
        _nic17_signal("CS-CORE-013a"),
        (_CS013A_TARGET, _CS013B_TARGET),
        (
            _observation(_CS013A_TARGET, ConditionState.RESOLVED, _CS013A_TARGET),
            _observation(_CS013B_TARGET, ConditionState.ACTIVE, _CS013B_TARGET),
        ),
        (
            _produced("signal-cs-core-013a", _CS013A_TARGET, 0),
            _produced("signal-cs-core-013a", _CS013B_TARGET, 1),
        ),
        "One Signal can retain distinct Observation records from separate target attempts.",
        ("CS-CORE-013a", "CS-CORE-013b", "NIC-5 invariant 3"),
    ),
    ContractCase(
        "OV1-UNKNOWN-OPTIONAL-SUPPORT",
        Classification.PRESERVE,
        _nic17_signal("CS-CORE-017"),
        (_CS017_TARGET,),
        (_observation(_CS017_TARGET, ConditionState.UNKNOWN, None),),
        (_produced("signal-cs-core-017", _CS017_TARGET, 0),),
        "A reviewed yes/no question may retain unknown without a support citation.",
        ("CS-CORE-017", "NIC-5 Part 7"),
    ),
    ContractCase(
        "OV1-UNKNOWN-RETAINED-SUPPORT",
        Classification.PRESERVE,
        SignalFixture("signal-unknown-support", "Checkout status remains unclear."),
        (CitationExpectation(SourcePart.TITLE, "Checkout status remains unclear"),),
        (
            _observation(
                CitationExpectation(
                    SourcePart.TITLE, "Checkout status remains unclear"
                ),
                ConditionState.UNKNOWN,
                CitationExpectation(SourcePart.TITLE, "remains unclear"),
            ),
        ),
        (
            _produced(
                "signal-unknown-support",
                CitationExpectation(
                    SourcePart.TITLE, "Checkout status remains unclear"
                ),
                0,
            ),
        ),
        "Unknown may retain literal support even though that support is optional.",
        ("NIC-5 producer rule",),
    ),
    ContractCase(
        "OV1-RECURRING-CURRENT-ACTIVE",
        Classification.PRESERVE,
        _nic17_signal("CS-CORE-005"),
        (_CS005_TARGET,),
        (_observation(_CS005_TARGET, ConditionState.ACTIVE, _CS005_TARGET),),
        (_produced("signal-cs-core-005", _CS005_TARGET, 0),),
        "Current active language is retained without inventing recurrence fields.",
        ("CS-CORE-005", "NIC-5 Part 9"),
    ),
    ContractCase(
        "OV1-CITATION-OVERLAP-ORDINAL",
        Classification.PRESERVE,
        SignalFixture("signal-overlap", "aaaa"),
        (CitationExpectation(SourcePart.TITLE, "aa", 2),),
        (
            _observation(
                CitationExpectation(SourcePart.TITLE, "aa", 2),
                ConditionState.UNKNOWN,
                None,
            ),
        ),
        (
            _produced(
                "signal-overlap",
                CitationExpectation(SourcePart.TITLE, "aa", 2),
                0,
            ),
        ),
        "Occurrence ordinals include overlapping exact matches at start positions 0, 1, and 2.",
        ("NIC-5 citation occurrence resolution",),
    ),
    ContractCase(
        "OV1-CITATION-SOURCE-PART",
        Classification.PRESERVE,
        SignalFixture(
            "signal-source-part",
            "Checkout status",
            "Checkout status is unresolved.",
        ),
        (CitationExpectation(SourcePart.CONTENT, "Checkout status is unresolved"),),
        (
            _observation(
                CitationExpectation(
                    SourcePart.CONTENT, "Checkout status is unresolved"
                ),
                ConditionState.ACTIVE,
                CitationExpectation(SourcePart.CONTENT, "is unresolved"),
            ),
        ),
        (
            _produced(
                "signal-source-part",
                CitationExpectation(
                    SourcePart.CONTENT, "Checkout status is unresolved"
                ),
                0,
            ),
        ),
        "The same text in title and content remains distinct citation provenance.",
        ("NIC-5 Part 3",),
    ),
    ContractCase(
        "OV1-CITATION-CASE-PRESERVING",
        Classification.PRESERVE,
        SignalFixture("signal-case", "Issue: the issue remains unresolved."),
        (CitationExpectation(SourcePart.TITLE, "issue remains unresolved"),),
        (
            _observation(
                CitationExpectation(SourcePart.TITLE, "issue remains unresolved"),
                ConditionState.ACTIVE,
                CitationExpectation(SourcePart.TITLE, "remains unresolved"),
            ),
        ),
        (
            _produced(
                "signal-case",
                CitationExpectation(SourcePart.TITLE, "issue remains unresolved"),
                0,
            ),
        ),
        "Citation matching is exact and case-preserving rather than normalized.",
        ("NIC-5 citation literal invariant",),
    ),
    ContractCase(
        "OV1-LEXICAL-FIXED-RATE",
        Classification.PRESERVE,
        SignalFixture(
            "signal-fixed-rate", "We renewed a fixed-rate maintenance contract."
        ),
        (
            CitationExpectation(
                SourcePart.TITLE, "We renewed a fixed-rate maintenance contract."
            ),
        ),
        (
            _observation(
                CitationExpectation(
                    SourcePart.TITLE,
                    "We renewed a fixed-rate maintenance contract.",
                ),
                ConditionState.UNKNOWN,
                None,
            ),
        ),
        (
            _produced(
                "signal-fixed-rate",
                CitationExpectation(
                    SourcePart.TITLE,
                    "We renewed a fixed-rate maintenance contract.",
                ),
                0,
            ),
        ),
        "The lexical cue 'fixed' does not establish resolution of a condition.",
        ("CS-CORE-027",),
    ),
    ContractCase(
        "OV1-LEXICAL-DNS-RESOLVED",
        Classification.PRESERVE,
        SignalFixture("signal-dns", "The hostname resolved to a backup address."),
        (
            CitationExpectation(
                SourcePart.TITLE, "The hostname resolved to a backup address."
            ),
        ),
        (
            _observation(
                CitationExpectation(
                    SourcePart.TITLE,
                    "The hostname resolved to a backup address.",
                ),
                ConditionState.UNKNOWN,
                None,
            ),
        ),
        (
            _produced(
                "signal-dns",
                CitationExpectation(
                    SourcePart.TITLE,
                    "The hostname resolved to a backup address.",
                ),
                0,
            ),
        ),
        "Technical name resolution is not condition resolution.",
        ("CS-ADV-008",),
    ),
    ContractCase(
        "OV1-LEXICAL-STILL-WITHIN-TARGET",
        Classification.PRESERVE,
        _nic17_signal("CS-CORE-028"),
        (_CS028_TARGET,),
        (_observation(_CS028_TARGET, ConditionState.UNKNOWN, None),),
        (_produced("signal-cs-core-028", _CS028_TARGET, 0),),
        "'Still' attached to a healthy metric does not establish an active problem.",
        ("CS-CORE-028",),
    ),
    ContractCase(
        "OV1-SOURCE-AUTHORITY-BOUNDARY",
        Classification.PRESERVE,
        SignalFixture(
            "signal-greenhouse",
            "Platform Engineer",
            "The Platform Engineer position remains open.",
            source="greenhouse_jobs",
        ),
        (
            CitationExpectation(
                SourcePart.CONTENT, "Platform Engineer position remains open"
            ),
        ),
        (
            _observation(
                CitationExpectation(
                    SourcePart.CONTENT,
                    "Platform Engineer position remains open",
                ),
                ConditionState.ACTIVE,
                CitationExpectation(SourcePart.CONTENT, "remains open"),
            ),
        ),
        (
            _produced(
                "signal-greenhouse",
                CitationExpectation(
                    SourcePart.CONTENT,
                    "Platform Engineer position remains open",
                ),
                0,
            ),
        ),
        "A narrow job-opening state grants no customer-demand or Opportunity authority.",
        ("NIC-5 invariant 10", "NIC-31 containment"),
    ),
    ContractCase(
        "OV1-NO-SUPPLIED-TARGET",
        Classification.PRESERVE,
        SignalFixture("signal-no-target", "A source item with no supplied target."),
        (),
        (),
        (),
        "No supplied target creates neither Observation nor run; segmentation is deferred.",
        ("NIC-6 zero-result boundary",),
    ),
    ContractCase(
        "OV1-OPERATIONAL-FAILURE",
        Classification.PRESERVE,
        SignalFixture("signal-failure", "Checkout remains unavailable."),
        (CitationExpectation(SourcePart.TITLE, "Checkout remains unavailable"),),
        (),
        (
            RunExpectation(
                "signal-failure",
                CitationExpectation(SourcePart.TITLE, "Checkout remains unavailable"),
                _FIXTURE_PRODUCER_KIND,
                _FIXTURE_PRODUCER_NAME,
                _FIXTURE_PRODUCER_REVISION,
                SEMANTIC_CONTRACT_VERSION,
                _FIXTURE_ATTEMPTED_AT,
                RunOutcome.OPERATIONAL_FAILURE,
                None,
                None,
            ),
        ),
        "Operational failure retains attempted provenance and creates no semantic Observation.",
        ("NIC-5 run outcome invariant", "NIC-6 zero-result boundary"),
    ),
    ContractCase(
        "OV1-WH-QUESTION",
        Classification.UNRESOLVED,
        _nic17_signal("CS-ADV-004"),
        (
            CitationExpectation(
                SourcePart.CONTENT,
                _NIC_17["CS-ADV-004"].target_span,
            ),
        ),
        None,
        None,
        "WH-question presupposition and successful no-record behavior remain undecided.",
        ("CS-ADV-004", "NIC-5 deferred ledger"),
        "Processing/evaluation",
    ),
    ContractCase(
        "OV1-ATTRIBUTED-CLAIM",
        Classification.UNRESOLVED,
        _nic17_signal("CS-CORE-007"),
        (
            CitationExpectation(
                SourcePart.CONTENT,
                _NIC_17["CS-CORE-007"].target_span,
            ),
        ),
        None,
        None,
        "The contract does not settle how attributed claims determine Condition State.",
        ("CS-CORE-007", "NIC-5 deferred ledger"),
        "Processing/evidence policy",
    ),
    ContractCase(
        "OV1-SUCCESSFUL-NO-OBSERVATION",
        Classification.UNRESOLVED,
        SignalFixture("signal-abstention", "Checkout behavior is unclear."),
        (CitationExpectation(SourcePart.TITLE, "Checkout behavior is unclear"),),
        None,
        None,
        "Successful abstention/no-record is not unknown or operational failure and is deferred.",
        ("NIC-5 null abstention ledger", "NIC-6 zero-result boundary"),
        "Interpreter/evaluation design",
    ),
    ContractCase(
        "OV1-ALTERNATE-TARGET-EQUIVALENCE",
        Classification.UNRESOLVED,
        SignalFixture(
            "signal-target-equivalence",
            "The checkout flow is still failing for returning customers.",
        ),
        (
            CitationExpectation(SourcePart.TITLE, "checkout flow is still failing"),
            CitationExpectation(
                SourcePart.TITLE,
                "checkout flow is still failing for returning customers",
            ),
        ),
        None,
        None,
        "Both targets are auditable; V1 does not decide their semantic equivalence.",
        ("NIC-5 Part 4",),
        "Later Processing/Correlation design",
    ),
)


BOUNDARY_CASES: tuple[BoundaryCase, ...] = (
    BoundaryCase(
        "OV1-BOUNDARY-C2",
        Classification.LIMITATION,
        ("C2",),
        "Correlation",
        "Paraphrase clustering remains a Correlation limitation, not Observation meaning.",
    ),
    BoundaryCase(
        "OV1-BOUNDARY-C4",
        Classification.LIMITATION,
        ("C4",),
        "Correlation",
        "Homonym separation remains a Correlation limitation.",
    ),
    BoundaryCase(
        "OV1-BOUNDARY-CONFIDENCE",
        Classification.LIMITATION,
        ("CONFIDENCE_PAIR",),
        "Analysis",
        "Observation may supply bounded states but cannot compute BIA confidence.",
    ),
    BoundaryCase(
        "OV1-BOUNDARY-CONTESTED",
        Classification.INEXPRESSIBLE,
        ("CONTESTED_VERDICT_NOTE",),
        "Correlation/Analysis",
        "V1 has no cross-source contested/supported verdict.",
    ),
    BoundaryCase(
        "OV1-BOUNDARY-DEMAND-AUTHORITY",
        Classification.INEXPRESSIBLE,
        ("NIC-5 invariant 10",),
        "Evidence policy",
        "A Condition State cannot assert that a source proves customer demand.",
    ),
    BoundaryCase(
        "OV1-BOUNDARY-P3",
        Classification.UNRESOLVED,
        ("P3",),
        "Problem identity",
        "Actor/context participation in canonical Problem identity remains unresolved.",
    ),
)


STORAGE_CONTRACT_CASES: tuple[StorageContractCase, ...] = (
    StorageContractCase(
        "STORAGE-OBS-NULL-ID",
        "insert NULL observation_id",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-RUN-NULL-ID",
        "insert NULL run_id",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-OBS-REPEATED-NULL",
        "repeat NULL observation_id",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-RUN-REPEATED-NULL",
        "repeat NULL run_id",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-OBS-UPDATE",
        "update Observation",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
        True,
    ),
    StorageContractCase(
        "STORAGE-OBS-DELETE",
        "delete Observation",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
        True,
    ),
    StorageContractCase(
        "STORAGE-RUN-UPDATE",
        "update run",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
        True,
    ),
    StorageContractCase(
        "STORAGE-RUN-DELETE",
        "delete run",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
        True,
    ),
    StorageContractCase(
        "STORAGE-OBS-SAME-ID-INSERT",
        "same-key Observation INSERT",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
        True,
    ),
    StorageContractCase(
        "STORAGE-RUN-SAME-ID-INSERT",
        "same-key run INSERT",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
        True,
    ),
    StorageContractCase(
        "STORAGE-OBS-INSERT-OR-REPLACE",
        "Observation INSERT OR REPLACE",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
        True,
    ),
    StorageContractCase(
        "STORAGE-OBS-REPLACE-INTO",
        "Observation REPLACE INTO",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
        True,
    ),
    StorageContractCase(
        "STORAGE-RUN-INSERT-OR-REPLACE",
        "run INSERT OR REPLACE",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
        True,
    ),
    StorageContractCase(
        "STORAGE-RUN-REPLACE-INTO",
        "run REPLACE INTO",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
        True,
    ),
    StorageContractCase(
        "STORAGE-OBS-FRESH-ID",
        "fresh Observation INSERT",
        StorageExpectation.ALLOW,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-RUN-FRESH-ID",
        "fresh run INSERT",
        StorageExpectation.ALLOW,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-SIGNAL-TEXT-UPDATE",
        "update cited Signal title/content",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
        True,
    ),
    StorageContractCase(
        "STORAGE-SIGNAL-REPLACE-OBS",
        "replace Signal referenced by Observation",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
        True,
    ),
    StorageContractCase(
        "STORAGE-SIGNAL-REPLACE-FAILURE",
        "replace Signal referenced by failure run",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
        True,
    ),
    StorageContractCase(
        "STORAGE-DUPLICATE-SUCCESSOR",
        "insert second direct successor",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-MULTIPLE-ROOTS",
        "insert multiple NULL supersession roots",
        StorageExpectation.ALLOW,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-SELF-SUPERSESSION",
        "self supersession",
        StorageExpectation.REJECT,
        EnforcementLayer.APPLICATION,
    ),
    StorageContractCase(
        "STORAGE-CYCLE",
        "supersession cycle",
        StorageExpectation.REJECT,
        EnforcementLayer.APPLICATION,
    ),
    StorageContractCase(
        "STORAGE-PRODUCED-SIGNAL-MISMATCH",
        "produced run mismatched attempted Signal",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-PRODUCED-PART-MISMATCH",
        "produced run mismatched source_part",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-PRODUCED-LITERAL-MISMATCH",
        "produced run mismatched literal_text",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-PRODUCED-OCCURRENCE-MISMATCH",
        "produced run mismatched occurrence",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-PRODUCED-CONTRACT-MISMATCH",
        "produced run mismatched semantic contract",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-PRODUCED-EXACT-MATCH",
        "produced run exact correspondence",
        StorageExpectation.ALLOW,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-FAILURE-NO-RESULT",
        "failure run with NULL result",
        StorageExpectation.ALLOW,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-FAILURE-WITH-RESULT",
        "failure run with result",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-PRODUCED-NO-RESULT",
        "produced run without result",
        StorageExpectation.REJECT,
        EnforcementLayer.SQLITE,
    ),
    StorageContractCase(
        "STORAGE-ATOMIC-ROLLBACK",
        "new Observation then invalid initial run",
        StorageExpectation.ROLLBACK,
        EnforcementLayer.TRANSACTION,
    ),
)


LINEAGE_CONTRACT_CASES: tuple[LineageContractCase, ...] = (
    LineageContractCase(
        "LINEAGE-CROSS-TARGET",
        "signal-lineage-shared",
        CitationExpectation(SourcePart.TITLE, "checkout flow is failing"),
        "signal-lineage-shared",
        CitationExpectation(
            SourcePart.TITLE,
            "checkout flow is failing for returning customers",
        ),
        StorageExpectation.ALLOW,
    ),
    LineageContractCase(
        "LINEAGE-CROSS-SIGNAL",
        "signal-lineage-predecessor",
        CitationExpectation(SourcePart.CONTENT, "the export remains unavailable"),
        "signal-lineage-successor",
        CitationExpectation(SourcePart.CONTENT, "the export is available again"),
        StorageExpectation.ALLOW,
    ),
)


IMPLEMENTATION_MATRIX_CASES: tuple[ImplementationMatrixCase, ...] = (
    ImplementationMatrixCase(
        "MATRIX-IDENTITY-CANONICAL-SIGNAL",
        "identity",
        MatrixExpectation.ALLOW,
        "Observation uses the canonical persisted Signal identity after collector deduplication.",
    ),
    ImplementationMatrixCase(
        "MATRIX-IDENTITY-TEMPORARY-SIGNAL",
        "identity",
        MatrixExpectation.REJECT,
        "A collector-temporary or in-memory Signal ID is not citation provenance.",
    ),
    ImplementationMatrixCase(
        "MATRIX-ISOLATION-FAILURE-CONTINUES",
        "isolation",
        MatrixExpectation.ALLOW,
        "One target operational failure does not suppress a later target attempt on the same Signal.",
    ),
    ImplementationMatrixCase(
        "MATRIX-ISOLATION-SIBLING-EXTRACTION",
        "isolation",
        MatrixExpectation.ALLOW,
        "Observation interpretation and Entity/Relationship Extraction remain independent siblings.",
    ),
    ImplementationMatrixCase(
        "MATRIX-RERUN-EXACT-REUSE",
        "rerun",
        MatrixExpectation.ALLOW,
        "Exact-result reuse creates a new run referencing the existing Observation without duplicate content.",
    ),
    ImplementationMatrixCase(
        "MATRIX-RERUN-CORRECTION-LINEAGE",
        "rerun",
        MatrixExpectation.ALLOW,
        "A correction creates an append-only successor rather than rewriting history.",
    ),
    ImplementationMatrixCase(
        "MATRIX-RERUN-NO-NEWEST-WINS",
        "rerun",
        MatrixExpectation.REJECT,
        "Interpreter selection cannot silently choose the newest producer.",
    ),
    ImplementationMatrixCase(
        "MATRIX-MIGRATION-NO-AUTOMATIC-BACKFILL",
        "migration",
        MatrixExpectation.NON_PRODUCING,
        "A migration alone does not create semantic Observations for historic Signals.",
    ),
    ImplementationMatrixCase(
        "MATRIX-MIGRATION-DRY-RUN-NONPRODUCING",
        "migration",
        MatrixExpectation.NON_PRODUCING,
        "Dry runs and migration checks retain no Observation or run without approved invocation.",
    ),
    ImplementationMatrixCase(
        "MATRIX-MIGRATION-HISTORICAL-REPLAY",
        "migration",
        MatrixExpectation.ALLOW,
        "Historical Signals remain replayable from their immutable evidence.",
    ),
    ImplementationMatrixCase(
        "MATRIX-NONCONSUMPTION-CORRELATION",
        "non_consumption",
        MatrixExpectation.REJECT,
        "Observation has no Correlation authority before NIC-9 validation.",
    ),
    ImplementationMatrixCase(
        "MATRIX-NONCONSUMPTION-PROBLEM",
        "non_consumption",
        MatrixExpectation.REJECT,
        "Observation has no Problem-matching authority before NIC-9 validation.",
    ),
    ImplementationMatrixCase(
        "MATRIX-NONCONSUMPTION-SCORING",
        "non_consumption",
        MatrixExpectation.REJECT,
        "Observation has no scoring authority before NIC-9 validation.",
    ),
    ImplementationMatrixCase(
        "MATRIX-NONCONSUMPTION-CONFIDENCE",
        "non_consumption",
        MatrixExpectation.REJECT,
        "Observation has no BIA-confidence authority before NIC-9 validation.",
    ),
    ImplementationMatrixCase(
        "MATRIX-NONCONSUMPTION-FINDINGS",
        "non_consumption",
        MatrixExpectation.REJECT,
        "Observation has no Findings authority before NIC-9 validation.",
    ),
    ImplementationMatrixCase(
        "MATRIX-NONCONSUMPTION-REPORTS",
        "non_consumption",
        MatrixExpectation.REJECT,
        "Observation has no report authority before NIC-9 validation.",
    ),
)


def resolve_citation(
    signal: SignalFixture,
    citation: CitationExpectation,
) -> tuple[int, int] | None:
    """Resolve the V1 overlap-inclusive occurrence against one source part."""
    if not citation.literal_text or citation.occurrence < 1:
        return None
    source_text = signal.source_text(citation.source_part)
    starts = [
        index
        for index in range(len(source_text) - len(citation.literal_text) + 1)
        if source_text.startswith(citation.literal_text, index)
    ]
    if citation.occurrence > len(starts):
        return None
    start = starts[citation.occurrence - 1]
    return start, start + len(citation.literal_text)


def validate_contract_cases(cases: tuple[ContractCase, ...]) -> list[str]:
    """Return structural errors without calling production code."""
    errors: list[str] = []
    seen: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            errors.append(f"{case.case_id}: duplicate case ID")
        seen.add(case.case_id)

        if case.classification is Classification.PRESERVE:
            if case.expected_observations is None or case.expected_runs is None:
                errors.append(f"{case.case_id}: PRESERVE case lacks expected results")
        elif case.expected_observations is not None or case.expected_runs is not None:
            errors.append(
                f"{case.case_id}: non-PRESERVE case carries an asserted result"
            )

        if case.signal is None:
            if case.attempted_targets:
                errors.append(f"{case.case_id}: target exists without Signal")
            if case.expected_observations:
                errors.append(f"{case.case_id}: Observation exists without Signal")
            if case.expected_runs:
                errors.append(f"{case.case_id}: run exists without Signal")
            if case.classification is Classification.PRESERVE:
                errors.append(f"{case.case_id}: PRESERVE case lacks immutable Signal")
            continue

        for target in case.attempted_targets:
            if resolve_citation(case.signal, target) is None:
                errors.append(f"{case.case_id}: attempted target does not resolve")

        if case.expected_observations is None or case.expected_runs is None:
            continue

        if len(case.expected_runs) != len(case.attempted_targets):
            errors.append(
                f"{case.case_id}: one run is required per supplied target attempt"
            )

        target_set = set(case.attempted_targets)
        run_targets = [run.attempted_condition_citation for run in case.expected_runs]
        if len(target_set) != len(case.attempted_targets):
            errors.append(f"{case.case_id}: attempted targets are not unique")
        if len(set(run_targets)) != len(run_targets):
            errors.append(f"{case.case_id}: duplicate run for attempted target")
        if set(run_targets) != target_set:
            errors.append(f"{case.case_id}: runs do not map one-to-one to targets")

        produced_count = sum(
            run.outcome is RunOutcome.PRODUCED for run in case.expected_runs
        )
        if produced_count != len(case.expected_observations):
            errors.append(
                f"{case.case_id}: produced run/Observation cardinality differs"
            )
        produced_indices = [
            run.resulting_observation_index
            for run in case.expected_runs
            if run.outcome is RunOutcome.PRODUCED
        ]
        if (
            any(index is None for index in produced_indices)
            or len(set(produced_indices)) != len(produced_indices)
            or set(produced_indices) != set(range(len(case.expected_observations)))
        ):
            errors.append(
                f"{case.case_id}: produced runs do not map one-to-one to Observations"
            )

        for observation in case.expected_observations:
            if observation.condition_citation not in target_set:
                errors.append(f"{case.case_id}: Observation target was not attempted")
            target_range = resolve_citation(case.signal, observation.condition_citation)
            if target_range is None:
                errors.append(f"{case.case_id}: condition citation does not resolve")
                continue
            support = observation.state_evidence_citation
            if (
                observation.condition_state
                in (
                    ConditionState.ACTIVE,
                    ConditionState.RESOLVED,
                )
                and support is None
            ):
                errors.append(f"{case.case_id}: active/resolved state lacks support")
            if support is not None:
                support_range = resolve_citation(case.signal, support)
                if support_range is None:
                    errors.append(f"{case.case_id}: state support does not resolve")
                elif (
                    support.source_part
                    is not observation.condition_citation.source_part
                    or not (
                        target_range[0] <= support_range[0]
                        and support_range[1] <= target_range[1]
                    )
                ):
                    errors.append(f"{case.case_id}: state support is outside target")

        for run in case.expected_runs:
            if run.attempted_signal_id != case.signal.signal_id:
                errors.append(
                    f"{case.case_id}: run attempted Signal does not match case"
                )
            if not run.attempted_semantic_contract_version:
                errors.append(f"{case.case_id}: run lacks attempted semantic contract")
            if not isinstance(run.producer_kind, ProducerKind):
                errors.append(f"{case.case_id}: run has invalid producer kind")
            if not run.producer_name or not run.producer_revision:
                errors.append(f"{case.case_id}: run lacks producer provenance")
            if not run.attempted_at:
                errors.append(f"{case.case_id}: run lacks attempted time")
            if run.attempted_condition_citation not in target_set:
                errors.append(f"{case.case_id}: run citation was not attempted")
            if run.outcome is RunOutcome.PRODUCED:
                if not run.produced_at:
                    errors.append(f"{case.case_id}: produced run lacks produced time")
                index = run.resulting_observation_index
                if index is None or not 0 <= index < len(case.expected_observations):
                    errors.append(
                        f"{case.case_id}: produced run lacks one valid result"
                    )
                    continue
                observation = case.expected_observations[index]
                if (
                    run.attempted_condition_citation != observation.condition_citation
                    or run.attempted_semantic_contract_version
                    != observation.semantic_contract_version
                ):
                    errors.append(
                        f"{case.case_id}: produced run does not match attempt"
                    )
            else:
                if run.resulting_observation_index is not None:
                    errors.append(
                        f"{case.case_id}: failure run references an Observation"
                    )
                if run.produced_at is not None:
                    errors.append(f"{case.case_id}: failure run has produced time")
    return errors
