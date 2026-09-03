"""
Gemini adapter for the offline NIC-19 Condition State shadow experiment.

This module is test/evaluation-only.  It calls no BIA production code and its
results are not persisted to the production database.  The NIC-18 rules
interpreter remains a separate, frozen reference baseline.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping

from tests.condition_state_eval.dataset import ConditionState
from tests.condition_state_eval.result import InterpreterCase, InterpreterResult, now_iso

INTERPRETER_ID = "gemini-condition-state-shadow"
INTERPRETER_VERSION = "3.0.0"
PROMPT_VERSION = "nic-19-gemini-3.1-flash-lite-accepted-v1"
PROVIDER = "Google Gemini Developer API"
MODEL_ID = "gemini-3.1-flash-lite"
API_VERSION = "v1beta"
REQUEST_TIMEOUT_SECONDS = 30.0
ENDPOINT = (
    "https://generativelanguage.googleapis.com/"
    f"{API_VERSION}/models/{MODEL_ID}:generateContent"
)

# This prompt, schema, and generation configuration are frozen before any
# NIC-17 corpus case is sent to the model.  Do not tune them from corpus
# outcomes; a changed experiment needs a new prompt version and review.
SYSTEM_INSTRUCTION = """You are an offline evaluator for BIA's NIC-15 Condition State task.

Classify only the condition described by TARGET_SPAN. Do not use facts outside
TARGET_SPAN, do not infer an unstated current state, and do not give advice.

Use exactly one label:
- active: TARGET_SPAN explicitly says the condition currently exists, persists,
  recurs, or is still occurring.
- resolved: TARGET_SPAN explicitly says the condition has been fixed, resolved,
  or no longer occurs.
- unknown: TARGET_SPAN explicitly leaves the condition's state indeterminate,
  including hedged, hypothetical, interrogative, conflicting, or non-condition
  statements.
- null: abstain only when no defensible classification can be grounded in a
  literal span of TARGET_SPAN.

