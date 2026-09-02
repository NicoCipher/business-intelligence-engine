"""
tests/condition_state_eval/run_rules_baseline.py — runs the rules
interpreter (NIC-18) against NIC-17's Core and Adversarial sets and
reports measured results.

This is a diagnostic report, not a pass/fail gate -- exactly the same
split established for the Semantic Evaluation Baseline
(run_baseline.py vs. test_semantic_eval_controls.py): only mechanically
unambiguous, hand-verifiable behavior is locked into pytest
(test_condition_state_rules_interpreter.py); the full run against every
case, including expected failures this narrow deterministic vocabulary
was never meant to solve, lives here as a measurement, not an
assertion. Per NIC-18's own instruction, known failures are recorded,
not hidden or special-cased away.

Only the Core and Adversarial sets run here. The real-world holdout is
intentionally absent -- it does not exist in this repository, is being
constructed independently from the production BIA database, and must
never be touched while tuning this interpreter.

Run with:
    cd backend && python -m tests.condition_state_eval.run_rules_baseline
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.condition_state_eval.dataset import CASES, EvidenceCase
from tests.condition_state_eval.evaluate import (
    confusion_matrix,
    observe_diagnostic,
    precision_recall,
    score,
    summarize,
)
from tests.condition_state_eval.result import InterpreterCase
from tests.condition_state_eval.rules_interpreter import INTERPRETER_ID, INTERPRETER_VERSION, interpret


def main() -> int:
    scored_cases = [c for c in CASES if c.scored]
    diagnostic_cases = [c for c in CASES if not c.scored]

    print("=" * 78)
    print(f"Condition State rules baseline: {INTERPRETER_ID} v{INTERPRETER_VERSION}")
    print(f"({len(scored_cases)} scored cases, {len(diagnostic_cases)} diagnostic)")
    print("=" * 78)

    scored_results = []
    for case in scored_cases:
        result = interpret(InterpreterCase(case.case_id, case.source_text, case.target_span))
        outcome = score(case, result)
        scored_results.append(outcome)
        flag = " <== CRITICALLY WRONG" if outcome.outcome == "critically_wrong" else ""
        print(f"[{outcome.outcome:18s}] {case.case_id:14s} expected={outcome.expected_label.value:8s} "
              f"predicted={outcome.predicted_label.value if outcome.predicted_label else 'none':8s} "
              f"cue={result.matched_cue!r}{flag}")

    print("\n" + "-" * 78)
    print("Diagnostic cases (no gold label -- NIC-15 underspecified; observed, not scored):")
    print("-" * 78)
    for case in diagnostic_cases:
        result = interpret(InterpreterCase(case.case_id, case.source_text, case.target_span))
        obs = observe_diagnostic(case, result)
        print(f"  {obs.case_id:14s} predicted={obs.predicted_label.value if obs.predicted_label else 'none':8s} "
              f"cue={result.matched_cue!r}")
        print(f"    note: {obs.notes}")

    print("\n" + "=" * 78)
    print("Summary (scored cases only)")
    print("=" * 78)
    counts = summarize(scored_results)
    total_scored = len(scored_results)
    non_error = [r for r in scored_results if r.outcome != "error"]
    accuracy = counts["correct"] / len(non_error) if non_error else 0.0
    abstention_predictions = sum(1 for r in scored_results if r.predicted_label is None and r.outcome != "error")
    unknown_prediction_rate = abstention_predictions / len(non_error) if non_error else 0.0

    print(f"  total_scored      : {total_scored}")
    for outcome_name, n in counts.items():
        print(f"  {outcome_name:18s}: {n}")
    print(f"  accuracy          : {accuracy:.3f}  ({counts['correct']}/{len(non_error)})")
    print(f"  unknown_pred_rate : {unknown_prediction_rate:.3f}  ({abstention_predictions}/{len(non_error)})")

    print("\n  Per-label precision / recall:")
    pr = precision_recall(scored_results)
    for label, stats in pr.items():
        p = f"{stats['precision']:.3f}" if stats["precision"] is not None else "n/a (0 predicted)"
        r = f"{stats['recall']:.3f}" if stats["recall"] is not None else "n/a (0 actual)"
        print(f"    {label:10s} precision={p:20s} recall={r:20s} "
              f"(predicted={stats['predicted_count']}, actual={stats['actual_count']})")

    print("\n  Confusion matrix (expected x predicted):")
    matrix = confusion_matrix(scored_results)
    for expected in ["active", "resolved", "unknown"]:
        row = {pred: matrix.get((expected, pred), 0) for pred in ["active", "resolved", "unknown"]}
        print(f"    expected={expected:10s} -> {row}")

    critical = [r for r in scored_results if r.outcome == "critically_wrong"]
    other_errors = [r for r in scored_results if r.outcome == "wrong"]
    if critical:
        print(f"\n  CRITICAL FAILURES ({len(critical)}): {[r.case_id for r in critical]}")
    else:
        print("\n  No critically_wrong outcomes.")
    print(f"  other scored errors (wrong, non-critical): {len(other_errors)}: {[r.case_id for r in other_errors]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
