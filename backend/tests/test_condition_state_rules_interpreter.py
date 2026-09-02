"""
tests/test_condition_state_rules_interpreter.py — focused pytest tests
for the NIC-18 deterministic rules baseline
(tests/condition_state_eval/rules_interpreter.py).

Scope, deliberately narrow, mirroring the precedent already established
for the Semantic Evaluation Baseline (run_baseline.py vs.
test_semantic_eval_controls.py): only determinism/contract-shape
invariants and a small set of mechanically unambiguous, hand-verifiable
cue behaviors are locked into pytest here. The full measured run
against NIC-17's 44-case dataset -- including known, accepted failures
this narrow deterministic vocabulary was never meant to solve -- is a
diagnostic report (run_rules_baseline.py), not a pass/fail gate. Do not
add assertions here that would require extending the cue vocabulary to
pass; that is the exact "tuning against the benchmark" this baseline is
required to avoid.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.condition_state_eval.dataset import ConditionState
from tests.condition_state_eval.result import InterpreterCase
from tests.condition_state_eval.rules_interpreter import INTERPRETER_ID, INTERPRETER_VERSION, interpret


def _run(text: str):
    return interpret(InterpreterCase(case_id="unit-test", source_text=text, target_span=text))


class TestDeterminism:
    def test_identical_input_produces_identical_output(self):
        """NIC-18 'Done when' criterion: identical input and
        configuration produce identical output."""
        text = "The bug is not fixed yet."
        results = [_run(text) for _ in range(20)]
        labels = {r.label for r in results}
        cues = {r.matched_cue for r in results}
        assert labels == {ConditionState.ACTIVE}
        assert cues == {"not fixed"}

    def test_no_randomness_across_the_full_cue_vocabulary(self):
        from tests.condition_state_eval.dataset import CASES
        for case in CASES:
            first = _run(case.target_span)
            second = _run(case.target_span)
            assert first.label == second.label
            assert first.matched_cue == second.matched_cue


class TestResultContractShape:
    def test_label_and_error_are_mutually_exclusive(self):
        result = _run("The bug is not fixed yet.")
        assert result.label is not None
        assert result.error is None

    def test_evidence_span_required_when_label_present(self):
        result = _run("The bug is fixed.")
        assert result.label is not None
        assert result.evidence_span is not None

    def test_evidence_span_absent_on_abstention(self):
        result = _run("We're planning to redesign the dashboard next quarter.")
        assert result.label is None
        assert result.evidence_span is None

    def test_provenance_fields_populated(self):
        result = _run("The bug is fixed.")
        assert result.interpreter_id == INTERPRETER_ID == "rules-reference-baseline"
        assert result.interpreter_version == INTERPRETER_VERSION
        assert result.run_timestamp
        assert result.latency_ms >= 0

    def test_model_only_fields_stay_none_for_the_rules_interpreter(self):
        result = _run("The bug is fixed.")
        assert result.prompt_version is None
        assert result.model_identity is None
        assert result.cost_usd is None
        assert result.token_usage is None
        assert result.execution_parameters is None


class TestMechanicallyUnambiguousCueBehavior:
    """Hand-verifiable single-cue cases, no interacting rules."""

    def test_plain_resolved_cue(self):
        r = _run("The bug is fixed.")
        assert r.label == ConditionState.RESOLVED
        assert r.matched_cue == "fixed"

    def test_plain_active_cue(self):
        r = _run("We still have no fix for this.")
        assert r.label == ConditionState.ACTIVE
        assert r.matched_cue == "no fix"

    def test_negation_flip(self):
        r = _run("The bug is not fixed.")
        assert r.label == ConditionState.ACTIVE
        assert r.matched_cue == "not fixed"

    def test_no_longer_idiom(self):
        r = _run("The service is no longer failing.")
        assert r.label == ConditionState.RESOLVED
        assert r.matched_cue == "no longer failing"

    def test_degree_modified_negation_abstains(self):
        r = _run("The issue was not fully fixed.")
        assert r.label is None

    def test_no_cue_present_abstains(self):
        r = _run("Our team grew by three engineers this month.")
        assert r.label is None
        assert r.matched_cue is None


class TestBugFixRegressions:
    """The four mechanical fixes made during this pass -- locked in as
    regressions, since each is a generic correctness fix to the
    already-declared vocabulary, not new semantic coverage."""

    def test_solved_does_not_false_fire_inside_resolved(self):
        r = _run("This issue was resolved.")
        assert r.matched_cue != "solved"
        assert r.label == ConditionState.RESOLVED
        assert r.matched_cue == "resolved"

    def test_hyphenated_fixed_term_is_blocklisted(self):
        r = _run("We signed a fixed-term contract with the new vendor.")
        assert r.label is None

    def test_thought_it_was_fixed_hedge_suppresses(self):
        r = _run("I thought it was fixed.")
        assert r.label is None

    def test_maybe_is_recognized_as_a_modal_hedge(self):
        r = _run("Maybe it's resolved now.")
        assert r.label is None
