"""
tests/condition_state_eval/result.py — the NIC-15 InterpreterResult
contract, shared by the rules baseline (NIC-18, this module) and the
future external-model interpreter (NIC-19). Neither interpreter owns
this shape independently -- it's what makes their results directly
comparable.

`label` and `error` are mutually exclusive and jointly exhaustive per
NIC-15's revised contract: every attempted (case, interpreter) run
produces exactly one result, and exactly one of the two is populated.
`evidence_span` is required whenever `label` is `active` or `resolved`
(the interpreter's own citation, grounded in the input it was given --
see rules_interpreter.py for how this differs from the dataset's own
`target_span`), optional for `unknown`.

Fields relevant only to model-based interpreters (`prompt_version`,
`model_identity`, `cost_usd`, `token_usage`, `execution_parameters`)
stay None here -- the rules interpreter is local and deterministic, has
no prompt, no model, and no execution cost, so populating them with
placeholder zeros/strings would misrepresent what actually ran.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from tests.condition_state_eval.dataset import ConditionState


@dataclass(frozen=True)
class InterpreterCase:
    """
    What an interpreter is actually given -- deliberately NOT the full
    EvidenceCase from dataset.py. `expected_label` is withheld; an
    interpreter under evaluation must never see the answer key.
    """
    case_id: str
    source_text: str
    target_span: str


@dataclass(frozen=True)
class InterpreterResult:
    case_id: str
    label: Optional[ConditionState]
    error: Optional[str]

    evidence_span: Optional[str]
    matched_cue: Optional[str]

    interpreter_id: str
    interpreter_version: str
    run_timestamp: str
    latency_ms: float

    # Model-only fields, always None for the rules interpreter
    prompt_version: Optional[str] = None
    model_identity: Optional[str] = None
    cost_usd: Optional[float] = None
    token_usage: Optional[dict] = None
    execution_parameters: Optional[dict] = None
    raw_output: Optional[str] = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
