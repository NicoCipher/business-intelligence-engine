"""One synthetic, non-corpus connectivity check for the frozen NIC-19 adapter.

This runner deliberately does not import the NIC-17 dataset. It is the only
live request permitted before explicit approval to evaluate the corpus.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.condition_state_eval.gemini_adapter import (  # noqa: E402
    GENERATION_CONFIG,
    INTERPRETER_ID,
    MODEL_ID,
    PROMPT_VERSION,
    PROVIDER,
    RESPONSE_SCHEMA,
    SYSTEM_INSTRUCTION,
    interpret,
)
from tests.condition_state_eval.result import InterpreterCase  # noqa: E402


def main() -> int:
    case = InterpreterCase(
        case_id="NIC-19-SMOKE-SYNTHETIC",
        source_text="The demo issue is still failing after a test deployment.",
        target_span="The demo issue is still failing after a test deployment.",
    )
    result = interpret(case)
    report = {
        "synthetic_case_id": case.case_id,
        "provider": PROVIDER,
        "model": MODEL_ID,
        "prompt_version": PROMPT_VERSION,
        "label": result.label.value if result.label else None,
        "operational_error": result.error,
        "evidence_span": result.evidence_span,
        "latency_ms": result.latency_ms,
        "token_usage": result.token_usage,
        "cost_usd": result.cost_usd,
        "generation_config": GENERATION_CONFIG,
        "response_schema": RESPONSE_SCHEMA,
        "system_instruction": SYSTEM_INSTRUCTION,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if result.error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
