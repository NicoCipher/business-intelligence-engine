"""
tests/condition_state_eval/evaluate.py — scores InterpreterResults
against NIC-17's EvidenceCase gold labels, per NIC-15's revised
evaluation table.

Outcome categories (mutually exclusive, exhaustive for scored cases):

    Expected \\ Predicted | active          | resolved        | unknown
    active                | correct         | critically_wrong | abstained
    resolved              | critically_wrong| correct          | abstained
    unknown               | wrong           | wrong            | correct

`critically_wrong` is reserved specifically for a direct active<->resolved
inversion -- the interpreter asserting the exact opposite of a
mutually-exclusive ground truth -- distinct in kind, not just severity,
from `abstained` (under-committing) or `wrong` (over-committing when
truly unknown).

`error` (an interpreter's own operational failure) is a separate axis,
tracked independently, never mapped into this table.

Diagnostic cases (scored=False in the dataset) are never scored here --
NIC-15 has no gold label for them by design. Their results are still
recorded, per NIC-18's "record known failure cases rather than hiding
them," just outside the scored-outcome table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tests.condition_state_eval.dataset import ConditionState, EvidenceCase
from tests.condition_state_eval.result import InterpreterResult

Outcome = Literal["correct", "critically_wrong", "wrong", "abstained", "correct_abstention", "error"]


@dataclass(frozen=True)
class ScoredResult:
    case_id: str
    outcome: Outcome
    expected_label: ConditionState
    predicted_label: ConditionState | None


@dataclass(frozen=True)
class DiagnosticObservation:
    case_id: str
    predicted_label: ConditionState | None
    error: str | None
    notes: str


def score(case: EvidenceCase, result: InterpreterResult) -> ScoredResult:
    if not case.scored:
        raise ValueError(f"{case.case_id} is a diagnostic case and must not be scored")
    if result.error is not None:
        return ScoredResult(case.case_id, "error", case.expected_label, None)

    expected = case.expected_label
    predicted = result.label

    if predicted is None:
        outcome: Outcome = "correct_abstention" if expected == ConditionState.UNKNOWN else "abstained"
    elif predicted == expected:
        outcome = "correct"
    elif expected == ConditionState.UNKNOWN:
        outcome = "wrong"
    elif {predicted, expected} == {ConditionState.ACTIVE, ConditionState.RESOLVED}:
        outcome = "critically_wrong"
    else:
        outcome = "wrong"

    return ScoredResult(case.case_id, outcome, expected, predicted)


def observe_diagnostic(case: EvidenceCase, result: InterpreterResult) -> DiagnosticObservation:
    if case.scored:
        raise ValueError(f"{case.case_id} is a scored case, not diagnostic")
    return DiagnosticObservation(case.case_id, result.label, result.error, case.notes)


def summarize(scored_results: list[ScoredResult]) -> dict[str, int]:
    counts: dict[str, int] = {
        "correct": 0, "critically_wrong": 0, "wrong": 0,
        "abstained": 0, "correct_abstention": 0, "error": 0,
    }
    for r in scored_results:
        counts[r.outcome] += 1
    return counts


def confusion_matrix(scored_results: list[ScoredResult]) -> dict[tuple[str, str], int]:
    """Expected x Predicted, over {active, resolved, unknown}, where an
    abstention (predicted_label is None) is treated as a prediction of
    'unknown' for this matrix -- consistent with score()'s own
    correct_abstention/abstained semantics."""
    matrix: dict[tuple[str, str], int] = {}
    for r in scored_results:
        if r.outcome == "error":
            continue
        predicted = r.predicted_label.value if r.predicted_label is not None else "unknown"
        key = (r.expected_label.value, predicted)
        matrix[key] = matrix.get(key, 0) + 1
    return matrix


def precision_recall(scored_results: list[ScoredResult]) -> dict[str, dict[str, float]]:
    matrix = confusion_matrix(scored_results)
    labels = ["active", "resolved", "unknown"]
    out: dict[str, dict[str, float]] = {}
    for label in labels:
        tp = matrix.get((label, label), 0)
        predicted_as_label = sum(v for (exp, pred), v in matrix.items() if pred == label)
        actually_label = sum(v for (exp, pred), v in matrix.items() if exp == label)
        precision = tp / predicted_as_label if predicted_as_label else None
        recall = tp / actually_label if actually_label else None
        out[label] = {
            "precision": precision, "recall": recall,
            "predicted_count": predicted_as_label, "actual_count": actually_label,
        }
    return out