For every non-null label, evidence_span must be a non-empty, exact contiguous
substring copied from TARGET_SPAN. For a null label, evidence_span must be
null. rationale must be a concise explanation based only on that evidence."""

GENERATION_CONFIG: dict[str, Any] = {
    "temperature": 0.0,
    "topP": 1.0,
    "maxOutputTokens": 256,
    "responseMimeType": "application/json",
}

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {
            "type": ["string", "null"],
            "enum": ["active", "resolved", "unknown", None],
            "description": "NIC-15 condition-state label, or null for abstention.",
        },
        "evidence_span": {
            "type": ["string", "null"],
            "description": "Exact contiguous citation from TARGET_SPAN, or null only for abstention.",
        },
        "rationale": {
            "type": "string",
            "description": "Concise explanation grounded only in evidence_span.",
        },
    },
    "required": ["label", "evidence_span", "rationale"],
    "additionalProperties": False,
}

HttpPost = Callable[[str, bytes, Mapping[str, str], float], Mapping[str, Any]]


class GeminiRequestError(RuntimeError):
    """A transport or API error, deliberately distinct from semantic unknown."""


def _retry_after_seconds(headers: Mapping[str, str] | None) -> float | None:
    """Return the server-specified retry delay, when it is safely parseable."""
    if headers is None:
        return None
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
    return max(delay, 0.0)


def _case_prompt(case: InterpreterCase) -> str:
    return (
        "SOURCE_TEXT:\n"
        f"{case.source_text}\n\n"
        "TARGET_SPAN:\n"
        f"{case.target_span}"
    )


def build_request_payload(case: InterpreterCase) -> dict[str, Any]:
    """Build the stable, inspectable request body without any credential."""
    generation_config = deepcopy(GENERATION_CONFIG)
    generation_config["responseJsonSchema"] = deepcopy(RESPONSE_SCHEMA)
    return {
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": [{"text": _case_prompt(case)}]}],
        "generationConfig": generation_config,
    }


def _post_json(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> Mapping[str, Any]:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Never include response/request bodies here: an error must not expose a
        # credential or become an accidental raw-output persistence channel.
        message = f"Gemini API HTTP {exc.code}: {exc.reason}"
        retry_after = _retry_after_seconds(exc.headers)
        if retry_after is not None:
            message += f"; retry_after_seconds={retry_after}"
        raise GeminiRequestError(message) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GeminiRequestError(f"Gemini API request failed: {exc.__class__.__name__}") from exc


def _raw_text(response: Mapping[str, Any]) -> str:
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise GeminiRequestError("Gemini response contained no candidate")
    content = candidates[0].get("content") if isinstance(candidates[0], Mapping) else None
    parts = content.get("parts") if isinstance(content, Mapping) else None
    if not isinstance(parts, list):
        raise GeminiRequestError("Gemini response candidate contained no text parts")
    text = "".join(part.get("text", "") for part in parts if isinstance(part, Mapping))
    if not text:
        raise GeminiRequestError("Gemini response candidate contained empty text")
    return text


def _execution_parameters() -> dict[str, Any]:
    return {
        "provider": PROVIDER,
        "transport": "direct_https",
        "api_version": API_VERSION,
        "model": MODEL_ID,
        "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
        "generation_config": deepcopy(GENERATION_CONFIG),
        "response_schema": deepcopy(RESPONSE_SCHEMA),
    }


def _result(
    case: InterpreterCase,
    *,
    start: float,
    label: ConditionState | None,
    error: str | None,
    evidence_span: str | None = None,
    raw_output: str | None = None,
    token_usage: dict[str, Any] | None = None,
) -> InterpreterResult:
    return InterpreterResult(
        case_id=case.case_id,
        label=label,
        error=error,
        evidence_span=evidence_span if error is None else None,
        matched_cue=evidence_span if error is None else None,
        interpreter_id=INTERPRETER_ID,
        interpreter_version=INTERPRETER_VERSION,
        run_timestamp=now_iso(),
        latency_ms=(time.perf_counter() - start) * 1000,
        prompt_version=PROMPT_VERSION,
        model_identity=f"{PROVIDER}/{MODEL_ID}",
        # Gemini generateContent usage metadata contains tokens, but not billed
        # cost. Do not estimate a price from a moving external price sheet.
        cost_usd=None,
        token_usage=token_usage,
        execution_parameters=_execution_parameters(),
        raw_output=raw_output,
    )


def interpret(
    case: InterpreterCase,
    *,
    api_key: str | None = None,
    http_post: HttpPost = _post_json,
) -> InterpreterResult:
    """Run one isolated model interpretation; operational failures set error.

    The API key is read only from the supplied argument or GEMINI_API_KEY and
    is transmitted solely in an HTTP header. It is never returned or logged.
    """
    start = time.perf_counter()
    key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY")
    if not key:
        return _result(
            case,
            start=start,
            label=None,
            error="Gemini API key is not configured",
        )

    raw_output: str | None = None
    token_usage: dict[str, Any] | None = None
    try:
        payload = build_request_payload(case)
        response = http_post(
            ENDPOINT,
            json.dumps(payload).encode("utf-8"),
            {"Content-Type": "application/json", "x-goog-api-key": key},
            REQUEST_TIMEOUT_SECONDS,
        )
        usage = response.get("usageMetadata")
        token_usage = dict(usage) if isinstance(usage, Mapping) else None
        raw_output = _raw_text(response)
        parsed = json.loads(raw_output)
        if not isinstance(parsed, dict):
            raise GeminiRequestError("Gemini structured output was not an object")
        if set(parsed) != {"label", "evidence_span", "rationale"}:
            raise GeminiRequestError("Gemini structured output did not match the required fields")

        raw_label = parsed["label"]
        raw_evidence = parsed["evidence_span"]
        if raw_label is None:
            if raw_evidence is not None:
                raise GeminiRequestError("Gemini abstention included evidence_span")
            return _result(
                case,
                start=start,
                label=None,
                error=None,
                raw_output=raw_output,
                token_usage=token_usage,
            )
        if not isinstance(raw_label, str):
            raise GeminiRequestError("Gemini label was not a string or null")
        try:
            label = ConditionState(raw_label)
        except ValueError as exc:
            raise GeminiRequestError(f"Gemini returned unsupported label {raw_label!r}") from exc
        if not isinstance(raw_evidence, str) or not raw_evidence or raw_evidence not in case.target_span:
            raise GeminiRequestError("Gemini evidence_span was not a literal non-empty target-span citation")
        if not isinstance(parsed["rationale"], str):
            raise GeminiRequestError("Gemini rationale was not a string")
        return _result(
            case,
            start=start,
            label=label,
            error=None,
            evidence_span=raw_evidence,
            raw_output=raw_output,
            token_usage=token_usage,
        )
    except Exception as exc:
        # An interpreter failure is deliberately recorded on the operational
        # axis rather than recast as the semantic `unknown` label.
        return _result(
            case,
            start=start,
            label=None,
            error=str(exc),
            raw_output=raw_output,
            token_usage=token_usage,
        )
