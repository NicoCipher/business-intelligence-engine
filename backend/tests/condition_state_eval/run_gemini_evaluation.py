"""Run one controlled NIC-19 Gemini evaluation and preserve raw results.

The runner deliberately delegates all model invocation and result validation
to ``gemini_adapter.interpret`` and all scoring to ``evaluate``.  It does not
change the frozen prompt or evaluate policy.  Scored and diagnostic cases are
executed and recorded in separate sections; diagnostics never enter metrics.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.condition_state_eval.dataset import CASES, ConditionState, EvidenceCase  # noqa: E402
from tests.condition_state_eval.evaluate import precision_recall, score, summarize  # noqa: E402
from tests.condition_state_eval.gemini_adapter import (  # noqa: E402
    GENERATION_CONFIG,
    INTERPRETER_ID,
    INTERPRETER_VERSION,
    MODEL_ID,
    PROMPT_VERSION,
    PROVIDER,
    RESPONSE_SCHEMA,
    interpret,
)
from tests.condition_state_eval.result import InterpreterCase, InterpreterResult  # noqa: E402


def _label_value(label: ConditionState | None) -> str | None:
    return label.value if label is not None else None


def _token_count(result: InterpreterResult, field: str) -> int | None:
    usage = result.token_usage or {}
    value = usage.get(field)
    return value if isinstance(value, int) else None


def _result_record(case: EvidenceCase, result: InterpreterResult) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "category": case.category,
        "case_set": case.case_set.value,
        "expected_label": _label_value(case.expected_label),
        "predicted_label": _label_value(result.label),
        "evidence_span": result.evidence_span,
        "rationale_raw_structured_output": result.raw_output,
        "operational_error": result.error,
        "request_latency_ms": result.latency_ms,
        "input_tokens": _token_count(result, "promptTokenCount"),
        "output_tokens": _token_count(result, "candidatesTokenCount"),
        "total_tokens": _token_count(result, "totalTokenCount"),
        "token_usage": result.token_usage,
        "provider": PROVIDER,
        "model": MODEL_ID,
        "model_identity": result.model_identity,
        "prompt_version": result.prompt_version,
        "generation_configuration": result.execution_parameters["generation_config"],
        "execution_parameters": result.execution_parameters,
        "retry_count": 0,
    }


def _latency_statistics(records: list[dict[str, Any]]) -> dict[str, float | int | None]:
    values = sorted(record["request_latency_ms"] for record in records)
    if not values:
        return {"count": 0, "min_ms": None, "max_ms": None, "mean_ms": None, "p50_ms": None, "p95_ms": None}
    percentile = lambda fraction: values[round((len(values) - 1) * fraction)]
    return {
        "count": len(values),
        "min_ms": values[0],
        "max_ms": values[-1],
        "mean_ms": sum(values) / len(values),
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
    }


def _token_totals(records: list[dict[str, Any]]) -> dict[str, int]:
    fields = {"input_tokens": "input", "output_tokens": "output", "total_tokens": "total"}
    return {
        f"{name}_tokens": sum(record[field] for record in records if record[field] is not None)
        for field, name in fields.items()
    }


def _metrics(scored_records: list[dict[str, Any]], scored_outcomes: list[Any]) -> dict[str, Any]:
    counts = summarize(scored_outcomes)
    non_errors = [outcome for outcome in scored_outcomes if outcome.outcome != "error"]
    non_error_count = len(non_errors)
    explicit_unknown = sum(record["predicted_label"] == "unknown" for record in scored_records if record["operational_error"] is None)
    effective_unknown = sum(
        record["predicted_label"] in {"unknown", None}
        for record in scored_records
        if record["operational_error"] is None
    )
    for record, outcome in zip(scored_records, scored_outcomes):
        record["outcome"] = outcome.outcome
    return {
        "scored_cases": len(scored_outcomes),
        "accuracy": counts["correct"] / non_error_count if non_error_count else None,
        "correct": counts["correct"],
        "wrong": counts["wrong"],
        "critically_wrong": counts["critically_wrong"],
        "abstained_null": counts["abstained"],
        "correct_abstention": counts["correct_abstention"],
        "operational_failure_count": counts["error"],
        "explicit_unknown_prediction_rate": explicit_unknown / non_error_count if non_error_count else None,
        "effective_unknown_or_null_rate": effective_unknown / non_error_count if non_error_count else None,
        "per_label_precision_recall": precision_recall(scored_outcomes),
    }


def run(run_id: str) -> dict[str, Any]:
    scored_cases = [case for case in CASES if case.scored]
    diagnostic_cases = [case for case in CASES if not case.scored]
    scored_records: list[dict[str, Any]] = []
    scored_outcomes = []
    diagnostic_records: list[dict[str, Any]] = []

    for case in scored_cases:
        result = interpret(InterpreterCase(case.case_id, case.source_text, case.target_span))
        record = _result_record(case, result)
        scored_records.append(record)
        scored_outcomes.append(score(case, result))

    for case in diagnostic_cases:
        result = interpret(InterpreterCase(case.case_id, case.source_text, case.target_span))
        diagnostic_records.append(_result_record(case, result))

    all_records = scored_records + diagnostic_records
    return {
        "run_id": run_id,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "provider": PROVIDER,
        "model": MODEL_ID,
        "interpreter_id": INTERPRETER_ID,
        "interpreter_version": INTERPRETER_VERSION,
        "prompt_version": PROMPT_VERSION,
        "generation_configuration": GENERATION_CONFIG,
        "response_schema": RESPONSE_SCHEMA,
        "retry_policy": "none",
        "metrics": _metrics(scored_records, scored_outcomes),
        "latency_statistics_ms": _latency_statistics(all_records),
        "token_totals": _token_totals(all_records),
        "scored_results": scored_records,
        "diagnostic_results": diagnostic_records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    report = run(args.run_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"run_id": args.run_id, "metrics": report["metrics"], "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
