"""Unit tests for the isolated, pre-corpus Gemini NIC-19 adapter."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.condition_state_eval.dataset import ConditionState
from tests.condition_state_eval.gemini_adapter import (
    ENDPOINT,
    GENERATION_CONFIG,
    INTERPRETER_ID,
    MODEL_ID,
    PROMPT_VERSION,
    RESPONSE_SCHEMA,
    SYSTEM_INSTRUCTION,
    build_request_payload,
    interpret,
)
from tests.condition_state_eval.result import InterpreterCase


CASE = InterpreterCase(
    case_id="adapter-unit",
    source_text="The example service is still failing.",
    target_span="The example service is still failing.",
)


def _response(label, evidence_span, *, usage=None):
    payload = {
        "label": label,
        "evidence_span": evidence_span,
        "rationale": "Synthetic adapter fixture.",
    }
    response = {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}
    if usage is not None:
        response["usageMetadata"] = usage
    return response


class TestFrozenExperimentContract:
    def test_model_prompt_and_generation_configuration_are_explicit(self):
        assert MODEL_ID == "gemini-3.1-flash-lite"
        assert PROMPT_VERSION == "nic-19-gemini-3.1-flash-lite-accepted-v1"
        assert GENERATION_CONFIG == {
            "temperature": 0.0,
            "topP": 1.0,
            "maxOutputTokens": 256,
            "responseMimeType": "application/json",
        }
        assert "TARGET_SPAN" in SYSTEM_INSTRUCTION
        assert "Do not use facts outside" in SYSTEM_INSTRUCTION

    def test_structured_schema_keeps_contract_labels_and_abstention(self):
        assert RESPONSE_SCHEMA["properties"]["label"]["enum"] == ["active", "resolved", "unknown", None]
        assert RESPONSE_SCHEMA["properties"]["evidence_span"]["type"] == ["string", "null"]
        assert RESPONSE_SCHEMA["required"] == ["label", "evidence_span", "rationale"]

    def test_request_uses_system_instruction_and_json_schema_without_a_credential(self):
        payload = build_request_payload(CASE)
        assert payload["systemInstruction"]["parts"][0]["text"] == SYSTEM_INSTRUCTION
        assert payload["contents"][0]["parts"][0]["text"].endswith(CASE.target_span)
        assert payload["generationConfig"]["responseJsonSchema"] == RESPONSE_SCHEMA
        assert "api_key" not in json.dumps(payload).lower()


class TestGeminiResultContract:
    def test_records_grounded_semantic_unknown_separately_from_an_operational_error(self):
        def post(url, body, headers, timeout):
            assert url == ENDPOINT
            assert headers["x-goog-api-key"] == "unit-key"
            return _response("unknown", "still failing", usage={"promptTokenCount": 9, "totalTokenCount": 14})

        result = interpret(CASE, api_key="unit-key", http_post=post)

        assert result.label == ConditionState.UNKNOWN
        assert result.error is None
        assert result.evidence_span == "still failing"
        assert result.token_usage == {"promptTokenCount": 9, "totalTokenCount": 14}
        assert result.cost_usd is None
        assert result.interpreter_id == INTERPRETER_ID
        assert result.prompt_version == PROMPT_VERSION
        assert result.model_identity.endswith(MODEL_ID)
        assert result.execution_parameters["generation_config"] == GENERATION_CONFIG

    def test_records_abstention_without_turning_it_into_an_error(self):
        result = interpret(CASE, api_key="unit-key", http_post=lambda *_: _response(None, None))

        assert result.label is None
        assert result.error is None
        assert result.evidence_span is None

    def test_rejects_ungrounded_model_evidence_as_an_operational_contract_error(self):
        result = interpret(CASE, api_key="unit-key", http_post=lambda *_: _response("active", "not in target"))

        assert result.label is None
        assert result.error == "Gemini evidence_span was not a literal non-empty target-span citation"

    def test_missing_key_is_an_operational_error_not_semantic_unknown(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        result = interpret(CASE)

        assert result.label is None
        assert result.error == "Gemini API key is not configured"

    def test_api_failure_is_an_operational_error(self):
        def failing_post(*_):
            raise RuntimeError("network unavailable")

        result = interpret(CASE, api_key="unit-key", http_post=failing_post)

        assert result.label is None
        assert result.error == "network unavailable"
