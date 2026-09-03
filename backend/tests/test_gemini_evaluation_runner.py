"""Tests for NIC-19's fixed operational execution protocol."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.condition_state_eval.dataset import CaseSet, ConditionState, EvidenceCase
from tests.condition_state_eval.gemini_adapter import INTERPRETER_ID, INTERPRETER_VERSION, PROMPT_VERSION
from tests.condition_state_eval.result import InterpreterResult
from tests.condition_state_eval.run_gemini_evaluation import RATE_LIMIT_PROTOCOL, _retry_delay, run


CASE = EvidenceCase(
    case_id="runner-unit",
    source_text="The test condition is still active.",
    target_span="The test condition is still active.",
    expected_label=ConditionState.ACTIVE,
    scored=True,
    category="unit",
    case_set=CaseSet.CORE,
)


def _result(*, label=None, error=None):
    return InterpreterResult(
        case_id=CASE.case_id,
        label=label,
        error=error,
        evidence_span="still active" if label else None,
        matched_cue="still active" if label else None,
        interpreter_id=INTERPRETER_ID,
        interpreter_version=INTERPRETER_VERSION,
        run_timestamp="2026-01-01T00:00:00+00:00",
        latency_ms=12.0,
        prompt_version=PROMPT_VERSION,
        model_identity="unit/model",
        execution_parameters={"generation_config": {}},
    )


def test_only_http_429_is_retryable_and_uses_provider_delay_when_present():
    assert _retry_delay("Gemini API HTTP 429: Too Many Requests; retry_after_seconds=12.5") == 12.5
    assert _retry_delay("Gemini API HTTP 429: Too Many Requests") == RATE_LIMIT_PROTOCOL["fallback_retry_delay_seconds"]
    assert _retry_delay("Gemini API HTTP 500: Internal Server Error") is None


def test_rate_limit_retry_is_bounded_recorded_and_does_not_become_semantic_unknown():
    responses = iter(
        [
            _result(error="Gemini API HTTP 429: Too Many Requests; retry_after_seconds=3.0"),
            _result(label=ConditionState.ACTIVE),
        ]
    )
    sleeps = []

    report = run("runner-unit", cases=[CASE], interpreter=lambda _: next(responses), sleep=sleeps.append)

    record = report["scored_results"][0]
    assert report["complete_semantic_evaluation"] is True
    assert record["predicted_label"] == "active"
    assert record["operational_error"] is None
    assert record["retry_count"] == 1
    assert record["operational_attempts"] == [
        {
            "attempt_number": 1,
            "operational_error": "Gemini API HTTP 429: Too Many Requests; retry_after_seconds=3.0",
            "request_latency_ms": 12.0,
            "retry_delay_seconds": 3.0,
        },
        {
            "attempt_number": 2,
            "operational_error": None,
            "request_latency_ms": 12.0,
            "retry_delay_seconds": None,
        },
    ]
    assert sleeps == [3.0]
