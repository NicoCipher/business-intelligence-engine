"""
tests/test_condition_state_dataset.py — automated validation for the
NIC-17 Condition State evaluation dataset
(tests/condition_state_eval/dataset.py).

These tests validate the DATASET's own structural integrity (unique
IDs, literal span containment, valid labels, scored/diagnostic
separation) -- they do not implement, call, or evaluate any
interpreter. No Condition State interpreter, model integration,
production schema, or pipeline behavior is exercised or introduced
here; NIC-18/19 remain untouched.

Also guards that building this dataset did not modify the existing,
separate Semantic Evaluation Baseline V1 corpus in any way.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.condition_state_eval.dataset import (
    ADVERSARIAL_CASES,
    CASES,
    CORE_CASES,
    CaseSet,
    ConditionState,
    validate_dataset,
)
from tests.semantic_eval.corpus import CORPUS as SEMANTIC_EVAL_CORPUS
from tests.semantic_eval.corpus import PRESERVE_CASE_IDS as SEMANTIC_EVAL_PRESERVE_IDS


class TestDatasetStructuralValidity:
    def test_no_validation_errors(self):
        errors = validate_dataset(CASES)
        assert errors == [], f"dataset validation errors: {errors}"

    def test_case_ids_are_unique(self):
        ids = [c.case_id for c in CASES]
        assert len(ids) == len(set(ids))

    def test_target_span_is_literal_substring_of_source_text(self):
        for c in CASES:
            assert c.target_span in c.source_text, (
                f"{c.case_id}: target_span {c.target_span!r} not found "
                f"literally in source_text {c.source_text!r}"
            )

    def test_scored_cases_carry_a_valid_label(self):
        for c in CASES:
            if c.scored:
                assert c.expected_label in (
                    ConditionState.ACTIVE, ConditionState.RESOLVED, ConditionState.UNKNOWN,
                ), f"{c.case_id}: scored case has an invalid or missing label"

    def test_diagnostic_cases_carry_no_label(self):
        diagnostic = [c for c in CASES if not c.scored]
        assert len(diagnostic) == 3, "expected exactly 3 diagnostic cases per the gold-label audit"
        for c in diagnostic:
            assert c.expected_label is None, (
                f"{c.case_id}: diagnostic case must not carry a gold label"
            )
        assert {c.case_id for c in diagnostic} == {"CS-CORE-007", "CS-CORE-008", "CS-ADV-004"}

    def test_scored_and_diagnostic_cases_cannot_be_confused(self):
        """The structural invariant itself: expected_label is None if
        and only if scored is False. This is what makes it impossible
        for a diagnostic case to be silently treated as scored, or a
        scored case to silently be missing its gold label."""
        for c in CASES:
            assert (c.expected_label is None) == (not c.scored), (
                f"{c.case_id}: scored/diagnostic and expected_label are inconsistent"
            )

    def test_no_real_world_holdout_content_present(self):
        assert all(c.case_set in (CaseSet.CORE, CaseSet.ADVERSARIAL) for c in CASES)


class TestDatasetCounts:
    def test_core_set_count(self):
        assert len(CORE_CASES) == 32

    def test_adversarial_set_count(self):
        assert len(ADVERSARIAL_CASES) == 12

    def test_total_case_count(self):
        assert len(CASES) == 44

    def test_scored_vs_diagnostic_split(self):
        scored = [c for c in CASES if c.scored]
        diagnostic = [c for c in CASES if not c.scored]
        assert len(scored) == 41
        assert len(diagnostic) == 3


class TestExistingSemanticEvalBaselineUnchanged:
    def test_corpus_length_and_ids_unchanged(self):
        assert len(SEMANTIC_EVAL_CORPUS) == 12
        ids = {c.id for c in SEMANTIC_EVAL_CORPUS}
        assert ids == {
            "C1", "C2", "C3", "C4", "P1", "P2", "P3",
            "N1_N2", "S1", "S2", "S3", "CONFIDENCE_PAIR",
        }

    def test_preserve_case_ids_unchanged(self):
        assert SEMANTIC_EVAL_PRESERVE_IDS == frozenset({"C1", "C3", "P1", "P2", "S3"})
